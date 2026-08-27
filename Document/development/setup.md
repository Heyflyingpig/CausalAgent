# 开发环境

文档职责：记录当前仓库的本地、Docker、管理员前端和数据库初始化入口。

适用范围：首次配置开发环境、切换运行方式或修改启动入口时使用；服务拓扑与镜像发布见 [`deployment.md`](deployment.md)，测试命令见 [`testing.md`](testing.md)。

## 配置前提

配置统一由 `config/settings.py` 从系统环境变量读取；仓库根目录存在 `.env` 时会先加载它。至少需要应用密钥、模型配置、MySQL 写/读账号、业务数据库名和非空 `CHECKPOINT_POSTGRES_PASSWORD`。不要把 `.env`、密码、API key 或数据库连接串提交到 Git、日志或文档。

主从开发使用职责分离账号：写主库、业务读、复制状态观测和复制通道账号各自配置。没有专用复制状态账号时，eventual read 会安全回退主库。

## Docker 开发

Docker 是当前首选开发方式：

```bash
docker compose -f docker-compose.yml up -d
```

默认开发 Compose 会同时启动日志采集拓扑 `loki`、`alloy` 和 `grafana`。由于 Grafana 服务要求密码非空，首次启动前必须在 `.env` 设置 `GRAFANA_ADMIN_PASSWORD`；修改 Alloy 配置或首次拉取镜像时，先执行：

```bash
docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.yml pull loki alloy grafana
docker compose -f docker-compose.yml run --rm --no-deps alloy validate /etc/alloy/config.alloy
```

日志查看地址为 `http://127.0.0.1:3000`。完整的日志启动、停止、生产边界和验收步骤见
[`observability.md`](observability.md) 与 [`deployment.md`](deployment.md)。

首次启动、空卷重建或数据库环境重建时，Compose 会先运行 `db-bootstrap`。需要单独重跑一次性初始化时执行：

```bash
docker compose -f docker-compose.yml run --rm db-bootstrap
```

首次启动时，`searxng-init` 会在配置目录内生成临时文件，完成复制、随机 `secret_key` 注入和校验后原子发布 `searxng/core-config/settings.yml`，无需手动复制；文件已存在则跳过且不会覆盖用户配置。`searxng` 使用固定版本镜像并提供 `/healthz` 浅层 healthcheck。默认 `app`/`worker` 不依赖 SearXNG 健康，联网搜索不可用时由 Job 运行期重试并降级。

查看搜索服务的启动和健康状态：

```bash
docker compose -f docker-compose.yml ps searxng searxng-init valkey
```

需要验证 Compose 合并后的部署契约时，使用 `docker compose config`；不要使用 `down -v` 清理共享数据库或搜索数据卷。

开发 Compose 使用 `mysql-primary`、`mysql-replica`、`postgres-checkpoint`、`app`、`worker`、`monitor`、`checkpoint-cleanup`、`rag-eval-worker`、`searxng-init`、`searxng`、`valkey`、`loki`、`alloy` 和 `grafana`；固定端口和数据卷属于共享 Docker daemon 资源，多个 worktree 同时运行时必须采用独立 project/端口策略，不能误用 `down -v`。

## 本地 Python

不使用 Docker 时先进入项目 Python 环境，然后按需启动：

```bash
python -m Database.bootstrap
python CausalAgent.py
python -m app.agent.worker
python -m Database.monitor_worker
python -m Database.checkpoint_cleanup_worker
```

`Database/database_init.py` 只确保 MySQL 数据库存在并检查连接；完整业务表和 PostgreSQL checkpoint schema 仍由 `Database.bootstrap` 负责。新空库不要先运行旧库 preflight。

## 管理员前端开发

管理员 Vue 源码位于 `admin-frontend/`。需要热更新时执行：

```bash
cd admin-frontend
npm ci
npm run dev
```

Vite 固定使用 `/admin/` base，默认端口为 5173，并把 `/api` 代理到 `http://127.0.0.1:5001`。Flask 仍先完成页面鉴权；只有显式设置 `ADMIN_VITE_DEV_SERVER_URL=http://127.0.0.1:5173` 才跳转到 Vite。普通部署保持该变量为空，让 Flask 托管构建产物。

## 初始管理员

完成 migration 并注册一个启用的普通用户后，只通过现有 CLI 提升管理员：

```bash
python -m app.auth.admin_cli promote <username>
```

Docker 中可使用：

```bash
docker compose -f docker-compose.yml run --rm app python -m app.auth.admin_cli promote <username>
```

该命令不创建公开管理员注册接口，也不负责降级管理员。
