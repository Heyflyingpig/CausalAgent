# 管理员前端开发与部署

## 生产部署

Dockerfile 使用 Node 24 构建 `admin-frontend/`，再把产物复制到最终 Python 镜像的 `/opt/causalchat-admin`。运行镜像不包含 Node、不启动 Vite，也不开放 Node 端口。

非 Docker 环境需要先生成管理员前端产物：

```bash
cd admin-frontend
npm ci
npm run typecheck
npm run test:unit
npm run test:e2e:mock
npm run build
```

未设置开发服务器地址时，Flask 默认托管仓库中的 `admin-frontend/dist/`；Docker 镜像通过 `ADMIN_FRONTEND_DIST_DIR=/opt/causalchat-admin` 指向镜像内产物。

## 创建初始管理员

先完成 Alembic migration，并注册一个处于启用状态的普通用户，然后执行：

```bash
# 本地运行
python -m app.auth.admin_cli promote <username>

# Docker 运行
docker-compose -f docker-compose.replica.yml run --rm app python -m app.auth.admin_cli promote <username>
```

该命令只做幂等提升，不创建用户，也不负责降级管理员。管理员登录后进入 `/admin/database`。

## PostgreSQL checkpoint

迁移前请在 `.env` 设置非空的 `CHECKPOINT_POSTGRES_PASSWORD`。Docker 主从拓扑会启动
`postgres-checkpoint`、一次性 `checkpoint-setup` 和持续运行的
`checkpoint-cleanup`；本地运行等价命令为：

```bash
python -m Database.checkpoint_setup
python -m Database.checkpoint_cleanup_worker
```

`alembic upgrade head` 中的 PostgreSQL 迁移会删除 MySQL checkpoint 表和数据；
`alembic downgrade` 只重建空的兼容表结构，不恢复已删除数据。
由于该迁移合并了两个历史 head，回退时必须指定明确目标 revision，不能使用
`alembic downgrade -1`；例如回退到 `e4f5a6b7c8d9`。

## 启动 monitor

数据库看板读取共享快照。要持续产生新快照，需要独立启动：

```bash
python -m Database.monitor_worker
```

如果 monitor 未运行，页面仍可读取已有快照，但自动刷新和手动刷新请求不会产生新的采集结果。

## 本地 Vite 开发

只有修改管理员 Vue 源码并需要热更新时，才使用 Vite：

```bash
cd admin-frontend
npm ci
npm run dev
```

同时在 Flask 进程环境中设置：

```text
ADMIN_VITE_DEV_SERVER_URL=http://127.0.0.1:5173
```

Flask 仍先完成管理员页面鉴权，再跳转到 Vite。Vite 只代理 `/api` 到 Flask，不替代 Python 后端。普通部署应保持该配置为空。

## 发布产物

`admin-frontend/dist/` 是随管理员 Vue 源码同步更新的发布产物。`.dockerignore` 排除本地产物，因为镜像会从当前源码重新构建；最终镜像使用 `/opt/causalchat-admin` 中的构建结果。
