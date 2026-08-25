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

`app`、worker、monitor 和 cleanup 依赖 `db-bootstrap` 成功退出；开发拓扑当前不提供自动故障切换。启动命令见 [`setup.md`](setup.md)。

## 生产部署

当前 `docker-compose.prod.yml` 实际定义生产 MySQL、统一 bootstrap、Web、monitor 和隔离 `rag-eval-worker`；它没有定义 Agent worker、PostgreSQL checkpoint 或 checkpoint cleanup。生产 Agent worker/checkpoint 拓扑是后续事项，本轮不凭空新增。生产环境不挂载源代码，使用独立卷、网络和日志轮转设置，不能假设它自动提供开发 Compose 的 MySQL replica 或故障切换能力。

开发、兼容副本和 staging 的 Agent worker 使用 `JOB_DRAIN_TIMEOUT_SECONDS`（默认 60 秒）进行优雅 drain，并设置至少 75 秒的 Compose `stop_grace_period`。staging worker 显式只读挂载多模态 index、active/previous runtime pointer、assets 和 retrieval policy 目录。发布新 release 后必须先完成独立评测与显式 publish，再通过停止/重启 worker 使 active pointer 生效；不会热切换、蓝绿切换或声称零停机。

生产必须通过环境变量或安全的 secret 机制提供 `SECRET_KEY`、模型配置、MySQL 职责账号和非空 `CHECKPOINT_POSTGRES_PASSWORD`。不要在文档、镜像层、命令行日志或 API 响应中打印密钥。

## 管理员产物

本地非 Docker 发布前必须在 `admin-frontend/` 执行 typecheck、unit、Mock E2E 和 build。未设置 `ADMIN_VITE_DEV_SERVER_URL` 时，Flask 从 `admin-frontend/dist/`（或 `ADMIN_FRONTEND_DIST_DIR` 指定目录）提供 `/admin/`；Docker 运行镜像从 `/opt/causalagent-admin` 提供构建结果。

`.dockerignore` 排除本地产物，镜像构建阶段从当前源代码重新生成。开发热更新才显式启动 Vite，生产不要把 Vite 端口作为后端依赖。

## 数据库发布顺序

空库或数据库环境重建时先启动依赖数据库，再运行 `Database.bootstrap` 完成 Alembic 和 checkpoint setup，确认成功后才启动 app/worker/monitor/cleanup。具有破坏性的 checkpoint/file migration 不会自动回填旧数据；执行 downgrade 必须选择明确 revision，并在隔离环境先验证往返。迁移风险和 preflight 规则见 [`../database/migrations-checkpoints.md`](../database/migrations-checkpoints.md)。
