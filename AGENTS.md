# CausalAgent AGENTS.md

本文件适用于仓库根目录及其所有子目录；如果更深层目录存在新的 `AGENTS.md`，以更近的文件为准。
评测策略 profile 统一包含 retrieval 与 Ragas 配置：`active_current`、`quick_cached`、`reviewed_5_core_metrics` 等内置 profile 来自代码且只读；用户自定义 profile 持久化在 MySQL 的 `rag_eval_profiles` 表，可通过 `/api/rag_eval/profiles` 创建、更新、删除和发布。发布只写入 `Agent/knowledge_base/rag/runtime/production_rag_config.json` 的正式 retrieval 快照；每次隔离评测仍把完整策略 profile 快照写入自己的 `run_manifest.json`。

## 1. 工作规则

1. 总是用中文回复。
2. 严禁删除重要文件；如果确实需要删除，请提示用户自行删除，或先获得用户明确确认。
3. 使用第一性原理思考。不要默认用户已经完全明确目标和实现路径；如果目标不清晰，先澄清问题；如果目标清晰但路径不是最短，明确指出并给出更直接的方案。
4. 查询文档、规范、官方示例时，优先使用真实查询工具，例如 MCP、内置网络工具、已安装的合适 skills 等，并返回真实链接。
5. 先读后写，先核实后修改；不要凭空猜测项目结构、接口、配置或业务逻辑。
6. 以最小必要改动解决问题，不做无关重构，不引入炫技式复杂度。
7. 修改后必须做与改动直接相关的验证；如果受环境限制无法验证，要明确说明未验证部分和风险。
8. 对于结构、目录、启动方式、数据库初始化方式等“项目事实”的改动，需要同步检查并更新 `AGENTS.md` 和 `README.md` 是否仍准确。

### git 要求
1. 禁止主动提交更改
2. 当修改完成时候，为修改提出相应的提交信息和批次建议
3. git标准：keyword(function):dec
   - keyword 支持 `feat`、`fix`、`docs`、`refactor`、`test`、`chore`、`ci`、`build`、`perf`、`revert`
   - Pull Request 标题使用相同格式，例如 `ci(actions):增加轻量检查`
4. 分支标准：keyword(function)/dec

### 文档日志
1. 当一个功能完成时，补充日志
2. 不要更改日志的历史文件，当需要新增日志的时候，请在日志后增加

## 2. 项目目录

项目结构会持续更新，以下内容仅用于快速定位；最新情况请以仓库实际目录和代码实现为准。

```text
.
├── CausalAgent.py          # Flask 后端入口
├── Run_causal.py           # 桌面端启动入口（pywebview）
├── requirements.txt        # 完整依赖
├── requirements-base.txt   # 基础依赖（docker/生产使用）
├── requirements-test.txt   # Docker 单元测试依赖
├── Dockerfile
├── docker-compose.yml         # MySQL 主从 + PostgreSQL checkpoint 开发拓扑
├── docker-compose.prod.yml
├── docker-compose.staging.yml # 隔离预发：主从 MySQL + PostgreSQL checkpoint + gateway
├── docker-compose.replica.yml # 旧路径兼容副本，不作为默认开发入口
├── docker-compose.test.yml # 按需创建的一次性单元测试环境
├── .github/                 # GitHub Actions 与 Issue 模板
│   ├── workflows/           # GitHub Actions 工作流
│   └── ISSUE_TEMPLATE/      # Issue Form 模板
├── docker-compose.admin-e2e.yml # 3.1/3.2 独立主从验收覆盖
├── README.md               # 项目说明
├── Document/
│   └── admin/              # 管理员 API、开发部署与测试文档
├── admin-frontend/         # Vue 3 + TypeScript 管理员后台
│   ├── src/
│   ├── tests/
│   ├── package.json
│   └── package-lock.json
├── database_init.log       # 数据库初始化日志
├── app/                    # Flask 应用主目录（Blueprint 结构）
│   ├── __init__.py         # 创建 Flask app，注册蓝图
│   ├── db.py               # 数据库会话与连接封装
│   ├── main/               # 通用页面相关路由
│   ├── auth/               # 登录、注册等认证相关路由
│   ├── admin/              # 管理员 API、审计服务与受保护 Vue 入口
│   ├── chat/               # 聊天与会话相关路由和服务
│   ├── files/              # 文件上传与管理相关路由
│   └── static/             # 前端静态资源
│       ├── chat.html       # 主聊天界面
│       ├── css/
│       ├── js/
│       └── generated_graphs/
├── Agent/                  # 因果分析与智能体核心逻辑
│   ├── causal/
│   ├── causal_agent/
│   ├── Processing/
│   ├── Postprocessing/
│   ├── Report/
│   ├── knowledge_base/     # RAG 知识库
│   │   ├── build_knowledge.py # 知识库构建入口，支持 default / medical profile
│   │   ├── query_rag.py       # RAG 查询、检索 trace 与证据生成入口
│   │   ├── db/                # 当前运行时向量知识库存储；医疗库应使用 PubMedQA active corpus 重建
│   │   ├── models/            # 本地嵌入模型，default profile 使用 bge-small-zh-v1.5
│   │   └── rag/               # RAG 测评框架、数据集操作、报告和外部医疗数据
│   │       ├── rag_config.py
│   │       ├── RAG测评框架开发.md
│   │       ├── data/
│   │       │   └── external/pubmedqa/
│   │       ├── operation_datasets/
│   │       ├── rag_eval/
│   │       ├── tools/
│   │       └── output/
│   └── tool_node/
├── Database/               # 数据库初始化与迁移逻辑
│   ├── database_init.py
│   ├── bootstrap.py        # MySQL/Alembic/PostgreSQL 统一初始化入口
│   ├── audit_before_db_upgrade.py
│   ├── inspection.py       # 数据库看板统一只读检查服务
│   ├── deep_audit.py       # 手动 deep 数据库事实审计
│   ├── monitoring.py       # 共享快照存取、调度与兼容接口
│   ├── monitor_worker.py   # 数据库看板分层采集进程
│   ├── monitor_settings.py # 在线配置解析、缓存、校验与事务写入
│   ├── lifecycle_repair.py # 3.2 孤立关系有限 dry-run/人工确认修复 CLI
│   ├── mysql/              # MySQL 主从配置与初始化脚本
│   ├── agent_connect.py
│   └── migrations/
├── config/
│   └── settings.py
├── tests/                  # 后端测试：先按层级、再按业务分类
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   ├── run_admin_31_e2e.ps1
│   └── run_admin_32_e2e.ps1
└── setting/
    ├── manual.md
    └── Userprivacy.md
```

## 3. 开发环境与项目事实

