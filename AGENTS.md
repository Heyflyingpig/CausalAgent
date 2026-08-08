# CausalAgent AGENTS.md

本文件适用于仓库根目录及其所有子目录；如果更深层目录存在新的 `AGENTS.md`，以更近的文件为准。

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
├── docker-compose.replica.yml # 旧路径兼容副本，不作为默认开发入口
├── docker-compose.test.yml # 按需创建的一次性单元测试环境
├── .github/                 # GitHub Actions 与 Issue 模板
│   ├── workflows/           # GitHub Actions 工作流
│   └── ISSUE_TEMPLATE/      # Issue Form 模板
├── docker-compose.admin-e2e.yml # 3.1/3.2 独立主从 + PostgreSQL 验收覆盖
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
│   ├── agent/              # 分析任务 API、共享队列服务与独立 worker
│   │   ├── routes.py       # Web 任务创建与 SSE 订阅
│   │   ├── job_service.py  # Web、monitor、worker 共享持久化服务
│   │   ├── core.py         # 无运行时状态的兼容导入门面
│   │   └── worker/         # worker package 与 python -m 入口
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
│   │   ├── build_knowledge.py
│   │   ├── db/
│   │   └── models/
│   └── tool_node/
├── Database/               # 数据库初始化与迁移逻辑
│   ├── database_init.py
│   ├── bootstrap.py        # MySQL/Alembic/PostgreSQL 统一初始化入口
│   ├── audit_before_db_upgrade.py
│   ├── inspection.py       # 数据库看板统一只读检查服务
│   ├── deep_audit.py       # 手动 deep 数据库事实审计
│   ├── checkpoint_inspection.py # PostgreSQL checkpoint 管理员只读与审计
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
- 后台 worker 入口仍是 `python -m app.agent.worker`，实际由 `app/agent/worker/__main__.py` 调用 `bootstrap.main()`；启动流程是：数据库就绪检查 -> PostgreSQL checkpoint 检查 -> 创建显式进程 runtime（LLM、RAG 可用性）-> 按 `JOB_WORKERS` 启动多个 slot。
- 每个 worker slot 会独占一组 MCP server process、一个通过 `MultiServerMCPClient.session("causal")` 打开的持久 `ClientSession`、一组由 `load_mcp_tools(session)` 生成的 LangChain tools，以及一个编译好的 Agent graph；`runtime.py` 通过 `ProcessRuntime` 和 `SlotRuntime` 显式返回这些依赖，执行函数不读取 `app.agent.core` 的全局 LLM 或 graph。真实执行单元是 slot，不是 Flask 请求线程。
- 父图当前只暴露 `mcp`、`rag` 两个工具阶段节点：`mcp` 子图正常路径执行 `mcp_planner -> mcp_tool_node -> mcp_result_parser`，planner、ToolNode 和 parser 的失败路径会在子图内生成标准 `success=False` 结果并结束子图；`rag` 子图内部执行 `rag_question_planner -> rag_tool_node -> rag_result_parser`。worker 使用 LangGraph v2 `updates/messages/custom/tasks` 多流：根图 `tasks` 形成用户时间线，子图工具事件折叠到 `mcp`/`rag` 阶段，只有 `normal_chat` 和 `inquiry_answer` 的文字进入 `text_delta`，原始 Prompt、ToolMessage、完整工具结果和内部 attempt 不进入普通用户 SSE 协议。
- Pydantic 结构化输出统一通过 `Agent/llm_structured_output.py` 的同步/异步入口执行，固定使用普通 `function_calling`；调用器仅对结构化请求发送 `thinking.type=disabled`，避免 DeepSeek Thinking 与固定 `tool_choice` 冲突。MCP 继续使用原生 Tool Calls；只有 MCP planner 使用关闭 Thinking 的 LLM 副本和 `tool_choice="required"`，确保模型必须自行选择一个已加载工具。
- `agent` 与 `fold` 的条件路由只读取 `route_decision`、`fold_decision` 显式 State 字段；展示消息仅用于用户可见内容和审计，不参与控制流。
- 配置统一由 `config/settings.py` 从系统环境变量读取；若项目根目录存在 `.env`，会先通过 `python-dotenv` 加载到环境变量。
- 普通用户前端仍是 Flask 静态资源方案，聊天 API/SSE 契约不变；关键文件是：
  - `app/static/chat.html`
  - `app/static/css/style.css`
  - `app/static/js/script.js`
