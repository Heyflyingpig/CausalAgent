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
- 每个 worker slot 会独占一组 MCP server process、一个 `ClientSession` 和一个编译好的 Agent graph；真实执行单元是 slot，不是 Flask 请求线程。
- 配置统一由 `config/settings.py` 从系统环境变量读取；若项目根目录存在 `.env`，会先通过 `python-dotenv` 加载到环境变量。
- 前端当前仍是 Flask 静态资源方案，不是 Node/Vite/React 工程；关键文件是：
  - `app/static/chat.html`
  - `app/static/css/style.css`
  - `app/static/js/script.js`
  - `app/static/rag_eval.html`
  - `app/static/css/rag_eval.css`
  - `app/static/js/rag_eval.js`
- RAG 评测控制台页面可通过 `/rag_eval` 或 `/rag-eval` 访问；静态文件仍位于 `app/static/rag_eval.html`。
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
- `Agent/knowledge_base/build_knowledge.py` 当前支持 `--profile default` 和 `--profile medical`：
  - `default` 从 `Agent/knowledge_base/source/` 读取 Pearl/因果资料，并使用本地 `bge-small-zh-v1.5`。
  - `medical` 从 `rag_config.py` 的 `MEDICAL_KNOWLEDGE_BUILD_CONFIG["corpus_path"]` 读取当前 active 医疗语料；当前指向 PubMedQA processed corpus，embedding provider 由 `RAG_EMBEDDING_PROVIDER` 控制：`auto` 保持旧兼容行为（存在 `MEDICAL_EMBEDDING_API_KEY` 或 `KNOWLEDGE_BUILD_PROFILE=medical` 时使用 OpenAI-compatible API，否则使用本地模型），`openai_compatible` 强制使用 `MEDICAL_EMBEDDING_API_KEY`、`MEDICAL_EMBEDDING_BASE_URL`、`MEDICAL_EMBEDDING_MODEL`，`local` 强制使用 `RAG_LOCAL_EMBEDDING_MODEL_PATH` 或默认 `Agent/knowledge_base/models/bge-small-zh-v1.5`。
  - 两个 profile 都写入原 `Agent/knowledge_base/db` 持久化目录；切换 profile 前如果要清空旧索引，必须先获得用户明确确认。
- 当前 active benchmark 是 PubMedQA labeled；PubMedQA processed corpus/eval 均为 1000 条，测试集使用通用 `benchmark_v2` schema。
- 当前本地 `Agent/knowledge_base/db` 已替换为 PubMedQA 医疗知识库，医疗查询与 medical 构建默认 collection 为 `pubmedqa_clean`；`causal_agent_default` 也指向 PubMedQA 但存在重复 chunk，旧 RAGCare 向量库已备份到 `tmp/RAGCare`。
- 当前医疗知识库应以 PubMedQA corpus 为准；若本地 `Agent/knowledge_base/db` 与 active benchmark 不一致，retrieval_eval 会通过向量库/benchmark mismatch 防护阻止误跑。
- `query_rag.py` 和 `build_knowledge.py` 支持用 `RAG_VECTOR_DB_DIR` 临时覆盖向量库目录、用 `RAG_COLLECTION_NAME` 临时覆盖 Chroma collection、用 `RAG_EMBEDDING_PROVIDER` 与 `RAG_LOCAL_EMBEDDING_MODEL_PATH` 控制查询/构建侧 embedding provider；这可用于 smoke，不必覆盖 `Agent/knowledge_base/db`。
- 正式 RAG 查询会读取 `Agent/knowledge_base/rag/runtime/production_rag_config.json` 中发布的检索配置；若该文件不存在或无效，则回退到 `query_rag.py` 的代码默认 `RagRetrievalConfig()`。前端 RAG 评测工作台可查看并将当前评测检索配置发布到该文件；这只影响后续正式 RAG 查询，不会改写知识库或数据库。
- `build_knowledge.py` 默认拒绝向非空 Chroma collection 追加写入，并记录到 `Agent/knowledge_base/build_knowledge.log`；只有明确传 `--allow-append` 才允许追加，避免重复 chunk 污染默认库。
- retrieval_eval 已增加向量库/benchmark mismatch 防护：若 active gold doc 前缀与当前向量库 doc 前缀不一致，会在检索前失败。
- `run_rag_eval.py` 默认步骤是 `validate_datasets -> retrieval_eval -> ragas_eval -> trace_export -> summary`；`claim_eval` 已从默认链路和前端工作台调参入口屏蔽，坏例链路只统计 retrieval/Ragas 相关问题。
- RAG 评测已移除 CLI 调参备份层；前端不再展示 CLI 等价字段，后端不再提供 `GET /api/rag_eval/cli-params`，也不再接受 `cli_overrides`。
- 当前 `pubmedqa_pipeline` 默认跑前 30 条，样本数通过前端动态调整；Ragas generation 默认使用 6 个 context、单 context 1600 字符、回答 1100 字符、PubMedQA prompt v6；100 条 `pubmedqa_eval100` profile 默认使用 `ragas_max_workers=4`、`ragas_max_retries=3`、`ragas_max_wait=20` 控制 Ragas judge 并发和限流等待；Ragas 运行会先校验 `rag_eval_result.json` 的样本数、问题顺序、检索配置和向量库摘要，不一致则自动刷新 retrieval latest，避免不同样本规模的 cross-metric 误报；默认 `trace_export` 产物在前端按 Bad Case Traces / 坏例链路展示；前端取消会在 `retrieval_eval` 和 Ragas dataset 构建/refresh 的当前样本结束后停止，并用 `step_progress` 展示样本进度。
- `ragas_eval.py` 和 `claim_eval.py` 会在导入 LangChain/Ragas 前用 `os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")` 做 Windows OpenMP 进程级兜底；不要写入 `.env`，命令行显式设置仅用于覆盖默认值。
- Active benchmark 测试集使用通用 `benchmark_v2` schema，`gold_doc_ids` 是通用 doc-level 检索 gold；旧因果数据集仍可继续使用 `gold_chunk_ids`。
- 当前 LLM 若不支持 `response_format` 结构化输出，`query_rag.py` 会退回普通 JSON answer 生成路径。


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
