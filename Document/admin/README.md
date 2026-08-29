# 管理员系统文档

文档职责：作为管理员模块的内部入口，集中记录管理员页面、Flask API、鉴权、受控操作和专项验证的当前事实。

适用范围：修改 `app/admin/`、`admin-frontend/` 或管理员与数据库 monitor、Job、文件、checkpoint 交界时使用；系统级能力的内部实现不在本目录重复维护。

## 文档索引

- [系统结构说明](system-overview.md)：管理员前后端、数据库治理和后台进程的整体结构图与功能地图。
- [模块架构](architecture.md)：后端、Vue、实时授权以及对共享系统能力的消费关系。
- [API 契约](api.md)：页面入口、数据库看板、业务查询、受控写入和审计接口。
- [开发与部署](development.md)：管理员前端构建、本地 Vite 开发、初始管理员和发布依赖。
- [测试说明](testing.md)：后端测试层级、管理员前端测试和隔离主从 E2E。

## 系统边界

管理员前端位于 `admin-frontend/`，使用 Vue 3、TypeScript、Vue Router、Element Plus 和 Vite。Flask 负责实时管理员鉴权、API 和生产静态资源托管；最终 Docker 运行镜像不需要 Node，也不会启动 Vite 服务。

管理员后台当前提供业务概览、用户、会话与消息、任务与事件、文件资产、数据库看板、采集配置和 Schema/deep 审计。它不提供任意 SQL、迁移、数据库账号授权、复制控制或任务控制。

普通用户前端和聊天 API/SSE 契约不受管理员后台影响。

## 依赖边界

- 数据库主从、一致性、迁移、checkpoint、cleanup 和 monitor 内部机制见 [`../database/`](../database/overview.md)。
- Job、文件冻结和普通用户 SSE 生命周期见 [`../architecture/job-file-lifecycle.md`](../architecture/job-file-lifecycle.md) 与 [`../api/agent-jobs.md`](../api/agent-jobs.md)。
- 管理员如何消费这些能力保留在本目录，不复制其内部实现。

接口或启动方式变化时，必须先核对实现和对应权威文档，再同步更新本目录、根规则和局部 `AGENTS.md` 中的执行约束；根 `README.md` 不属于本轮文档重构的修改范围。
