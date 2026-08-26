# CausalAgent 技术文档

文档职责：作为 `Document/` 当前技术事实库的入口，定义各主题的唯一权威归属和阅读路径。

适用范围：面向开发者和 AI agent 的系统架构、API、数据库、开发运维与管理员模块说明；执行约束以根目录和局部 `AGENTS.md` 为准。

## 使用方式

`Document/` 描述系统当前是什么、如何工作以及为什么这样设计。文档中的命令、路由、表名和配置必须以当前代码、迁移、Compose 和测试入口核对后为准；若实现与文档冲突，应先修正文档事实或指出实现偏移，不应把旧文档当作代码依据。

执行规则见根目录 [`AGENTS.md`](../AGENTS.md) 以及各实现目录的局部规则文件。文档职责与修改边界见 [`development/documentation.md`](development/documentation.md)。

## 文档导航

### 架构

- [`architecture/overview.md`](architecture/overview.md)：进程边界、主要数据流、运行拓扑和组件职责。
- [`architecture/agent-runtime.md`](architecture/agent-runtime.md)：Web、Agent worker、LangGraph、MCP、生产 RAG runtime、结构化输出和用户事件流。
- [`architecture/rag-evaluation.md`](architecture/rag-evaluation.md)：隔离评测的来源、staged index、数据集、release、评测 worker 和生产切换边界。
- [`architecture/job-file-lifecycle.md`](architecture/job-file-lifecycle.md)：Session、Job、输入账本、文件库、checkpoint 与跨库清理生命周期。

### API

- [`api/conventions.md`](api/conventions.md)：鉴权、CSRF、request ID、错误结构、分页、敏感内容和 SSE 通用约定。
- [`api/agent-jobs.md`](api/agent-jobs.md)：分析 Job 创建、恢复、取消、幂等与 SSE。
- [`api/chat-files.md`](api/chat-files.md)：普通用户会话、消息和文件接口。
- [`api/rag-eval.md`](api/rag-eval.md)：`/api/rag_eval` 完整 HTTP、长任务、SSE 和兼容路径契约。

### 数据库

- [`database/overview.md`](database/overview.md)：MySQL 业务数据、PostgreSQL checkpoint 和跨库边界。
- [`database/consistency.md`](database/consistency.md)：主从读写、一致性级别、账号职责和连接池。
- [`database/migrations-checkpoints.md`](database/migrations-checkpoints.md)：bootstrap、Alembic、checkpoint setup、cleanup outbox 与迁移风险。
- [`database/monitoring.md`](database/monitoring.md)：monitor worker、共享快照、在线配置、quick/deep audit 和 cleanup 运行状态。

### 开发

- [`development/setup.md`](development/setup.md)：本地、Docker 和管理员前端开发入口。
- [`development/testing.md`](development/testing.md)：后端、前端、集成和隔离 E2E 验证矩阵。
- [`development/deployment.md`](development/deployment.md)：镜像构建、开发/生产 Compose 拓扑和发布边界。
- [`development/documentation.md`](development/documentation.md)：文档归属、维护、链接和日志规则。

### 管理员模块

- [`admin/README.md`](admin/README.md)：管理员模块边界与内部索引。
- [`admin/architecture.md`](admin/architecture.md)：Flask 管理员 API、Vue 页面、鉴权和共享能力消费关系。
- [`admin/api.md`](admin/api.md)：管理员页面和 API 的完整契约。
- [`admin/development.md`](admin/development.md)：管理员前端构建、开发入口和发布依赖。
- [`admin/testing.md`](admin/testing.md)：管理员专项单元、Mock E2E 和隔离主从验收。

## 归属原则

系统级 checkpoint、cleanup worker、MySQL 主从、数据库连接和 monitor 内部机制只在 `database/` 维护；管理员页面如何消费这些能力只在 `admin/` 维护。生产 Agent Job、文件冻结和普通用户 SSE 的业务生命周期只在架构/API 对应页面维护；隔离 RAG 评测、来源、staged index、release 和 `rag-eval-worker` 只在 `architecture/rag-evaluation.md` 与 `api/rag-eval.md` 维护，管理员 API 只引用其消费契约。
