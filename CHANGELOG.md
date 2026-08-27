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
2026.5.28
- 【内容新增与重构】：
  - 重构 RAG 测评模块，将数据集处理、检索评测、Ragas 评测、Claim 评测、Trace 导出和报告生成拆分到独立目录。
  - 建立 `validate_datasets -> retrieval_eval -> ragas_eval -> trace_export -> summary` 评测流水线。
  - 移除不应长期保留在仓库中的运行产物，并补充 RAG 测评框架和数据集说明文档。

---
2026.5.29
- 【内容新增】
  - 将原先集中在 `execute_tools_node` 的 MCP 因果分析与 RAG 查询拆分为父图中的 `mcp`、`rag` 两个业务阶段节点，并将工具调用细节封装在各自的 compiled subgraph 内。
  - 支持原生 LangChain ToolNode 调用。

---
2026.5.29
- 【内容新增】
  - 将原先集中在 `execute_tools_node` 的 MCP 因果分析与 RAG 查询拆分为父图中的 `mcp`、`rag` 两个业务阶段节点，并将工具调用细节封装在各自的 compiled subgraph 内。
  - 支持原生 LangChain ToolNode 调用。

- 【BUG修复】：
  - 修复 `export_metadata.py` 重构后遗留的文件冲突和重复实现问题。

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
2026.5.31
- 【内容新增与重构】：
  - 增加可配置的 RAG 检索参数和检索配置结构。
  - 增加外部医疗数据集处理、评测数据生成和 Ragas 数据集构建能力。
  - 统一医疗语料、测试集、评测输出和检索配置入口。

- 【BUG修复】
  - 梳理 ToolNode 的标准消息协议。
  - MCP worker 主路径迁移到 `langchain-mcp-adapters`：每个 slot 通过 `MultiServerMCPClient.session("causal")` 维护持久 session，并用 `load_mcp_tools(session)` 加载 ToolNode 可执行工具。

---
2026.6.1
- 【内容新增】：医疗知识库构建增加 OpenAI-compatible embedding 支持，并继续复用原持久化目录。
- 【内容新增】：支持通过环境变量临时覆盖向量库目录和 Chroma collection。
- 【内容重构】：RAG benchmark 与医疗数据集解耦，统一使用 `benchmark_v2` schema。
- 【内容重构】：使用 `gold_doc_ids` 记录文档级检索目标，并兼容旧 `gold_chunk_ids`。

---
2026.6.3
- 【内容重构】：RAG active benchmark 切换为 PubMedQA labeled。
- 【内容新增】：增加 PubMedQA 数据处理脚本，生成 1000 条语料和 1000 条评测数据。
- 【内容重构】：医疗知识库统一从 active corpus 构建，默认使用 `pubmedqa_clean` collection。
- 【内容新增】：增加向量库与 benchmark 一致性检查，防止使用错误知识库运行评测。
- 【当前状态】：旧 RAGCare 向量库保留在 `tmp/RAGCare`。

---
2026.6.5
- 【内容新增】：完善 PubMedQA 检索、回答生成和 Ragas 评测流程。
- 【内容新增】：增加 PubMedQA 专用回答提示词、检索配置快照和评测结果校验。
- 【BUG修复】：评测前自动核对样本数、问题顺序、检索配置和向量库摘要，避免不同评测结果混用。

---
2026.7.10
- 【内容修复】
  - 修复 PC、OLC 因果边在后处理中的格式和矩阵方向不一致问题。
  - 环路修订会生成实际的修订图，最终 SSE、前端展示和历史会话统一使用该图；结构异常时安全回退原图。
  - 统一结构化输出配置入口，Compose 曾支持可切换的结构化输出模式，并移除 `LANGSMITH_*` 配置。
- 【验证】
  - 新增后处理、最终图选择和结构化输出配置测试；完整测试集已通过。

---
2026.7.11
- 【内容新增与重构】：
  - 新增 RAG 测评工作台前后端，可通过 `/rag_eval` 或 `/rag-eval` 访问。
  - `pubmedqa_pipeline` 默认评测前 30 条，样本数可由前端动态调整。
  - Ragas generation 默认使用 6 个 context、单个 context 1600 字符、回答 1100 字符和 PubMedQA prompt v6。
  - `claim_eval` 从默认 pipeline 和前端调参入口移除，坏例链路只统计 retrieval 和 Ragas 相关问题。
  - 保留 `trace_export`，在前端和报告中统一显示为 Bad Case Traces / 坏例链路。
  - 移除 CLI 调参备份层；前端不再展示 CLI 等价字段，后端不再提供 `GET /api/rag_eval/cli-params`，也不再接受 `cli_overrides`。
  - 新增正式 RAG 检索配置查看与发布接口：`GET /api/rag_eval/production-config` 和 `POST /api/rag_eval/production-config/publish`。
  - 正式 RAG 查询读取 `Agent/knowledge_base/rag/runtime/production_rag_config.json`；文件不存在或无效时，回退到 `query_rag.py` 的默认 `RagRetrievalConfig()`。
  - 新增 `GET /api/rag_eval/run-state`，支持运行页刷新恢复；取消请求会在当前样本完成后停止，并通过 `step_progress` 展示进度。
  - 新增 `GET /api/rag_eval/analysis/latest` 和 `GET /api/rag_eval/runs/<run_id>/analysis`，只读提供报告、坏例 Trace 和证据链。
  - `RAG_EMBEDDING_PROVIDER` 支持 `auto`、`openai_compatible` 和 `local` 三种模式，并支持通过 `RAG_LOCAL_EMBEDDING_MODEL_PATH` 指定本地模型。
  - `build_knowledge.py` 默认拒绝向非空 collection 追加数据；只有显式传入 `--allow-append` 才允许追加，避免重复 chunk 污染知识库。
  - 删除已停用的旧数据集处理和评测辅助脚本。

---
2026.7.18
- 【技术验证】：
  - 完成多模态知识摄取规划 P01S：冻结七类合法小型 fixture、来源哈希、人工 gold、环境记录和可复现实测脚本。
  - Windows CPU 对比 PyMuPDF 1.24.7、Docling 2.113.0 与 PaddleOCR PP-StructureV3 3.7.0；默认内部解析/OCR 路径选择 PaddleOCR，PyMuPDF 仅作为数字 PDF/原生表格 fallback，并保留许可证发布门禁。
  - Docling 因首次模型获取不可复现而不入选；Docker CPU 和 GPU 安装未通过的结果已如实记录，未用推测吞吐补齐。
  - PaddleOCR 对数字、扫描、混合 PDF 及复杂表格 gold 通过，项目自有中文图 OCR `1-CER` 为 98.25%，项目自有流程图为 100%；候选均不提供结构化因果边字段，质量标为 unsupported，仍需 P08 视觉语义与方向复核。
- 【验证】：
  - P01S fixture manifest 与来源哈希测试在 Python 3.10.20、3.12.13 环境通过；完整 `tests/rag_ingestion` 回归结果见 P01S 报告。

---
2026.7.19
- 【内容新增】：
  - 完成多模态知识摄取规划 P05：数字 PDF 适配器按阅读顺序输出正文与页内表格片段，保留页码和归一化 bbox，并单独发现内嵌图片位置。
  - 完成 P06：图片 OCR descriptor 保留 OCR 文字、置信度、bbox、语言配置和方向校正提示；低置信度或无文字均以非阻断诊断输出。Paddle PP-StructureV3 生产 port 在依赖缺失时显式失败，不伪造 OCR 结果。
- 【验证】：
  - Python 3.10.20 与 3.12.13 环境各通过 117 项 `tests/rag_ingestion` 测试，并通过新增文件的 `py_compile` 与 `git diff --check`。

---
2026.7.20
- 【问题修复】：
  - P06.1 将 PP-StructureV3 改为进程级唯一解析 slot；多个 `PaddleOcrPort` 复用同一 pipeline，不兼容的 device/语言配置显式失败，避免重复常驻约 6.2 GiB 的模型资源。
- 【验证】：
  - Python 3.10.20 与 3.12.13 环境各通过 119 项 `tests/rag_ingestion` 测试；新增 fake-Paddle 回归覆盖多 port 复用与配置冲突，且未运行真实模型。

---
2026.7.20
- 【内容新增】：
  - 新增 `execute_ingest(IngestCommand)`，完成已验证来源到 P06 OCR 片段与结构化问题的最小正式摄取编排；结果保留 `KnowledgeFragment`，不写 Chroma、不调用旧 `build_knowledge.py`。
  - PDF 来源在 PyMuPDF 的 AGPL/商业许可证发布门禁通过前，明确返回阻断问题，不会静默进入 P05 adapter。
- 【验证】：
  - Python 3.10.20 与 3.12.13 环境各通过 122 项 `tests/rag_ingestion` 测试；覆盖图片 OCR 编排、PDF 门禁与空来源失败，未运行真实模型。
  - P01S 隔离 Paddle Docker target 补齐 `libgomp1` 后完成安装与容器导入断言：`paddleocr=3.7.0`、`paddle=3.2.0`、`cuda=False`；未运行 PP-StructureV3 或下载模型权重。
  - 新增 P06 provenance smoke 工具与两项单测，记录输入、adapter、raw/stdout/stderr 和模型缓存哈希；两个本地 Python 环境的 `tests/rag_ingestion` 均通过 124 项。经授权在 `CA-py310` 安装固定 Paddle 依赖后，真实 adapter smoke 使用既有模型缓存输出 4 个 OCR 片段、0 个问题，raw/stdout/stderr/input 哈希均通过复核；未下载模型权重。
  - 删除已停用的旧数据集处理和评测辅助脚本。

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
2026.7.23
- 【BUG修复】
  - 完整恢复 `bbcdf46` 误删的前端初始化、聊天交互、任务事件订阅、会话历史与删除逻辑，修复未登录首页显示空白的问题。

---
2026.7.23
- 【工程规范】
  - 新增 GitHub Actions 轻量 CI，对 `main`、`develop` 执行 Python 语法编译、无外部服务依赖的轻量测试和 Pull Request 策略检查。
  - 统一 Pull Request 标题格式，并明确 `feature -> develop -> main` 的合并路径。

