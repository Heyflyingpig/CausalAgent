# Agent 运行时

文档职责：记录 Agent worker、LangGraph、MCP、RAG、结构化输出和执行事件的当前协作方式。

适用范围：修改 `Agent/`、`app/agent/worker/`、MCP server、RAG 初始化或用户可见事件协议时使用；Job 的持久化生命周期见 [`job-file-lifecycle.md`](job-file-lifecycle.md)，执行约束见 [`../../Agent/AGENTS.md`](../../Agent/AGENTS.md)。

## Worker 启动与 slot

`python -m app.agent.worker` 进入 `app/agent/worker/__main__.py`，再调用 bootstrap。启动顺序是数据库就绪检查、PostgreSQL checkpoint 检查、创建显式进程 runtime，然后按 `JOB_WORKERS` 启动 slot。每个 slot 持有一组独立运行依赖：

1. MCP server process 与一个通过 `MultiServerMCPClient.session("causal")` 建立的持久 `ClientSession`。
2. 由该 session 加载的 LangChain tools。
3. 当前配置下的 LLM、RAG 可用性和编译后的 Agent graph。

`runtime.py` 通过 `ProcessRuntime` 和 `SlotRuntime` 显式传递这些对象；执行函数不能从 `app.agent.core` 读取全局 graph 或 LLM。这样可以把真实并发单元限定为 slot，并让 MCP session 与 graph 的生命周期一致。

## 父图与工具阶段

父图当前只暴露 `mcp` 和 `rag` 两个工具阶段。MCP 子图的正常路径为 `mcp_planner -> mcp_tool_node -> mcp_result_parser`；RAG 子图内部对应 `rag_question_planner -> rag_tool_node -> rag_result_parser`。planner、ToolNode 和 parser 的失败路径在子图内转换为标准 `success=False` 结果并结束该阶段，不把异常对象直接写入用户事件。

结构化输出统一通过 `Agent/llm_structured_output.py` 的同步/异步入口调用，固定使用普通 `function_calling`。结构化请求会关闭 thinking；MCP planner 仍使用原生 Tool Calls，并对关闭 thinking 的 LLM 副本设置 `tool_choice="required"`，确保 planner 必须选择一个已加载工具。`agent` 和 `fold` 的条件路由只读取显式 State 字段 `route_decision`、`fold_decision`，不使用展示消息猜测控制流。

RAG 启动时只检查知识库目录是否可用，不在 worker 启动阶段完整加载向量库；知识库缺失时记录 warning 并以无知识库模式继续。DirectLiNGAM 作为 `causal_direct_lingam` MCP 工具提供连续数值 CSV 分析，输出的系数矩阵约定为 `target_to_source`，报告需要保留线性、非高斯、误差独立、DAG 和无潜在混杂等假设。

## 事件流与脱敏

worker 使用 LangGraph v2 的 `updates`、`messages`、`custom` 和 `tasks` 流，将内部执行事件转换为 `analysis_job_events`。根图 `tasks` 构成用户时间线，子图工具事件折叠为 `mcp` 或 `rag` 阶段。普通用户 SSE 只允许 `normal_chat` 和 `inquiry_answer` 的公开文字进入 `text_delta`；原始 prompt、ToolMessage、完整工具结果、图状态、内部 attempt 和隐藏推理都不能进入普通用户协议。

事件写入由 Job 的 `lease_epoch`、worker、attempt 和稳定 `event_key` 共同保护。终态事件与 assistant 消息、Job 状态在同一个 MySQL 事务中落盘；旧 worker 失去 lease 后不能覆盖新执行结果。前端断线恢复使用 Event ID 读取 MySQL 事件，不依赖 worker 内存。

## 修改时的验证边界

- 修改图节点或路由时，必须核对显式 State 字段和失败路径，不能只验证成功样例。
- 修改事件适配器、结果展示或 SSE 时，必须确认公共 payload 没有内部字段和原始工具数据。
- 修改 worker 初始化时，必须同时检查 `runtime.py`、`bootstrap.py`、Docker Compose 的 worker 入口和 slot 资源占用。
- 修改结构化输出或 MCP planner 时，必须分别验证普通 function calling、thinking 配置和原生 Tool Calls。
- 修改 RAG 或因果工具时，必须分别验证“知识库缺失可启动”和工具输入/输出契约。
