# 可观测性日志契约与现状盘点

文档职责：冻结第一阶段 v1 运行日志的字段、安全边界、兼容规则和后续布点依据，记录当前代码中的日志来源与风险。

适用范围：Web、Job worker、monitor、MCP、数据库 bootstrap、checkpoint cleanup 等进程的运行日志；管理员审计日志、MySQL/PostgreSQL 引擎日志和浏览器开发者控制台不归入本契约。

## 1. 当前结论与实施边界

共享 JSON 日志运行时现已位于 [`observability/logging_runtime.py`](../../observability/logging_runtime.py)，并由 Web、worker、monitor、db-bootstrap 和 checkpoint-cleanup 入口配置。旧 `LogRecord` 继续通过标准 `logging` 输出为单行 JSON；MCP 已删除本地 `FileHandler`，其 stdio transport 的应用日志只写 stderr。Alloy/Loki/Grafana 仍留在第 1.3 步。

当前代码中的旧日志不被伪造分类。无法可靠判断的 `event_code` 和 `category` 保持 `null`；只有新增的受管事件才提供完整 v1 分类。事件详情的业务字段白名单仍由后续业务布点负责，运行时只做递归脱敏、JSON object 形状校验和体积边界保护。

## 2. v1 JSON 契约

### 2.1 通用字段

目标输出是单行、UTF-8、合法 JSON。所有记录都应具备下表中的基础字段；`event_code` 和 `category` 对旧记录可以为空，对新增受管事件必填。

| 字段 | 类型/约束 | 规则 |
| --- | --- | --- |
| `timestamp` | string | UTC RFC3339，使用 `Z` 表示 UTC；不使用本地时间 |
| `level` | string | 仅允许 `debug`、`info`、`warning`、`error`、`critical` |
| `service` | string | 仅允许 `web`、`worker`、`monitor`、`mcp`、`maintenance` |
| `environment` | string | 当前部署环境名；不得包含密码、Token、连接串或主机凭据 |
| `event_code` | string/null | 受管事件使用小写点分式，例如 `logging.serialization_failed`；旧记录为 `null` |
| `category` | string/null | 受管事件仅允许 `request`、`lifecycle`、`dependency`、`security`；旧记录为 `null` |
| `message` | string | 经过脱敏的短摘要，不记录原始用户输入、提示词或文件正文 |
| `details` | object/null | 由 `event_code` 定义允许字段；禁止把任意请求 JSON 或异常对象原样放入 |
| `stack` | array/null | 仅异常记录可有；元素为清理后的栈帧摘要，不保留凭据、SQL 正文或文件正文 |
| `truncated` | boolean | 任一字段或整行发生截断时为 `true`，否则为 `false` |
| `logger`、`module` | string/null | 兼容旧 `LogRecord` 的来源信息，不作为高基数索引 |

`event_code` 必须匹配小写点分式约束：`^[a-z][a-z0-9]*(\.[a-z0-9]+)+$`。`category` 的四个值固定如下：

- `request`：HTTP 请求入口、参数拒绝和请求级结果；不携带正文。
- `lifecycle`：进程、Job、worker lease 和维护任务的启动、停止、状态转换。
- `dependency`：MySQL、PostgreSQL checkpoint、LLM、MCP、RAG 等外部依赖的可观测结果。
- `security`：认证、授权、敏感读取和安全策略拒绝；只记录结论和稳定原因码。

### 2.2 关联字段和标签边界

`request_id`、`user_id`、`session_id`、`job_id`、`worker_slot`、`node`、`tool`、`instance` 只能作为 JSON 字段。它们不进入 Loki 标签，不在日志采集层建立索引；后续 Alloy 仅把低基数的 `service` 映射为 `service_name`，并按 `environment`、`level`、`category` 选择标签。

`details` 必须按事件码定义字段白名单。允许记录稳定 ID、状态、数量、耗时、大小、原因码和布尔结论；禁止记录提示词、完整工具结果、文件名以外的文件正文、Cookie、Token、密码、数据库连接串、原始 SQL 参数和任意用户输入。文件大小只能记录经过授权的字节数统计，不能以日志内容代替文件访问。

### 2.3 体积、异常和降级

