## 更新日志

---
2025.5.9
- 【内容新增】：完成LLM chat框架的全构建
- 【内容新增】：统一数据库，增强安全性和规范性
- 【内容新增】：增加CSV文件上传功能
- 【内容新增】：增加文件上传的后端校验功能

---
2025.5.10
- 【内容新增】：完成MySQL数据库的构建
- 【内容新增】：将后端服务部署至服务器
- 【性能提升】：引入gunicorn，优化前后端交互模式

---
2025.5.11
- 【性能提升】：成功部署gunicorn，支持多用户并行登录
- 【内容新增】：实现Flask会话加密与多用户登录密钥检测
- 【bug修复】：修复了MySQL数据库的错误实现

---
2025.6.11
- 【内容新增】：实现MCP（Method Call Protocol）的初步演示
- 【性能提升】：构建异步任务逻辑，提升回答函数性能

---
2025.6.12
- 【内容新增】：实现基础的PC因果发现算法库
- 【内容新增】：连通MCP与因果库，允许LLM按需调用
- 【内容新增】：集成vis-network库，实现交互式因果图渲染
- 【内容新增】：增加LLM上下文理解功能（支持20轮对话）
- 【性能提升】：创建后台asyncio事件循环以支持异步任务
- 【内容新增】：实现历史会话中因果图的保存与加载
- 【性能提升】：优化多用户并行登录逻辑
- 【内容新增】：增加前端加载动画效果
---
2025.6.14
- 【性能提升】：分离数据库初始化脚本，提高系统健壮性

---
2025.6.15
- 【bug修复】：修复了AI回复时加载动画不消失的问题
- 【bug修复】：修复了特定场景下AI错误回复"上传成功"的问题
- 【bug修复】：修复了MCP在处理多文件上传时无响应的问题
- 【内容新增】：增加文件检查逻辑，支持同名文件更新
- 【内容新增】：优化了前端界面样式

---
2025.6.15
- 【内容新增】：重构数据库，增加归档和分区功能
- 【数据库更新内容】(Document/Database_NOTES.md)
- 【内容新增】：更新前端样式以适配新版数据库
- 【内容新增】：调整后端逻辑以适配新版数据库

---
2025.6.16
- 【内容新增】：增加会话标题可编辑功能
- 【内容新增】：增加会话标题实时预览功能
- 【内容新增】：在设置中新增操作手册与用户隐私协议

---
2025.6.17 晨
- 【内容新增】：完成后端对会话标题编辑功能的支持
- 【内容新增】：增加会话列表的删除功能，现在可以向左滑动删除会话啦
- 【内容新增】：增加模糊搜索，现在用户不需要指定文件名，也可以调用因果分析功能
- 【BUG修复】：修复了AI回复时加载动画不消失的问题
- 【BUG修复】：修复了创建新会话的时候显示错误的问题

---
2025.6.17 晚
- 【内容新增】：增加文件列表功能，现在可以查看上传的文件列表啦
- 【内容新增】：文件库设计，文件库对齐
- 【内容新增】：增加文件删除功能
- 【BUG修复】：增加文件哈希大小检测，不只是检测文件名
- 【内容新增】：css文件增加注释，方便后续维护
- 【内容新增】：增加文件引用功能，现在点击文件可以在聊天框引用啦
- 【BUG修复】：修复了文件列表滚动后内容显示不正确的问题
- 【BUG修复】：修复了按下文件名之后，清空输入框的问题
---
2025.6.21
- 【内容新增】：设置页面的md格式支持
- 【内容新增】：消息支持复制

---
2025.6.23
- 【BUG修复】：修改会话更新逻辑

---
2025.7.1
- 【BUG修复】：修复ai回复时禁用输入框逻辑

---
2025.7.6
- 【内容新增】：重置与ai交互逻辑，新增agent智能体和langchain架构，对mcp进行重新架构升级，对参数接口进行统一，现在回复是基于agent啦

---
2025.7.7
- 【内容新增】：系统完美集成了rag和mcp功能，生成报告的时候会查询知识库，生成一份更加详细的报告了
- 【内容新增】：集成langsmith，可以在后端查看具体的调用结果
- 【bug修复】：修复用户新建对话时，无论是否发送消息都创建新的会话的问题，增加延迟会话逻辑，会话等待逻辑

---
2025.7.14
- 【内容新增】：加载密匙逻辑全面更改
- 【内容新增】：全面重构agent逻辑，新增langgraph逻辑

---
2025.8.7
- 【内容新增】：全面重构agent，增加langgraph图，节点，边关系构建
- 【内容新增】：增加后处理逻辑，增加报告生成逻辑，增加预处理逻辑

---
2025.8.13
- 【内容新增】： 补充agent中文件加载节点，预处理节点部分功能实现

---
2025.8.16
- 【内容新增】： 拓展fold节点，增加数据分析内容，增加数据内容验证文件

---
2025.9.17
  - 【内容新增】： 补充fold节点，增加数据分析内容，增加数据内容验证文件。
  - 目前对于用户上传文件可以进行初步判断，对于不合理的数据进行人工干预，对于需要更改数据提出建议，后期再进行更改。用户需要补充目标变量和处理变量才可以进行因果分析。

---
2025.9.18
  - 【内容新增】： 补充预处理节点，增加数据分析内容，增加数据内容可视化，增加数据内容总结。
  - 【内容新增】： 补充rag节点，增加知识库查询功能，补充mcp调用causal-learn因果分析算法。

---
2025.9.20
  - 【内容新增】： 补充human节点，增加人机交互过程

---
2025.10.14
  - 【内容新增】： 补充后处理节点，增加后处理功能
  - 【内容新增】： 后处理节点：1. 查看是否有环路，如果存在环路，则使用LLM辅助决策进行修正。2. 查看是否有不合理边，如果存在不合理边，则使用LLM辅助决策进行修正。