- GitHub Actions 轻量 CI 位于 `.github/workflows/lightweight-ci.yml`，对 `main`、`develop` 的 push 和 Pull Request 生效；它只执行 Python 语法编译、无外部服务依赖的轻量测试以及 Pull Request 策略检查。
- GitHub Issue 使用 `.github/ISSUE_TEMPLATE/issue.yml` 统一填写背景、问题描述、预期结果、复现步骤、验收标准和环境信息；除附件外的字段启用原生必填校验，但不限制填写内容。普通贡献者不能选择空白 Issue。
- 功能分支应向 `develop` 发起 Pull Request，只有 `develop` 可以向 `main` 发起 Pull Request；分支保护需要在 GitHub Rulesets 中启用，并把 `Python syntax`、`Light tests`、`Pull request policy` 设置为必需检查。
- 桌面端入口是 `Run_causal.py`，它固定加载 `http://127.0.0.1:5001`；桌面模式本质上仍依赖先启动后端。
- Web 后端入口是 `CausalAgent.py`，它导入 `app/__init__.py` 中的 `create_app()` 生成 Flask app；本地直接运行时使用 `app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)`，Docker 镜像默认通过 `gunicorn ... CausalAgent:app` 启动。
- `create_app()` 会先执行 `app/db.py` 中的 `check_database_readiness()`，确认数据库和关键表已就绪，然后再注册蓝图。
- 当前实际注册的蓝图有 7 个：`auth`、`chat`、`files`、`agent`、`main`、`admin`、`admin_page`。
- Web 进程只负责登录态校验、短请求、analysis job 入队和 SSE 推送；Agent/RAG/MCP 长任务不在 Web 进程内执行，而是由独立 worker 进程处理。
- 后台 worker 入口是 `python -m app.agent.worker`；启动流程为数据库与 PostgreSQL checkpoint 就绪检查、创建主 LLM、检查知识库目录，再按 `JOB_WORKERS` 启动多个 slot。
- 每个 worker slot 会独占一组 MCP server process、一个通过 `MultiServerMCPClient.session("causal")` 打开的持久 `ClientSession`、一组由 `load_mcp_tools(session)` 生成的 LangChain tools，以及一张独立 Agent graph。真实执行单元是 slot，不是 Flask 请求线程。
- 父图保留 `mcp`、`rag` 两个业务阶段：两者均为子图。`mcp` 为 `mcp_planner -> mcp_tool_node -> mcp_result_parser`；`rag` 为 `rag_question_planner -> rag_tool_node -> rag_result_parser -> rag_finalize`，通过适配节点只将最终 `knowledge_base_result` 投影回父图。
- Pydantic 结构化输出统一通过 `Agent/llm_structured_output.py` 的同步/异步入口执行，固定使用普通 `function_calling`；调用器仅对结构化请求发送 `thinking.type=disabled`，避免 DeepSeek Thinking 与固定 `tool_choice` 冲突。MCP 继续使用原生 Tool Calls；只有 MCP planner 使用关闭 Thinking 的 LLM 副本和 `tool_choice="required"`，确保模型必须自行选择一个已加载工具。
- `agent` 与 `fold` 的条件路由只读取 `route_decision`、`fold_decision` 显式 State 字段；展示消息仅用于用户可见内容和审计，不参与控制流。
- 配置统一由 `config/settings.py` 从系统环境变量读取；若项目根目录存在 `.env`，会先通过 `python-dotenv` 加载到环境变量。
- 聊天页面仍是 Flask 静态资源方案，关键文件是 `app/static/chat.html`、`app/static/css/style.css` 和 `app/static/js/script.js`；`/rag_eval` 使用 `app/rag_eval/frontend/` 下的 Vue 3 + Vite + TypeScript 工程，生产构建输出到 `app/static/rag_eval_app/`，由 `app/main/routes.py` 提供。
- 旧版 `app/static/rag_eval.html`、`app/static/css/rag_eval.css`、`app/static/js/rag_eval.js` 及其 `/run`、`/runs/*` 兼容接口已移除；RAG 运行台页面可通过 `/rag_eval` 或 `/rag-eval` 访问。
- 管理员前端独立位于 `admin-frontend/`，使用 Vue 3、严格 TypeScript、Vue Router、Element Plus、Vite、Vitest 和 Playwright；路由为 `/admin/database` 与 `/admin/database/settings`，Vite base 固定为 `/admin/`。
- 管理员 Vue 生产构建默认从 `admin-frontend/dist` 读取；Docker 镜像使用 Node 24 构建阶段，并把产物复制到 `/opt/causalagent-admin`。最终 Python 运行镜像不包含 Node、不启动 Vite、不开放 Node 端口。开发期只有显式设置 `ADMIN_VITE_DEV_SERVER_URL` 时，Flask 在完成页面鉴权后才跳转到 Vite。
- `admin-frontend/dist/` 是需要随管理员 Vue 源码同步更新并提交的发布产物；根 `.gitignore` 只忽略仓库根目录 `/dist/`。`.dockerignore` 继续排除本地前端产物，因为 Dockerfile 会在 Node 构建阶段从当前源码重新构建并复制到 `/opt/causalagent-admin`。
- 旧管理员 `db_admin.html`、`db_admin.css`、`db_admin.js` 已在等价测试、真实快照和整版回滚演练通过后移除；管理员页面只使用 Vue 生产构建或显式启用的 Vite 开发服务器，普通用户静态前端不受影响。
- `Database/database_init.py` 只负责加载环境变量、确保 MySQL 数据库存在并检查连接；`Database/bootstrap.py` 负责按顺序编排 MySQL 建库、Alembic migration 和 LangGraph PostgreSQL checkpoint setup；业务表结构维护入口仍是 Alembic，而不是 `database_init.py`。
- Alembic 迁移目录由 `alembic.ini` 指向 `Database/migrations`；业务 schema 变更应以迁移脚本为准。
- LangGraph checkpoint 的运行时真相在 PostgreSQL；`Database/checkpoint_setup.py` 使用官方 `AsyncPostgresSaver.setup()` 创建 schema，`Database/checkpoint_cleanup_worker.py` 消费 MySQL `checkpoint_cleanup_outbox` 并调用 `adelete_thread()`。MySQL 只保存 outbox，不再保存 checkpoint 数据。
- `Database/audit_before_db_upgrade.py` 是旧库添加外键前的 schema-aware preflight，不是新库初始化步骤：仅当相关表已存在、目标外键尚未建立且待执行迁移需要该约束时才做孤立数据扫描；全新空库直接执行 Alembic。
- `app/db.py` 提供写库连接、业务读连接、复制状态观测连接、慢查询计时、从库延迟回退和不暴露真实主机名的逻辑来源标记；`get_db_connection()` 仅作为兼容旧代码的主库写入口。
- `get_read_connection(consistency='strong')` 固定读主库；`consistency='eventual'` 只会在从库复制状态正常且延迟不超过阈值时使用副本，否则安全回退主库。
- 用户角色采用 `users.role` 的最小两级模型，只允许 `user` / `admin`；登录、会话恢复和管理员授权每次都通过主库强一致读确认 `role` 与 `is_active`，不把 session 中的角色值作为后端授权依据。
- `/api/admin/*` 由统一管理员装饰器保护：无有效会话返回 `401`，普通登录用户返回 `403`；管理员页面未登录时回到统一登录入口并只保留白名单管理页面的安全回跳，普通用户直访页面先返回真实 `403` 拒绝页，再回普通首页提示“无管理员权限”。初始管理员只通过 `python -m app.auth.admin_cli promote <username>` 提升现有启用用户，不提供公开管理员注册接口。
- `POST /api/login` 可接收可选的内部 `next`，只在服务端白名单校验后返回 `redirect_to`；没有安全回跳时管理员默认进入 `/admin/database`。登录成功和有效 `check_auth` 会返回 Session 绑定的 CSRF token；管理员刷新、完整性审计、配置保存/重置和全部 3.2 受控写入必须提供匹配的 `X-CSRF-Token`。所有响应都有 `X-Request-ID`，格式合法的上游 request ID 会被沿用。
- 管理员普通登录后仍以 `/admin/database` 为默认落点，但可通过后台“进入聊天”使用普通用户界面；聊天接口继续只按当前管理员自身的 `user_id` 访问会话、文件和任务，聊天页向管理员提供返回后台入口。管理员主动进入 `/` 时不会被强制送回后台，重新进入任一管理页面时仍由服务端实时复核角色和启用状态。普通用户继续进入聊天页。后台为白色简约 Vue 页面，现开放业务概览、用户、会话、任务、文件、数据库看板、采集配置和 Schema/deep 审计；3.2 只增加受控用户启停/角色/改密以及用户/文件物理删除，不提供聊天、任意 SQL、修复、迁移、账号授权、复制控制或任务控制。桌面左侧导航可在 248px/约 76px 间收缩并持久化，移动端为可关闭抽屉，Logo 通过受保护接口复用 `README/CausalAgent.png`。
- 3.1 管理列表默认 20、最多 50 条并使用不透明游标；消息/附件正文和任务输入/结果/错误只允许管理员明确点击后按最多 64 KiB 源字节分块读取。成功敏感访问要求审计可写；审计只保存管理员、动作、目标、结果、错误码和 request ID，不保存正文。
- 3.2 用户/文件写接口固定在 `/api/admin/business/*`：执行前必须主库预览、CSRF、当前管理员密码重新认证、明确确认和 `Idempotency-Key`；批量默认 20、硬上限 50，成功变更与 `admin_operations`、`admin_operation_items` 和逐目标 `admin_audit_events` 同事务提交。操作者不能禁用、降级或删除自己，事务锁保护最后一个启用管理员；角色、状态和密码实际变化通过 `users.auth_version` 使旧 Session 失效。用户删除的 MySQL 业务数据先提交，PostgreSQL checkpoint cleanup 通过 `/api/admin/operations/<operation_id>` 查询并聚合为 `running/succeeded/failed`。
- 3.2 文件物理删除同时删除 `uploaded_files` 行与 BLOB，不提供回收站；因文件与 job 没有稳定直接关系，归属用户存在 queued/running job 时保守阻断。用户物理删除显式处理 archived session，并为每个会话写入 checkpoint cleanup outbox，其余依赖现有外键级联，并受同步关联行阈值保护。
- CSV 预览最多读取 256 KiB、100 行、50 列、单元格 1000 字符且只按文本渲染；管理员预览/下载以及 Agent 真正读取文件内容会在同一主库事务原子更新 `last_accessed_at`、`access_count`，重复上传命中已有文件不计为访问。
- 管理看板新增聚合读取接口 `GET /api/admin/db/dashboard`，以及只登记共享刷新请求的 `POST /api/admin/db/refresh` 和 `POST /api/admin/db/integrity/run`；`/db/health`、`/db/overview`、`/db/integrity`、`/db/slow-queries`、`/jobs/workers` 继续兼容，但所有 GET 都只读取最近快照，不现场执行完整数据库采集。
- 在线配置接口为 `GET/PUT /api/admin/db/settings`、`POST /api/admin/db/settings/reset` 和 `GET /api/admin/db/settings/history`。七项有效值固定按“数据库覆盖 > 环境变量 > 代码默认值”解析，`NULL` 表示继承；每个进程最多缓存 5 秒，读取失败时先使用最后有效值、再回退环境/默认值并标记降级。保存使用乐观版本锁，成功、拒绝和失败结果写入 `admin_audit_events`。
- 独立 monitor 入口是 `python -m Database.monitor_worker`；它按 `realtime`、`sql_performance`、`capacity`、`integrity` 四类周期生成 MySQL 共享快照，并通过命名锁避免多个 monitor 或并发手动请求重复采集。默认周期分别为 `10s`、`60s`、`900s`，完整性定时审计默认关闭，启用后默认 `86400s`。
- monitor 还接受仅手动请求的 `deep_audit` 快照：它永不定时调度，覆盖 revision、关键 schema、字符集/UTC/隔离级别、账号职责结论、Job/Event、checkpoint cleanup outbox、归档关系、`active_session_key` 和逐从库状态；每项有查询超时和异常样本上限，不自动修复，也不返回账号、host 或 grants。
- 看板连接使用率 warning/error 默认阈值为 `70%`/`85%`，由 `DB_DASHBOARD_CONNECTION_WARNING_PERCENT` 和 `DB_DASHBOARD_CONNECTION_CRITICAL_PERCENT` 配置；快速 SELECT 超时由 `DB_INSPECTION_QUERY_TIMEOUT_MS` 配置，默认 `3000ms`。刷新和采集配置统一由 `DB_MONITOR_AUTO_REFRESH_ENABLED`、`DB_MONITOR_REALTIME_INTERVAL_SECONDS`、`DB_MONITOR_SQL_INTERVAL_SECONDS`、`DB_MONITOR_TABLE_CAPACITY_INTERVAL_SECONDS`、`DB_MONITOR_SLOW_QUERY_WARNING_DELTA`、`DB_MONITOR_INTEGRITY_ENABLED`、`DB_MONITOR_INTEGRITY_INTERVAL_SECONDS` 控制，不得在路由、SQL 或前端硬编码。
- SQL digest 区块语义是“SQL 性能摘要/高负载 SQL”，按单次平均 `AVG_TIMER_WAIT` 降序选取和展示，平均耗时相同时按累计 `SUM_TIMER_WAIT` 降序次排序；它不等价于超过 `long_query_time` 的单次慢查询，慢查询告警优先使用采集窗口内 `Slow_queries` 增量，累计值仅作兼容和辅助展示。
- 运行期完整性审计不再对已有外键保证的 message、attachment、job、event 和 checkpoint write 关系执行 `COUNT(*) + LEFT JOIN` 全表扫描，而是轻量确认关键约束存在；仍保留当前没有外键保证的 `checkpoints.thread_id → sessions.id` 检查，也不再要求 `chat_messages` 必须存在分区。
- `check_database_readiness()` 当前会检查 `users`、`sessions`、`chat_messages`、`chat_attachments`、`uploaded_files`、`archived_sessions`、`checkpoints`、`checkpoint_writes`、`analysis_jobs`、`analysis_job_events`、`database_monitor_snapshots`、`database_monitor_settings`、`admin_audit_events`、`admin_operations`、`admin_operation_items` 这些关键表，以及 `users.role`、`users.auth_version`、`users.password_changed_at`、`checkpoint_writes.write_identity_hash` 和 3.2 三个关键索引是否已存在。
- 当前 LangGraph MySQL checkpointer 使用 `session_id` 作为 `thread_id`；删除已创建会话时必须在同一事务内先删除对应 `checkpoints`，并依赖 `checkpoint_writes → checkpoints` 的级联外键清理 writes，不能调用会自行开事务的 `MySQLSaver.delete_thread()`。
- `checkpoint_writes` 的幂等业务键是 `(thread_id, checkpoint_ns, checkpoint_id, task_id, idx)`；由于完整 utf8mb4 联合索引超长，应用写入并由 3.2 migration 回填长度前缀编码的 SHA-256 `BINARY(32)` 摘要，再建立唯一索引，不截断 LangGraph 标识。该列不能使用 generated column，因为其基列属于带 `ON DELETE CASCADE` 的复合外键。特殊 writes 走 upsert，普通 writes 忽略重复；最新 checkpoint 按 `created_at DESC, checkpoint_id DESC` 稳定排序。
- `Database/lifecycle_repair.py` 默认只列出有限孤立 archived session/checkpoint/pending writes 主键；只有 `--apply --confirm-database <精确库名>` 才执行，migration 不得调用它或静默删除历史数据。
- 运行期完整性审计不再查询已经迁移走的 MySQL checkpoint 表，而是轻量确认 cleanup outbox 外键/领取索引，并报告失败清理任务；也不再要求 `chat_messages` 必须存在分区。
- `check_database_readiness()` 当前会检查 `users`、`sessions`、`chat_messages`、`chat_attachments`、`uploaded_files`、`archived_sessions`、`checkpoint_cleanup_outbox`、`analysis_jobs`、`analysis_job_events`、`database_monitor_snapshots`、`database_monitor_settings`、`admin_audit_events`、`admin_operations`、`admin_operation_items` 这些关键表，以及 `users.role`、`users.auth_version`、`users.password_changed_at`、cleanup outbox 领取索引和管理员幂等索引是否已存在。
- 当前 LangGraph PostgreSQL checkpointer 使用 `session_id` 作为 `thread_id`；会话或用户删除只能在 MySQL 事务内先写 `checkpoint_cleanup_outbox`，不能把 PostgreSQL `adelete_thread()` 假装纳入 MySQL 事务。
- `checkpoint_cleanup_outbox` 使用 `(thread_id)` 唯一键幂等，cleanup worker 用 `FOR UPDATE SKIP LOCKED` 领取任务，租约过期可恢复，最多执行三次，失败后按 10 秒、30 秒退避；管理员用户删除的操作状态由 outbox 聚合推进。
- `Database/lifecycle_repair.py` 默认只列出有限孤立 archived session 和失败/过期 cleanup outbox 主键；只有 `--apply --confirm-database <精确库名>` 才执行，migration 不得调用它或静默删除历史数据。
- `analysis_jobs` 和 `analysis_job_events` 是当前长任务系统的真实持久化基础：前者是任务队列，后者是事件日志；job 创建、领取、状态更新、事件写入和 SSE 读取都必须走主库或强一致读。
- 同一 `user_id + session_id` 同时只允许一个 `queued/running` job；当前实现不是 generated column，而是把 `active_session_key` 作为可空普通列，并通过唯一键 `uq_analysis_jobs_active_session` 兜底并发竞态。
- 旧 `/api/send_stream` 只保留为迁移提示接口，返回 `410`；前端真实路径应使用 `POST /api/agent/jobs` 创建任务，再用 `GET /api/agent/jobs/<job_id>/events` 订阅 SSE，断线续传依赖 `Last-Event-ID`。
- 数据库账号按职责拆分：
  - `MYSQL_WRITE_USER` / `MYSQL_WRITE_PASSWORD`：应用写主库、迁移、启动检查用。
  - `MYSQL_READ_USER` / `MYSQL_READ_PASSWORD`：业务读主库/从库数据用；除业务库 `SELECT` 外，只额外读取 `performance_schema.events_statements_summary_by_digest`，不得扩大为全局 `SELECT`。
  - `MYSQL_REPLICA_STATUS_USER` / `MYSQL_REPLICA_STATUS_PASSWORD`：只用于执行 `SHOW REPLICA STATUS`。
  - `MYSQL_REPLICATION_USER` / `MYSQL_REPLICATION_PASSWORD`：只给 MySQL 从库复制通道拉 binlog 用。
  - `MYSQL_USER` / `MYSQL_PASSWORD`：仅作为写/读账号兼容兜底，不承担复制状态检查职责。
