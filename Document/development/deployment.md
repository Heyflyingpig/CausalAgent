# 构建与部署

文档职责：记录 CausalAgent Docker 镜像构建、开发/生产 Compose 拓扑、初始化顺序和管理员静态产物的发布边界。

适用范围：修改 Dockerfile、Compose 服务、镜像启动命令、生产环境变量或发布流程时使用；数据库内部迁移和 checkpoint 细节见 [`../database/migrations-checkpoints.md`](../database/migrations-checkpoints.md)。

## 镜像构建

`Dockerfile` 当前有三个重要阶段：

1. `python-deps` 安装基础 Python 依赖和 CPU PyTorch。
2. `test` 在共享依赖上安装 `requirements-test.txt`，默认执行 `tests/unit`。
3. `admin-builder` 使用 Node 24 Alpine 执行管理员前端构建，`runtime` 是最终 Python 镜像，将产物复制到 `/opt/causalagent-admin`。

最终运行镜像不包含 Node，不启动 Vite，不开放 Node 端口；Gunicorn 默认绑定 `0.0.0.0:5001`，由 `WEB_WORKERS`、`WEB_THREADS` 和 `WEB_TIMEOUT` 调整 Web 进程参数。

## 开发部署

默认 `docker-compose.yml` 是包含主系统、RAG 评测、联网搜索和可观测性的 15 服务开发拓扑；服务职责如下：

| 服务 | 作用 |
| --- | --- |
| `mysql-primary` / `mysql-replica` | 主库写入与复制副本，分别使用独立数据卷 |
| `postgres-checkpoint` | LangGraph checkpoint 数据库 |
| `db-bootstrap` | 一次性 MySQL/Alembic/PostgreSQL 初始化 |
| `app` | Flask Web，暴露 5001 |
| `worker` | Agent Job worker |
| `monitor` | 数据库共享快照采集 |
| `checkpoint-cleanup` | 跨库 checkpoint 删除 |
| `rag-eval-worker` | 独立领取 RAG 摄取、候选、评测和治理队列任务 |
| `searxng-init` | 一次性 init，首次启动时在配置目录内生成临时文件，完成 secret_key 注入和校验后原子发布 `settings.yml`，已存在则跳过 |
| `searxng` / `valkey` | 固定版本的 SearXNG 联网学术搜索及其缓存/队列依赖 |
| `loki` / `alloy` / `grafana` | 开发环境运行日志采集、存储和查看；只加入独立的 observability network |

`app`、Agent worker、monitor、RAG evaluation worker 和 cleanup 依赖 `db-bootstrap` 成功退出；`searxng` 依赖 Valkey 健康和 `searxng-init` 成功退出。联网搜索是 Job 级可选能力，默认拓扑不让 `app` 或 Agent worker 等待 SearXNG 健康，运行期不可用时由 Web Search 子图重试并降级；非搜索 Job 不会因此阻止启动。开发拓扑当前不提供自动故障切换。启动命令见 [`setup.md`](setup.md)。

## 联网搜索（SearXNG）

仓库只提交 `searxng/core-config/settings.yml.example`。`searxng-init` 服务在首次启动时自动兜底：`settings.yml` 缺失则在同一配置目录内创建临时文件，复制 example、把 `secret_key` 占位符替换为随机 64 位 hex，并在校验通过后通过原子重命名发布；生成失败不会留下半初始化的目标文件。`settings.yml` 已存在时仍然跳过，不覆盖用户配置。

当前开发 Compose 固定使用 `searxng/searxng:2026.8.21-bbb3c7d82`。升级镜像时必须重新验证当前 `settings.yml.example`、JSON 输出格式、三学术引擎配置和 `/healthz`；不要直接改回 `latest`。`/healthz` 只检查 SearXNG Web 进程和配置加载后的 HTTP 响应，不检查外部学术引擎、DNS 或出站网络；真实搜索可用性仍由 web_search 的运行期重试和降级处理。

开发 Compose 的可观测组件使用固定版本和独立命名卷：Loki、Alloy 不开放宿主机端口，Grafana 只绑定 `127.0.0.1:3000`。启动 Grafana 前必须设置非空的 `GRAFANA_ADMIN_PASSWORD`；采集范围由应用容器的 `causalagent_observability` 标签筛选，不包含 MySQL、PostgreSQL、Loki、Alloy 或 Grafana 自身。完整字段、标签和真实验收边界见 [`observability.md`](observability.md)。