---
2025.10.19
  - 【结构重置】：重构代码中人设部分
  - 【结构重置】：重构数据库连接

---
2025.10.22
  - 【bug修复】： 解决agent路由的bug问题，目前可以正常跑通

---
2025.10.23
  - 【bug修复】：修复agent中的用户暂停逻辑
  - 【bug修复】：修复agent当中的文件上传逻辑

---
2025.10.26
  - 【内容新增】：增加langgraph中的checkpoint支持,重构langgraph的节点逻辑
  - 【内容新增】：实现mysql数据库的langgraph checkpoint功能，实现同步/异步方法
  - 【内容新增】：增加inquiry_answer节点，实现对用户追问的回答
  - 【bug修复】： 修复目前节点的reducer机制，修复state中的reducer机制，实现消息记录的补充说明
  - 【bug修复】： 主程序对checkpoint的响应逻辑补充，补充config配置，修复对多次回答的逻辑缺失
  - 【内容新增】：补充Alembic数据库迁移功能

---
2025.10.28
  - 【内容重构】：重构工具执行节点，封装@task工具，支持数据库的task支持
  - 【bug修复】：重构human in loop节点，支持interrupt机制，支持用户输入的传递

---
2025.10.31
  - 【内容新增】：docker部署

---
2025.11.2
  - 【BUG修复】：修复用户注册密码加密问题，使用bcrypt进行加密

---
2025.11.6
  - 【内容新增】：增加思考过程气泡和详情面板，支持思考过程的展示和展开/收起
  - 【内容新增】：支持SSE流式传输节点，支持显示思考进度
  - 【内容新增】：支持ai的流式传输重构

---
2025.11.11
  - 【内容新增】：增加预处理图表支持，完善报告生成
  - 【内容新增】：数据库中支持可代替图表生成

---
2025.11.16
  - 【内容新增】：优化报告样式

---
2025.11.21
  - 【重构】：重构Agent目录关系，增强结构可读性，修改模块内部导入路径，修改目录层级关系,修改引用关系
  - 【重构】：重构flask框架，增加blueprint，增加app目录，修改CausalAgent主文件，适配目前APP文件目录，修改模块内部导入路径
  - 【bug修复】：修复docker由于目录重置导致的问题，修改目录关系


---
2025.11.26
  - 【内容新增】：完善MCP机制，支持动态选择不同算法
  - 【内容新增】：新增olc算法支持

---
2025.12.18
- 【重构】：更名为CausalAgent

---
2026.3.20
- 【内容重构和新增】：
  - 重构了查询主链路， dense 检索 -> MMR -> sparse 检索 -> 候选融合重排 -> 证据块构造 -> 结构化回答 -> 证据链输出。
  - 重构了知识库构建脚本，在 build_knowledge.py 中补齐了文档级和 chunk 级 metadata，包括 doc_id、chunk_id、doc_type、corpus、page 等，为后续检索过滤、证据链保存和评测提供基础。
  - 重构了问题生成模块，在 rag_questions.py 中把 RAG 问题从字符串列表升级为结构化对象，新增 intent、priority、why_needed，让知识库查询更贴近报告增强目标。
  - 重构了任务与状态传递，在 rag_query_task.py 和 state.py 中把 knowledge_base_result 从字符串改为结构化结果，保证 LangGraph 流程中可以传递完整证据链。
  - 适配了下游消费逻辑，在 nodes.py、fix_cycles.py、evaluate_edge_llm.py 中增加了摘要转换逻辑，使报告生成、环路修正和边评估都能消费结构化 RAG 结果，而不是依赖旧的字符串结果。
  - 增加了混合检索能力：dense 检索负责语义召回，sparse 检索负责关键词召回。
  - 增加了 MMR 去重能力，减少相似 chunk 重复进入最终证据集合。
  - 增加了轻量级融合重排逻辑，综合 dense 分数、sparse 分数、语料类型和双路命中情况得到最终 rerank_score。
  - 新增了评测脚本 rag_eval.py，当前支持检索层指标 Recall@k、Precision@k、MRR、Hit Rate，以及轻量级生成层关键点覆盖评测。
  - 新增了 metadata 导出脚本 export_metadata.py，

---
2026.5.17
**重要更新**
- 【内容新增与重构】：
  - 建立了更完整的数据库迁移链：新增核心业务表基线迁移，并补上 checkpoint 迁移依赖关系。
  - 将 `Database/database_init.py` 从“直接创建业务表”改为“数据库引导脚本”，业务表结构正式交给 Alembic 维护。
  - 在 `app/db.py` 中完成数据库访问分层：写连接、业务读连接、复制状态检查连接三条路径分离，并加入连接池、弱一致读回退和慢查询告警。
  - 新增主从开发拓扑 `docker-compose.replica.yml` 及 MySQL primary/replica 初始化脚本，支持 GTID、半同步复制、慢查询日志和应用侧读写分离验证。
  - 新增数据库审计脚本、轻量监控接口和一组覆盖配置解析、连接边界、迁移链、主从初始化、失效会话保护的测试。
  - 修复旧实现中多个容易在生产化阶段暴露的问题，包括：应用误用业务账号执行 `SHOW REPLICA STATUS`、数据库初始化职责和 Alembic 迁移职责重叠、旧 session 在用户数据失效后仍可能继续访问接口、上传文件缺少体积上限等。