所有限制按 UTF-8 字节数计算：

| 部分 | 上限 |
| --- | ---: |
| `message` | 2 KiB |
| 序列化后的 `details` | 4 KiB |
| `stack` | 8 KiB，最多 20 帧 |
| 完整 JSON 行 | 16 KiB |

超限时必须先截断可截断字段，再保证输出仍是合法 JSON，并设置 `truncated=true`。不得为了保留大字段而丢掉 `timestamp`、`level`、`service`、`environment`、`event_code`、`category` 和稳定错误结论。序列化失败的统一事件码固定为 `logging.serialization_failed`，降级路径不得再次通过同一 logger 递归记录失败。

## 3. 当前日志来源盘点

以下是基于当前源码的静态盘点；仓库没有运行期计数器或代表性负载数据，因此“产生速率”暂记为未测量，不能从源码行数推导每秒日志量。

| 服务/来源 | 当前入口和输出 | 已观察到的内容 | 第 1.2 步风险/动作 |
| --- | --- | --- | --- |
| `web` | `CausalAgent.py`、`app/__init__.py`；入口配置共享 JSON stderr handler | Web 启动、数据库检查、聊天/文件/认证/管理员路由日志；旧业务消息仍可能带高基数文本，后续按布点清单收敛 | 已统一 JSON stderr；readiness 失败不再 `print`，新增启动成功/失败受管事件 |
| `worker` | `app/agent/worker/__main__.py`、`bootstrap.py`、`runtime.py`、`execution.py` | slot、Job、worker、工具和执行异常；异常使用 `exc_info=True` 的路径较多 | 已增加稳定启动事件并清理异常栈；Job/工具业务字段留到后续布点 |
| `monitor` | `Database/monitor_worker.py`、`Database/monitoring.py`、`app/db.py` | 快照更新、慢查询、从库回退、readiness 和采集异常 | 已统一 JSON stderr；慢查询 SQL 正文的业务布点收敛仍属后续工作 |
| `maintenance` | `Database/bootstrap.py`、`Database/database_init.py`、`Database/checkpoint_setup.py`、`Database/checkpoint_cleanup_worker.py`、`Database/audit_before_db_upgrade.py` | bootstrap、checkpoint setup、cleanup Job ID/attempt 和数据库初始化结果 | 已统一维护入口日志；移除 `database_init.py` 的文件 handler，数据库凭据/连接元数据不进入新受管详情 |
| `mcp` | `Agent/CausalAgentMCP/mcp_server.py` 作为 worker 内 stdio 子进程运行 | 工具读取文件的字节数、工具失败栈和启动/关闭消息 | 已删除本地文件日志；应用日志只进 stderr，stdout 留给 MCP 协议。当前 MCP stdio client 将子进程 stderr 绑定到 worker stderr，因此不增加重复转发线程 |

### 3.1 `print`、文件日志和非服务输出

- `app/__init__.py` 的 readiness 异常已改为受管错误事件，不再把异常原文写到标准输出。
- `Database/database_init.py` 的 CLI 提示仍是人工命令行输出；其应用日志不再配置 stdout 或本地文件，直接运行时由维护日志运行时接管。
- `Database/lifecycle_repair.py` 和 `Database/mysql_checkpointer.py` 的 `__main__`/修复演示输出属于人工 CLI 或测试工具，不纳入应用日志采集；后者当前还会打印 checkpoint ID 和 State 内容，不能在生产流程调用或迁移为受管日志。
- `Run_causal.py` 和 `app/static/js` 的 `print`/`console.log` 属于桌面或浏览器客户端，不进入容器日志；其中的会话、用户名和 SSE 调试信息也不应被误认为服务端审计日志。
- `Agent/CausalAgentMCP/mcp_server.py` 不再创建应用文件日志；MySQL `/var/lib/mysql/mysql-slow.log` 属于数据库引擎日志，第一阶段明确不采集。

### 3.2 敏感内容、重复和异常栈风险

静态扫描确认以下位置仍需要在后续业务日志布点阶段逐项改造或加测试：