- `docker-compose.yml` 是本地主从加 PostgreSQL checkpoint 开发拓扑，当前包含 `mysql-primary`、`mysql-replica`、`postgres-checkpoint`、`db-bootstrap`、`app`、`worker`、`monitor`、`checkpoint-cleanup` 八个服务；`db-bootstrap` 是一次性初始化服务，运行成功后其他运行服务才启动，本轮仍不提供自动故障切换。`docker-compose.replica.yml` 仅保留为旧路径兼容副本。
- 连接池按 OS 进程计算：`write_pool + read_pool * (1 + replica_count)`，worker slot 共享所在进程的池。默认建连/获取池/管理员锁等待/从库状态缓存分别为 5s/3s/5s/2s；复制状态失效或异常只回退主库，不自动切主。真实容量依据和读写矩阵记录在 `setting/database_governance.md`。
- Docker 是当前首选开发方式；`docker-compose.yml` 中 `app` 和 `worker` 都会挂载以下知识库目录：
  - `Agent/knowledge_base/models`
  - `Agent/knowledge_base/db`
- 后端单元测试使用独立 `docker-compose.test.yml`：`unit-test` 服务基于 Dockerfile 的 `test` 目标预装 `requirements-test.txt`，不依赖数据库，以 `tests/unit-test.env` 屏蔽项目 `.env` 并关闭 LangSmith 追踪，禁用网络，只读挂载当前仓库；通过 `docker compose ... run --rm` 按需创建和删除测试容器，测试镜像继续复用。
- `docker-compose.replica.yml` 是本地主从开发拓扑，当前包含 `mysql-primary`、`mysql-replica`、`app`、`worker` 和 `rag-eval-worker` 五个服务；本轮仍不提供自动故障切换。`rag-eval-worker` 专门领取隔离评测任务。
- `docker-compose.staging.yml` 是预发 V1 专用隔离拓扑，包含 MySQL primary/replica、PostgreSQL checkpoint、bootstrap、app、worker、monitor、checkpoint cleanup、隔离评测 worker 和 Nginx gateway；所有 Python 服务先运行 `scripts/staging_environment_guard.py`，拒绝 project/DSN/数据库/卷名中的 production/prod 标识，且 `db-bootstrap` 失败时禁止其它应用服务启动。gateway 弃用 JSONL 在“上游返回 Deprecation 头或命中五个观察候选路由”时写入，六个 run 兼容端点族按家族标签掩蔽 run_id；nginx:alpine 无 logrotate/cron，轮转由容器内 `deploy/staging/rotate_gateway_logs.sh` 按 `deploy/staging/logrotate.conf` 策略执行（24h/20MiB 触发，保留 45 份压缩）。当前内测设置 `VISION_ALLOW_REMOTE_DATA=true`，显式选中的冻结或用户上传来源均可外发并生成 outbound manifest；正式环境上线前必须恢复来源授权门禁。
- Docker 是当前首选开发方式；`docker-compose.replica.yml` 中 `app`、`worker` 和 `rag-eval-worker` 都会挂载以下知识库目录：
  - `Agent/knowledge_base/models`
  - `Agent/knowledge_base/db`