- 【修复问题】
  - 修复数据库初始化与迁移职责重叠的问题
   旧版 `Database/database_init.py` 同时负责建库、建表、建索引和部分结构逻辑，容易与 Alembic 演进冲突。现在它只负责确保数据库存在和连接可用，结构统一由迁移脚本维护。
  - 修复主从读写边界不清的问题
   旧代码主要通过单一路径访问 MySQL，主从环境下很难明确“哪些查询必须强一致、哪些查询允许弱一致”。本轮将强一致读、弱一致读和写入路径拆开，并在弱一致读失败时自动回退主库。
  - 修复复制状态检查权限模型不干净的问题
   旧设计容易让应用继续用业务账号执行 `SHOW REPLICA STATUS`。现在新增专用状态账号；未配置该账号时，系统会安全回退主库，而不是继续误用高权限账号。
  - 修复旧 session 残留导致的伪登录状态问题
   当浏览器 session 还在、但数据库中的用户已失效时，原逻辑可能继续把请求当作已登录。现在引入 `app/auth/session_guard.py`，会在鉴权时校验真实用户，不存在则清空 session。
  - 修复上传文件缺少大小上限的问题
   文件上传现在新增 `MAX_UPLOAD_SIZE_MB` / `MAX_UPLOAD_SIZE_BYTES` 限制，避免过大文件直接写入 `uploaded_files.file_content`。
  - 修复迁移链起点不完整的问题
   新增 `1a2b3c4d5e6f_create_core_schema.py` 作为核心 schema 基线，并让 checkpoint 迁移依赖它，避免空库初始化只能依赖历史手工建表。

---
2026.5.18
**重要更新**
- 【内容新增与重构】：
  - 任务创建、任务领取、事件写入和 SSE 推送已经拆分到不同层，Web 不再直接承担长任务执行。
  - 新增 `analysis_jobs` 与 `analysis_job_events` 数据库作为任务队列和事件流的持久化数据库。
  - 后台 worker 以 slot 为单位持有独立 MCP session 和 Agent graph，避免 Web 进程阻塞。
  - 同一 `user_id + session_id` 的并发任务通过唯一约束兜底，防止重复执行。
  - 旧接口 `POST /api/send_stream` 已转为迁移提示，前端改走 `POST /api/agent/jobs` 与 SSE 订阅。

---
2026.5.26
- 【内容新增】
  本次改造是在不改变现有架构的前提下，引入 LangGraph 1.2 的节点级容错能力。已完成依赖升级门禁、LangChain v1 兼容迁移、节点 async 化、MCP/RAG task 异步化，以及基于 `retry_policy / timeout / error_handler` 的集中容错策略。

- 【bug修复】
  - 升级到 langgraph-checkpoint==4.1.1 后，JsonPlusSerializer 不再有 dumps/loads，新版接口是 dumps_typed/loads_typed。
  - 修复前端报告占位符问题

---
2026.5.29
- 【内容新增】
  - 将原先集中在 `execute_tools_node` 的 MCP 因果分析与 RAG 查询拆分为父图中的 `mcp`、`rag` 两个业务阶段节点，并将工具调用细节封装在各自的 compiled subgraph 内。
  - 支持原生 LangChain ToolNode 调用。

---
2026.5.30
- 【BUG修复】
  - 修复外键写入、LangGraph checkpointer 写 MySQL 与 RAG 格式化问题。

---
2026.5.31
- 【BUG修复】
  - 梳理 ToolNode 的标准消息协议。
  - MCP worker 主路径迁移到 `langchain-mcp-adapters`：每个 slot 通过 `MultiServerMCPClient.session("causal")` 维护持久 session，并用 `load_mcp_tools(session)` 加载 ToolNode 可执行工具。

---
2026.7.10
- 【内容修复】
  - 修复 PC、OLC 因果边在后处理中的格式和矩阵方向不一致问题。
  - 环路修订会生成实际的修订图，最终 SSE、前端展示和历史会话统一使用该图；结构异常时安全回退原图。
  - 统一结构化输出配置入口，Compose 曾支持可切换的结构化输出模式，并移除 `LANGSMITH_*` 配置。
- 【验证】
  - 新增后处理、最终图选择和结构化输出配置测试；完整测试集已通过。
---
2026.7.22
- 【内容新增】
  - 完成数据库管理阶段一的最小管理员权限：`users.role` 仅支持 `user` / `admin`，历史用户默认保持普通用户。
  - 管理接口统一校验数据库中的实时角色和启用状态，未登录返回 `401`，普通用户返回 `403`。
  - 新增初始管理员提升命令 `python -m app.auth.admin_cli promote <username>`（本地运行）、`docker-compose -f docker-compose.replica.yml run --rm app python -m app.auth.admin_cli promote <username>`（docker运行），只允许幂等提升已注册且已启用的用户。
  - 登录与会话恢复固定使用主库强一致读，禁用用户无法登录，已有会话也会立即失效。

- 【BUG修复】
  - 修复删除已创建会话时遗留 MySQL checkpoint 的问题：会话、消息、附件和 checkpoint 现在在同一事务内删除，`checkpoint_writes` 由外键级联清理。
  - 删除流程会锁定目标会话并拒绝仍有 queued/running job 的会话，避免并发任务与删除操作交叉写入。
---
2026.7.23
- 【BUG修复】
  - 完整恢复 `bbcdf46` 误删的前端初始化、聊天交互、任务事件订阅、会话历史与删除逻辑，修复未登录首页显示空白的问题。

---
2026.7.23
- 【工程规范】
  - 新增 GitHub Actions 轻量 CI，对 `main`、`develop` 执行 Python 语法编译、无外部服务依赖的轻量测试和 Pull Request 策略检查。
  - 统一 Pull Request 标题格式，并明确 `feature -> develop -> main` 的合并路径。

