# CausalChat AGENTS.md

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
4. 分支标准：keyword(function)/dec

### 文档日志
1. 当一个功能完成时，补充日志

## 2. 项目目录

项目结构会持续更新，以下内容仅用于快速定位；最新情况请以仓库实际目录和代码实现为准。

```text
.
├── Causalchat.py           # Flask 后端入口
├── Run_causal.py           # 桌面端启动入口（pywebview）
├── requirements.txt        # 完整依赖
├── requirements-base.txt   # 基础依赖（docker/生产使用）
├── Dockerfile
├── docker-compose.yml
├── docker-compose.prod.yml
├── docker-compose.replica.yml # MySQL 主从开发拓扑
├── README.md               # 项目说明
├── database_init.log       # 数据库初始化日志
├── app/                    # Flask 应用主目录（Blueprint 结构）
│   ├── __init__.py         # 创建 Flask app，注册蓝图
│   ├── db.py               # 数据库会话与连接封装
│   ├── main/               # 通用页面相关路由
│   ├── auth/               # 登录、注册等认证相关路由
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
│   ├── audit_before_db_upgrade.py
│   ├── monitoring.py
│   ├── mysql/              # MySQL 主从配置与初始化脚本
│   ├── agent_connect.py
│   └── migrations/
├── config/
│   └── settings.py
└── setting/
    ├── manual.md
    └── Userprivacy.md
```

## 3. 开发环境与项目事实

- 桌面端入口是 `Run_causal.py`，它固定加载 `http://127.0.0.1:5001`；桌面模式本质上仍依赖先启动后端。
- Web 后端入口是 `Causalchat.py`，它导入 `app/__init__.py` 中的 `create_app()` 生成 Flask app；本地直接运行时使用 `app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)`，Docker 镜像默认通过 `gunicorn ... Causalchat:app` 启动。
- `create_app()` 会先执行 `app/db.py` 中的 `check_database_readiness()`，确认数据库和关键表已就绪，然后再注册蓝图。
- 当前实际注册的蓝图有 6 个：`auth`、`chat`、`files`、`agent`、`main`、`admin`。
- Web 进程只负责登录态校验、短请求、analysis job 入队和 SSE 推送；Agent/RAG/MCP 长任务不在 Web 进程内执行，而是由独立 worker 进程处理。
- 后台 worker 入口是 `python -m app.agent.worker`；worker 启动流程是：数据库就绪检查 -> 初始化 LLM -> 检查 RAG 可用性 -> 按 `JOB_WORKERS` 启动多个 slot。
- 每个 worker slot 会独占一组 MCP server process、一个通过 `MultiServerMCPClient.session("causal")` 打开的持久 `ClientSession`、一组由 `load_mcp_tools(session)` 生成的 LangChain tools，以及一个编译好的 Agent graph；真实执行单元是 slot，不是 Flask 请求线程。旧 `open_mcp_session()` / 手写 `list_tools()` 包装仅保留作历史兼容入口。
- 父图当前只暴露 `mcp`、`rag` 两个工具阶段节点：`mcp` 子图内部执行 `mcp_planner -> mcp_tool_node -> mcp_result_parser`，`rag` 子图内部执行 `rag_question_planner -> rag_tool_node -> rag_result_parser`；worker 事件流仍沿用旧 `astream(stream_mode="updates")` 适配，不要求本轮输出 tool-level SSE 事件。
- 配置统一由 `config/settings.py` 从系统环境变量读取；若项目根目录存在 `.env`，会先通过 `python-dotenv` 加载到环境变量。
- 前端当前仍是 Flask 静态资源方案，不是 Node/Vite/React 工程；关键文件是：
  - `app/static/chat.html`
  - `app/static/css/style.css`
  - `app/static/js/script.js`