- `docker-compose.replica.yml` 中 `app`、`worker` 和 `rag-eval-worker` 的 `MULTIMODAL_DOCLING_ARTIFACTS_DIR` 指向 `/app/Agent/knowledge_base/models/docling`；Docling 模型必须放在工作区该子目录，宿主机原始缓存可保留作为回滚副本。
- 默认 RAG 通过 `rag_enrichment_search` 工具进入 RAG 子图；工具调用 `query_rag.py` 的 dense、BM25s、rerank 与回答链路。知识库目录不可用或工具未注册时，Planner 会以稳定降级结果跳过 ToolNode 并回到父图。
- `query_rag.py` 的 dense + BM25s + rerank + answer 流程继续作为默认检索实现，并已兼容 `document_id`、`page_number`、`asset_uri`、`modality` 和 `content_kind` 等多模态 metadata。PubMedQA 构建与专用评测入口暂作为医疗兼容代码保留，后续分阶段清理。
- 多模态公共知识库维护模块位于 `Agent/knowledge_base/multimodal/`，其 assets、暂存索引和 active pointer 使用独立目录，严禁写入或清理 `Agent/knowledge_base/db/` 与 PubMedQA collection。PDF 当前默认 Docling；manifest 必须保存 source、parser 原始产物、标准化单元与资源的 URI/内容哈希关联，发布门禁必须回读校验。WCode 模型固定 `qwen/qwen3-vl-8b-instruct`、域名必须为 `wcode.net`，默认预算不超过 100 且 smoke 应显式限制；审计日志不得记录图片、提示词、响应正文或密钥。隔离运行默认开启远程 VLM，并为本次显式选中的冻结来源和用户上传来源生成隔离 outbound manifest；设置 `VISION_ALLOW_REMOTE_DATA=false` 可关闭，用户上传来源的默认远程行为仅适用于内测，正式环境仍需独立授权策略。
- 隔离评测 `/rag_eval` 的知识源上传接口为 `POST /api/rag_eval/isolated/sources`，支持 `.pdf`、`.txt`、`.md`、`.markdown`、`.csv`、`.xlsx`、`.png`、`.jpg`、`.jpeg`、`.webp`、`.tif`、`.tiff`，默认保存到 `tmp/rag_eval_sources/`，可通过 `RAG_EVAL_SOURCE_ROOT` 覆盖；上传只登记来源并刷新目录，不自动摄取。用户可通过 `PATCH /api/rag_eval/isolated/sources/<source_id>` 设置显示名，元数据保存在来源目录的 `source_metadata.json`，不改变 source_id、内容 hash 或历史运行。用户上传来源可通过 `DELETE /api/rag_eval/isolated/sources/<source_id>` 删除，但固定来源、运行中的摄取和已生成的 staged index/评测产物不会被删除。用户手动启动摄取后，上传来源可在内测远程开关开启时走自动 outbound manifest 和远程 VLM。
- 新的正式 PDF 摄取按物理页运行关闭 OCR 的 Docling，并保存页级 checkpoint；当前默认使用 `spawn_per_batch`、批量大小 8、关闭 Docling 图像/表格生成、布局/表格/OCR batch size 为 1，以控制内存峰值。图片必须先通过 outbound manifest、解码/RGB 归一化和像素/字节上限，再由 provider adapter 返回远程 OCR 与视觉语义；`PictureItem` 和页级图片资产由 PDF bbox 渲染器生成，不把图片识别改回本地 OCR。Docling 空 `TableItem` 会按 bbox 裁剪为 `table_recovery` 资产，由可替换的 `TableRecoveryProvider` 生成 `table_markdown`；当前远程实现只是一个 WCode adapter，未来可替换为本地 VLM。远程失败不得回退 RapidOCR 或生成伪完成图片单元。当前 active 仍是迁移前本地 OCR 回滚基线。Chroma 必须分批写入独立 attempt 目录，成功后才能提交为版本的 `chroma/`。生产评测命中必须同时匹配文档、页码和 `expected_modality`；`run` 默认停在可发布 staged 状态，只有显式通过发布门禁并调用 publish 才切换 active pointer。
- `Agent/knowledge_base/build_knowledge.py` 当前支持 `--profile default` 和 `--profile medical`：
  - `default` 从 `Agent/knowledge_base/source/` 读取 Pearl/因果资料，并使用本地 `bge-small-zh-v1.5`。
  - `medical` 从 `rag_config.py` 的 `MEDICAL_KNOWLEDGE_BUILD_CONFIG["corpus_path"]` 读取当前 active 医疗语料；当前指向 PubMedQA processed corpus，embedding provider 由 `RAG_EMBEDDING_PROVIDER` 控制：`auto` 保持旧兼容行为（存在 `MEDICAL_EMBEDDING_API_KEY` 或 `KNOWLEDGE_BUILD_PROFILE=medical` 时使用 OpenAI-compatible API，否则使用本地模型），`openai_compatible` 强制使用 `MEDICAL_EMBEDDING_API_KEY`、`MEDICAL_EMBEDDING_BASE_URL`、`MEDICAL_EMBEDDING_MODEL`，`local` 强制使用 `RAG_LOCAL_EMBEDDING_MODEL_PATH` 或默认 `Agent/knowledge_base/models/bge-small-zh-v1.5`。
  - 两个 profile 都写入原 `Agent/knowledge_base/db` 持久化目录；切换 profile 前如果要清空旧索引，必须先获得用户明确确认。