---
2026.7.26
- 【BUG修复】
  - 修复 MCP 正常返回但载荷被包装为嵌套 `result`、二次 JSON 或缺少顶层 `success` 时，父图误判结果并重复执行 `agent -> fold -> preprocess -> mcp` 的问题。
  - MCP 服务端改为返回结构化字典；客户端兼容历史字符串载荷和 `structured_content` 包装，并将协议异常统一转换为 `success=False`。
  - 为 MCP planner、ToolNode 和结果 parser 补充失败出口；ToolNode 异常恢复后不再强行进入 parser，避免二次异常。
  - 修复mcp在返回tollcall时的文件内容错误
- 【json输出格式化】
  - 完成统一结构化调用器及业务调用点迁移，统一走langchain的toolcall方式，实现json格式调用
  - 完成 Agent、Fold 显式 State 路由和恢复路径调整。
  - 完成 RAG、MCP、环路修复和边评估失败降级。
  - 修复 MCP planner did not return tool_calls：补充 tool_choice="required"。
  

---
2026.7.22
- 【内容新增】
  - 完成数据库管理阶段一第二步管理员只读数据库看板：新增 revision、主从节点、连接、表容量、快速完整性、慢查询和 worker/job 只读检查。
  - 新增受统一管理员校验保护的 `/admin/database` 后台页面；管理员登录后只进入后台，普通用户继续进入聊天界面。
  - 后台使用 Flask 原生 HTML/CSS/JavaScript，建立白色简约左侧导航骨架，按钮仅使用蓝色和绿色，不提供 SQL、修复、迁移或数据库写入能力。
  - 旧管理接口保持 `data` 类型和旧字段兼容，新接口与新增元数据统一标记状态、逻辑来源、采集时间、估算属性和降级警告。
  - 升级前审计复用快速完整性检查，并扩展到 job、event、checkpoint 和 pending write 轻量孤立计数。

---
2026.7.22
- 【内容新增与重构】
  - 新增独立数据库 monitor 进程和 MySQL 共享监控快照，将实时状态、SQL 性能、表容量、完整性审计拆分为不同采集周期，管理 GET 接口只读取最近快照。
  - 新增聚合看板接口、共享手动刷新接口和独立完整性审计接口；自动刷新可以关闭，但仍保留首次读取与手动刷新。
  - 将 digest 区块更名为“SQL 性能摘要/高负载 SQL”，明确其按累计总耗时排序；慢查询告警改为优先使用采集窗口内 `Slow_queries` 增量。
  - 运行期完整性审计移除已有外键保证关系的全表孤立扫描，改为检查关键约束是否存在；升级前审计按 schema 和迁移需要决定是否执行，新库不再先跑 preflight。
  - 三套 Compose 增加 `monitor` 服务，并集中提供自动刷新、分层周期、慢查询告警和完整性审计配置。
---
2026.7.25
- 【内容新增与重构】
  - 管理员系统迁移到独立 `admin-frontend/`：使用 Vue 3、严格 TypeScript、Vue Router、Element Plus 和 Vite，保留数据库看板五卡、容量、完整性、SQL 性能、Worker/Job 及全部来源、过期、估算、排队、空态和失败态语义；普通用户聊天前端和 API/SSE 协议未修改。
  - 新增数据库监控在线配置与审计：七项覆盖按“数据库 > 环境变量 > 代码默认值”解析，进程缓存最多 5 秒，数据库读取失败时优先保留最后有效值；配置保存/重置使用乐观锁并记录 success、rejected、failed 审计事件。
  - 管理员写请求新增 Session 绑定 CSRF，所有响应新增 request ID；未登录管理员页面回到统一登录入口，API 继续保持 401/403 JSON 契约。
  - Dockerfile 改为 Node 24 构建阶段与 Python 运行阶段，Vue 产物固定复制到 `/opt/causalchat-admin`；三套 Compose 不增加 Node/Vite 服务或端口。
- 【BUG修复】
  - 修复看板“最后采集”把毫秒时间戳原样显示的问题，统一展示本地可读日期时间。
  - 普通刷新和完整性审计成功提示改为 5 秒后自动消失；警告、超时和错误提示继续保留。
  - 五张核心状态卡的截断来源与采集时间增加原生悬停提示，可查看完整内容。
  - 主库初始化为应用读账号补充 `events_statements_summary_by_digest` 的最小表级 `SELECT`，修复高负载 SQL 摘要因 1142 权限错误持续降级的问题，不授予全局 Performance Schema 读取。


---
2026.7.26
- 【管理员看板体验优化】
  - SQL 性能摘要新增前端业务语义映射，按任务调度、聊天、文件、Agent 状态、数据库监控、事务和连接操作解释 Digest；未知表按 SQL 操作与表名弱推断并明确标注。
  - 继续按真实共享快照逐条反查仓库 SQL：SHOW 状态/变量、Performance Schema 摘要、monitor 命名锁、快照读写、配置读取、Worker/Job 汇总、主库版本、server UUID 和会话身份复核均改为“代码确认”，详情展示对应文件与函数依据。
  - 连接初始化类 SQL 明确区分仓库显式调用和 mysql-connector 自动行为；`SET NAMES`、autocommit、sql_mode 的依据来自连接池配置及运行镜像中的实际驱动实现。
  - 高负载 SQL 列表默认展示业务模块、业务动作和中文说明，保留后端原始排序且不隐藏事务、连接或监控语句。
  - 每条摘要新增右侧详情抽屉，完整展示 Digest、执行次数、累计/平均耗时、扫描行和返回行，并说明归一化模板无法恢复 `?` 对应的真实参数。
  - 详情抽屉桌面端最大约 720px，760px 以下铺满屏幕；关闭后清理当前详情状态。