---
2026.7.24
- 【架构重构】：
  - 将生产 RAG 的 embedding、Chroma、BM25 corpus 和回答 LLM 收敛到 worker 进程级 `RagRuntime`，通过 `RagService -> Tool -> Graph` 显式注入；同一 worker 的所有 slot 共享 Runtime/Service。
  - worker 启动时严格验证已有且非空的 Chroma collection；初始化失败时绑定 `UnavailableRagService`，任务继续执行并返回稳定、脱敏的知识库不可用结果，修复后通过重启 worker 恢复。
  - `query_rag.py` 保留评测、CLI 和 Web 兼容入口，统一委托给独立的延迟 compatibility Service；生产检索配置继续逐问题动态读取。
  - 移除生产 RAG Tool 对 `langgraph.func.task` 的依赖，Service/Runtime 不进入 Tool schema 或 LangGraph state。
- 【验证】：
  - 新增 Runtime 生命周期、严格失败阶段、日志脱敏、BM25 parity、候选隔离、并发检索、Service 动态配置、Tool 降级和 worker 多 slot 共享测试。
  - 变更文件通过 `py_compile`；已执行完整测试发现和有限 worker 启动，但当前本机 Python 缺少项目 LangChain/pytest/Flask 依赖且 Docker daemon 未启动，两者均在导入阶段受阻，需在完整项目运行环境中复验。

---
2026.7.24
- 【依赖与检索重构】：
  - 引入固定版本 `bm25s==0.3.10`，以 BM25s NumPy/Lucene 稀疏索引替换生产路径中的手写 BM25 语料统计、逐文档打分和排序。
  - 保留现有中英文 tokenizer、512 token 截断、`SparseRetriever` 协议、候选结构和分数归一化；Chroma 继续作为唯一知识库来源，worker 启动时构建一次进程级只读内存索引，不增加磁盘索引。
  - 适配层恢复 BM25s Lucene 为排序省略的 `(k1 + 1)` 常数，保持旧 `sparse_score` 原始分数尺度；缺少 BM25s 或索引构建失败仍进入 `sparse_corpus` 降级阶段。
  - 移除只暴露旧词频结构且仓库内无调用的 `_get_sparse_corpus()`、`_bm25_score()` 私有兼容入口。
  - 多模态契约测试共 34 项，覆盖解析、审计、索引身份、发布门禁、远程策略、检索防护及 Agent 路由；Python 编译检查与差异格式检查通过。
  - 100 页 OmniDocBench 固定样本已完成官方 end-to-end 评测，文本 Edit Distance 为 0.193744，公式 CDM 为 0.0574299，共评估 26 个表格和 107 个公式。
- 【当前边界】：
  - OmniDocBench 仅作为解析能力 benchmark，不纳入知识库；布局 mAP 尚未完成。
  - 当前尚未按新质量门禁发布生产索引；需在正式知识源确定后重新摄取、评估并发布。
  - 持久化运行摘要、异常退出后的陈旧锁恢复、并发成功幂等实测以及完整父图因果链验收仍待完成。

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
2026.7.26
- 【多模态知识库流程】：
  - 新增独立的多模态公共知识库模块，提供资料检查、摄取、质量评估、发布、回滚和自动维护命令；其资产、索引与发布指针均与现有医疗知识库隔离。
  - 支持文本、Markdown、表格、图片及 PDF 的标准化处理。PDF 默认使用 Docling，原始资料、解析产物、标准化单元和资源均通过 URI 与 SHA-256 建立可回读的审计关系。
  - 索引版本绑定 embedding 与视觉配置；发布前执行完整性和质量门禁，查询时再次校验发布指针、manifest 与运行时 embedding 指纹。
  - 远程视觉增强受资料白名单、模型配置、调用预算和审计策略约束；失败状态会持久化，未增强的低价值图片不会进入有效检索结果。
  - 完整开发依赖统一由 `requirements.txt` 引入多模态依赖清单；基础生产依赖保持不变。
- 【Agent 与 worker 接入】：
  - 新增 `multimodal_rag_search` 工具，并通过问题的 `corpus` 字段在医疗知识库与多模态知识库之间显式路由；同一批问题禁止混用语料范围。
  - RAG 子图支持持久化检查点，worker 事件流可记录 RAG 规划、工具调用和解析结果；现有医疗 RAG 行为保持不变。
- 【维护与发布控制】：
  - 自动维护支持版本互斥、暂存版本复用、失败不发布以及阶段边界取消和超时。
  - 旧格式 manifest 缺少构建配置、质量策略或质量观测时不能通过新发布门禁。
- 【验证】：
  - Python 3.10.20 与 3.12.13 环境各通过 105 项 `tests/rag_ingestion` 测试。

---
2026.7.26
- 【内容新增】：新增多模态知识库现状分析与发展规划文档。
- 【内容新增】：建立独立的多模态知识库模块，支持资料检查、摄取、评估、发布、回滚和自动维护。
- 【内容新增】：支持文本、Markdown、表格、图片和 PDF，并保存可追溯的 URI 与 SHA-256。
- 【内容新增】：增加索引完整性、质量、manifest 和 embedding fingerprint 发布门禁。
- 【内容新增】：增加远程视觉资料白名单、模型限制、调用预算和审计策略。
- 【内容重构】：将多模态知识库设为默认且唯一的生产 RAG corpus，不再回退到 PubMedQA。
- 【内容重构】：Runtime 改为从多模态 active pointer 加载索引，并校验版本、manifest 和 embedding fingerprint。
- 【内容重构】：将 RAG ToolNode 子图收缩为普通 `rag` 节点，直接完成问题生成、RagService 调用和结果写回。
- 【验证】：多模态摄取测试在 Python 3.10 和 Python 3.12 环境通过。
- 【验证】：默认 corpus、Runtime、metadata、RAG 节点和 worker Service 共享测试通过。

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
2026.7.27
- 【内容新增】：固定本地 `bge-small-zh-v1.5`、两本 Pearl PDF 及其 SHA-256，远程视觉默认关闭。
- 【内容新增】：新增 24 条页级检索题，覆盖 15 条文本、6 条图片和 3 条表格问题。
- 【内容新增】：增加 worker 离线构建前检查，验证 embedding、知识源、Docling、RapidOCR 和磁盘空间。
- 【内容重构】：PDF 改为逐物理页运行 Docling 和 RapidOCR，降低大文件解析的内存峰值。
- 【内容新增】：增加页级 checkpoint，任务中断后可跳过已完成页面继续执行。
- 【内容重构】：Chroma 分批写入独立 attempt 目录，成功后再提交为正式索引。
- 【内容重构】：评测命中必须同时匹配文档、页码和预期模态。
- 【内容重构】：`run` 默认只执行摄取和评测，必须显式授权才能发布。
- 【验证】：本地 embedding 连续两次初始化的 fingerprint 一致。
- 【验证】：两本 PDF 的格式和 SHA-256 校验通过，Docling 与 RapidOCR 模型资产完整，单页 PDF smoke 通过。
- 【当前状态】：两本 PDF 共 889 页；当日全量摄取、24 题正式评测和 active pointer 发布尚未完成。

---
2026.7.28
- 【BUG修复】：纠正 5 条评测题的错误页码和模态标注，未通过伪造图表单元或降低评测要求绕过门禁。
- 【验证】：24/24 gold 页覆盖通过，文本、图片和表格题数量保持为 15、6 和 3。
- 【内容重构】：暂存评测改为复用生产 dense、BM25s 和 rerank 检索链路。
- 【内容新增】：明确要求图片或表格的问题会补充对应模态候选，普通问题不启用模态偏置。
- 【内容重构】：正式返回数量与 Hit@5 评测口径统一为 5。
- 【验证】：完成 889 页摄取，生成 5364 个标准化单元和 5364 个 Chroma 向量，数量一致。
- 【验证】：Hit@5 为 `0.75`、MRR 为 `0.675`、首条引用定位准确率为 `0.625`、空结果率为 `0`，全部通过发布门禁。
- 【验证】：候选索引通过离线 Docker Runtime smoke，相关测试 `72/72` 通过。
- 【当前状态】：获得明确确认后，active pointer 已切换至 `mm_74b5aef2f5e7322b5a79`。
- 【验证】：发布后 Runtime 成功加载本地 embedding、manifest、collection 和 5364 个向量。
- 【验证】：Compose worker 的两个 slot 均成功加载新索引，未进入不可用降级，也未回退到 PubMedQA。
- 【BUG修复】：修复 MCP artifact 中字符串结果的解析，并区分成功、失败和需要用户补充信息的路由。
- 【BUG修复】：RAG 完成后直接进入后处理，避免再次进入 Agent 造成重复 MCP 循环。
- 【验证】：RAG 节点测试 `10/10` 通过，Python 编译和差异格式检查通过。
- 【验证】：真实父图成功执行 MCP、RAG、后处理和报告流程，并返回图片证据、页码、资产引用和最终报告。
- 【验证】：使用当前代码在隔离目录重新执行 OmniDocBench 固定子集审计、摄取、完整性评测和 OCR probe，生产 active pointer 保持不变。
- 【BUG修复】：独立图片复用 RapidOCR 生成 `raw_text`，OmniDocBench evaluator 支持识别本地 OCR 图片单元，不再依赖远程视觉模型。
- 【验证】：6 个固定样本全部通过审计；隔离索引包含 6 个单元和 6 个向量，完整性门禁和 OCR probe 均通过。
- 【验证】：多模态契约与生产默认测试共 52 项，其中 50 项通过；新增 OCR 回归、Python 编译和差异格式检查通过。
- 【当前状态】：两项真实 Docling PDF 测试在低内存环境触发 `std::bad_alloc`，单独重试后仍未通过。
- 【验证】：使用真实 active pointer 完成纯文本、表格、图片/OCR、跨页和无法回答五类检索 smoke。
- 【验证】：前四类问题返回 `answered`；无法回答问题返回 `insufficient_evidence`，且引用为空。
- 【验证】：检索结果均包含文档 ID、页码、`content_kind` 和 `modality`；图片证据包含可回读的 `asset_uri`。
- 【当前状态】：Compose worker 已加载新索引的 5364 个 chunks，BM25s 和 RagRuntime 初始化成功，未绑定 `UnavailableRagService`。

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
2026.7.29
- 【路线调整】：统一采用 WCode `qwen/qwen3-vl-flash`（7.30 切换为 `qwen/qwen3-vl-8b-instruct`）一次请求返回 OCR 与视觉语义；不再继续本地 OCR 与 VLM 双候选方案。
- 【外发契约】：只允许冻结且明确批准的来源，图片需解码、RGB 归一化并匹配 source/page/image/context/策略 hash；远程失败不回退 RapidOCR，active pointer 保持不变。
- 【本地运行边界】：Windows Docling `std::bad_alloc` 促使 R2/R3 解析入口转为 Docker worker；R2 只生成本地审阅清单，不联网、不建库、不发布。
- 【验证与暂停】：R1/R2 离线契约测试和 Docker preflight 通过；本地 OCR 候选在 729/889 页暂停，未进入评测或发布。