- 管理员前端独立位于 `admin-frontend/`，使用 Vue 3、严格 TypeScript、Vue Router、Element Plus、Vite、Vitest 和 Playwright；路由为 `/admin/database` 与 `/admin/database/settings`，Vite base 固定为 `/admin/`。
- 管理员 Vue 生产构建默认从 `admin-frontend/dist` 读取；Docker 镜像使用 Node 24 构建阶段，并把产物复制到 `/opt/causalagent-admin`。最终 Python 运行镜像不包含 Node、不启动 Vite、不开放 Node 端口。开发期只有显式设置 `ADMIN_VITE_DEV_SERVER_URL` 时，Flask 在完成页面鉴权后才跳转到 Vite。
- `admin-frontend/dist/` 中只提交入口文件 `index.html`，`dist/assets/` 的哈希构建产物由 `.gitignore` 排除并在 Dockerfile 的 Node 构建阶段重新生成；`.dockerignore` 继续排除本地前端产物，镜像会从当前源码构建并复制到 `/opt/causalagent-admin`。
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
- 文件库由 `file_objects` 不可变 BLOB 和 `user_files` 逻辑记录组成；同一用户相同 hash 复用对象，不同文件名保留不同逻辑文件。管理员和 Agent 只能按 `user_file_id` 访问，文件预览、下载和 Agent 真实读取在同一主库事务内更新访问时间与次数。
- 3.2 文件物理删除同时删除 `user_files` 行，并仅在没有其他逻辑引用且没有 queued/running/waiting_input Job 使用时删除 BLOB，不提供回收站；用户物理删除显式处理 archived session，并为每个会话写入 checkpoint cleanup outbox，其余依赖现有外键级联，并受同步关联行阈值保护。
- `a1b2c3d4e5f6_add_file_library_and_job_recovery.py` 是面向开发/测试库的破坏性替换 migration：直接删除旧 `uploaded_files` 表，不回填旧数据，不提供旧数据 fallback，也不增加旧数据拒绝迁移逻辑；downgrade 只恢复空的旧表结构。
- CSV 预览最多读取 256 KiB、100 行、50 列、单元格 1000 字符且只按文本渲染；管理员预览/下载以及 Agent 真正读取文件内容会在同一主库事务原子更新 `last_accessed_at`、`access_count`，重复上传命中已有文件不计为访问。
- 管理看板新增聚合读取接口 `GET /api/admin/db/dashboard`，以及只登记共享刷新请求的 `POST /api/admin/db/refresh` 和 `POST /api/admin/db/integrity/run`；`/db/health`、`/db/overview`、`/db/integrity`、`/db/slow-queries`、`/jobs/workers` 继续兼容，分析任务页复用 `/jobs/workers` 的汇总和明细。数据库看板按 URL query 的 database、cleanup-worker、outbox 三段视图展示，cleanup worker 约每 10 秒写入 `checkpoint_cleanup_runtime` 心跳，monitor 采集脱敏 `checkpoint_cleanup_outbox` 摘要；所有 GET 都只读取最近快照，不现场执行完整数据库采集。
- 在线配置接口为 `GET/PUT /api/admin/db/settings`、`POST /api/admin/db/settings/reset` 和 `GET /api/admin/db/settings/history`。七项有效值固定按“数据库覆盖 > 环境变量 > 代码默认值”解析，`NULL` 表示继承；每个进程最多缓存 5 秒，读取失败时先使用最后有效值、再回退环境/默认值并标记降级。保存使用乐观版本锁，成功、拒绝和失败结果写入 `admin_audit_events`。
- 独立 monitor 入口是 `python -m Database.monitor_worker`；它按 `realtime`、`sql_performance`、`capacity`、`integrity` 四类核心周期生成 MySQL 共享快照，并额外按实时周期采集 `checkpoint_cleanup_outbox` 队列摘要，通过命名锁避免多个 monitor 或并发手动请求重复采集。默认周期分别为 `10s`、`60s`、`900s`，完整性定时审计默认关闭，启用后默认 `86400s`。
- monitor 还接受仅手动请求的 `deep_audit` 快照：它永不定时调度，覆盖 revision、关键 schema、字符集/UTC/隔离级别、账号职责结论、Job/Event、checkpoint cleanup outbox、归档关系、`active_session_key` 和逐从库状态；每项有查询超时和异常样本上限，不自动修复，也不返回账号、host 或 grants。
- 看板连接使用率 warning/error 默认阈值为 `70%`/`85%`，由 `DB_DASHBOARD_CONNECTION_WARNING_PERCENT` 和 `DB_DASHBOARD_CONNECTION_CRITICAL_PERCENT` 配置；快速 SELECT 超时由 `DB_INSPECTION_QUERY_TIMEOUT_MS` 配置，默认 `3000ms`。刷新和采集配置统一由 `DB_MONITOR_AUTO_REFRESH_ENABLED`、`DB_MONITOR_REALTIME_INTERVAL_SECONDS`、`DB_MONITOR_SQL_INTERVAL_SECONDS`、`DB_MONITOR_TABLE_CAPACITY_INTERVAL_SECONDS`、`DB_MONITOR_SLOW_QUERY_WARNING_DELTA`、`DB_MONITOR_INTEGRITY_ENABLED`、`DB_MONITOR_INTEGRITY_INTERVAL_SECONDS` 控制，不得在路由、SQL 或前端硬编码。
- SQL digest 区块语义是“SQL 性能摘要/高负载 SQL”，按单次平均 `AVG_TIMER_WAIT` 降序选取和展示，平均耗时相同时按累计 `SUM_TIMER_WAIT` 降序次排序；它不等价于超过 `long_query_time` 的单次慢查询，慢查询告警优先使用采集窗口内 `Slow_queries` 增量，累计值仅作兼容和辅助展示。
- 运行期完整性审计不再查询已经迁移走的 MySQL checkpoint 表，而是轻量确认 cleanup outbox 外键/领取索引，并报告失败清理任务；也不再要求 `chat_messages` 必须存在分区。
- `check_database_readiness()` 当前会检查 `users`、`sessions`、`chat_messages`、`chat_attachments`、`file_objects`、`user_files`、`archived_sessions`、`checkpoint_cleanup_outbox`、`analysis_jobs`、`analysis_job_events`、`analysis_job_inputs`、`database_monitor_snapshots`、`database_monitor_settings`、`admin_audit_events`、`admin_operations`、`admin_operation_items` 这些关键表，以及 Job 恢复、冻结文件、`users.role`、`users.auth_version`、`users.password_changed_at`、cleanup outbox 领取索引和幂等索引是否已存在。
- 当前 LangGraph PostgreSQL checkpointer 使用 `analysis_jobs.job_id` 作为 `thread_id`，根 `checkpoint_ns` 为空；业务 `session_id` 仍指向 `sessions.id`，新 Job 从 MySQL 聊天历史加载有界初始窗口，同一 Job 的 resume/stale recovery 才继续原 State。旧的 session-thread checkpoint 不迁移、不读取、不清理。
- quick integrity 通过独立 PostgreSQL 只读连接检查 checkpoint 连通性、官方四表集合和 setup migration 版本；deep audit 额外检查官方字段/主键、三张数据表的估算统计，并抽取最多 20 个 `thread_id → analysis_jobs.job_id` 跨库关系样本，同时允许 cleanup outbox 过渡中的 Job 暂不报孤儿。所有结果只返回逻辑别名，不返回 PostgreSQL host、账号或连接串。
- `checkpoint_cleanup_outbox` 使用 `(thread_id)` 唯一键幂等，cleanup worker 用 `FOR UPDATE SKIP LOCKED` 领取任务，租约过期可恢复，最多执行三次，失败后按 10 秒、30 秒退避；管理员用户删除的操作状态由 outbox 聚合推进。
- cleanup worker 心跳周期由 `CHECKPOINT_CLEANUP_HEARTBEAT_INTERVAL_SECONDS` 控制，默认 `10s`；运行快照只写入逻辑别名、计数、时间和安全错误结论，不写入主机、账号或 `last_error` 原文。
- `Database/lifecycle_repair.py` 默认只列出有限孤立 archived session 和失败/过期 cleanup outbox 主键；只有 `--apply --confirm-database <精确库名>` 才执行，migration 不得调用它或静默删除历史数据。
- `analysis_jobs` 和 `analysis_job_events` 是当前长任务系统的真实持久化基础：前者是任务队列，后者是事件日志；job 创建、领取、状态更新、事件写入和 SSE 读取都必须走主库或强一致读。
- 管理员任务详情通过单视图选择器展示 MySQL `analysis_job_events` 的节点/任务事件或 PostgreSQL checkpoint 安全摘要，默认进入节点/任务事件；新 checkpoint 通过 `metadata.job_id` 与任务精确关联，旧记录缺少该字段时不得按时间猜测归属。管理员接口不得读取或返回 checkpoint 状态正文、blob 或 pending writes。
- 同一 `user_id + session_id` 同时只允许一个 `queued/running/waiting_input` job；当前实现不是 generated column，而是把 `active_session_key` 作为可空普通列，并通过唯一键 `uq_analysis_jobs_active_session` 兜底并发竞态。Job 创建时冻结文件对象和文件名/hash，`waiting_input` 时保留活动锁但释放 worker lease，恢复输入写入 `analysis_job_inputs` 后重新排队；取消只能作用于等待输入的 Job，并写入稳定生命周期事件。