---
2026.7.26
- 【3.1 只读业务后台】
  - 新增业务概览、用户与权限、会话与内容、分析任务、文件资产及 Schema/deep 审计六个 Vue 页面；保留数据库看板、采集配置和 `/admin/database` 登录落点，不修改普通用户 `chat.html`、`style.css`、`script.js`、聊天 API 或 Job/Event/SSE 契约。
  - 新增 `/api/admin/business/*` 统一只读接口，列表默认 20、最多 50 条并使用不透明游标；DTO 不返回密码哈希、完整正文、文件 BLOB/哈希或认证/数据库秘密。
  - 消息、附件与任务输入/结果/错误改为管理员明确点击后按最多 64 KiB 源字节分块读取；短消息列表只返回长度摘要，避免把短正文伪装成摘要提前泄露。
  - 新增敏感访问审计包装器：记录管理员、动作、目标、结果、错误码和 request ID，不保存正文；成功敏感访问在审计不可写时失败关闭，401/403、404 和服务失败记录拒绝或失败结果。
  - 新增 CSV 纯文本安全预览和附件式下载；预览限制为 256 KiB、100 行、50 列、单元格 1000 字符，成功预览/下载在同一事务中更新 `last_accessed_at`、增加 `access_count` 并写审计。
  - 新增只手动调度的 `deep_audit` 共享快照，覆盖 revision、关键字段/索引/外键、字符集/UTC/隔离级别、账号职责结论、Job/Event、checkpoint/pending writes、归档关系、`active_session_key` 和逐从库状态；不自动修复，不返回账号、host 或 grants。
  - 新增 `d3e4f5a6b7c8` migration，为用户角色/状态、会话活动时间、任务创建时间、文件上传时间和审计目标时间增加只读查询索引；未对当前开发库执行 migration。
  - 左侧导航桌面端支持 248px/约 76px 收缩并保存浏览器偏好，移动端使用可关闭抽屉；展开和折叠均通过受保护接口复用 `README/CausalAgent.png`，未复制或生成新 Logo。
---
2026.7.27
- 【BUG 修复】
  - 将根 `.gitignore` 中会匹配任意层级的 `dist/` 改为只匹配仓库根目录的 `/dist/`，避免 `admin-frontend/dist/` 再次被误忽略。
  - 管理员 Vue 生产构建产物改为随源码同步纳入 Git；Docker 镜像仍由 Node 24 构建阶段从当前源码重新生成产物，并通过 `ADMIN_FRONTEND_DIST_DIR=/opt/causalchat-admin` 交给 Flask 托管。
  - 按原始 Logo 画布中心重新计算折叠侧栏与移动端裁剪偏移，分别向左校正 5px，展开态品牌图保持不变。


---
2026.7.27
- 【3.2 受控业务写入与数据库治理收口】
  - 新增用户单个/批量启停、角色切换和同密码设置，以及用户/文件物理删除；执行接口统一要求 Session CSRF、当前管理员密码重新认证、幂等键、影响预览、明确确认和主库事务。
  - 新增 `users.auth_version` 会话版本、`password_changed_at`、`admin_operations` 与 `admin_operation_items`；角色、状态或密码实际变化会使目标用户旧 Session 失效，成功写入与逐目标去敏审计同事务提交。
  - 禁止操作者禁用、降级或删除自己，并通过稳定锁顺序保护最后一个启用管理员；用户删除显式清理 archived session 与 session checkpoint，文件删除同时删除行和 BLOB 且不提供回收站。
  - `checkpoint_writes` 由应用写入、migration 回填完整业务键摘要并建立唯一索引，特殊 writes 走 upsert、普通 writes 忽略重复；没有使用与级联外键冲突的 generated column，最新 checkpoint 增加 `checkpoint_id` 稳定次排序。
  - 新增 `Database/lifecycle_repair.py`：默认只输出有限孤立关系清单，只有显式 `--apply` 和精确数据库名确认才执行，migration 不静默删除历史数据。
  - 数据库连接池增加有界获取等待、建连超时和从库状态短缓存；副本状态不可用时安全回退主库，不实现自动故障切换。
  - 管理员 Vue 增加当前值/执行后值预览、重新认证、批量选择、删除影响和操作后强一致刷新；生产构建产物随源码更新。
  - 新增删除/保留矩阵、读写一致性矩阵、连接容量依据、发布恢复说明、隐私说明和阶段三 fencing/event/heartbeat/终态原子性设计交接，阶段三能力未提前启用。

---
2026.7.27
- 【3.2 管理员交互修复】
  - 修复受控写入重新认证失败被误判为 Session 失效的问题：只有 `auth_required` / `admin_required` 才离开当前管理页面，`reauth_failed` 保持原 URL 和原弹窗。
  - 用户操作、用户删除和文件删除失败信息改在当前弹窗内部展示；密码错误时清空密码框并允许原地重试，不再把通知藏到页面遮罩后。
  - 用户/文件物理删除弹窗增加明确的两步说明、可见字段名、动态确认值、占位提示和辅助说明，明确第一个输入框填写完整用户名/文件名，第二个填写当前管理员登录密码。

---
2026.7.27
- 【文档与测试结构】
  - 根 README 的管理员部分收敛为首次部署流程，新增 `Document/admin/` 集中维护 API、开发部署与测试说明。
  - 后端测试改为 `unit`、`integration`、`e2e` 三层，并在层内按 admin、agent、auth、chat、database 和 migrations 业务分类。

---
2026.7.29
- 【管理员普通用户能力修复】
  - 管理员继续默认进入 `/admin/database`，同时增加后台与聊天界面的双向入口；管理员主动进入聊天页后不再被前端强制送回后台。
  - 管理员在普通接口中只按自身 `user_id` 访问会话、文件和任务，管理 API 的实时角色校验、`401/403`、CSRF、审计和重新认证边界保持不变。
  - 未登录管理页面使用白名单路径安全回跳；普通用户直访管理页面先返回真实 `403` 拒绝页，再回普通首页明确提示“无管理员权限”。
  - 新增 `/admin` 与 `/admin/` 受保护入口、登录 `redirect_to` 契约及对应后端、Vue 和隔离 E2E 回归覆盖。