- 旧医疗兼容 benchmark 是 PubMedQA labeled；其 processed corpus/eval 均为 1000 条，不再属于默认 RAG 测试链路。
- 当前本地 `Agent/knowledge_base/db` 已替换为 PubMedQA 医疗知识库，医疗查询与 medical 构建默认 collection 为 `pubmedqa_clean`；`causal_agent_default` 也指向 PubMedQA 但存在重复 chunk，旧 RAGCare 向量库已备份到 `tmp/RAGCare`。
- PubMedQA 构建与专用评测入口仍是显式 medical 工具；隔离评测 `/rag_eval` 不读取其 corpus，也不使用 source-specific mismatch 防护。
- `build_knowledge.py` 的旧构建入口仍支持 `RAG_VECTOR_DB_DIR`、`RAG_COLLECTION_NAME` 等显式覆盖；默认查询 Runtime 不再读取这两个旧医疗路径变量，而是通过 `MULTIMODAL_INDEX_ROOT` 与 `MULTIMODAL_ACTIVE_INDEX_CONFIG` 定位已发布多模态索引。embedding provider 仍由 `RAG_EMBEDDING_PROVIDER` 与 `RAG_LOCAL_EMBEDDING_MODEL_PATH` 等现有配置控制。
- 默认多模态 RAG 查询继续读取 `Agent/knowledge_base/rag/runtime/production_rag_config.json` 中的 dense、BM25s、rerank 和证据长度参数。
- `build_knowledge.py` 默认拒绝向非空 Chroma collection 追加写入，并记录到 `Agent/knowledge_base/build_knowledge.log`；只有明确传 `--allow-append` 才允许追加，避免重复 chunk 污染默认库。
- 隔离评测 `/rag_eval` 使用 `rag_eval_v1` 通用题集契约；题集必须通过 `RAG_EVAL_DATASET_PATH` 显式提供，未配置时校验失败，不读取当前知识库路径。
- `run_rag_eval.py` 默认步骤是 `validate_datasets -> retrieval_eval -> ragas_eval -> trace_export -> summary`；`claim_eval` 已从默认链路和前端工作台调参入口屏蔽，坏例链路只统计 retrieval/Ragas 相关问题。
- RAG 评测已移除 CLI 调参备份层；前端不再展示 CLI 等价字段，后端不再提供 `GET /api/rag_eval/cli-params`，也不再接受 `cli_overrides`。
- 当前隔离评测使用 `generic_pipeline`：Ragas generation 默认使用通用回答 prompt；题集可包含 `reference_answer`、`expected_claims` 和可选 `gold_evidence`，没有 gold 时检索指标为 `unscored`，不会伪造为 0。Ragas 运行会记录题集 identity 和 Runtime 提供的向量库 identity；评测层不读取多模态 active pointer，也不绑定 Pearl、PubMedQA 或具体文件格式。
- 完整 Ragas 评测必须失败关闭：回答生成出现 API/结构化输出失败时立即停止准备阶段，不调用 judge，并把 run、SQL job、summary 和事件统一收敛为 `failed/answer_generation_failed`；judge 返回全 NaN 或没有任何有效数值分数时收敛为 `failed/ragas_judge_no_valid_scores`。失败 run 仍保留 `result.json` 和 Ragas 报告供前端读取，禁止用 `needs_review` 或“步骤完成”掩盖外部模型故障。
- `rag_eval_v1` 题集按 `dataset_kind` 区分 `gold_regression`、`generated_candidate` 和 `reference_free`；Pearl 与 PubMedQA 的正式转换产物位于 `Agent/knowledge_base/rag/data/eval/`，生成入口为 `python -m Agent.knowledge_base.rag.operation_datasets.build_eval_datasets`。不同题集 kind/id 不得合并写入同一文件。
- 隔离评测入口为 `POST /api/rag_eval/isolated/evaluation-runs`；它必须绑定 `ingestion_run_id + index_version`，按本次评测目录生成 retrieval、Ragas、trace 和 summary 产物。`POST /api/rag_eval/isolated/evaluation-batches` 可一次创建 2–4 个不同策略 profile 的独立 evaluation run；`rag-eval-worker` 默认启动 5 个 slot，并允许通过 `RAG_EVAL_EVALUATION_WORKERS` 在 1–16 范围覆盖，各 run 的题集、配置、状态和报告仍隔离保存。评测创建后先写入 `rag_eval_jobs` SQL 队列并返回 `queued`，由 `python -m app.rag_eval.worker`（Docker 服务 `rag-eval-worker`）领取执行；worker 以 SQL heartbeat 租约和独立 `worker_heartbeat.json` 保活，进程异常退出后由下一次 worker 启动将超时 `running` 任务标记为 `failed`，不自动重跑 Ragas。跨进程 SSE 从 `run.json` 轮询事件。`retrieval` 支持显式 profile/overrides 及 sweep，`ragas` 支持显式 profile、prepare-only 或 judge 运行；评测接口不得读取旧 latest 输出、默认知识库路径或 active pointer。`generated_candidate` 在入队前必须通过所选 staged index 的 source snapshot 与 locator 绑定校验；所有题集在入队前执行 `dataset_kind` 语义校验。`DELETE /api/rag_eval/isolated/evaluation-runs/<run_id>` 默认只允许删除已结束的 evaluation run；若运行中任务超过无事件活动窗口（默认 1800 秒，支持 `RAG_EVAL_EVALUATION_STALE_AFTER_SECONDS` 覆盖），history 会自动收敛为失败，前端确认后用 `{"force":true}` 清理其 `tmp/rag_eval_isolated_runs/<run_id>/` 目录。不删除关联 ingestion run、staged index 或共享知识库。对比接口同时按 `run_manifest.json` 的路径返回两次 run 的配置差异。隔离摄取接口支持可选 `page_ranges`，按每个选中来源校验并执行 1-based、首尾包含的物理页范围；旧 `max_pages` 仍表示按来源顺序累计的总上限，两者不能同时提交。
- 正式 RAG P0–P2 约束记录在 `Document/rag_formal_p0_p2.md`：正式 retrieval 基线来自 `production_rag_config.json`；`answer_max_contexts` 和 `answer_context_compression` 才是正式回答上下文控制，Ragas `max_contexts` 不能替代它们。正式回答和隔离 Ragas judge 必须复用同一份压缩后 evidence。
- 多个隔离评测 slot 在同一进程首次构造本地 HuggingFace embedding 时必须经过 `Agent/knowledge_base/rag_runtime.py` 的进程内初始化锁；该锁只串行化模型构造，Runtime 创建完成后的检索、回答和 Ragas 执行仍可并行，避免 Transformers/PyTorch `meta tensor` 初始化竞态。
- `ragas_eval.py` 和 `claim_eval.py` 会在导入 LangChain/Ragas 前用 `os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")` 做 Windows OpenMP 进程级兜底；不要写入 `.env`，命令行显式设置仅用于覆盖默认值。
- 隔离评测题集使用通用 `rag_eval_v1` schema；`gold_regression` 必须同时提供 `reference_answer`、`expected_claims` 和 `gold_evidence`，后者是由 Runtime metadata 严格匹配的 locator 列表。`generated_candidate` 可由 Ragas 生成并在唯一映射后获得 gold，`reference_free` 只用于未评分观测；旧 source-specific 字段不属于 `/rag_eval` 契约。
- 当前 LLM 若不支持 `response_format` 结构化输出，`query_rag.py` 会退回普通 JSON answer 生成路径。