`/api/new_chat` 生成 ID 后会立即在 MySQL 主库创建会话记录；创建 job、保存聊天、修改标题和上传文件都要求该会话已经存在且属于当前用户，不会根据未知 ID 自动重建。LangGraph 使用 `analysis_jobs.job_id` 作为 `thread_id`，业务 `session_id` 仍然是会话外键，根 `checkpoint_ns` 为空；新 Job 从同一会话的 MySQL 聊天历史加载有界初始消息窗口，同一 Job 的 resume/stale recovery 才继续原 checkpoint。删除已经创建的会话时，主库事务会删除会话、聊天消息和附件，并按该会话全部 Job ID 写入 `checkpoint_cleanup_outbox`；独立 cleanup worker 随后调用 PostgreSQL `adelete_thread(job_id)`。两个数据库之间不伪造分布式事务，用户接口会明确返回后台清理状态。旧的 session-thread checkpoint 不迁移、不读取、不清理。

文件库使用 `file_objects` 保存不可变 BLOB，使用 `user_files` 保存用户可见的逻辑文件记录；同一用户的相同 SHA-256 对象会复用 BLOB，不同文件名仍保留独立逻辑记录。上传只进入文件库，不创建 session 关联或 Job。创建分析 Job 时才锁定并保存 `input_user_file_id`、对象 ID、hash 和文件名快照，后续替换或清除浏览器草稿不会改变已创建 Job。Job 支持 `waiting_input`、同 Job `resume` 和 `canceled`，用户输入统一写入 `analysis_job_inputs`。
- 旧 `/api/send_stream` 只保留为迁移提示接口，返回 `410`；前端真实路径应使用 `POST /api/agent/jobs` 创建任务，再用 `GET /api/agent/jobs/<job_id>/events` 订阅 SSE，断线续传依赖 `Last-Event-ID`。创建任务必须提供客户端 `Idempotency-Key`；相同用户、相同幂等键和相同请求参数返回原 job，不同参数返回 `409`。
- 数据库账号按职责拆分：
  - `MYSQL_WRITE_USER` / `MYSQL_WRITE_PASSWORD`：应用写主库、迁移、启动检查用。
  - `MYSQL_READ_USER` / `MYSQL_READ_PASSWORD`：业务读主库/从库数据用；除业务库 `SELECT` 外，只额外读取 `performance_schema.events_statements_summary_by_digest`，不得扩大为全局 `SELECT`。
  - `MYSQL_REPLICA_STATUS_USER` / `MYSQL_REPLICA_STATUS_PASSWORD`：只用于执行 `SHOW REPLICA STATUS`。
  - `MYSQL_REPLICATION_USER` / `MYSQL_REPLICATION_PASSWORD`：只给 MySQL 从库复制通道拉 binlog 用。
  - `MYSQL_USER` / `MYSQL_PASSWORD`：仅作为写/读账号兼容兜底，不承担复制状态检查职责。