---
2026.7.29
- 【管理员前端显示与会话标题优化】
  - 会话标题保留单行省略显示，并增加悬停完整标题提示。
  - 高负载 SQL 的业务模块标签与表头统一居中；侧栏导航、管理员身份和操作按钮字号同步缩小。
  - “进入聊天”与“退出登录”按钮统一对齐，移除聊天入口链接下划线；配置变更记录为管理员和错误码列保留更宽的单行展示空间。
  - 修复会话创建时把首条消息硬截为 8 个字符并永久写入标题的问题；两个创建入口改为统一保存不超过数据库 500 字符上限的完整单行标题，列表省略仅保留为显示效果。
  - 其他文字表述合理性修复。

---
2026.7.30
- 【Docker 单元测试环境】
  - 新增独立 `docker-compose.test.yml` 和 Dockerfile `test` 目标，将项目 Python 依赖与 `pytest` 固化为可复用测试镜像，不再向运行中的应用容器临时安装测试工具。
  - `unit-test` 服务不依赖 MySQL、Web、worker 或 monitor，以非敏感空白文件屏蔽项目 `.env` 并关闭 LangSmith 追踪，禁用容器网络，并只读挂载当前源码。
  - 单元测试通过 `docker compose ... run --rm` 按需创建容器，测试结束或退出 Shell 后删除容器；镜像继续保留，只有依赖变化时才需重建。
  - 当前 MVP 只保证 `tests/unit`，集成测试和隔离主从 E2E 保持原有独立执行边界。

---
2026.7.31
- 【SQL 性能摘要修复】
  - 高负载 SQL Digest 改为按单次平均耗时降序选取，平均耗时相同时按累计耗时降序次排序。
  - 管理员看板主表新增“平均耗时”列和秒单位，并在前端对旧共享快照执行同口径兼容排序，缺失或非法耗时统一置底。

---
2026.8.1
- 【取消延迟创建】
- /api/new_chat 创建 UUID 后立即写入 sessions。
- create_job 增加 session 存在性和归属校验。
- save_chat 拒绝未知 session。
- 文件上传拒绝未知 session。
- 加载、改标题、删除未知 session 统一返回 404。
- 更新普通聊天前端，使会话删除支持 202 响应。

- 【LangGraph PostgreSQL Checkpointer】
  - `/api/new_chat` 立即持久化会话；创建 job、保存聊天、改标题和上传文件均拒绝未知 session，取消延迟建行。
  - Agent worker 改用官方 `AsyncPostgresSaver`，按进程共享 PostgreSQL 连接池、按 slot 创建 Saver；新增一次性 setup 入口和独立 cleanup worker。
  - 新增合并两个 Alembic head 的迁移：创建 `checkpoint_cleanup_outbox` 后删除 MySQL checkpoint 表；downgrade 只恢复空表结构，不恢复已删除数据。
  - 会话/用户删除改为 MySQL 业务事务写 outbox，cleanup 使用 `FOR UPDATE SKIP LOCKED`、租约恢复、最多三次尝试和 10/30 秒退避；管理员操作状态支持 `running/succeeded/failed` 查询。
  - 隔离库验证 `upgrade head` 成功删除旧表并创建 outbox；明确回退到 `e4f5a6b7c8d9` 后恢复空 checkpoint 表。合并 head 场景下 `downgrade -1` 本身会因路径歧义失败。

---
2026.8.2
- 【CausalAgent 命名统一】
  - 品牌显示名统一为 `CausalAgent`，Docker、Compose、checkpoint 默认值、镜像、网络、容器、连接池和监控锁统一使用 `causalagent` 前缀。
  - Flask 入口改为 `CausalAgent.py`，MCP 入口目录改为 `Agent/CausalAgentMCP`，Agent 状态类型改为 `CausalAgentState`。
  - 同步更新 CI、管理员构建目录、隔离 E2E 配置、README、AGENTS 和管理员部署测试；未修改现有 `.env`、数据库数据、知识库和历史日志记录。
  - 将主从开发 + PostgreSQL checkpoint 拓扑统一为 `docker-compose.yml` 默认入口；`docker-compose.replica.yml` 暂保留为旧路径兼容副本。

---
2026.8.2
- 【工程规范】
  - 新增 GitHub Issue Form 模板，统一收集背景、问题描述、预期结果、复现步骤、验收标准和环境信息。
  - 除附件外的 Issue 字段启用 GitHub 原生必填校验，不增加空格或 `...` 等内容限制；普通贡献者不能选择空白 Issue。

---
2026.8.2
- 【数据库初始化入口统一】
  - 新增 `python -m Database.bootstrap`，按 MySQL 建库、Alembic migration、LangGraph PostgreSQL checkpoint setup 的顺序执行一次性初始化。
  - 开发 Compose 将初始化入口收敛为一次性的 `db-bootstrap`，app、worker、monitor 和 cleanup worker 都等待统一 bootstrap 成功后启动。
  - 保留 `Database/checkpoint_setup.py` 作为底层独立命令，`checkpoint-cleanup` 继续承担运行期跨数据库清理职责。