---
2026.7.30
- 【Docker 单元测试环境】
  - 新增独立 `docker-compose.test.yml` 和 Dockerfile `test` 目标，将项目 Python 依赖与 `pytest` 固化为可复用测试镜像，不再向运行中的应用容器临时安装测试工具。
  - `unit-test` 服务不依赖 MySQL、Web、worker 或 monitor，以非敏感空白文件屏蔽项目 `.env` 并关闭 LangSmith 追踪，禁用容器网络，并只读挂载当前源码。
  - 单元测试通过 `docker compose ... run --rm` 按需创建容器，测试结束或退出 Shell 后删除容器；镜像继续保留，只有依赖变化时才需重建。
  - 当前 MVP 只保证 `tests/unit`，集成测试和隔离主从 E2E 保持原有独立执行边界。

---
2026.7.30
- 【R3 门禁】：新增一次性 maintenance worker；R3a 只做全量本地发现和人工审阅清单，R3b 必须先批准清单并取得独立外发授权，maintenance worker 不替代常驻业务 worker。
- 【全量发现】：两份 Pearl 共完成 889/889 页解析，形成 275 条冻结记录；未批准前不调用 WCode。
- 【R3b 结果】：候选 `mm_587799887fc8efb68409` 生成 5460 units，270/275 图片远程成功；决定不做 generation3 重试，保留失败审计，后续门禁不再把远程失败数量机械地作为唯一阻断条件。
- 【存储调整】：页级 checkpoint 从大量小文件收敛到 `checkpoints.sqlite3`，保留按页恢复和完整 hash 身份。

---
2026.7.31
- 【SQL 性能摘要修复】
  - 高负载 SQL Digest 改为按单次平均耗时降序选取，平均耗时相同时按累计耗时降序次排序。
  - 管理员看板主表新增“平均耗时”列和秒单位，并在前端对旧共享快照执行同口径兼容排序，缺失或非法耗时统一置底。

---
2026.7.31
- 【架构决策】：R4 将“解析/索引可用性”与“固定 gold/评测题集”解耦；Pearl 24 条题只作为 Pearl 公共语料回归集，隔离评测使用知识源无关的 `rag_eval_v1`，题集必须显式传入，检索 gold 通过 `gold_evidence` locator 绑定；缺 gold 时显示未评分而不是 0。
- 【解析与索引】：`why-003` 空表通过 bbox `table_recovery` 和 provider-neutral `TableRecoveryProvider` 修复；隔离评测摄取使用低内存 Docling、页级 checkpoint，支持自定义页范围和容器 Docling 模型目录；隔离结果绑定 ingestion/index/manifest/策略 identity，不修改 active pointer。
- 【隔离评测运行台】：Vue 工作台、评测中心、报告编辑和对比分析完成；默认检索与完整 Ragas 两种执行边界明确；固定 4 页真实摄取、RAG 和 prepare-only 流程验证通过。
- 【可靠性】：Windows `WinError 5` 文件占用通过共享原子替换重试修复；确认 PowerShell 默认编码会破坏中文请求，后续调试不再用默认编码判断 RAG 质量。
- 【重要否决】：本地 OCR 候选在 729/889 页暂停，未评测或发布；从 source-specific 题集默认和远程/本地双候选假设切换为通用题集与统一远程授权边界。

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
2026.8.1
- 【来源与远程边界】：工作台支持多格式知识源登记和删除；上传只刷新 `tmp/rag_eval_sources/`，不自动摄取。内测默认允许本次运行通过精确 outbound manifest 使用远程 VLM，`VISION_ALLOW_REMOTE_DATA=false` 可关闭。
- 【评测配置】：统一 retrieval/Ragas profile 由 MySQL `rag_eval_profiles` 保存，内置 profile 只读，自定义 profile 支持保存、删除和发布；修复可编辑字段边界、profile 参数串改和题集 placeholder 校验。
- 【前端可用性】：补充大模型等待提示、Ragas 完成弹窗、阶段进度合并、sticky 导航和基线/候选完整指标对比，完成类型检查、构建和浏览器验证。

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
2026.8.2
- 【评测可靠性】：隔离评测 Evaluation Run 改为写入 MySQL `rag_eval_jobs` 持久队列，由独立 `rag-eval-worker` 执行；worker 以 heartbeat 保活，异常退出后将超时 `running` 任务收敛为 `failed`，不自动重跑可能产生外部调用的 Ragas。
- 【报告与对比】：报告入口统一为“报告编辑”；删除已结束或确认失活的 evaluation run 时同步清理对应 `tmp` 目录，history 和对比接口不再返回该运行；对比页同时展示指标和两次 run 的配置差异。
- 【执行边界】：关闭完整 Ragas 时只执行题集校验、retrieval 和 summary；开启时才进行回答生成、Ragas prepare/judge。自定义 profile 的保存、切换、刷新恢复问题已修复。
- 【验证】：隔离运行、评测与路由单测 32 项通过；Vue typecheck/build、Python 编译、Alembic head 和 Compose 校验通过。`rag_eval_jobs` 迁移尚未执行。

---
2026.8.2（Docker 启动修复补充）
- 【BUG修复】：修复 merge 后 MySQL Alembic 出现双 head 的问题，新增合并迁移，使评测任务、管理员和 PostgreSQL 检查点迁移可以由统一 bootstrap 顺序执行。
- 【BUG修复】：统一检索回答链的结构化输出调用接口，修复旧容器镜像入口和隔离评测 Compose 网络名不一致导致的启动失败。
- 【验证】：Compose 配置、数据库 bootstrap、Alembic 单 head、`/rag_eval` HTTP 200、业务 worker 和评测 worker 启动均通过；数据库 bootstrap 单测 3 项通过。
- 【当前状态】：当前正式索引目录缺少 `mm_74b5aef2f5e7322b5a79/manifest.json`，业务 worker 按安全策略暂绑定不可用 RAG Service；未自动伪造清单或切换 active pointer，待恢复完整索引产物后重启 worker。

---
2026.8.2
- 【评测依赖修复】：明确安装 PyTorch CPU 对应的 `torchvision==0.22.1+cpu`，避免 Docling 间接依赖从 PyPI 拉取 CUDA wheel，导致 RAG Runtime 导入 `sentence-transformers` 时加载 `libcudart.so.12` 失败。
- 【验证边界】：待重新构建 `rag-eval-worker` 后先用单题评测验证 embedding 初始化，再恢复 24 条正式题集评测。

---
2026.8.2
- 【隔离评测修复】：Ragas `answer_relevancy` 改为使用当前评测 staged Runtime 的 embedding，不再读取生产 active pointer；同一评测始终绑定自己的索引 manifest 与运行配置快照。
- 【兼容性】：旧版代码配置入口未传入隔离 embedding 时仍保留原有全局 Runtime 回退；仅在真正执行 Ragas judge 时要求 staged embedding，prepare-only 流程不额外加载它。
- 【验证】：Ragas 与隔离评测相关测试 13 项通过；在 active manifest 缺失、staged index 完整的场景下，单题 Ragas judge `eval_20260802_135826_6a0bccbfe8` 通过。

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
2026.8.5
- 【功能】：新增 staged index 候选题集自动扩充入口，从 `units.jsonl` 按模态轮询生成 `generated_candidate`，保存 manifest hash、证据 locator 和版本快照；重复题、短答案和无法解析 evidence 的样本只进入拒绝摘要，不自动升级为 gold。
- 【功能】：retrieval sweep 改为最多 8 个 worker 的有界并行执行，保留每组配置、失败/取消状态、空结果数和样本级退化数，最多推荐 2 组候选供人工确认；不自动执行 Ragas、修改 profile 或发布 active pointer。
- 【验证】：候选题集与并行 sweep 新增测试 3 项，连同题集契约和隔离评测测试共 11 项通过；多模态 RAG 评测测试 10 项通过。

---
2026.8.5（候选题集与 sweep 修复补充）
- 【完整性】：候选生成入口增加 staged complete、manifest/unit/vector/Chroma 计数和 embedding 指纹门禁，并把 units/build-state hash 写入来源快照；全部候选失败或被筛除时拒绝写出无效空题集。
- 【并发可靠性】：串行和并行 sweep 现在都会为全部未开始配置补齐 cancelled 记录，不再因已取消 future 抛出 `CancelledError`；默认候选题集 revision 使用微秒时间和随机后缀，临时文件名也彼此隔离。
- 【交付】：新增候选生成与 sweep 测试已从 `.gitignore` 精确反忽略，避免正常提交和 CI 漏掉核心回归测试。
- 【验证】：候选生成、题集契约、隔离评测和多模态 RAG 评测共 26 项 `unittest` 通过；候选 CLI `--help`、8 个相关 Python 文件编译和 `git diff --check` 通过。

---
2026.8.6
- 【Agent Worker包结构重构】
  - 将单文件 `app/agent/worker.py` 拆分为可通过 `python -m app.agent.worker` 启动的 package，按启动编排、运行时、单任务执行、事件写入、图执行、事件适配和结果展示划分职责。
  - 新增显式 `ProcessRuntime` 与 `SlotRuntime`：LLM 在进程级创建，MCP session、tools 与 graph 在 slot 级创建；任务执行不再读取 `app.agent.core.llm` 等模块全局变量。
  - `job_service.py` 和 `routes.py` 保持在 worker package 外，继续供 Web、monitor、管理员看板与 worker 共用；管理员任务、checkpoint 和 SSE 数据契约不变。
  - 测试改为直接导入新职责模块，并将管理员 checkpoint 约束检查指向实际写入 `job_id` metadata 的 `graph_runner.py`。