- `docker-compose.yml` 是本地主从加 PostgreSQL checkpoint 开发拓扑，当前包含 `mysql-primary`、`mysql-replica`、`postgres-checkpoint`、`db-bootstrap`、`app`、`worker`、`monitor`、`checkpoint-cleanup` 八个服务；`db-bootstrap` 是一次性初始化服务，运行成功后其他运行服务才启动，本轮仍不提供自动故障切换。`docker-compose.replica.yml` 仅保留为旧路径兼容副本。
- `docker-compose.prod.yml` 同样包含 PostgreSQL checkpoint、统一 bootstrap、Agent worker、monitor 和 checkpoint cleanup；`app` 与 `monitor` 需要 PostgreSQL 配置以支持管理员 checkpoint 摘要和 quick/deep 审计。
- 连接池按 OS 进程计算：`write_pool + read_pool * (1 + replica_count)`，worker slot 共享所在进程的池。默认建连/获取池/管理员锁等待/从库状态缓存分别为 5s/3s/5s/2s；复制状态失效或异常只回退主库，不自动切主。真实容量依据和读写矩阵记录在 `setting/database_governance.md`。
- Docker 是当前首选开发方式；`docker-compose.yml` 中 `app` 和 `worker` 都会挂载以下知识库目录：
  - `Agent/knowledge_base/models`
  - `Agent/knowledge_base/db`