---
2026.8.2
- 【DirectLiNGAM 适配 develop】
  - 将 DirectLiNGAM MCP 工具适配到 `Agent/CausalAgentMCP`、`CausalAgentState` 和 `tests/unit/agent` 新结构，保留 develop 的 PostgreSQL checkpointer、管理员后台、数据库初始化与默认 Compose 拓扑。
  - 显式点名 DirectLiNGAM 时确定性选择 `causal_direct_lingam`；结果统一使用 `B[target, source]` 表示 `source -> target`，并在报告中披露线性、非高斯、误差独立、DAG 和无潜在混杂假设。
  - 修复 DirectLiNGAM 边权在后处理修订图中丢失的问题；保留未反转边的数值 `weight`，反转边会清除不再适用的旧方向系数。

---
2026.8.3
- 【管理员 checkpoint 读取迁移至 PostgreSQL】
  - Worker 将 `job_id` 写入 LangGraph checkpoint metadata，管理员按会话与任务精确读取 PostgreSQL 安全摘要；历史记录缺少 `job_id` 时不做时间归属猜测。
  - 任务详情分栏展示 MySQL 节点/任务事件和 PostgreSQL checkpoint 状态，PostgreSQL 故障不影响任务元数据与事件读取。
  - quick/deep 审计新增 PostgreSQL 连通性、官方 schema/setup 版本、估算统计和有界跨库关系样本，同时保留 MySQL cleanup outbox 检查。
  - 默认、生产与管理员隔离 Compose 补齐 PostgreSQL、bootstrap、worker、monitor 和 checkpoint cleanup 配置；MySQL SQL Digest 不再把已迁移表标为现行 Agent 状态表。

---
2026.8.3
- 【管理员任务详情视图切换】
  - 任务详情不再同时排列节点事件与 checkpoint 状态，在敏感内容审计提示下新增单视图选择器，默认展示节点与任务事件。
  - PostgreSQL checkpoint 摘要改为选择后按需加载，两套视图分别保留分页、加载态、空态和失败态。

---
2026.8.3
- 【管理员侧边栏图标统一】
  - 使用按需打包的 Lucide Vue 线性 SVG 图标替换侧边栏、折叠控制、移动端导航以及底部操作区中的 Emoji 和字符图标。
  - 导航图标统一为 18px、1.8px 描边并继承当前文字颜色，保持默认灰色与选中蓝色的一致状态。
  - 增加单元测试与管理员 mock E2E 断言，覆盖导航图标数量、SVG 渲染和统一描边。

---
2026.8.4
- 【管理员数据库清理视图】
  - cleanup worker 约每 10 秒写入 `checkpoint_cleanup_runtime` 共享心跳；monitor 采集最多 100 条脱敏 `checkpoint_cleanup_outbox` 待处理/异常记录，不返回 `last_error` 原文。
  - 数据库看板新增按 URL 保持状态的“数据库运行状态 / Cleanup Worker / Outbox 队列”三段视图，并将 Agent Worker/Job 汇总迁移到分析任务管理页。
  - 用户物理删除后持续显示 MySQL 删除结果、PostgreSQL checkpoint 清理聚合和 Operation ID，可直接跳转到带 Operation ID 高亮的 Outbox 视图。
- 【Quick 完整性检查说明】
  - Quick 审计结果新增逐项检查目的说明，覆盖 MySQL 外键、ENUM、cleanup outbox 索引与失败清理任务，以及 PostgreSQL checkpoint 连接、官方表集合和 setup 版本。
  - 异常或不可用时在检查目的后追加具体原因；旧共享快照继续兼容无说明字段的返回结果。
- 【Quick 完整性状态标签】
  - Quick 完整性状态列改用 Element Plus 标签组件，healthy 显示绿色。
  - warning、error、danger 和 unknown 统一显示红色，保留后端返回的英文状态文字。
- 【用户最后登录时间修复】
  - `POST /api/login` 在密码验证成功后通过主库更新 `users.last_login_at`，管理员用户列表继续按上海时间展示；Session 恢复和管理员进入聊天模式不会重复计为登录。
  - 最后登录时间写入失败时仍允许完成登录，响应增加稳定警告码，登录页显示一次约 3 秒后自动消失的非阻塞提示；管理员在提示结束后继续跳转后台。
- 【Job 终态与 worker 租约 BUG 修复】
  - 成功终态将聊天保存、幂等标记、终态事件和 job=succeeded 收敛到同一个 MySQL 事务，提交前崩溃会整体回滚，重复终态调用不会重复保存聊天。
  - worker 的事件、心跳、成功和失败更新统一校验 `job_id + worker_id + attempt_count`，旧 worker 失去租约后不能写事件、聊天或覆盖新 worker 结果。
  - 领取任务时原子收敛心跳过期且已达到最大尝试次数的 running job，写入 error 事件、释放 `active_session_key` 并标记 failed。
---
2026.8.5
- 【LangGraph 执行时间线与普通回答文字流】
  - worker 改用 LangGraph v2 `updates/messages/custom/tasks` 多流，父图真实 task 生命周期生成可重复阶段实例，MCP/RAG 子图工具调用以脱敏摘要嵌套展示。
  - 普通问答与报告追问使用流式 LLM 副本，文字经单一顺序写协程按 150ms 或 384 字符批量写入 `text_delta`；阶段、重试和终态前强制刷新。
  - SSE 重连继续通过数据库事件 ID 与 `Last-Event-ID` 补发，浏览器按 `step_id + stream_id + sequence` 去重，`final_result` 校正草稿且不重复创建回答。
  - 时间线按阶段实例折叠展示，处理中显示转圈，完成后不显示成功图标；真实重试、脱敏失败与 EventSource 重连状态保留为用户可见详情。
- 【聊天时间线无卡片视觉调整】
  - 普通 AI 回答和思考入口去除背景框，顶部显示客户端总耗时，展开后以“思考过程”文本流展示阶段与工具详情。
  - 父级时间线和子级阶段统一使用右三角/倒三角，阶段详情改用缩进和细线表达层级，保留处理中转圈、失败展开和重试状态。
  - 移除展开详情中的“思考过程”标题，保持展开后直接显示阶段文本。