## 预发部署

`docker-compose.staging.yml` 是隔离预发拓扑，保留 `gateway`、`scripts/staging_environment_guard.py` 启动 guard 和独立 `rag-eval-worker`，并使用独立 MySQL 主从、PostgreSQL checkpoint、卷和 gateway 日志。所有 Python 服务先通过 guard 校验项目/DSN/数据库/卷名中的 production/prod 标识，`db-bootstrap` 成功后才启动应用服务；gateway 负责入口和日志轮转。staging 显式只读挂载多模态 index、active/previous runtime、assets 与 retrieval policy。它不自动加入开发专用 SearXNG/Valkey 或 Loki/Alloy/Grafana。

## 生产部署

`docker-compose.prod.yml` 使用生产 MySQL、PostgreSQL checkpoint、统一 bootstrap、Web、Agent worker、monitor、checkpoint cleanup 和独立 `rag-eval-worker`；生产环境不挂载源代码，使用独立卷、网络和日志轮转设置。RAG evaluation worker 与主系统进程隔离，并通过独立评测卷共享必要的运行产物；它不带开发可观测性标签，不应把评测日志混入主系统观测流。当前生产 Compose 是单独的生产配置，不能假设它自动提供开发 Compose 的 MySQL replica、SearXNG、Loki/Alloy/Grafana 或故障切换能力。
当前生产 Compose 未定义 SearXNG 服务；如果生产环境启用 `web_search_enabled`，必须另外提供可访问的 `SEARXNG_URL` 和对应的搜索服务部署，搜索不可用时仍遵循 worker 运行期降级语义。

## RAG release 与 worker 生命周期

开发、兼容副本和 staging 的 Agent worker 使用 `JOB_DRAIN_TIMEOUT_SECONDS`（默认 60 秒）进行优雅 drain，并设置至少 75 秒的 Compose `stop_grace_period`。worker 启动只做 active pointer、manifest、正式来源、embedding、版本、collection 和向量目录的轻量 readiness 检查；失败时继续运行并标记内部 `rag_unavailable`，不加载 RAG 重资源。发布新 release 后必须先完成隔离评测和显式 publish，再通过停止/重启 worker 使 active pointer 生效；不支持热切换、蓝绿切换或零停机。active pointer 发布会保留 previous pointer，candidate/资产/评测产物不自动删除。完整行为契约见 [`../architecture/rag-evaluation.md`](../architecture/rag-evaluation.md)。

生产必须通过环境变量或安全的 secret 机制提供 `SECRET_KEY`、模型配置、MySQL 职责账号、非空 `CHECKPOINT_POSTGRES_PASSWORD` 和 RAG evaluation worker 所需配置。不要在文档、镜像层、命令行日志或 API 响应中打印密钥。

## 管理员产物

本地非 Docker 发布前必须在 `admin-frontend/` 执行 typecheck、unit、Mock E2E 和 build。未设置 `ADMIN_VITE_DEV_SERVER_URL` 时，Flask 从 `admin-frontend/dist/`（或 `ADMIN_FRONTEND_DIST_DIR` 指定目录）提供 `/admin/`；Docker 运行镜像从 `/opt/causalagent-admin` 提供构建结果。

`.dockerignore` 排除本地产物，镜像构建阶段从当前源代码重新生成。开发热更新才显式启动 Vite，生产不要把 Vite 端口作为后端依赖。

## 数据库发布顺序

开发/预发空库或数据库环境重建时先启动依赖数据库，再运行 `Database.bootstrap` 完成 Alembic 和 checkpoint setup，确认成功后才启动 app/worker/monitor/cleanup/rag-eval-worker。当前唯一 Alembic head 是 `s4d5e6f7a8b9`；具有破坏性的 checkpoint/file migration 不会自动回填旧数据，执行 downgrade 必须选择明确 revision，并在隔离环境先验证往返。迁移风险和 preflight 规则见 [`../database/migrations-checkpoints.md`](../database/migrations-checkpoints.md)。