---
2026.8.7（候选审核、Gold v2 与并行调优闭环）
- 【正确性】：候选输出拒绝覆盖已有 revision，dataset_id 做安全校验；retrieval sweep 的首个配置失败时标记 `baseline_failed`，不再把候选错误提升为基线；自定义 steps 缺少 `retrieval_eval` 时不再抛索引异常。
- 【生成与审核】：候选生成默认接入 Ragas 0.4.3 `generate_with_chunks()`，记录生成错误和拒绝摘要；新增隔离候选 run、SSE 进度/取消、逐题编辑、三态审核和 reviewed revision。
- 【版本门禁】：新增 Pearl 24 + 审核候选 48 的 Gold v2 冻结契约，以及只读绑定 active pointer、index manifest 和 `active_current` 的 Baseline v2 契约；不自动切换 active pointer 或发布 profile。
- 【前端】：候选题审核页面与 retrieval sweep 配置已接入 `/rag_eval`；前端可提交 sweep 配置矩阵和 `retrieval_sweep` 步骤。
- 【验证】：候选/Gold/Baseline/隔离任务及既有评测回归共 26 项 `unittest` 通过，Vue typecheck/build、Python 编译和 `git diff --check` 通过；真实 Ragas/Chroma 端到端仍待 Docker 可用且修复当前主机 Ragas 导入依赖后复验。

---
2026.8.7（候选接口与 Ragas SDK 受控复验）
- 【接口验证】：新增 Flask `test_client` 覆盖候选生成、状态、结果、产物下载、审核、Gold v2 冻结和 Baseline v2 失败关闭；非法布尔整数字段返回 400。
- 【Ragas 验证】：在关闭 LangSmith 追踪且不联网的受控模型下，实际调用已安装 Ragas 0.4.3 的 `TestsetGenerator.generate_with_chunks()` 并得到候选行；该结果只证明 SDK/适配链路，不代表真实模型生成质量。
- 【环境边界】：Docker 当前不可用，未执行 app/worker HTTP 端到端，也未调用外部 DeepSeek 或修改 active pointer。

---
2026.8.7（Docker 真实隔离评测复验）
- 【运行面】：Docker Desktop 恢复后，MySQL 主从、PostgreSQL、app、worker、monitor、checkpoint-cleanup 和 `rag-eval-worker` 均成功启动；`/rag_eval` 返回 200，页面显示后端已连接。
- 【真实链路】：通过 HTTP 创建 `eval_20260807_031531_00972a87bd`，经 SQL 队列和持久 worker 完成 `validate_datasets`、`retrieval_eval`、`retrieval_sweep`，2 组检索配置均为 `pass`，结果产物可由接口读取。
- 【结果边界】：该一题 smoke 的 retrieval 指标为 0，不能作为质量提升证据；候选题真实外部模型生成仍未执行，当前 active index 仍缺少 manifest，Baseline v2 保持 409 失败关闭。

---
2026.8.7（候选生成中断恢复）
- 【可靠性】：真实候选 smoke 在 Ragas `SummaryExtractor` 长时间无进展后通过取消接口收敛；补充 app 进程重启恢复逻辑，将不可续跑的 `created/running/cancelling` 候选 run 标记为 `failed`，避免永久悬挂。
- 【验证】：重启 app 后原 run `candidate_20260807_031820_095cbf2b56` 已收敛为 `failed/process_restart`；候选生成未产生有效题集，也未升级 Gold 或修改 active pointer。

---
2026.8.7（Ragas 真实候选 smoke）
- 【可靠性】：候选生成调用期间关闭 LangSmith tracing，并为 Ragas 0.4.3 设置有界超时、重试和等待参数；避免外部 telemetry 403 干扰生成，也避免默认重试窗口无限拉长取消收敛时间。
- 【真实链路】：HTTP 创建 `candidate_20260807_034548_b382b6a00e`，1 个 staged unit 经 `generate_with_chunks()` 完成 Summary、Embedding、Themes、NER、personas、scenario 和 sample 阶段，最终 `succeeded`，生成 1 条、通过筛选 1 条，生成错误/拒绝均为 0；随后真实 API 审核写入 reviewed revision。
- 【边界】：该 smoke 只有 1 条候选，Gold v2 冻结因未满足 Pearl 24 + 候选 48 返回 409；Baseline v2 因正式 Gold v2 不存在保持 409 失败关闭，未修改 active pointer 或正式 profile。

---
2026.8.7（Candidate audit 伴随产物）
- Candidate revision 现在始终生成同 revision 的 `candidate.json.audit.json`，保存生成错误、筛选拒绝和计数摘要；API 对成功和失败状态均保留固定 artifact 名称，便于追溯。
- 增加 audit 产物存在性和版本覆盖回归测试。

---
2026.8.7（前端真实候选 smoke）
- 通过 `/rag_eval` 页面真实启动 1 单元候选生成，收到 SSE `run_created`、`candidate_progress`、`screening` 和 `run_done`，随后在页面完成逐题审核并写入 reviewed revision；Gold v2 因只有 1 题按门禁返回 409。
- 修复前端把 HTTP 业务错误误显示为“后端接口不可用”的状态误报；服务器已响应但业务拒绝时保留“后端接口已连接”。

---
2026.8.7（候选 coverage 报告）
- Candidate audit 和题集 screening 增加 `rag_candidate_coverage_v1`，记录选中/覆盖 staged unit、evidence locator、多 evidence 样本及模态/内容类型分布；前端在逐题审核区展示该摘要，并明确它不等同于审核通过或 Gold 质量结论。
- 【验证】：候选生成专项 13 项、相关完整回归 30 项 unittest，Vue typecheck/build 均通过。

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

---
2026.8.9（知识源显示名与候选审核布局）
- 新增来源显示名元数据，用户可在来源目录为知识源命名；名称保存到 `tmp/rag_eval_sources/source_metadata.json`，摄取和候选 run 会快照该名称，source_id、内容 hash 和历史产物不变。
- 候选审核页统一显示知识源名称和短索引别名，并将审核/冻结门禁移动到生成区下方；审核员仍只保存到本地隔离候选 revision 与 review manifest，不写入 MySQL。
- 【验证】：新增来源显示名 API/本地元数据回归覆盖；相关后端回归 32 项通过，前端 typecheck/build、静态页 HTTP 200 和 `git diff --check` 通过。

---
2026.8.10
- 【管理员会话正文审计提示前置】
  - 将“读取正文将会记录管理员、目标、结果和 request ID。”从会话正文弹窗移至会话详情的消息摘要标题下方，使管理员在读取正文前即可看到提示。
  - 保留分析任务等其他敏感正文弹窗的默认审计提示，并补充组件与 Mock E2E 覆盖。

---
2026.8.11
- 【会话历史恢复 Agent 执行阶段】
  - `/api/load_session` 在单个主库只读事务中批量读取消息、附件、Job、输入账本和事件，通过既有外键与事件 ID 为用户输入组装 `thinking_after`，不新增数据库 schema。
  - 历史时间线只返回脱敏节点事件，排除 `text_delta` 与边界事件；关联缺失或多义时跳过对应区间并记录服务端告警，不使用时间猜测。
  - 前端复用实时节点处理器回放多次 interrupt/resume 阶段，interrupt 后保留已完成时间线；活动 Job 从实际回放游标继续 SSE，避免刷新期间重复或跳过事件。
  - 普通用户历史与 SSE 统一使用按事件类型的字段白名单，移除 `attempt` 和未知内部字段。

---
2026.8.13
- 【任务执行边界】将隔离摄取和候选题生成接入既有 `rag_eval_jobs` 持久队列，与 evaluation 共享 `rag-eval-worker`、SQL heartbeat、SSE run.json 事件和 fail-closed 超时收敛；Web 进程不再为这两类长任务创建后台线程。`rag_query` 暂保留兼容线程链路，未纳入本轮迁移。
- 【迁移门禁】新增 `job_kind` 队列字段，支持 `ingestion`、`candidate_generation`、`evaluation` 三类任务；不新建第二套队列，不改变 active pointer、staged index、Candidate/Gold/Baseline 门禁。

---
2026.8.13（三类任务持久队列收口，修正 8.13 早先日志的提前结论）
- 【问题修正】：此前 8.13 日志中「三类任务已统一接入持久队列」的结论早于实际完成状态，本轮补齐并修复阻断验收的问题。
- 【worker 终态】：修复摄取成功终态 `staged` 被 worker 误判为失败的问题——worker 现将 `ingestion + staged` 视为成功并同步 SQL 为 `succeeded`，其它三类任务的 `succeeded/cancelled/failed` 收敛保持不变。
- 【数据库迁移】：执行 Alembic 迁移，`rag_eval_jobs` 新增 `job_kind` 列与 `idx_rag_eval_jobs_kind_queue` 索引，数据库升级到 `g7c8d9e0f1a2`。
- 【启动门禁】：`check_database_readiness()` 新增对 `rag_eval_jobs.job_kind` 列与 `idx_rag_eval_jobs_kind_queue` 索引的检查，避免缺列时 worker 误启动、直到提交任务才报错。
- 【租约 fencing】：worker 心跳失联后触发 fencing，阻止原 worker 继续把成功结果写回 run.json/SQL；`complete_job` 返回是否真正发生 running→succeeded 迁移，失败时把 run.json 收敛为 failed，消除 SQL=failed、run.json=succeeded 的不一致。
- 【SSE 游标】：事件改用单调递增 `event_id` 作为游标，事件数超过 500 上限后不再永久漏读后续事件（含最终完成事件）。
- 【生产 Compose】：`docker-compose.prod.yml` 补齐 `rag-eval-worker` 服务，并为 app 与 worker 共享 `rag_eval_isolated_runs` / `rag_eval_sources` 运行目录。
- 【摄取页范围】：修复无 `page_ranges` 时 worker 二次归一化把空列表误判为非法的问题（`_normalize_page_ranges` 对空列表与 None 一视同仁），否则「HTTP 创建摄取 → 领取」会在 worker 侧直接失败。
- 【测试对齐】：更新因持久队列重构而过时的测试（evaluation 入队断言、候选生成同步执行、候选 run 进程重启恢复），新增「摄取 staged 视为成功」worker 测试。
- 【验证】：迁移后 readiness 通过；相关回归 50 项 unittest 通过；两份 Compose 配置解析通过；真实链路「创建摄取 → SQL 领取 → staged → SQL succeeded」实测通过（run.json=staged，SQL=succeeded，job_kind=ingestion）。

