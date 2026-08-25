# 系统架构总览

文档职责：记录 CausalAgent 当前的进程边界、组件职责、运行拓扑和主要数据流。

适用范围：修改 Flask 应用注册、Web/worker/monitor/cleanup 进程、Compose 服务或跨组件数据流时使用；Job 和文件的细粒度生命周期见 [`job-file-lifecycle.md`](job-file-lifecycle.md)。

## 系统边界

CausalAgent 的 Web 入口是 `CausalAgent.py`，它调用 `app/__init__.py` 的 `create_app()`。应用启动时先执行数据库就绪检查，再注册 `auth`、`chat`、`files`、`agent`、`main`、`admin` 和 `admin_page` 七个 blueprint。Web 进程只负责认证、短请求、Job 入队和 SSE 推送，不在请求线程中执行 Agent、MCP 或 RAG 长任务。

桌面入口 `Run_causal.py` 固定加载 `http://127.0.0.1:5001`，因此桌面模式仍依赖 Web 后端先启动。普通用户前端是 Flask 静态资源；管理员前端是独立的 Vue 3 + TypeScript 工程，但生产运行时由 Flask 提供构建后的同源静态文件。

## 进程与职责

| 组件 | 当前入口 | 主要职责 | 持久化边界 |
| --- | --- | --- | --- |
| Web | `python CausalAgent.py` 或 Gunicorn `CausalAgent:app` | 认证、会话/文件短请求、Job 入队、普通用户 SSE、管理员 API | MySQL 业务表；读取 PostgreSQL 安全摘要 |
| Agent worker | `python -m app.agent.worker` | 领取 Job、运行 LangGraph/MCP/RAG、写事件和终态结果 | MySQL Job/Event；PostgreSQL LangGraph checkpoint |
| monitor | `python -m Database.monitor_worker` | 采集 MySQL/PostgreSQL 运行事实并写共享快照 | MySQL monitor 快照和在线配置 |
| checkpoint cleanup | `python -m Database.checkpoint_cleanup_worker` | 消费 MySQL outbox 并删除 PostgreSQL Job checkpoint | MySQL outbox；PostgreSQL checkpoint |
| db-bootstrap | `python -m Database.bootstrap` | 建库、Alembic migration、PostgreSQL checkpoint schema setup | 修改初始化目标数据库 |

worker 的实际执行单元是 slot。一个 worker 进程可以启动多个 slot；每个 slot 独占自己的 MCP server process、持久 MCP `ClientSession`、已加载工具和编译后的 Agent graph。具体运行时约束见 [`agent-runtime.md`](agent-runtime.md)。

## 主要数据流

```mermaid
flowchart LR
    Browser[普通用户或管理员浏览器] --> Web[Flask Web]
    Web -->|strong write/read| MySQL[(MySQL 主库)]
    Web -->|SSE 轮询| Events[(analysis_job_events)]
    Worker[Agent worker slots] -->|领取 Job / 写 Event| MySQL
    Worker -->|checkpoint| PostgreSQL[(PostgreSQL checkpoint)]
    Web -->|只读安全摘要| PostgreSQL
    MySQL -->|checkpoint_cleanup_outbox| Cleanup[cleanup worker]
    Cleanup -->|adelete_thread(job_id)| PostgreSQL
    Monitor[monitor worker] -->|采集| MySQL
    Monitor -->|quick/deep 只读检查| PostgreSQL
    MySQL --> Snapshots[(database_monitor_snapshots)]
    Snapshots --> Web
```

跨库删除不使用分布式事务。MySQL 业务删除和 cleanup outbox 在同一 MySQL 事务提交，cleanup worker 之后异步删除 PostgreSQL checkpoint；用户接口和管理员操作查询接口分别暴露后台清理状态。

## Docker 拓扑

默认开发 Compose `docker-compose.yml` 当前包含八个服务：`mysql-primary`、`mysql-replica`、`postgres-checkpoint`、`db-bootstrap`、`app`、`worker`、`monitor` 和 `checkpoint-cleanup`。`db-bootstrap` 成功后，依赖它的运行服务才启动；开发拓扑没有自动故障切换。

当前生产 Compose `docker-compose.prod.yml` 实际使用生产命名的 MySQL、`app`、`monitor`、`rag-eval-worker` 和 `db-bootstrap` 服务，未定义 Agent worker、PostgreSQL checkpoint 或 checkpoint cleanup；它不是开发拓扑的自动升级版。生产 Agent worker/checkpoint 拓扑需后续单独核对，不能由本轮 spec 凭空补造。部署入口见 [`../development/deployment.md`](../development/deployment.md)。

## 组件边界

- `app/` 负责 HTTP、认证、持久化服务编排和 Job worker 外壳，不承载因果算法实现。
- `Agent/` 负责 LangGraph 图、结构化输出、MCP/RAG 工具节点和因果工具。
- `Database/` 负责连接、迁移、bootstrap、monitor、checkpoint setup 和 cleanup worker。
- `admin-frontend/` 只负责管理员页面与 API 消费，不替代 Flask 后端，也不直接连接数据库。
- `Document/admin/` 只描述管理员如何消费系统能力；数据库内部机制归 `Document/database/`。

修改这些边界时，必须同时核对对应目录的局部 `AGENTS.md` 和本页链接的权威文档。