1. `app/chat/routes.py` 和相关服务使用 f-string/格式化参数记录用户名、会话 ID、标题和异常；标题属于用户输入，不能进入消息或 `details`。
2. `Agent/tool_node/rag_questions.py` 直接记录 LLM 生成的问题列表。问题可能由当前任务摘要派生，必须改成数量、稳定类型和耗时，不记录问题正文。
3. `app/db.py` 的慢查询日志会把规范化 SQL 字符串放入消息；即使多数语句使用占位符，也不能把 SQL 文本作为 v1 受管消息，需改为耗时、操作类型和安全 digest/原因码。
4. `app/agent/worker/execution.py`、MCP server、数据库 bootstrap 和多个路由使用 `exc_info=True` 或记录异常原文；栈帧必须清理，禁止出现连接串、文件正文、Token、提示词和数据库账号。
5. Web、worker、monitor、bootstrap、checkpoint cleanup 和数据库脚本现在由共享运行时幂等收敛；后续新增维护入口也必须复用该配置，不能重新调用 `basicConfig()`。
6. `Database/database_init.py` 和 `app/db.py` 当前会记录 host、database 名称或连接异常摘要；这些连接元数据不能进入新的受管日志字段，失败只能保留稳定原因码。

## 4. 第二阶段日志布点清单

下表只定义候选事件和允许的最小字段，本步不批量改写业务日志。事件码落地时必须继续遵守本文件的格式、分类和禁止项。

| 进程 | 候选事件码 | 分类 | 可记录字段/详情 | 明确禁止 |
| --- | --- | --- | --- | --- |
| Web | `web.startup.ready`、`request.rejected`、`job.create.accepted`、`job.create.replayed` | `lifecycle`/`request` | `request_id`、`user_id`、`session_id`、`job_id`、状态、原因码、耗时 | 消息正文、标题、Cookie、Token、完整请求体 |
| Worker | `worker.startup.ready`、`worker.job.claimed`、`worker.job.finished`、`worker.job.failed` | `lifecycle` | `job_id`、`worker_slot`、attempt、lease 结论、耗时、稳定错误码 | prompt、ToolMessage、模型输出、完整异常文本 |
| Monitor | `monitor.startup.ready`、`monitor.snapshot.updated`、`monitor.snapshot.failed` | `lifecycle`/`dependency` | 快照键、计数、耗时、source 逻辑别名、warning 结论 | host、账号、grants、SQL 正文 |
| MCP | `mcp.startup.ready`、`mcp.tool.finished`、`mcp.tool.failed` | `lifecycle`/`dependency` | `job_id`、`tool`、字节数、耗时、稳定错误码 | CSV 正文、工具完整结果、stdout 应用日志 |
| Maintenance | `maintenance.startup.ready`、`checkpoint.cleanup.succeeded`、`checkpoint.cleanup.failed` | `lifecycle`/`dependency` | `job_id`、attempt、outbox 状态、耗时、失败原因码 | PostgreSQL 状态正文、连接信息、原始 `last_error` |

## 5. 验收记录和后续边界

- 第 1.1 步验收：契约字段、五类 service、四类 category、事件码格式、脱敏禁录项、各级体积限制、旧记录 `null` 过渡规则和 Job 请求关联必须无歧义。
- 第 1.2 步已补充 `tests/unit/test_logging_runtime.py` 和 `tests/unit/agent/test_mcp_logging_transport.py`，覆盖 UTC/Unicode、上下文隔离、线程与异步任务隔离、递归脱敏、各级截断、异常栈清理、重复初始化、序列化失败和 MCP stdout/stderr 边界。
- 第 1.3 步验收：Compose、Alloy/Loki/Grafana、五类测试事件、标签低基数、positions 重启、Loki 不可用时的非阻塞和代表性负载数据必须在真实 Docker 环境验证。
- 目前没有真实运行速率、行数、字节数或 stream 数证据；没有 Docker daemon 时不得把本地 unit 测试或静态扫描当作端到端日志验收。

相关权威事实见 [`API 通用约定`](../api/conventions.md)、[`分析 Job API`](../api/agent-jobs.md)、[`Job 与文件生命周期`](../architecture/job-file-lifecycle.md) 和 [`迁移与 Checkpoint`](../database/migrations-checkpoints.md)。