---
2026.8.13（第二轮：跨进程一致性、取消终态收敛与生产部署门禁）
- 【跨进程锁】：app 与 rag-eval-worker 分属不同进程却共用卷内 run.json，`threading.RLock` 只在单进程内有效。新增 `_run_file_lock`（Linux `fcntl.flock` / Windows `msvcrt.locking`），`_set_status` 与 `_emit` 的「读-改-写」现在串行化，避免并发丢失 `cancel_requested`、`event_seq` 与终态。
- 【终态收敛】：`complete_job` 返回 false（SQL 已终态）时不再一律 `mark_worker_fenced`，改为 `_reconcile_terminal_state` 按 SQL 实际终态收敛——`cancelled`→run.json cancelled、`failed`→run.json failed、`succeeded`→幂等保持，消除「SQL=cancelled、run.json=failed」分裂。
- 【生产模型与来源】：生产 Compose 修正 legacy 的 `./knowledge_base/db` 错误路径，并为 app 与 rag-eval-worker 挂载 `Agent/knowledge_base/models`（只读）、`Agent/knowledge_base/source`（只读）与 `Agent/knowledge_base/db`，补充 `MULTIMODAL_DOCLING_ARTIFACTS_DIR`，使生产摄取具备本地 embedding 模型、Docling 资源与冻结来源。
- 【生产 bootstrap 门禁】：生产 Compose 新增一次性 `db-bootstrap` 服务（`python -m Database.bootstrap`），app/worker/monitor 依赖其 `service_completed_successfully`；`Database.bootstrap` 在未配置 `CHECKPOINT_POSTGRES_PASSWORD` 时优雅跳过 PostgreSQL schema setup，避免隔离评测专用拓扑因缺 PostgreSQL 而整体失败。
- 【页范围校验】：`max_pages + page_ranges=[]` 不再被误判为「不能组合」，空列表与 None 一视同仁。
- 【回归测试】：新增跨进程文件锁（多进程并发读改写 run.json 不丢失更新）、`complete_job(false)` 时 SQL 分别为 cancelled/failed 的终态收敛、`max_pages + page_ranges=[]` 三项回归。
- 【验证】：相关回归 54 项 unittest 通过（含 fork 多进程锁测试）；两份 Compose 配置解析通过；bootstrap 无 PostgreSQL 时优雅跳过；真实链路「创建摄取 → staged → SQL succeeded → 终态一致」实测通过。

---
2026.8.13（候选题生成说明与布局收紧）
- 【前端】：候选题生成卡片在参数前增加紧凑说明框，明确“保存逐题审核”“冻结 Gold v2”“绑定 Baseline v2”的产物与边界；其中 Baseline v2 仅绑定已冻结 Gold v2 与只读 `active_current` retrieval，不修改 active pointer 或正式配置。
- 【布局】：候选题生成卡片不再继承工作台的大面积最小高度，说明框后依次展示目标单元数、每单元题数和并行 worker，减少空白区域。
- 【验证】：Vue `typecheck` 与生产 `build` 通过。

---
2026.8.13（候选题生成参数实时提示）
- 【前端】：候选题生成页直接展示当前 staged index 单元总数、本次实际最多选中单元数与请求生成题数；当 staged 单元不足 48 时提示无法按 Gold v2 推荐配置覆盖 48 个单元。
- 【参数边界】：目标单元数、每单元题数和并行 worker 分别补充就地说明，明确 worker 只影响速度；同时说明请求量不保证等于最终候选题数，筛选仍会拒绝重复题、短答案和无法回溯 evidence 的题。
- 【验证】：Vue `typecheck` 与生产 `build` 通过。

---
2026.8.13（RAG 评测运行台视觉系统升级）
- 【前端】：基于 UI/UX Pro Max 的研究运维型 SaaS 设计系统，统一 RAG 评测运行台的青蓝主色、绿色状态语义、表单焦点、流程状态、表格、报告和移动端样式；保留既有工作台、候选题审核、评测、对比和报告接口与业务流程。
- 【可用性】：补充稳定悬停、键盘焦点与 `prefers-reduced-motion` 降低动画支持，避免纯色传达状态。
- 【验证】：Vue `typecheck`、Vite 生产 `build` 与变更范围 `git diff --check` 通过。

---
2026.8.14（候选审核恢复与本地 Gold 闭环）
- 【前端】恢复源码中的“候选题审核”导航和逐题翻页审核界面；通过、待修改、拒绝会立即反映在实时摘要中，页面展示通过 48 题的冻结门槛、生成覆盖摘要和固定操作栏。
- 【Gold】已有 Gold 时改为就地确认：保留当前基准，或确认后先归档旧 Gold 再替换冻结；主界面统一使用“冻结 Gold 基准集”和“绑定评测基准”名称，内部版本号不再作为主操作文案。
- 【评测】评测配置改为读取服务端本地已冻结 Gold 的安全摘要，不再要求浏览器粘贴 JSON；未冻结时禁止启动评测，运行请求只提交 `dataset_source=gold_v2`。
- 【验证】Vue `typecheck`、Vite 生产 `build` 以及候选/Gold/隔离评测相关 Python 单元测试均已通过；未执行 Docker 重建或部署。

---
2026.8.14（候选生成取消可抢占）
- 【修复】Ragas `generate_with_chunks()` 本身不支持进程内抢占；候选生成改由 `rag-eval-worker` 的独立 Linux 子进程执行。取消请求到达后，父 worker 会终止该子进程、收敛 run 状态为 cancelled 并立即释放唯一 slot，避免后续评测长期排队。
- 【前端】SSE 收到候选/摄取/阶段进度后会同步刷新 run 状态，避免真实已运行仍持续显示“排队中”。
- 【验证】新增 worker 取消回归测试；候选、Gold 和隔离评测相关单元测试共 15 项通过，Vue typecheck/build 与变更检查通过。

---
2026.8.15
- 【即时取消与 Worker补强】
  - 增 execution_state、释放时间/原因字段、索引及数据库约束。
  - 实现 queued/running/waiting_input 取消、幂等重放和 fencing。
  - running 取消后进入 canceled/draining，支持 worker cleanup 或 420 秒失联回收。
  - 修复 EventWriter abort、迟到结果、终态 fencing 和 worker cleanup。
  - 更新 Session、用户、文件删除阻断规则。
  - 更新管理员 DTO、worker 看板、普通用户取消按钮、文档和测试。
  - `fail_job()` 在 Job 行锁内区分 `APPLIED`、`CANCELED_FENCED` 和 `OTHER_FENCED`；取消获胜时不再补写普通失败事件或失败聊天投影。
  - `OrderedEventWriter.abort()` 改为幂等且可观察：丢弃文字 buffer、结束排队 Future，并向 worker 传递未预期 consumer/数据库异常；只有被接受的终态写入才设置 `terminal_seen`。
  - `JobExecutionGuard` 覆盖节点、ToolNode、parser、router、retry backoff、error handler、终态生成和事件持久化边界；cleanup 未完成时不确认 `worker_confirmed` 释放。
  - 普通用户取消改为按 Job 隔离幂等键和 SSE subscription generation，支持 `409 canceled` 对账、真实终态展示，并丢弃取消后的迟到事件。
- 【聊天输入区与取消时间线修复】
  - 移除任务排队状态框；Job 进入 queued/running 后，发送按钮显示旋转外环与中心停止方块，输入框保持可编辑。
  - 创建或恢复 Job 后立即释放输入区，不再等待整个 SSE 订阅生命周期；waiting_input 继续保留恢复发送和紧凑取消入口。
  - 取消 Job 时统一收尾所有仍处于进行中的时间线阶段、文字草稿和动画，避免子阶段继续显示“进行中”。

---
2026.8.15（Gold locator 门禁与候选题重绑复审）
- 【冻结门禁】Gold v2 冻结前强制校验候选题 `bound_index_version` 与当前 staged index 一致，并逐条确认 `unit_id/document_id/page_number/modality/content_kind` 在该索引的 `units.jsonl` 中真实存在；绑定审计字段不再混入运行时 locator 匹配。
- 【历史候选】将 48 道候选题重绑到 `mm_f956e532ed6d49ae1f0e`，生成独立待复审候选产物；48/48 题均重置为 `needs_revision`，86 条 locator 校验通过。另生成待复审 manifest，不覆盖原 Gold 或原候选文件。
- 【质量提示】自动标记拼写/非正式措辞、歧义引用、过短、过度复合和跨文档题目；当前 48 题中 20 题触发至少一项提示，全部仍需人工重新审核。
- 【运行门禁】评测与 Baseline 绑定遇到未绑定当前索引的旧 Gold 时直接拒绝，避免继续产生伪低分结果。
- 【验证】相关 Python 回归 17 项、Vue typecheck/build 均通过。

---
2026.8.16
- 【RAG 子图 State 隔离与父图统一输出】
  - 新增 `RagSubgraphState`，将 RAG route、问题列表、ToolMessage、Parser 中间结果和最终输出限制在子图内部。
  - 增加父子 State 适配节点，显式透传 LangGraph `config` 与执行上下文，父图只接收 `knowledge_base_result`，并保持 `mcp -> rag -> agent` 路径。
  - 将 RAG 子图统一为 Planner、ToolNode、Parser、Finalize 条件路由；保留 Planner、RAG task 和 ToolNode 的既有重试次数及普通异常降级边界。
  - 统一 RAG 降级结构，保留 `success`、单问题 `insufficient_evidence` 语义，并继续向 worker 传播 `JobExecutionRevoked` 与 `CancelledError`。
- 【RAG 不可用预检与协议错误分流】
  - 将已有 worker 进程级 `rag_available` 和空工具列表传入 RAG Planner；知识库未初始化或工具未注册时在 Planner 预检阶段跳过 ToolNode，经 Finalize 继续回到 Agent。
  - 为 RAG 查询失败和非法 ToolMessage JSON 增加明确错误标记，分别保持 `unavailable` 与 `protocol_error` 语义，不改变取消/撤销异常传播和既有重试边界。
  - 补充 RAG 预检、查询错误标记、协议错误分流和权威验证边界文档。