- 隔离评测摄取状态持久化在 tmp/rag_eval_isolated_runs/<ingestion_run_id>/run.json，页级 checkpoint 持久化在每个 staged index 的 checkpoints.sqlite3，GET /api/rag_eval/isolated/ingestion-runs 可枚举并恢复最近状态；前端首次恢复失败后，顶部刷新会再次读取历史并恢复 staged index。隔离评测长任务状态同样写入 run.json，执行队列位于 `rag_eval_jobs` 表，摄取、候选生成、staged index RAG 试跑、完整评测和两类题集治理都不在 Web 进程线程执行。tmp/rag_eval_isolated_runs 和 tmp/rag_eval_sources 属于本地运行产物，已加入 Git 忽略。worker 重启后继续领取 queued 任务；失联的 running 任务在 heartbeat 超时后标记失败。
- 隔离评测的 canonical run lifecycle 固定为 `GET /api/rag_eval/isolated/runs/<run_id>`、`/result`、`/artifacts/<artifact_name>`、`/stream` 和 `POST /cancel`。各具体 run 类型的状态、结果、产物、SSE、取消接口仍注册为兼容路径并返回 `Deprecation: true` 与 successor `Link`；本轮只在 `Document/rag_eval_api_inventory.md` 列出待用户审核移除项，未删除接口。静态扫描不能证明没有外部消费者，移除前须结合访问日志、公告和弃用窗口；鉴权不在本轮范围。
- `rag_eval_datasets` 是共享 `RAG_EVAL_DATASET_ROOT` 下的不可变注册表，隔离任务以 `dataset_ref` 解析版本；入队必须通过 staged index 完整身份门禁（ingestion run、index version、manifest/source snapshot、dataset/locator identity）。`GET /api/rag_eval/isolated/capacity` 只读返回队列容量快照，不做 reconcile。`RAG_EVAL_EVALUATION_WORKERS` 默认 5；六类服务端并发上限的实际键依次为 `RAG_EVAL_INGESTION_CONCURRENCY_LIMIT`、`RAG_EVAL_CANDIDATE_GENERATION_CONCURRENCY_LIMIT`、`RAG_EVAL_TUNING_DATASET_GOVERNANCE_CONCURRENCY_LIMIT`、`RAG_EVAL_DATASET_GOVERNANCE_CONCURRENCY_LIMIT`、`RAG_EVAL_EVALUATION_CONCURRENCY_LIMIT`、`RAG_EVAL_RAG_QUERY_CONCURRENCY_LIMIT`，默认 `1/1/1/1/3/2`。worker 用 MySQL 命名锁串行 claim，并按服务端固定优先级选择可运行任务。
- `Document/rag_eval_production_acceptance_matrix.json` 和 `scripts/run_rag_eval_production_acceptance.py` 将验收分为 contract、integration、production：contract 仅非变更白名单检查，integration 使用临时 fixture，production 仅在显式确认后运行只读 readiness；不得把该分层或 contract 结果表述为真实生产摄取、评测、冻结、发布或 active pointer 切换已经执行。

### 3.2 常用命令

