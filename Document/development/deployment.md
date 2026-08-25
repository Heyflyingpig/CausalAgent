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

`docker-compose.yml` 是 MySQL 主从 + PostgreSQL checkpoint 的开发拓扑，服务职责如下：

| 服务 | 作用 |
| --- | --- |
| `mysql-primary` / `mysql-replica` | 主库写入与复制副本，分别使用独立数据卷 |
| `postgres-checkpoint` | LangGraph checkpoint 数据库 |
| `db-bootstrap` | 一次性 MySQL/Alembic/PostgreSQL 初始化 |
| `app` | Flask Web，暴露 5001 |
| `worker` | Agent Job worker |
| `monitor` | 数据库共享快照采集 |
| `checkpoint-cleanup` | 跨库 checkpoint 删除 |
| `searxng-init` | 一次性 init，首次启动时在配置目录内生成临时文件，完成 secret_key 注入和校验后原子发布 `settings.yml`，已存在则跳过 |
| `searxng` | 固定版本的联网搜索服务（SearXNG），提供 `format=json` + arxiv/crossref/openalex 三引擎，并以 `/healthz` 提供浅层容器健康检查 |
| `loki` / `alloy` / `grafana` | 开发环境运行日志采集、存储和查看；只加入独立的 observability network |

`app`、worker、monitor 和 cleanup 依赖 `db-bootstrap` 成功退出；`searxng` 依赖 Valkey 健康和 `searxng-init` 成功退出。默认拓扑不让 `app` 或 worker 等待 SearXNG 健康：联网搜索是 Job 级可选能力，运行期不可用时由 web_search 重试并降级，非搜索 Job 不会因 SearXNG 不可用而阻止启动。开发拓扑当前不提供自动故障切换。启动命令见 [`setup.md`](setup.md)。

## 联网搜索（SearXNG）

仓库只提交 `searxng/core-config/settings.yml.example`。`searxng-init` 服务在首次启动时自动兜底：`settings.yml` 缺失则在同一配置目录内创建临时文件，复制 example、把 `secret_key` 占位符替换为随机 64 位 hex，并在校验通过后通过原子重命名发布；生成失败不会留下半初始化的目标文件。`settings.yml` 已存在时仍然跳过，不覆盖用户配置。

当前开发 Compose 固定使用 `searxng/searxng:2026.8.21-bbb3c7d82`。升级镜像时必须重新验证当前 `settings.yml.example`、JSON 输出格式、三学术引擎配置和 `/healthz`；不要直接改回 `latest`。`/healthz` 只检查 SearXNG Web 进程和配置加载后的 HTTP 响应，不检查外部学术引擎、DNS 或出站网络；真实搜索可用性仍由 web_search 的运行期重试和降级处理。

开发 Compose 的可观测组件使用固定版本和独立命名卷：Loki、Alloy 不开放宿主机端口，Grafana 只绑定 `127.0.0.1:3000`。启动 Grafana 前必须设置非空的 `GRAFANA_ADMIN_PASSWORD`；采集范围由应用容器的 `causalagent_observability` 标签筛选，不包含 MySQL、PostgreSQL、Loki、Alloy 或 Grafana 自身。完整字段、标签和真实验收边界见 [`observability.md`](observability.md)。

## 生产部署

`docker-compose.prod.yml` 使用生产 MySQL、PostgreSQL checkpoint、统一 bootstrap、Web、worker、monitor 和 cleanup 服务；生产环境不挂载源代码，使用独立卷、网络和日志轮转设置。当前生产 Compose 是单独的生产配置，不能假设它自动提供开发 Compose 的 MySQL replica 或故障切换能力。
当前生产 Compose 未定义 SearXNG 服务；如果生产环境启用 `web_search_enabled`，必须另外提供可访问的 `SEARXNG_URL` 和对应的搜索服务部署，搜索不可用时仍遵循 worker 运行期降级语义。

生产必须通过环境变量或安全的 secret 机制提供 `SECRET_KEY`、模型配置、MySQL 职责账号和非空 `CHECKPOINT_POSTGRES_PASSWORD`。不要在文档、镜像层、命令行日志或 API 响应中打印密钥。

## 管理员产物

本地非 Docker 发布前必须在 `admin-frontend/` 执行 typecheck、unit、Mock E2E 和 build。未设置 `ADMIN_VITE_DEV_SERVER_URL` 时，Flask 从 `admin-frontend/dist/`（或 `ADMIN_FRONTEND_DIST_DIR` 指定目录）提供 `/admin/`；Docker 运行镜像从 `/opt/causalagent-admin` 提供构建结果。

`.dockerignore` 排除本地产物，镜像构建阶段从当前源代码重新生成。开发热更新才显式启动 Vite，生产不要把 Vite 端口作为后端依赖。

## 数据库发布顺序

空库或数据库环境重建时先启动依赖数据库，再运行 `Database.bootstrap` 完成 Alembic 和 checkpoint setup，确认成功后才启动 app/worker/monitor/cleanup。具有破坏性的 checkpoint/file migration 不会自动回填旧数据；执行 downgrade 必须选择明确 revision，并在隔离环境先验证往返。迁移风险和 preflight 规则见 [`../database/migrations-checkpoints.md`](../database/migrations-checkpoints.md)。