- 后端单元测试使用独立 `docker-compose.test.yml`：`unit-test` 服务基于 Dockerfile 的 `test` 目标预装 `requirements-test.txt`，不依赖数据库，以 `tests/unit-test.env` 屏蔽项目 `.env` 并关闭 LangSmith 追踪，禁用网络，只读挂载当前仓库；通过 `docker compose ... run --rm` 按需创建和删除测试容器，测试镜像继续复用。
- RAG 启动期只检查知识库目录是否可用，不会在启动时完整加载向量库；若 `Agent/knowledge_base/db` 不存在，worker 会记录 warning，并以“无知识库模式”继续运行。
- DirectLiNGAM 已作为独立 MCP 工具 `causal_direct_lingam` 接入 `Agent/CausalAgentMCP/mcp_server.py`；显式点名 DirectLiNGAM 时 planner 会确定性选择该工具。runner 只接受连续数值 CSV，返回因果顺序、`matrix_convention="target_to_source"` 的系数矩阵和带权有向图；后处理会保留未反转边的 `weight`，报告必须说明线性、非高斯、误差独立、DAG 和无潜在混杂假设。


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

本地启动桌面端：

```bash
python Run_causal.py
```


Docker 主从开发启动（推荐）：

```bash
docker compose -f docker-compose.yml up -d
```

首次启动、空卷重建或数据库环境重建后，推荐按下面顺序执行；全新空库不要先运行 preflight：

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
- 修改 MCP、RAG 或 worker 初始化路径但没检查 `app/agent/worker/runtime.py`、`bootstrap.py` 和 Docker Compose 入口

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

- `app/agent/worker/runtime.py`
- `app/agent/worker/bootstrap.py`
- `app/agent/worker/graph_runner.py`
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