- `Database/database_init.py` 只负责加载环境变量、确保数据库存在并检查连接；业务表结构维护入口是 Alembic，而不是这个脚本。
- Alembic 迁移目录由 `alembic.ini` 指向 `Database/migrations`；业务 schema 变更应以迁移脚本为准。
- 数据库生产化升级前应先执行 `Database/audit_before_db_upgrade.py`；它是只读审计，不会修改数据，重点检查孤立消息、孤立附件、非法附件类型和分区状态。
- `app/db.py` 提供写库连接、业务读连接、复制状态观测连接、慢查询计时和从库延迟回退能力；`get_db_connection()` 仅作为兼容旧代码的主库写入口。
- `get_read_connection(consistency='strong')` 固定读主库；`consistency='eventual'` 只会在从库复制状态正常且延迟不超过阈值时使用副本，否则安全回退主库。
- `check_database_readiness()` 当前会检查 `users`、`sessions`、`chat_messages`、`chat_attachments`、`uploaded_files`、`archived_sessions`、`checkpoints`、`checkpoint_writes`、`analysis_jobs`、`analysis_job_events` 这些关键表是否已存在。
- `analysis_jobs` 和 `analysis_job_events` 是当前长任务系统的真实持久化基础：前者是任务队列，后者是事件日志；job 创建、领取、状态更新、事件写入和 SSE 读取都必须走主库或强一致读。
- 同一 `user_id + session_id` 同时只允许一个 `queued/running` job；当前实现不是 generated column，而是把 `active_session_key` 作为可空普通列，并通过唯一键 `uq_analysis_jobs_active_session` 兜底并发竞态。
- 旧 `/api/send_stream` 只保留为迁移提示接口，返回 `410`；前端真实路径应使用 `POST /api/agent/jobs` 创建任务，再用 `GET /api/agent/jobs/<job_id>/events` 订阅 SSE，断线续传依赖 `Last-Event-ID`。
- 数据库账号按职责拆分：
  - `MYSQL_WRITE_USER` / `MYSQL_WRITE_PASSWORD`：应用写主库、迁移、启动检查用。
  - `MYSQL_READ_USER` / `MYSQL_READ_PASSWORD`：业务读主库/从库数据用。
  - `MYSQL_REPLICA_STATUS_USER` / `MYSQL_REPLICA_STATUS_PASSWORD`：只用于执行 `SHOW REPLICA STATUS`。
  - `MYSQL_REPLICATION_USER` / `MYSQL_REPLICATION_PASSWORD`：只给 MySQL 从库复制通道拉 binlog 用。
  - `MYSQL_USER` / `MYSQL_PASSWORD`：仅作为写/读账号兼容兜底，不承担复制状态检查职责。
- `docker-compose.replica.yml` 是本地主从开发拓扑，当前包含 `mysql-primary`、`mysql-replica`、`app`、`worker` 四个服务；本轮仍不提供自动故障切换。
- Docker 是当前首选开发方式；`docker-compose.replica.yml` 中 `app` 和 `worker` 都会挂载以下知识库目录：
  - `Agent/knowledge_base/models`
  - `Agent/knowledge_base/db`
- RAG 启动期只检查知识库目录是否可用，不会在启动时完整加载向量库；若 `Agent/knowledge_base/db` 不存在，worker 会记录 warning，并以“无知识库模式”继续运行。


### 3.1 常用命令

激活本地 conda 环境（仅在不用 Docker 时）：

```bash
conda activate causalchat
```

本地启动后端：

```bash
python Causalchat.py
```

本地启动后台 worker：

```bash
python -m app.agent.worker
```

本地启动桌面端：

```bash
python Run_causal.py
```


Docker 主从开发启动（推荐）：

```bash
docker-compose -f docker-compose.replica.yml up -d
```

首次启动、空卷重建或数据库环境重建后，推荐按下面顺序执行：

```bash
docker-compose -f docker-compose.replica.yml run --rm app python Database/database_init.py
docker-compose -f docker-compose.replica.yml run --rm app python Database/audit_before_db_upgrade.py
docker-compose -f docker-compose.replica.yml run --rm app alembic upgrade head
```

如果你当前不是在 Docker 里开发，再使用本地等价命令：

```bash
python Database/database_init.py
python Database/audit_before_db_upgrade.py
alembic upgrade head
```

### 3.2 数据库相关特别要求

数据库结构变更不能只改一处；至少同时检查以下位置：
注意数据库采用主从开发

```text
Database/database_init.py
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
- 修改 MCP 或 RAG 初始化路径但没检查 `Causalchat.py` 和 `app/agent/core.py`

## 6. 修改后的验证要求

### 6.1 Python / 后端改动

至少做以下一项或多项验证：

```bash
python -m py_compile <变更的Python文件>
```

如果改动涉及导入链、启动链、配置链，优先再做一次后端启动级验证：

```bash
python Causalchat.py
```

如果因为缺少 `.env`、数据库或模型目录而无法启动，要明确说明。

### 6.2 数据库相关改动

必须检查：

- `Database/database_init.py` 是否同步
- 对应 Alembic migration 是否存在且升级/回滚逻辑自洽
- `app/db.py` 的就绪检查是否需要更新
- 相关 SQL 是否仍兼容旧数据和空数据场景

未经用户明确确认，不要执行高风险数据库操作。

### 6.3 前端改动

前端为静态资源方案，没有现成的 Node 构建流程。改动后至少要：

- 检查 `chat.html`、`style.css`、`script.js` 的引用关系
- 检查接口路径是否仍与后端一致
- 检查加载态、空态、失败态是否受影响
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