---
2026.8.16（隔离评测显式 staged 索引重绑）
- 【重绑目标】：候选题重绑接口改为必须接收页面明确选择的 `ingestion_run_id + index_version`，并在服务端确认该目标为已就绪的 staged 摄取运行；重绑成功后同步更新候选题运行的索引归属，冻结不会再回落到候选题生成时的旧索引。
- 【前端边界】：审核区展示实际重绑目标的日期、知识源和状态；“绑定正式生产基准”只在冻结 Gold 与已发布 active 索引一致时可用，避免把 staged 评测索引误当作生产基准绑定目标。
- 【验证】：候选题路由回归 3 项、Vue `typecheck` 和 Vite 生产 `build` 通过。

---
2026.8.16（隔离评测工作台全局索引上下文）
- 【交互边界】：已摄取索引只允许在隔离知识源工作台切换；候选审核、Gold 冻结与评测中心只展示并使用当前工作索引，不能在子页面另行切换。
- 【恢复规则】：刷新后优先恢复浏览器上次明确选择的摄取运行，仅在该运行不存在时才回退到运行中或最新 staged 索引。
- 【验证】：Vue `typecheck` 与 Vite 生产 `build` 通过。

---
2026.8.16（隔离评测无法重绑时重新生成候选集）
- 【审核出口】：当历史候选题 locator 无法迁移到当前工作索引时，候选审核页提供“重新生成当前索引候选集”；新任务使用当前全局 staged 索引，旧审核记录只保留为历史运行，不会删除。
- 【验证】：Vue `typecheck` 与 Vite 生产 `build` 通过。

---
2026.8.16（隔离评测候选题生成确认配置）
- 【确认步骤】：生成与重新生成候选题均先进入配置页，不再点击即入队；页面展示当前全局索引、预计请求题数和冻结目标，并允许在服务端边界内调整选中单元数、每单元题数和并行 worker。
- 【验证】：Vue `typecheck` 与 Vite 生产 `build` 通过。

---
2026.8.16（隔离评测候选任务恢复与事件隔离）
- 【恢复】：页面刷新不再自动导入历史重绑候选包覆盖当前候选任务；与当前工作索引不一致的已完成候选题会被忽略并提示用户生成当前索引的新候选集。
- 【事件】：候选摄取/生成事件不再写入评测流程事件面板；候选任务失败时在候选页展示服务端错误摘要。
- 【验证】：Vue `typecheck` 与 Vite 生产 `build` 通过。

---
2026.8.16（隔离评测候选题 locator 索引绑定修复）
- 【修复】：候选题生成现在会把 staged `source_snapshot` 同步写入样本级 `source.index_binding`，并为每个 `gold_evidence` locator 写入 `bound_index_version`；避免审核完成后在 Gold 冻结阶段才因 locator 未绑定当前索引而失败。
- 【一致性】：候选题重绑产物同样保留样本级索引绑定，且仍强制生成待复审清单，不自动迁移历史审核通过结论。
- 【验证】：候选/Gold/路由回归 20 项在宿主和 `rag-eval-worker` 运行镜像均通过；真实后台重绑 63 条候选后，样本与 locator 均绑定到 `mm_285e8738562b11e8adb1`。未复审候选冻结仍按预期拒绝。

---
2026.8.17（隔离评测运行对比题集版本提示）
- 【提示】：运行 A/B 下拉框新增 Gold dataset revision；当后端因两次运行的完整题集 identity 不一致而拒绝严格比较时，前端改为说明基线与候选所用 revision、同名题集不等于同内容，以及应选择同一 revision 或仅作趋势参考。
- 【可访问性】：比较错误提示新增 `role="alert"`，使辅助技术可及时获知不可比较原因。
- 【验证】：Vue `typecheck` 与 Vite 生产构建通过，生产静态产物已同步。

---
2026.8.17（隔离评测完整策略并行实验）
- 【后端】：新增 `POST /api/rag_eval/isolated/evaluation-batches`，一次校验并创建 2–4 个不同策略 profile 的独立 evaluation run；run 状态保存 `batch_id/batch_position/batch_size`，仍复用现有持久队列、租约、取消和报告链路。
- 【执行】：`RAG_EVAL_EVALUATION_WORKERS` 默认改为 2，并限制在 1–4；开发、兼容副本和生产 Compose 同步该默认值。每个 slot 仍独立领取一个 SQL 任务，不在 Web 进程执行长任务。
- 【前端】：评测中心支持多选 2–4 个 profile 并行启动，统一轮询批次状态、切换查看逐 run 事件、批量取消，并在全部结束后进入严格 A/B 对比。
- 【并发修复】：真实双 slot 冒烟首次暴露本地 HuggingFace embedding 同时构造的 PyTorch `meta tensor` 竞态；Runtime 现在只串行化进程内本地模型初始化，初始化完成后的两个评测仍并行执行。
- 【实验方案】：新增 `Document/rag_experiment_2_plan.md`，依据实验一的阶段召回损失和固定题/候选题分组指标，提出“混合召回增强”主实验及三个并行对照组；相同 Gold revision 下只改变检索参数。
- 【验证】：并行批次 HTTP 契约、批次快照、worker 多 slot 启动、本地模型并发初始化回归及既有队列回归通过；Vue typecheck/build 和三份 Compose 解析通过。Docker 真实冒烟中两个 retrieval-only run 于同一秒分别由 slot 1/2 启动，并在同一秒成功结束。

---
2026.8.17（Ragas 外部模型失败关闭）
- 【根因】：最新完整评测确实提交了 `run=true` 并进入 `ragas_eval`，但回答生成 72/72 收到模型服务 `HTTP 402 Insufficient Balance`；旧实现仍继续调用/聚合 Ragas，并把全 NaN 结果标记为 `needs_review/ragas_no_valid_scores`，事件因此误导为“Ragas 已完成”。
- 【修复】：隔离 Ragas 准备阶段在首个明确的回答生成失败时立即停止，不调用 judge；step 改发 `step_error`，run 与 SQL job 收敛为 `failed/answer_generation_failed`。judge 无有效数值分数时同样失败关闭为 `ragas_judge_no_valid_scores`。
- 【可诊断性】：失败 evaluation 仍暴露 `result.json` 和报告；Ragas Markdown 新增失败原因、失败回答数和错误摘要，前端可加载失败运行结果。
- 【验证】：新增回答生成失败与 run 终态传播回归；真实单题 Ragas 冒烟 `eval_20260817_162511_a65c4e1dfd` 在首题收到 402 后快速失败，事件包含 `step_error/run_error`、无 judge 事件，结果与报告均可读取并展示 402 原因。

---
2026.8.18
- 【日志管理第一阶段 1.1：日志契约与 Job 请求关联】
  - 新增可观测性日志 v1 契约、现状盘点、敏感信息边界和第二阶段布点清单，并接入 `Document/` 导航。
  - 新增 `c3d4e5f6a7b8_add_analysis_job_request_id` migration，保存创建 Job 的原始 `X-Request-ID`；历史行保持 `NULL`，不新增索引。
  - 将请求 ID 从创建路由传入 Job service，服务层执行格式校验；幂等重放保留首次请求 ID，不被后续请求覆盖。
  - 同步 readiness、deep audit、迁移链测试、Job 创建测试、迁移 head 文档和 E2E head 预期。
- 【日志管理第一阶段 1.2：共享 JSON 运行时与进程接入】
  - 新增共享 `observability` 日志运行时，统一 UTC、单行 JSON stderr、标准 `logging.extra` 事件字段、contextvars 上下文、递归脱敏、体积限制、异常栈清理和序列化失败降级。
  - 接入 Web、worker、monitor、db-bootstrap、checkpoint-cleanup 及维护脚本的启动日志，新增稳定启动事件；旧业务日志保持合法 JSON，无法可靠分类时不伪造 `event_code/category`。
  - 移除 MCP server 本地 `FileHandler` 和数据库初始化文件日志；MCP stdout 保留协议，应用日志经 worker stderr 进入容器日志。
  - 补充日志运行时、并发上下文和 MCP stdio 边界单元测试；未执行真实 Docker、数据库、PostgreSQL checkpoint 和模型/MCP 端到端验收。
- 【日志管理第一阶段 1.3：默认开发可观测拓扑】
  - 在默认开发 Compose 中锁定 Grafana 13.1.1、Loki 3.7.4 和 Alloy v1.18.0，新增独立 observability network、Grafana/Loki/Alloy 持久卷和资源上限；Grafana 仅绑定 127.0.0.1:3000，并要求非空 GRAFANA_ADMIN_PASSWORD。
  - 通过 Compose 静态标签限定 Alloy 只采集 Web、worker、monitor、MCP 转发和维护容器，排除数据库与可观测组件自身；MCP 继续复用 worker stderr。
  - 新增 Loki 单节点 TSDB/filesystem、72 小时保留、compactor、写入/查询限制、Logs Drilldown 能力配置，以及 Alloy Docker 解包、应用 JSON 提取、低基数标签和持久 positions 配置。
  - 新增 Grafana Loki datasource、最小错误仪表盘和可观测拓扑静态契约测试；本次未执行真实 Docker 镜像拉取、全栈启动、positions 重启、Loki 暂停恢复和 30 分钟负载验收。

---
2026.8.18（正式 RAG P0–P2 上下文链路）
- 【P0】：新增并冻结 `Agent/knowledge_base/rag/runtime/production_rag_config.json`，正式 retrieval 基线采用 sparse16、final_top_k6、MMR 0.6，并记录来源 run 与 Gold revision。
- 【P1】：`RagRetrievalConfig` 新增 `answer_max_contexts`；正式 `RagService` 在回答前应用该预算，不再把 Ragas judge 的 `max_contexts` 误认为正式回答上下文限制。
- 【P2】：新增 `answer_context_compression=page_dedupe`，按文档/物理页/内容类型去重；隔离评测的回答模型与 Ragas judge 复用同一 evidence，并记录压缩审计字段。
- 【前端】：评测配置增加正式回答 evidence 压缩选择，检索 profile 快照会包含回答上下文配置。
- 【验证】：新增正式服务上下文预算、page dedupe、隔离回答/judge evidence 一致性回归；`query_rag` 读取 P0 production config 为 `published_config`。
- 【前端修正】：将 `answer_max_contexts` 从通用 retrieval 参数网格中独立成“正式回答上下文”区域，和 evidence 压缩并列展示；旧 profile 缺少该字段时默认显示 P0 的 6 条上下文。Vue typecheck/build 通过，静态页面已同步。
- 【前端调整】：按使用反馈取消独立上下文卡片，将 `answer_max_contexts` 与 `answer_context_compression` 并回原 retrieval 参数列表；前者为普通数值字段，后者为普通下拉字段，不再制造特殊配置区。
- 【修复】：E4 两个并行 run 因 `official_only_when_available` 被误判为不支持的 retrieval override 而在启动阶段失败。原因是新增 answer context 字段时白名单错误收窄到 `RagRetrievalConfig`，已改为允许 profile 字段与 dataclass 字段的并集；adapter-only 字段仍由 `build_retrieval_config` 安全忽略。
- 【验证】：新增隔离评测 override 回归，相关容器测试 27 项通过；失败 run `eval_20260818_074121_84964d4825`、`eval_20260818_074121_56e064a519` 是旧代码生成的历史失败记录，不会被修改，修复后需重新创建 E4 批次。