激活本地 conda 环境（仅在不用 Docker 时）：

```bash
conda activate causalagent
```

本地启动后端：

```bash
python CausalAgent.py
```

本地启动后台 worker：

```bash
python -m app.agent.worker
```

本地启动数据库监控采集器：

```bash
python -m Database.monitor_worker
```

管理员 Vue 本地验证：

```bash
cd admin-frontend
npm ci
npm run typecheck
npm run test:unit
npm run test:e2e:mock
npm run build
```

后端单元测试默认使用按需 Docker 环境：

```bash
docker compose -f docker-compose.test.yml build unit-test
docker compose -f docker-compose.test.yml run --rm unit-test
```

指定测试可以在服务名后覆盖默认命令；只有依赖变化时才需要重新构建测试镜像。集成测试、本地 Python 回退和完整分类见 `tests/README.md`。

真实隔离环境 E2E 还需提供 `PLAYWRIGHT_BASE_URL`、管理员/普通用户测试凭据后运行
`npm run test:e2e`；本机仅有 Edge 时可显式设置 `PLAYWRIGHT_CHANNEL=msedge`，
未设置时仍使用 Playwright 标准 Chromium。

3.2 完整隔离主从验收在管理员生产构建完成后运行：

```powershell
powershell -ExecutionPolicy Bypass -File tests/run_admin_32_e2e.ps1
```

该脚本不会触碰当前开发库，覆盖空库升级、3.2 migration 往返、受控写入/删除、主从追平和普通用户回归；不会自动删除隔离容器和卷，清理仍需单独明确确认。物理删除种子不能通过 `KeepSeededData` 重放。

本地启动隔离评测 worker：

```bash
python -m app.rag_eval.worker
```
本地启动桌面端：

```bash
python Run_causal.py
```


Docker 主从开发启动（推荐）：

```bash
docker compose -f docker-compose.yml up -d
```

首次启动、空卷重建或数据库环境重建后，推荐按下面顺序执行：

```bash
docker compose -f docker-compose.yml up -d
```

`.env` 必须提供非空 `CHECKPOINT_POSTGRES_PASSWORD`；Compose 会自动运行
`db-bootstrap` 和 `checkpoint-cleanup`。本地等价命令为：

```bash
python -m Database.bootstrap
python -m Database.checkpoint_cleanup_worker
```

如果你当前不是在 Docker 里开发，再使用本地等价命令：

```bash
python -m Database.bootstrap
```

如需在不重启运行服务的情况下手动重跑一次性初始化入口，可执行：

```bash
docker compose -f docker-compose.yml run --rm db-bootstrap
```

只有旧库尚未建立目标外键、且即将执行添加这些外键的迁移时，才在 `alembic upgrade head` 前运行 `Database/audit_before_db_upgrade.py`。

### 3.2 数据库相关特别要求

数据库结构变更不能只改一处；至少同时检查以下位置：
注意数据库采用主从开发

```text
Database/database_init.py
Database/bootstrap.py
Database/migrations/versions/*
app/db.py
相关 SQL 读写代码
```
不要把“读写分离”简化成“所有 SELECT 都去副本”；先按一致性要求区分 strong read、eventual read 和必须写主库的实时路径。

MYSQL_WRITE_USER：应用写主库、迁移、启动检查用。
MYSQL_READ_USER：应用读主库/从库业务数据用。
MYSQL_REPLICA_STATUS_USER：只给应用执行 SHOW REPLICA STATUS 用。
MYSQL_REPLICATION_USER：只给 MySQL 从库拉主库 binlog 用。
MYSQL_USER/MYSQL_PASSWORD：现在主要是兼容兜底，主从开发里不依赖它。

### 3.3 环境问题
1. 如果在本地无法找到包，如langgrph，尝试访问conda环境

## 4. 工具与 skills 使用原则

1. 如果某个 skill 不可用，必须回退到通用工具链继续完成任务，不能因为缺少该 skill 就中止工作。
2. 对外部资料查询类任务，优先返回真实来源链接，而不是只给二手总结。

## 5. 工作方式

### 5.1 先读后写

修改前至少先检查与当前任务相关的这些内容：

- 调用入口
- 路由
- service 或核心业务函数
- 数据库表结构或迁移
- 前端调用点
- README 或用户文档中是否已有说明

优先使用 `rg` 搜索已有实现，避免重复造轮子。

### 5.2 基于事实，不靠猜

- 不要假设某个接口、文件、表、字段一定存在。
- 不要因为 README 写了某句话，就忽略代码中的真实行为。
- 如果 README、注释、实现不一致，以当前实现为准，并在最终答复中指出差异。

### 5.3 精确改动

- 不做与当前任务无关的全局重命名、风格统一或大重构。
- 不为“未来可能用到”预埋复杂抽象。
- 优先修根因，不打表面补丁。
- 每个函数需要补充函数层描述

### 5.4 举一反三

如果一个 bug 由模式性问题引起，要顺手检查同类位置是否也存在相同风险，例如：

- 新增数据库表但忘了更新 `check_database_readiness`
- 修改接口返回结构但没有检查前端 `script.js`
- 改了上传或聊天附件结构却没同步恢复逻辑
- 修改 MCP 或 RAG 初始化路径但没检查 `CausalAgent.py` 和 `app/agent/core.py`

## 6. 修改后的验证要求

### 6.1 Python / 后端改动

至少做以下一项或多项验证：

```bash
python -m py_compile <变更的Python文件>
```

如果改动涉及导入链、启动链、配置链，优先再做一次后端启动级验证：

```bash
python CausalAgent.py
```

如果因为缺少 `.env`、数据库或模型目录而无法启动，要明确说明。

### 6.2 数据库相关改动

必须检查：

- `Database/database_init.py` 和 `Database/bootstrap.py` 是否同步
- 对应 Alembic migration 是否存在且升级/回滚逻辑自洽
- `app/db.py` 的就绪检查是否需要更新
- 相关 SQL 是否仍兼容旧数据和空数据场景

未经用户明确确认，不要执行高风险数据库操作。

### 6.3 前端改动

普通用户前端仍为 Flask 静态资源；管理员前端有独立 Node 构建流程。改动后至少要：

- 检查 `chat.html`、`style.css`、`script.js` 的引用关系
- 检查接口路径是否仍与后端一致
- 检查加载态、空态、失败态是否受影响
- 在 `admin-frontend/` 执行 `npm ci`、`npm run typecheck`、`npm run test:unit` 和 `npm run build`
- 管理员看板变更必须通过等价矩阵测试；真实数据库写流程只允许在隔离环境提供 Playwright 凭据后执行
- 如条件允许，启动后端并在浏览器中做一次最小交互验证

### 6.4 RAG / MCP / Agent 图改动

至少核对：

- `app/agent/core.py`
- `Agent/causal_agent/`
- `Agent/tool_node/`
- `Agent/knowledge_base/`

## 7. 敏感文件与高风险区域

以下内容默认视为敏感或高风险，不能随意改动、清空或覆盖：

- `.env`
- `secrets.json`
- `database_init.log`
- `Agent/knowledge_base/db/`
- `Agent/knowledge_base/models/`
- 用户上传和历史数据对应的数据库表
- `Database/migrations/versions/` 中已存在的迁移脚本
- 任何可能包含用户数据、密钥、知识库索引或生成产物的目录

补充要求：

- 不要输出密钥、口令、数据库连接信息。
- 不要擅自清理知识库目录、数据库目录或日志目录。
- 不要仅因为本地运行失败就删除迁移脚本、数据库表、缓存目录或静态资源目录。

