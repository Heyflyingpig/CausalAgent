# 管理员系统文档

本目录集中记录管理员后台的使用契约。项目根 `README.md` 只保留首次部署所需步骤，接口、安全约束和验收细节在这里维护。

## 文档索引

- [API 契约](api.md)：页面入口、数据库看板、业务查询、受控写入和审计接口。
- [开发与部署](development.md)：生产构建、本地 Vite 开发、初始管理员和 monitor 进程。
- [测试说明](testing.md)：后端测试层级、管理员前端测试和隔离主从 E2E。

## 系统边界

管理员前端位于 `admin-frontend/`，使用 Vue 3、TypeScript、Vue Router、Element Plus 和 Vite。Flask 负责实时管理员鉴权、API 和生产静态资源托管；最终 Docker 运行镜像不需要 Node，也不会启动 Vite 服务。

管理员后台当前提供业务概览、用户、会话与消息、任务与事件、文件资产、数据库看板、采集配置和 Schema/deep 审计。它不提供任意 SQL、迁移、数据库账号授权、复制控制或任务控制。

普通用户前端和聊天 API/SSE 契约不受管理员后台影响。

## 深入设计

- [数据库治理、读写矩阵和恢复流程](../../setting/database_governance.md)
- [阶段三并发设计交接](../../setting/phase3_concurrency_handoff.md)

接口或启动方式变化时，应同步更新本目录、根 `README.md` 和 `AGENTS.md` 中对应的项目事实。