---
2026.8.18（Gold v2 无人值守题目健康治理）
- 【治理规则】：新增 `dataset_governance` 持久队列任务。只处理带 `source.generator` 的生成题；`human_reviewed`、无 generator 和其他非生成来源永久保护。单次或单指标低 Ragas 分只作为诊断，不能独立退休题目。
- 【审核门禁】：生成题需存在 intrinsic 风险且独立结构化 reviewer 返回 `replace`/confidence >= 0.8；替换候选复用现有 hard screen，并需 `accept`/confidence >= 0.8。审核异常、超时、解析失败统一保留原题。
- 【版本与恢复】：题数、Gold schema、index identity、locator 或候选数量不满足时治理失败，旧 Gold 不变；有替换时在跨进程锁内复核源 evaluation 的数据集 SHA，拒绝 stale run 覆盖新 revision，再归档旧 Gold 并原子写入；零替换只返回 `no_change`，Gold 文件与 revision 不变。不切换 production active index/profile。`/api/rag_eval/gold-v2/governance` 与治理 run API/SSE 提供一次确认、阶段、计数、逐题原因和失败恢复信息。
- 【验证】：治理规则、reviewer fail-closed、stale publish、no-change、index binding 与治理路由回归共 8 项 Docker pytest 通过；5 个相关 Python 文件完成不写 `.pyc` 的内存语法编译，Vue `typecheck` 和 Vite `build` 通过。未调用真实外部 AI。

---
2026.8.19（Gold v2 治理候选分批恢复）
- 【修复】：治理专用候选生成按 8 个 staged 单元分批，每批最多 3 次尝试并按 3/6 秒退避；连接中断只重试当前批次，已通过 hard screen 的批次产物及审计会保留。
- 【失败边界】：累计候选不足时写入批次汇总审计并 fail closed，旧 Gold 不变；达到所需候选数后提前停止，避免无效额外模型调用。
- 【验证】：治理分批重试、候选生成和路由相关 Docker pytest 共 24 项通过；未调用真实外部 AI。

---
2026.8.20（索引绑定调参集自动治理闭环）
- 【边界】：新增独立 `tuning_dataset_governance` 任务，仅消费当前 staged index 绑定的 Gold 自动题；人工题永久保留，不进入正式评测 history、报告或对比分析。
- 【循环】：每轮只评测当前自动题，按四项 Ragas 单题门槛和 retrieval recall/MRR 门槛淘汰低分题，再生成候选、执行证据审核并补齐题数；审核或分数缺失均 fail-closed。
- 【登记】：通过后将题集写入本次隔离运行的 `registered_dataset.json`，携带 index version 与 tuning run 身份；不修改 Gold 文件、不发布 active pointer。
- 【前端】：工作台新增索引绑定调参集入口，说明目标题数、门槛和“不会进入正式报告”的边界，运行状态通过隔离 SSE 展示。
- 【验证】：新增闭环核心单测；Docker 相关契约与治理测试 31 项通过；RAG 评测前端 typecheck/build 通过。

---
2026.8.20（隔离任务状态刷新兜底）
- 【修复】：治理进度事件现在会立即触发状态拉取；运行期间增加 5 秒轮询兜底，SSE 丢事件或断线时仍能收敛到后端终态。
- 【恢复】：浏览器标签页重新激活时主动刷新当前运行；调参集状态明确区分“本轮评测题数”和“待补题数”，避免把当前批次数误认为剩余题数。
- 【验证】：RAG 评测前端 typecheck/build 通过。

---
2026.8.20（RAG 测评后端队列与题集绑定审计）
- 【统一执行】：staged index RAG 试跑从 Web daemon thread 迁入 `rag_eval_jobs`，与摄取、候选生成、完整评测和题集治理共享持久 worker；开发、兼容副本和生产 Compose 的 `RAG_EVAL_EVALUATION_WORKERS` 默认统一为 5。
- 【题集门禁】：所有内联 `rag_eval_v1` 题集在入队前执行 `dataset_kind` 语义校验；`generated_candidate` 还必须通过当前 staged index 的 source snapshot、unit locator 和 index version 校验，跨索引题集直接拒绝。
- 【接口一致性】：Gold 状态接口缺少成对的 `ingestion_run_id + index_version` 时返回 JSON 400，不再抛出 HTML 500；未删除任何接口，仓库无前端调用的接口单独列入人工审核清单。
- 【验证】：宿主与现有 `rag-eval-worker` 容器内相关回归均为 83 项通过；三份 Compose 配置展开、10 个相关 Python 文件不落盘语法编译和本次范围 `git diff --check` 通过。未重启正在运行的 worker，5 slot 默认在下次重建或重建容器后生效。

---
2026.8.20（候选题审核启动/收尾页与 Ragas 进度展示）
- 【审核流程】：候选题审核新增启动、逐题审核和完成三态；最后一题做出结论后进入完成页，不再跳回第一题。
- 【审核统计】：前端独立记录已操作题目，使“待修改”作为有效审核结论统计；完成页提供题号直达、保存审核、冻结 Gold 和返回评测工作台。
- 【进度展示】：复用现有 `step_progress` 事件展示五个评测阶段；Ragas 准备题集与 Judge 轮次分开显示，`1/1` 明确标注为 Judge 轮次。
- 【验证】：新增纯函数状态/进度回归测试 3 项；RAG 评测前端 `npm run typecheck`、`npm run build` 和 Node 测试通过。

---
2026.8.21（RAG 测评生产工程化 Tasks 1–8：接口审计与工程事实同步）
- 【Tasks 1–8 收口】：补齐通用 canonical run lifecycle、不可变 `rag_eval_datasets`/`dataset_ref`、staged index 完整身份门禁、持久队列优先级与分类型并发、容量只读快照、验收矩阵及安全 runner 的工程事实；接口审计清单写入 `Document/rag_eval_api_inventory.md`。具体 run 生命周期兼容接口继续返回弃用 header，本轮未删除任何接口；待移除项仅供用户后续审核。
- 【验证记录】：前序 Tasks 1–7 的交付已记录 focused tests、Python 编译、Alembic head、Compose config 和 contract list 验证；本 Task 8 重新执行路由/引用扫描、配置键扫描和 `git diff --check`。根验收已用 `D:\Anaconda\envs\CA-py310\python.exe scripts/run_rag_eval_production_acceptance.py --layer contract --list` 成功重跑 contract list（exit 0）；该命令只列出 checks、不执行 checks，且上述检查均不等同于真实生产验收通过。

---
2026.8.21（索引绑定调参集候选补题连接失败恢复）
- 【修复】：候选补题保留每批三次连接重试，但不再因连续两批短暂连接失败提前放弃其余已选知识单元；只有已选候选预算全部耗尽且数量仍不足时，才保持 fail-closed 失败。
- 【回归】：新增“连续两批连接失败后继续第三批并补齐候选”用例；原提前停止策略下用例稳定失败，移除提前停止后通过。

---
2026.8.22
- 【日志管理修复：补齐登录时间写入失败事件】
  - 保留 `mysql.connector.Error` 的数据库失败事件路径，为超时、连接异常和未知异常增加 `auth.login.last_login_update_failed` 事件及稳定原因码。
  - 更新认证服务测试和事件目录测试，验证登录时间写入失败不会阻断登录且不回显异常原文。

---
2026.8.23（RAG 子图编排与评测配置命名对齐）
- 【合并决策】：父图中的 RAG 阶段恢复为 Planner、ToolNode、Parser、Finalize 子图，并通过适配节点向父图投影最终检索结果；worker 同步采用模块化运行时入口。
- 【配置】：RAG 评测的配置键与临时目录统一使用 `RAG_EVAL`/`rag_eval` 命名，保留既有评测队列、题集与测试能力。

---
2026.8.24
- 【日志管理第三阶段：独立 Grafana 异常日志看板实现】
  - 保持 `causalagent-logs` Dashboard UID 和既有 Loki 数据源不变，将展示范围固定为 `warning`、`error`、`critical`，并继续在 Loki 中保留 INFO/DEBUG 供 Explore 排障。
  - 增加环境、服务、分类和异常级别筛选，以及异常总量、级别趋势、服务/分类分布、Top 10 事件码和最近 200 条异常日志面板。
  - `event_code` 仅在查询阶段解析；request、Job、用户、节点、工具和实例字段不新增为 Dashboard 变量或 Loki 标签。
  - 本次不新增 Flask/Vue 日志入口，不修改生产 Compose；只执行基础静态检查，真实 Grafana/Loki、浏览器和故障场景验收仍待人工完成。
- 【修复：旧 Job 执行占用阻塞数据库升级】
  - 为 `b2c3d4e5f6a7` 前的旧库增加只读迁移 preflight 和显式 dry-run/apply 修复工具，不改写历史 migration，也不自动清理业务数据。
  - 修复命令要求数据库、revision 和候选条数三重确认，拒绝运行中 Job、部分迁移 schema 和状态漂移；事务内只清除非运行 Job 的旧 `worker_id` / `locked_at`。
  - 程序化 bootstrap 保留共享 JSON stderr 日志配置，避免 Alembic `fileConfig` 覆盖最终失败事件，并补充数据库修复与启动编排测试。
- 【Grafana 默认简体中文】
  - 开发 Compose 将 Grafana 服务器默认语言设置为 `zh-Hans`，新账号和未保存个人语言偏好的账号默认使用简体中文。
  - 保留 Grafana 个人偏好优先级，不修改生产 Compose、数据卷、Loki 或异常日志看板查询。