- 【聊天时间线默认展开与间距调整】
  - 时间线创建后默认展开详情，处理完成后继续保留展开状态。
  - 抵消聊天区域通用间距在顶部入口与详情之间造成的额外空白。
  - 移除点击已处理行展开详情时的自动滚动，展开和收起不再改变用户当前阅读位置。
  - 决策事件仅由所属的 `agent`/`fold` 节点生成，避免后续因果工具阶段重复展示继承的旧路由决策。
- 【聊天页面滚动与工具阶段决策修正】
  - 聊天内容改为页面级自然滚动，取消聊天区域和思考详情的嵌套滚动条，时间线内容直接平铺在页面中。
  - 明确禁止 `mcp`、`rag` 阶段复用父图继承的 `route_decision`/`fold_decision`，避免知识库阶段错误显示“已识别为因果分析请求”。

---
2026.8.5
- 【修复：Agent 创建请求幂等】
  - `/api/agent/jobs` 要求客户端提供 `Idempotency-Key`，服务端将请求指纹和幂等键与 job 创建放在同一个 MySQL 事务中。
  - 网络重试使用同一幂等键时返回原 job；同一幂等键对应不同会话或消息时返回冲突，避免终态 job 释放 active 锁后重复保存聊天记录。

---
2026.8.6
- 【Agent Worker包结构重构】
  - 将单文件 `app/agent/worker.py` 拆分为可通过 `python -m app.agent.worker` 启动的 package，按启动编排、运行时、单任务执行、事件写入、图执行、事件适配和结果展示划分职责。
  - 新增显式 `ProcessRuntime` 与 `SlotRuntime`：LLM 在进程级创建，MCP session、tools 与 graph 在 slot 级创建；任务执行不再读取 `app.agent.core.llm` 等模块全局变量。
  - `job_service.py` 和 `routes.py` 保持在 worker package 外，继续供 Web、monitor、管理员看板与 worker 共用；管理员任务、checkpoint 和 SSE 数据契约不变。
  - 测试改为直接导入新职责模块，并将管理员 checkpoint 约束检查指向实际写入 `job_id` metadata 的 `graph_runner.py`。

---
2026.8.8
- 【文件库与可恢复 Job】
  - 将文件存储拆为 `file_objects` 不可变 BLOB 和 `user_files` 逻辑文件记录，上传、选择草稿和创建 Job 的职责边界分离；Job 创建时冻结文件对象、hash 和文件名。
  - 新增 `analysis_job_inputs` 输入账本，支持同一 Job 的 interrupt、`waiting_input`、resume、取消和稳定生命周期事件；stale worker 通过 lease epoch fencing，旧 worker 不能覆盖新 worker 的结果。
  - Agent、MCP 和管理员预览/下载按主库事务读取冻结文件并累计访问次数；完整 CSV 不进入 State、ToolMessage、checkpoint、事件、日志或 SSE。
  - 新增 `a1b2c3d4e5f6_add_file_library_and_job_recovery`。该 migration 只面向开发/测试库，直接删除旧 `uploaded_files` 表，不回填旧数据、不提供 fallback、不拒绝旧数据迁移；downgrade 只恢复空旧表结构。
  - 补充迁移静态测试、Job 恢复定向测试和管理员文件访问事务测试；完整 Docker 后端、管理员前端和隔离数据库往返验证在本次执行中单独记录。
- 【聊天文件附件预览与等待任务提示】
  - 修复 `hidden` 属性被 CSS `display` 覆盖导致的空白文件栏和空白任务栏；无文件、无等待输入时不再占据输入区空间。
  - 文件上传或从文件列表选择后，在输入区内部显示 CSV 文件卡片，包含文件名、类型、大小和清除按钮；输入区随附件卡片自然增高，并覆盖桌面端与 390px 移动端布局。
  - 将按钮文案明确为“取消等待任务”；当前接口只取消 `waiting_input` Job，不中断 `queued`/`running` Job 或正在执行的 LLM/MCP 调用。
  - 完成真实 Flask 页面 DOM 检查、桌面/移动端视觉检查、JavaScript 语法检查和 `git diff --check`。
- 【修复：Job checkpoint identity 与跨 Job 聊天历史】
  - LangGraph 根图统一使用 `analysis_jobs.job_id` 作为 `thread_id`，根 `checkpoint_ns` 保持为空；业务 `session_id` 继续作为会话外键和 State 上下文，不再使用 `job:<job_id>` namespace 或 session-thread identity。
  - 新 Job 按创建事务记录的 `chat_message_id` 从 MySQL 读取同一业务会话的最近消息窗口；同一 Job 的 interrupt/resume 和 stale recovery 继续使用原 checkpoint，当前用户消息不会重复注入。
  - 输入账本按 `initial`/`resume` 区分运行时解析，结构化 resume 值仅作为 `Command(resume=...)` 的原值传入，并在图消息中统一转换为 JSON 文本；PostgreSQL checkpoint 不可用时阻止 stale Job 盲目重放。
  - 会话和管理员用户删除按全部 `analysis_jobs.job_id` 写入 cleanup outbox；管理员 checkpoint/deep audit 按 Job ID 归属，并识别 cleanup outbox 过渡状态。
- 【聊天页面滚动与文件日期显示修复】
  - 将页面和主聊天容器固定在视口内，长报告、时间线和历史消息只在 `chat-area` 内滚动，输入区保持固定可见。
  - 自动滚动目标改为聊天区域，避免新增报告内容继续推动整个页面滚动。
  - 文件列表时间仅显示 `YYYY-MM-DD`，并补充报告图片、表格和代码块的宽度约束，避免内容超出聊天区域。
