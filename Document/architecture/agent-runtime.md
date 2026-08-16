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

父图当前只暴露 `mcp` 和 `rag` 两个工具阶段。MCP 子图的正常路径为 `mcp_planner -> mcp_tool_node -> mcp_result_parser`；RAG 子图内部对应 `rag_question_planner -> rag_tool_node -> rag_result_parser -> rag_finalize`。父图通过适配节点只向 RAG 子图传入 `messages`、`analysis_parameters`、`preprocess_summary` 和 `causal_analysis_result`，子图只投影 `rag_output` 为父图的 `knowledge_base_result`；RAG route、问题列表、ToolMessage 和解析中间结果不会进入父 State。

RAG Planner 在调用 LLM 前检查进程级 `rag_available` 和已注册的 `rag_tools`。知识库目录未初始化或工具列表为空时，Planner 写入私有 `rag_route=finish`、`rag_status=unavailable` 和统一降级中间结果，跳过 ToolNode，仍经 `rag_finalize` 回到父图的 Agent。正常 ToolNode 返回（包括 `success=False`）继续进入 Parser；ToolNode 或 Planner 的未捕获普通异常在重试结束后由 error handler 跳到 Finalize，Parser 异常标记为 `protocol_error` 后也进入 Finalize。

RAG 查询任务捕获普通查询、连接和目录异常时返回 `success=False`、`status=unavailable` 及 `error_type=RAGQueryError`，这表示知识库不可用，不表示 ToolMessage 协议错误。`parse_tool_message_json()` 遇到非法 JSON 时返回 `error_type=ToolMessageProtocolError`，RAG Parser 将其归类为 `protocol_error`；正常业务失败的 `success=False` 仍归类为 `unavailable`。所有路径最终由 Finalize 生成稳定的 `rag_output`，报告继续使用 `format_rag_summary_for_prompt()` 读取父图统一字段。

结构化输出统一通过 `Agent/llm_structured_output.py` 的同步/异步入口调用，固定使用普通 `function_calling`。结构化请求会关闭 thinking；MCP planner 仍使用原生 Tool Calls，并对关闭 thinking 的 LLM 副本设置 `tool_choice="required"`，确保 planner 必须选择一个已加载工具。`agent` 和 `fold` 的条件路由只读取显式 State 字段 `route_decision`、`fold_decision`，不使用展示消息猜测控制流。

RAG 启动时只检查知识库目录是否可用，不在 worker 启动阶段完整加载向量库；知识库缺失时记录 warning 并以无知识库模式继续。DirectLiNGAM 作为 `causal_direct_lingam` MCP 工具提供连续数值 CSV 分析，输出的系数矩阵约定为 `target_to_source`，报告需要保留线性、非高斯、误差独立、DAG 和无潜在混杂等假设。

## 事件流与脱敏

worker 使用 LangGraph v2 的 `updates`、`messages`、`custom` 和 `tasks` 流，将内部执行事件转换为 `analysis_job_events`。根图 `tasks` 构成用户时间线，子图工具事件折叠为 `mcp` 或 `rag` 阶段。普通用户 SSE 只允许 `normal_chat` 和 `inquiry_answer` 的公开文字进入 `text_delta`；原始 prompt、ToolMessage、完整工具结果、图状态、内部 attempt 和隐藏推理都不能进入普通用户协议。

事件写入由 Job 的 `lease_epoch`、worker、attempt、`execution_state=leased` 和稳定 `event_key` 共同保护。终态事件与 assistant 消息、Job 状态在同一个 MySQL 事务中落盘；旧 worker 失去 lease 或收到取消撤销后不能覆盖新执行结果。`JobExecutionGuard` 通过 LangGraph invocation runtime context 传递到父图、子图、ToolNode 包装器和 parser；节点开始、调用返回、异常处理、路由和事件持久化前均检查执行资格。`JobExecutionRevoked` 和 `asyncio.CancelledError` 是内部控制流，不进入 RetryPolicy、RAG 降级或公开 error 事件，必须继续向 worker 传播；普通 RAG 故障则在子图内收口并回到 Agent。前端断线恢复使用 Event ID 读取 MySQL 事件，不依赖 worker 内存。

普通异常的失败收敛会先在 Job 行锁内确认 worker、attempt、lease epoch 和 `leased` 状态；若锁住时发现业务取消，返回 `CANCELED_FENCED`，不再补写普通 `error` 事件。`OrderedEventWriter.abort()` 会丢弃未刷新的文字、结束排队 Future，并向调用方暴露消费协程的非预期异常；只有终态写入被接受后才设置 `terminal_seen`。worker 只有在 graph stream、EventWriter 和 heartbeat monitor 都完成 cleanup 后，才可以把 canceled/draining 执行占用标记为 `worker_confirmed`；cleanup 失败时保留 draining，交由租约回收路径处理。

普通用户历史与实时 SSE 共用字段白名单。历史阶段排除 `text_delta` 和所有边界事件，只重放节点、进度、决策、工具摘要、重试与节点结束；边界事件只在服务端用于阶段切分。页面刷新活动 Job 时，`load_session` 先重放已持久化节点事件并记录实际处理到的 `rendered_event_id`，随后活动 Job API 只补充状态，不能用数据库最新事件 ID 推进该游标；SSE 从 `rendered_event_id` 之后补发，避免加载与订阅之间的事件被跳过。

## 修改时的验证边界

- 修改图节点或路由时，必须核对显式 State 字段和失败路径，不能只验证成功样例。
- 修改事件适配器、结果展示或 SSE 时，必须确认公共 payload 没有内部字段和原始工具数据。
- 修改 worker 初始化时，必须同时检查 `runtime.py`、`bootstrap.py`、Docker Compose 的 worker 入口和 slot 资源占用。
- 修改结构化输出或 MCP planner 时，必须分别验证普通 function calling、thinking 配置和原生 Tool Calls。
- 修改 RAG 或因果工具时，必须分别验证“知识库缺失可启动”和工具输入/输出契约。