- 【管理员侧栏新增 Grafana 切换入口】
  - 在管理员侧栏页脚的“进入聊天”上方新增“进入 Grafana”按钮，直接跳转到默认开发环境的 `http://127.0.0.1:3000/`。
  - 为桌面展开、折叠和移动端布局补齐交换图标、按钮间距及 Mock E2E/组件测试覆盖，不改变 Flask 管理员鉴权或 Grafana 登录边界。

---
2026.8.24
- 【联网搜索引用接口边界纠正】
  - 保留报告终态 `final_result.data.references` 与历史消息 `message.references` 的 `title + url` 引用接口，以及独立附件持久化能力。
  - 撤回 `preprocess`、`postprocess` 和 `report` 节点与引用功能无关的流式 LLM 配置；公开文字流仍仅用于普通问答和报告追问。
  - 增加父图 LLM 流式使用范围的回归测试，并补充普通用户 SSE 引用字段契约。

---
2026.8.24
- 【BUG修复】：兼容 mysql-connector 返回的大写元数据列名，修复统一数据库 bootstrap 启动失败。
- 【数据库修复】：完成现有数据库至 `j9e0f1a2b3c4`，清理已结束 Job 的历史运行时租约字段。

---
2026.8.24（RAG 评测产物路径统一与历史迁移）
- 【路径统一】：新增 `RAG_EVAL_ROOT`，默认将运行、来源、登记题集、调参集、基线、制品和报告归档到 `tmp/rag_eval/` 下；旧的细分环境变量仍可覆盖默认路径。
- 【迁移】：将旧 `tmp/rag_eval_*`、`Agent/knowledge_base/rag/output/` 以及 Document 下历史 Gold 治理产物迁移到统一目录，并生成迁移 SHA-256 清单；压缩索引制品同步修正归档内外的恢复路径。
- 【脚本与部署】：候选生成、基线、离线评测、验收 runner、制品打包和 Docker Compose 均改用统一路径；人工维护文档仍保留在 `Document/`。

---
2026.8.24（RAG 评测运行产物删除与来源竞态修复）
- 【工作索引删除】：工作台下拉框只展示 staged 摄取运行；新增摄取运行删除接口，删除前检查候选题、RAG 试跑、评测、治理、Gold 和生产 active pointer 引用。
- 【运行产物删除】：候选题、调参集治理和 Gold 治理的终态运行支持删除；运行中任务和仍有下游引用的运行统一拒绝删除。
- 【来源生命周期】：来源删除同时阻断 queued 摄取，避免排队任务在来源已删除后才开始执行；工作台补充来源显示名改名入口并清理已删除来源的元数据。
- 【验证】：新增生命周期回归测试，容器内定向测试 26 项全部通过；。

---
2026.8.25
- 【SearXNG 部署初始化与可降级边界】
  - `searxng-init` 改为在配置目录内生成临时 `settings.yml`，完成 secret 注入和占位符校验后原子发布，生成失败不留下半初始化目标文件。
  - 固定开发 Compose 的 SearXNG 镜像版本，并增加 `/healthz` 浅层 healthcheck；默认 app/worker 保持与 SearXNG 解耦。
  - 保留联网搜索运行期重试和统一降级语义，补充 init 脚本、Compose 部署契约测试和隔离 Docker 验证入口，并同步部署、启动和测试文档。
- 【联网搜索容错、开关校验与结果上限】
  - 为联网搜索新增 `WebSearchStatus`、`build_web_search_degradation_result()`、`degrade_web_search_parser_failure()` 和 `degrade_web_search_adapter_result()`；result_parser 与父图 web_search 节点分别注册协议错误和子图整体失败兜底，统一降级后回到 `agent`。
  - 降级结果统一包含 `success`、`status`、`query`、`results`、`content` 和错误字段；异常对象经 `sanitize_error()` 归类，`CancelledError` 与 `JobExecutionRevoked` 保持原有传播语义，不转成普通搜索失败。
  - `web_search_enabled` 在路由层和 Job service 层均只接受 JSON 布尔值，非布尔请求返回 `400` 或在服务层拒绝，并继续参与请求指纹和幂等冲突判断。
  - 统一使用 `WEB_SEARCH_MAX_RESULTS=9` 控制搜索结果合并、报告/追问注入和最终引用投影，避免报告依据超出公开引用范围。

---
2026.8.25
- 【合并 develop：联网搜索与结构化日志能力整合】
  - 同时保留联网搜索上下文路由和 develop 的节点结构化错误日志，补齐联网搜索父图与子图 error handler 的节点、超时元数据。
  - Job 创建链路同时持久化 `web_search_enabled` 与原始 `request_id`，保持搜索开关参与幂等指纹且重放不覆盖首次请求 ID。
  - 正常报告与降级报告继续公开受限搜索引用，同时遵守统一 JSON stderr 日志合同。
  - Web Search Planner 内部结构化输出降级改用受管事件，移除 query、命中数和路由选择的普通日志；历史引用附件解析失败使用不含消息 ID 和正文的注册事件。
  - 默认开发 Compose 同时保留 SearXNG/Valkey 搜索服务和 Loki/Alloy/Grafana 可观测拓扑，并同步部署与测试文档。

---
2026.8.25（RAG release readiness 与 Agent worker drain）
- 【Runtime readiness】：worker 启动复用 active release resolver 做轻量 pointer、manifest、正式来源、embedding、版本、collection 和向量目录检查；失败时继续运行并标记内部 `rag_unavailable`，保留对外 `status=unavailable`，不加载 RAG 重资源。
- 【Worker 生命周期】：新增 `JOB_DRAIN_TIMEOUT_SECONDS`（默认 60 秒）；SIGTERM/SIGINT 停止领取新 Job，超时只取消本地任务并交由既有 stale lease recovery 接管，worker Compose stop grace 至少 75 秒。
- 【Release 保留】：active pointer 发布时保留 previous pointer，维护 status 只读展示 active/previous/candidate 与候选超额提示，不自动删除目录；retrieval policy 继续独立回退与发布。
- 【文档/验证】：同步运行时、部署、架构、README、Compose 契约和定向 worker/index 测试；本轮未扩展当前生产 Compose 中缺失的 Agent worker/PostgreSQL checkpoint 拓扑。

---
2026.8.25（多模态正式来源 canonical 契约收紧）
- 【来源契约】：正式来源改用 canonical `source_id`、稳定 `document_id` 和精确 SHA-256；只在配置声明的受控目录树内按哈希唯一解析，并校验扩展名与文件签名。配置文件名变化不改写既有 Gold `document_id`，目录外同 hash 和零/多命中均 fail-closed。
- 【发布门禁】：legacy manifest 仅保留只读历史识别，不能满足正式发布；发布前重新校验 manifest、来源、策略、评测和索引完整性。VLM 默认关闭，只接受来源级显式授权，不引入页级授权。
- 【验证边界】：改名、唯一 hash、签名/扩展名、目录外同 hash、未授权 VLM 和非正式 manifest 使用 tempfile 受控目录 fixture；隔离 worktree 不含 `.gitignore` 忽略的正式 PDF，默认本地文件检查记录为 0 命中，未复制文件或放宽目录边界。

---
2026.8.25（多模态 release API 与发布控制台）
- 【VLM 授权】：隔离摄取远程 VLM 默认关闭；前端按来源提交显式授权，run 状态和 manifest 保存授权集合。
- 【正式发布】：新增 release status、gate-check、publish、rollback API；隔离 staged 索引先晋级正式候选目录，再由用户确认切换 active pointer，保留 previous 且不自动删除旧产物。
- 【前端】：新增正式发布控制台、门禁清单、active/previous 摘要和发布确认弹窗；检索策略配置发布按钮改名，避免与 active pointer 发布混淆。

---
2026.8.25（历史来源兼容与隔离索引级联删除）
- 【来源兼容】：正式固定来源 ID 改为内容 SHA-256 派生 ID；历史文件名绑定 ID 仅作为只读别名解析，重新摄取不再从历史索引覆盖当前来源选择。
- 【级联删除】：工作台删除摄取运行时可级联清理同一隔离运行树下的终态候选、评测、检索和治理产物；生产 active pointer、Gold、运行中任务以及非隔离共享注册数据仍阻断删除。
- 【验证】：后端相关回归 48 项通过（跳过 1 项条件测试），前端 typecheck、单测 3 项、生产构建、Python 编译和 diff 检查通过；真实历史运行仅做阻断验证，未删除现有产物。

---
2026.8.26（RAG 文档职责收敛）
- 【架构文档】：新增 `Document/architecture/rag-evaluation.md`，统一记录隔离评测、来源、staged index、release、评测 worker 与生产切换边界。
- 【API 契约】：新增 `Document/api/rag-eval.md`，覆盖当前 `/api/rag_eval` 的 77 个 method-path 操作、请求/响应、SSE 和兼容路径。
- 【清理】：移除 `Document/` 下旧的独立 RAG 说明、runbook、实验计划和 release worker spec；历史 `CHANGELOG.md` 条目保持不变。
- 【验证】：完成现行引用、Markdown 头部/相对链接、路由集合与 `git diff --check` 检查。

---
2026.8.26
- 【RAG 白名单导入与 develop 融合】
  - 从 `feature/rag_enhancement` 仅导入隔离评测、多模态摄取/OCR/索引、active release publish/rollback、Agent worker readiness/drain、RAG worker/卷/配置、迁移、前端、测试和验收 runner；保留 develop 的 Job、WebSearch、日志与文档体系。
  - RAG 评测任务使用 MySQL 持久队列和独立 `rag-eval-worker`；生产 Agent worker 启动时轻量检查 active release，缺失时保持无 RAG 降级，SIGTERM/SIGINT 按 `JOB_DRAIN_TIMEOUT_SECONDS` 停止领取并等待在途任务。
  - 多模态链路保留受控来源、OCR/可选远程视觉、staged index、评测与显式 release gate；publish/rollback 保留 active/previous 指针且不自动删除索引或运行产物。
  - 新增 RAG API/架构文档、隔离评测前端、数据库迁移和生产验收入口；不导入 MySQL queue drill Compose、runner 与测试，并移除已被多模态运行时替代的旧 RAG 原型和样例导出文件。