## 8. 危险操作确认机制

以下操作属于高风险操作，执行前必须得到用户明确确认：

- 删除文件或目录
- 批量修改大量文件
- 移动系统关键文件
- `git commit` / `git push` / `git reset --hard` / 强制覆盖
- 修改环境变量、系统配置、权限
- 数据库删除、结构变更、批量更新
- 调用生产环境 API
- 全局安装 / 卸载依赖，升级核心依赖
- 任何可能造成数据丢失、环境破坏、不可逆副作用的操作

确认时必须使用这个格式：

```text
检测到危险操作！
操作类型：[具体操作]
影响范围：[详细说明]
风险评估：[潜在后果]
```

## 9. 决策型问题的回答方式

当用户提出的是“需要做选择”的问题，而不是“让我直接实现”的问题时，先不要直接给结论，先做四件事：

1. 指出问题里的隐含假设。
2. 说明哪些关键信息缺失会显著改变结论。
3. 指出这类问题最常见的一个错误。
4. 向用户提出一个能显著提升最终建议质量的关键问题。

只有在这些前置信息澄清后，再给最终建议。

适用场景包括但不限于：

- 技术选型
- 架构调整
- 数据库结构变更
- 依赖升级
- 成本、复杂度、风险差异明显的方案比较

## 10. 文档与代码冲突时的优先级

优先级从高到低如下：

1. 用户当前明确指令
2. 更近目录下的 `AGENTS.md`
3. 根目录 `AGENTS.md`
4. 当前代码实现
5. `README` / 注释 / 历史文档

如果发现文档与实现不一致：

- 不要盲目按旧文档修改代码
- 先说明差异
- 以当前可运行实现为准提出建议

## RAG 测试集自动扩充与并行调优

- 隔离评测的隔离摄取、候选题生成、staged index RAG 试跑、完整评测、调参集治理和 Gold 题目健康治理统一写入 MySQL `rag_eval_jobs` 持久队列，由 `python -m app.rag_eval.worker`（Docker 服务 `rag-eval-worker`）按 `job_kind` 分发执行；Web 进程只负责创建、读取和取消这些长任务。所有任务均使用 SQL heartbeat、`worker_heartbeat.json` 和 fail-closed 超时收敛，不自动重跑。
- staged RAG 题集可用 `python -m Agent.knowledge_base.rag.operation_datasets.candidate_generation --index-dir <staged-index> --output <candidate.json>` 生成；该命令只读校验 `manifest.json`、`units.jsonl`、`issues.jsonl`、`build_state.json`、当前 embedding 指纹和 Chroma 计数，仅接受完整 staged 版本。输出按模态轮询选择输入，并由 Ragas 0.4.3 `generate_with_chunks()` 生成 `generated_candidate`，保留 manifest/units/build-state hash 和 locator；每个 revision 同时写入 `candidate.json.audit.json`，保存生成错误、重复/拒绝样本、计数摘要和 `rag_candidate_coverage_v1` 覆盖报告；没有候选通过筛选时拒绝落盘，默认 revision 使用微秒时间与随机后缀避免碰撞，不自动升级为 gold。
- `retrieval.sweep_max_workers` 只允许有界并行 sweep（最多 8）；结果最多推荐 2 组供人工确认，不自动执行 Ragas 或发布 profile。
- `/rag_eval` 的候选题审核页面通过隔离 `candidate_generation` run 调用 Ragas 0.4.3 `generate_with_chunks()`；候选生成支持 SSE 进度和取消，逐题编辑/审核写入新的 reviewed candidate revision，原始候选文件不得覆盖。页面显示 ingestion 快照中的知识源显示名并使用短索引别名；审核员姓名仍只写入本地候选 revision/review manifest，不绑定 MySQL 用户。`POST /api/rag_eval/gold-v2/freeze` 只有在 Pearl 24 题、候选 48 题、完整 approved 清单和 `gold_evidence` 齐备时才允许冻结。
- `POST /api/rag_eval/baseline-v2/bind` 只读绑定已冻结 Gold v2、active pointer/index manifest 与 `active_current` retrieval；它不修改 active pointer 或 profile。候选生成失败、审核不完整、active manifest 缺失时均保持失败关闭。
- Gold v2 健康治理通过 `POST /api/rag_eval/gold-v2/governance` 接收已完成的 evaluation run，并由 `dataset_governance` worker 创建独立新 revision。`source.origin=human_reviewed`、无 `source.generator` 或其他非生成来源的题目永久保留；单次低 Ragas 分只进入诊断。生成题只有 intrinsic 风险且独立结构化 reviewer 返回 `replace` 且 confidence >= 0.8 才能退休；reviewer 异常、超时或解析失败保留原题。候选复用现有 hard screen 并需 `accept`/confidence >= 0.8；题数、Gold schema、index identity、locator 不一致或候选不足时治理失败且旧 Gold 不变。有实际替换时必须在 Gold 跨进程锁内重新核对源 evaluation 的 dataset SHA，拒绝 stale run 覆盖较新 revision，再归档旧 Gold 并原子写入；零替换任务只返回 `no_change`，不得改写 Gold 文件或 revision。流程不切 production active index/profile，治理 run 的状态、阶段、计数、逐题原因和恢复信息通过 `/api/rag_eval/gold-v2/governance-runs/*` 提供。
- 索引绑定调参集治理（`tuning_dataset_governance`）使用逐题证据账本与宽松复用语义：启动时扫描同 `ingestion_run_id + index_version` 的已完成正式评测和 tuning 轮次 machine 产物，按 sample_id + 题面哈希建立逐题账本；四项原始分齐全且不低于当前门槛的题直接保留（门槛读取时套用），数值低于门槛的缓存失败题直接淘汰等待替补，记录缺失或哈希不匹配的题现场评测。历史失败运行中已实测达标的替补题会从轮次快照按同样门槛救援回基线（题面哈希与 Gold 自动题重复的跳过），使跨运行净进展可累积。宽松语义不比较检索/judge 配置，但每条沿用证据保留来源 run、轮次、原始分、检索 config 摘要和 ragas profile/版本；混合配置在结果中以 `reused_across_configs` 显式标记。基线优先链式取 `tmp/rag_eval_tuning_datasets/<index_version>/` 最近可解析登记文件（损坏文件跳过并记事件），人工保护题始终来自当前 Gold。generate/review/evaluate 三个适配器统一使用 1-based 循环轮次编号，产物共享同一 `round_NNN` 命名空间；运行内已评测题不再跨轮重测，集合级 Recall@K/MRR 由合并逐题值重算。替补生成排除现有题目覆盖的证据单元并优先薄弱单元定位键。审核后新增一轮证据锚定改写：needs_revision 候选经 `rewrite_rejected_candidates` 从全部 gold_evidence 锚点提取逐字答案句（过滤扉页元数据/LaTeX 碎片/低字母密度句）生成单事实问题并用同一校准审核器复审，改写或复审失败只降级为沿用首轮结论，不改 fail-closed 标准。全集通过但集合级门禁不过立即以 `retrieval_gate_failed` 失败，替补零采纳立即以 `replacement_generation_exhausted` 失败，均不空转至 max_rounds。替补生成的可重试连接类失败按 15s/60s 批内退避重试；凑不齐缺口时不再整体失败，而是把缺口写入 aggregate 审计后返回已收集候选交由审核改写管线处理。
