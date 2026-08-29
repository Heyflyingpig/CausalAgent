[简体中文](README.md) | [English](README_EN.md)


<p align="center">
<img src="./README/CausalAgent.png" alt="Logo">
</p>

<h1 align="center">
CausalAgent
</h1>

<p align="center">
<em>新一代因果分析智能体</em>
</p>

<p align="center">
    <a href="#">
      <img src="https://img.shields.io/badge/Status-In%20Development-orange?style=flat-square" alt="Status">
    </a>
    <a href="#">
      <img src="https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python&logoColor=white" alt="Python Version">
    </a>
    <a href="#">
      <img src="https://img.shields.io/badge/Focus-Causal%20Inference-green?style=flat-square" alt="Topic">
    </a>
    <a href="#">
      <img src="https://img.shields.io/badge/Powered%20by-Langgraph-8A2BE2?style=flat-square" alt="Powered By">
    </a>
  </p>

  <br>

  <p>

*只需上传你的数据集，Causal-Agent 就能以对话的方式，自动帮你选用因果分析算法，并在生成可交互的对话面板和专业的分析报告。*

> [!IMPORTANT]
> **项目开发中**
> <br>
> 目前 CausalAgent 正在进行核心架构升级,我们正在努力完善功能，**请点击右上角 Star ⭐ 关注后续更新！**

## 目录

- [目录](#目录)
- [WHAT IS CausalAgent](#what-is-causalagent)
- [WHY CausalAgent](#why-causalagent)
- [技术栈](#技术栈)
- [用户功能](#用户功能)
  - [用户端展示](#用户端展示)
  - [核心功能](#核心功能)
  - [Agent 运行流程](#agent-运行流程)
  - [预处理](#预处理)
  - [因果分析（MCP）](#因果分析mcp)
  - [知识库（RAG）](#知识库rag)
  - [联网搜索](#联网搜索)
  - [后处理](#后处理)
  - [报告生成](#报告生成)
- [快速开始 | Quick Start](#快速开始--quick-start)
  - [可访问入口](#可访问入口)
  - [最小配置](#最小配置)
  - [Docker部署](#docker部署)
- [管理员与开发者](#管理员与开发者)
  - [管理员端展示](#管理员端展示)
  - [数据库生产化配置](#数据库生产化配置)
  - [管理员后台](#管理员后台)
  - [日志系统](#日志系统)
    - [开发环境启动](#开发环境启动)
  - [RAG评测工作台](#rag评测工作台)
  - [后端单元测试](#后端单元测试)
  - [windows部署](#windows部署)
- [技术文档](#技术文档)
- [贡献](#贡献)
- [Star History](#star-history)
- [项目结构](#项目结构)





## WHAT IS CausalAgent

**新一代因果分析智能体**: CausalAgent 是一个集成了AGENT的因果分析工具，它能够自动识别因果关系，生成专业的分析报告，并提供可交互的因果图谱。

**缩减因果分析门槛**：什么是因果？为什么需要因果分析？简单来说，[因果分析](https://zh.wikipedia.org/wiki/%E5%9B%A0%E6%9E%9C%E6%8E%A8%E6%96%B7)就是对真实世界数据进行逻辑分析。

## WHY CausalAgent

| 特性 | 说明 |
| :--- | :--- |
| **Agent 驱动** | 基于 LangGraph 父图编排分析节点、工具阶段与子图，自动路由任务。 |
|  **动态图谱** | 摒弃静态图片，生成可交互的 Network 图谱，支持节点拖拽、点击追问。 |
|  **论文实时搜索** | SearXNG 实时搜索，获取最新论文与时事。 |
|  **MCP 架构** | 采用MCP，将核心逻辑与工具解耦，极易扩展新算法。 |
|  **RAG 增强** | 内置因果推断领域的专业知识库，确保生成的分析报告学术性与严谨性并存，提供个性化的rag评测桌面，定制化rag服务 |
## 技术栈

| 类别 | 技术组件 |
| :--- | :--- |
| **Agent 与模型** | LangGraph、LangChain、MCP |
| **RAG 与搜索** | ChromaDB、BM25S、Ragas、SearXNG |
| **后端与数据** | Flask、MySQL、PostgreSQL、Alembic |
| **前端** | HTML5、JavaScript、Vue 3、Vite、WebView2 |
| **可观测性** | Grafana Alloy、Loki、Grafana |
| **运行与发布** | Docker Compose、GitHub Actions |

## 用户功能

### 用户端展示
<p align="center">
  <img src="./README/causalagent展示页.png" alt="主程序" width="850">
</p>
<p align="center">
  <img src="./README/因果图页.png" alt="因果图" width="850">
</p>
<p align="center">
  <img src="./README/image2.png" alt="因果图" width="450">
</p>

### 核心功能

CausalAgent 的整体因果分析流程可以抽象为：**用户上传数据 → 预处理与数据体检 → 因果结构学习 → 后处理与质量提升 → 报告与可视化输出**。下面按模块进行说明。

### Agent 运行流程

系统不是由多个彼此独立的 Agent 拼接而成，而是由一个 LangGraph 父图编排分析节点、MCP、RAG 与 Web Search 子图，并由独立 worker 执行 Job：

```mermaid
graph TD;
    subgraph "用户入口"
        User((用户)) --> UI[Web / Windows 客户端]
    end
    subgraph "任务与运行时"
        UI --> API[Flask API / Analysis Job]
        API --> Worker[Job Worker / Slot]
        Worker --> Graph[LangGraph 父图]
    end
    subgraph "工具阶段与子图"
        Graph --> MCP[MCP: PC / OLC / DirectLiNGAM]
        Graph --> RAG[RAG 知识库]
        Graph --> Search[Web Search / SearXNG]
        Graph --> Report[后处理与报告]
    end
    Worker --> Events[(MySQL Job / SSE 事件)]
    Graph <--> Checkpoint[(PostgreSQL checkpoint)]
    Events --> UI
```


### 预处理
*进行基本的数据建模，对数据进行可视化分析，并为后续因果分析做「体检与筛选」*

- **数据概览**：统计数据集的行数、列数和所有字段名，生成统一的表结构摘要，帮助快速理解数据规模与字段含义。
- **列级体检与类型推断**：逐列分析缺失率、唯一值、是否常数列，自动识别连续变量、分类变量、时间变量、疑似 ID 等，并给出每一列在因果分析中的适用性评级（如 *excellent / good / warning*）。
- **质量诊断与因果友好度评估**：汇总整体缺失率，标记高缺失列和常数列，识别高基数分类、疑似 ID 等问题字段，并按适用性分组出「优先用于因果分析」的候选变量列表。
- **可视化摘要**：通过直方图、箱线图、相关性热力图等可视化方式，辅助发现明显异常值和潜在共线性问题。

### 因果分析（MCP）
*基于 MCP（Model Context Protocol）快速迭代因果算法*

- **可插拔算法框架**：通过 MCP 将因果发现与估计算法以「工具」形式解耦，便于在不改动 Agent 主逻辑的前提下扩展/更换算法库。
- **当前支持**：
  - PC 算法（基于条件独立检验的因果结构学习）。
  - OLC（面向存在隐藏混杂因素的连续变量场景）。
  - DirectLiNGAM（面向连续数值数据的线性非高斯无环因果发现，输出因果顺序与带权有向图）。使用结果时需满足误差相互独立、无潜在混杂等模型假设，边权表示模型估计系数，不等同于实验验证。
- **规划中**：
  - FCI 等含潜在混杂的结构学习算法；
  - 因果效应估计（ATE/CATE）与反事实分析等模块。

### 知识库（RAG）
*通过多模态知识库、混合检索与受控 release，为报告和问答提供专业支撑*

- **运行方式**：仓库提供受版本控制的正式 active release，生产查询从 release manifest 加载索引与 embedding 身份；部署时仍需配置匹配的 Embedding API。
- **检索能力**：使用 ChromaDB 向量检索与 BM25S 稀疏检索，并支持 PDF、文本、表格和图片等多模态摄取。
- **知识来源**：使用大量因果推断相关书籍与论文的 PDF / TXT 文档构建，涵盖经典因果图论、干预推断、工具变量、面板因果等主题。
- **典型能力**：
  - 在生成报告时，自动检索相关理论和方法描述，为结论补充严谨的文献背景；
  - 支持面向初学者的「概念解释」，例如“什么是混杂变量”“为什么需要随机试验”等。
- **个性化检索评测**
  - 进入rag检索评测页面，可以自定义rag检索内容，实现个性化知识库定义。

### 联网搜索

用户可以在发起分析前开启联网搜索。Web Search 子图通过 SearXNG 聚合 arXiv、Crossref 与 OpenAlex 等学术来源，并把受限数量的引用随报告公开；规划、检索或解析失败时会返回统一降级结果，不阻断主分析流程。

### 后处理
*对因果图进行后处理，包括环路检测、边合理性评估等，提高因果结构的可解释性与可靠性*

- **环路检测与修正**：检查学习得到的因果图中是否存在违背 DAG（有向无环图）假设的环路；若发现异常，则调用 LLM 辅助判断合理的断边方案，给出修正建议。
- **边评估与置信度分析**：对每一条因果边进行强度或置信度评估，结合数据统计特征和领域常识，对明显不合理的边进行标记与修正建议。
- **结构约束与业务先验融合**：在后处理阶段支持引入业务先验（如「变量 A 不可能被 B 因果影响」），从而得到更符合领域知识的因果图。

### 报告生成
*根据后处理结果生成面向业务方与研究者的专业报告，并配套交互式可视化*

- **自动生成结构化报告**：围绕「分析背景 → 数据概况 → 方法说明 → 因果发现 → 结论与建议 → 局限性」等章节自动撰写自然语言报告。
- **交互式因果图谱**：基于 vis-network 等前端组件生成可交互的因果图，支持节点拖拽、缩放、查看变量说明、点击追问等操作。

## 快速开始 | Quick Start

### 可访问入口

默认开发 Compose 启动后，可以访问：

| 功能 | 地址 | 说明 |
| --- | --- | --- |
| 用户聊天 | [http://127.0.0.1:5001/](http://127.0.0.1:5001/) | 上传数据、发起分析和查看报告 |
| RAG 运行台 | [http://127.0.0.1:5001/rag_eval](http://127.0.0.1:5001/rag_eval) | 知识源摄取、staged index、评测与 release 管理 |
| 管理后台 | [http://127.0.0.1:5001/admin/database](http://127.0.0.1:5001/admin/database) | 管理员登录后的默认入口 |
| Grafana | [http://127.0.0.1:3000](http://127.0.0.1:3000) | 日志查询和仪表盘 |

注：RAG 运行台是隔离的知识库构建、评测和发布工作台。

### 最小配置

复制 [`.env.example`](.env.example) 后，至少按启用能力检查以下配置；不要把真实密码或 API key 提交到 Git：

- 基础服务：`SECRET_KEY`、MySQL 账号、`CHECKPOINT_POSTGRES_PASSWORD`。
- Chat 模型：`API_KEY`、`BASE_URL`、`MODEL`。
- RAG 查询：`EMBEDDING_API_KEY`、`EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`，且必须与 active release manifest 匹配。
- 日志界面：`GRAFANA_ADMIN_PASSWORD`。
- 联网搜索：Compose 默认使用 `WEB_SEARCH_PROVIDER=searxng` 和内部 `SEARXNG_URL`，通常无需额外修改。

完整配置和运行边界见 [`Document/development/setup.md`](Document/development/setup.md) 与 [`Document/development/deployment.md`](Document/development/deployment.md)。

### Docker部署
当前项目已经提供了完整的多阶段 `Dockerfile`，会先用 Node 24 构建管理员 Vue，再生成仅包含 Python 运行时与静态产物的应用镜像；暂未在公网镜像仓库发布官方镜像。
如果你已安装 Docker，可以在本地根据下面的步骤自行构建并运行镜像。


1. 安装docker并且gitclone项目
```bash
git clone https://github.com/Heyflyingpig/CausalAgent
cd CausalAgent
```

2. 创建并填写.env文件
```bash
cp .env.example .env
```

3. 在项目根目录运行docker-compose
```bash
docker compose -f docker-compose.yml up -d
```

`docker compose ... up -d` 会在 app、worker、monitor 和 cleanup worker 启动前，
自动运行一次性 `db-bootstrap`。它依次执行 MySQL 建库、Alembic migration 和
LangGraph 官方 PostgreSQL setup。若需要手动重跑该初始化入口，可执行：

```bash
docker compose -f docker-compose.yml run --rm db-bootstrap
```

请先在 `.env` 设置非空的 `CHECKPOINT_POSTGRES_PASSWORD`。
`checkpoint-cleanup` 仍是独立的常驻 worker，用于消费跨库清理 outbox。
`app` 负责管理员 checkpoint 摘要读取，`monitor` 负责 PostgreSQL quick/deep
检查，因此两者也必须取得相同的 `CHECKPOINT_POSTGRES_*` 配置。生产 Compose
同样包含 PostgreSQL、bootstrap、worker、monitor 和 cleanup 服务。

全新空库不需要运行升级前审计。只有旧库尚未建立目标外键、且即将执行添加这些外键的迁移时，才先运行：

```bash
docker compose -f docker-compose.yml run --rm app python Database/audit_before_db_upgrade.py
```

> [!IMPORTANT]
> 仓库已包含正式 active RAG release，但部署环境仍须提供与 manifest 匹配的 Embedding API 配置。readiness 检查失败时，worker 会继续启动并把 RAG 安全降级为不可用。

## 管理员与开发者

前面的章节面向普通用户和首次运行；本节集中说明管理员入口、数据库、日志、测试和桌面发布。

### 管理员端展示

<p align="center">
  <img src="./README/管理员.png" alt="管理员后台" width="850">
</p>

### 数据库生产化配置

主从开发：

如果你已经启动过 `mysql-primary` 或 `mysql-replica`，修复后要使用新的空 volume 重建；否则 `/docker-entrypoint-initdb.d` 初始化脚本不会重新执行。

主从模式下数据库账号按职责拆分：

- 写账号：`MYSQL_WRITE_USER` / `MYSQL_WRITE_PASSWORD`，用于应用写主库、Alembic 迁移和启动就绪检查；缺失时兼容回退到 `MYSQL_USER` / `MYSQL_PASSWORD`。
- 读账号：`MYSQL_READ_USER` / `MYSQL_READ_PASSWORD`，用于 `get_read_connection()` 的主库强一致读和从库弱一致读；除业务库 `SELECT` 外，仅额外授予 `performance_schema.events_statements_summary_by_digest` 的表级 `SELECT`，供高负载 SQL digest 摘要使用；缺失时兼容回退到 `MYSQL_USER` / `MYSQL_PASSWORD`。
- 复制状态检查账号：`MYSQL_REPLICA_STATUS_USER` / `MYSQL_REPLICA_STATUS_PASSWORD`，只用于读取 `SHOW REPLICA STATUS`；缺失或不可用时，`eventual` 读安全回退主库读连接。
- 复制通道账号：`MYSQL_REPLICATION_USER` / `MYSQL_REPLICATION_PASSWORD`，只用于 MySQL 主从复制链路，不参与应用业务查询。


### 管理员后台

管理员后台提供业务概览、用户、会话、任务、文件、数据库看板、采集配置和数据库审计。数据库看板通过 URL 查询参数在“数据库运行状态 / Cleanup Worker / Outbox 队列”三段视图间切换；用户删除后可从持续可见的 checkpoint 清理进度区跳转到对应 Operation ID 的 Outbox 排查。普通用户仍进入聊天页面，已启用的管理员登录后进入 `/admin/database`。

管理员仍默认进入 `/admin/database`，也可从后台进入普通聊天界面；聊天页只访问当前账号自己的会话、文件和任务，并向管理员提供返回后台的入口。管理员主动访问 `/` 时不会被再次强制送回后台。

未登录管理页面只保留白名单内的安全回跳；普通用户直访管理页面会得到 `403`。`POST /api/login` 仅在内部 `next` 通过服务端白名单校验后返回 `redirect_to`。

首次使用前，先完成数据库迁移和管理员前端构建，然后把一个已经注册且已启用的用户提升为管理员：

```bash
# Docker 运行
docker compose -f docker-compose.yml run --rm app python -m app.auth.admin_cli promote <username>
```

管理员系统的部署、开发、API、安全边界和测试说明统一放在 [`Document/admin/`](Document/admin/README.md)。其中：

- [API 契约](Document/admin/api.md)
- [开发与部署](Document/admin/development.md)
- [测试说明](Document/admin/testing.md)

### 日志系统

运行时日志链路为：

```text
app / worker / monitor / MCP / RAG worker
    → 结构化 JSON 日志
    → Grafana Alloy
    → Loki
    → Grafana Dashboard
```

运行时代码使用受控事件目录，并通过 request、job、session 和 worker slot 等字段关联请求。原始 prompt、文件正文、API key、Token 和 Cookie 等敏感内容不得进入日志；完整事件、降噪与脱敏规则见 [`Document/development/observability.md`](Document/development/observability.md)。

#### 开发环境启动

先在 `.env` 中设置非空的 `GRAFANA_ADMIN_PASSWORD`，然后从仓库根目录执行配置校验、Alloy语法校验和完整开发启动：

```bash
docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.yml pull loki alloy grafana
docker compose -f docker-compose.yml run --rm --no-deps alloy validate /etc/alloy/config.alloy
docker compose -f docker-compose.yml up -d
docker compose -f docker-compose.yml ps
```

打开 [http://127.0.0.1:3000](http://127.0.0.1:3000) 进入 Grafana，使用 `GRAFANA_ADMIN_USER`（默认值为 `admin`）和 `.env` 中设置的密码登录。Loki 数据源和 CausalAgent 日志仪表盘会由 Compose 自动 provision。需要直接查看容器输出时执行：

```bash
docker compose -f docker-compose.yml logs -f app worker monitor alloy loki grafana
```

停止服务建议使用 `docker compose -f docker-compose.yml stop`，这样会保留 Loki、Grafana 和Alloy positions 命名卷。不要使用 `down -v` 代替停止操作，否则会删除日志查看拓扑的持久化数据。
修改 `observability/alloy/config.alloy` 后，必须重新执行 `alloy validate`，确认通过后再重启Alloy。

[`Document/development/observability.md`](Document/development/observability.md)，Compose
部署边界见 [`Document/development/deployment.md`](Document/development/deployment.md)。

### RAG评测工作台

<p align="center">
  <img src="./README/rag评测工作台.png" alt="管理员后台" width="850">
</p>
RAG 评测工作台面向管理员和 RAG 维护人员，用于在不影响当前生产知识库的前提下，完成知识源摄取、隔离索引构建、检索试跑、题集治理、Ragas 评测和正式 release 发布。详细文档请看： [`Document/architecture/rag-evaluation.md`](Document/architecture/rag-evaluation.md)

页面主要分为工作索引、候选题集、评测中心、正式发布和报告管理等区域。工作台入口为 [http://127.0.0.1:5001/rag_eval](http://127.0.0.1:5001/rag_eval)。

```mermaid
flowchart LR
    A[选择或上传知识源] --> B[隔离摄取]
    B --> C[构建 staged index]
    C --> D[staged RAG 试跑]
    C --> E[候选题集与人工审核]
    D --> F[选择评测题集]
    E --> F
    F --> G[数据校验、检索评测与 Ragas]
    G --> H[生成评测报告]
    H --> I{正式 release 门禁}
    I -->|未通过| J[调整来源、索引或检索策略]
    J --> C
    I -->|通过并显式确认| K[发布 active pointer]
    K --> L[Agent worker drain / restart]
    L --> M[生产聊天 RAG 使用新 release]
```

### 后端单元测试

仓库提供独立的 `docker-compose.test.yml`，用于按需创建一次性单元测试容器。测试镜像预装项目 Python 依赖和 `pytest`，不连接 MySQL，禁用网络；当前源码以只读方式挂载到容器，因此修改代码后可以直接重新运行测试，无需重建镜像。

首次使用或测试依赖变化后构建测试镜像：

```bash
docker compose -f docker-compose.test.yml build unit-test
```

运行全部后端单元测试，测试结束后自动删除本次容器：

```bash
docker compose -f docker-compose.test.yml run --rm unit-test
```

运行指定测试文件：

```bash
docker compose -f docker-compose.test.yml run --rm unit-test python -m pytest -p no:cacheprovider tests/unit/agent/test_agent_state_routing.py
```

需要在相同环境内排查导入或依赖问题时，可以临时进入 Shell；退出后容器仍会自动删除：

```bash
docker compose -f docker-compose.test.yml run --rm unit-test sh
```

当前测试只保证 `tests/unit`；集成测试和隔离主从 E2E 的执行边界见 [`tests/README.md`](tests/README.md)。



### windows部署

CausalAgent已支持 Windows 桌面客户端：`Run_causal.py` 只启动 WebView2 Edge Chromium 窗口，并加载与浏览器相同的 CausalAgent 页面。

也可以进入release中，下载对应tag版本的桌面端

创建独立桌面环境并检查 WebView2 Runtime：

```powershell
python -m venv .venv-desktop
.\.venv-desktop\Scripts\python.exe -m pip install -r .\windows-client\requirements-desktop.txt
.\.venv-desktop\Scripts\python.exe .\Run_causal.py --check-environment
```

开发时先启动现有 Flask 服务，再运行桌面壳。URL 优先级为命令行 `--url` > `CAUSALAGENT_DESKTOP_URL` > `http://127.0.0.1:5001/`：

```powershell
$env:CAUSALAGENT_DESKTOP_URL = "http://127.0.0.1:5001/"
.\.venv-desktop\Scripts\python.exe .\Run_causal.py
```

Release 包在构建时嵌入正式 HTTPS origin，强制关闭 debug 和开发者工具；构建与 Windows 验收命令见 [`windows-client/README.md`](windows-client/README.md)、[`Document/development/setup.md`](Document/development/setup.md) 和 [`Document/development/testing.md`](Document/development/testing.md)。

## 技术文档

根 README 只提供项目概览和常用入口，具体技术事实统一由 [`Document/README.md`](Document/README.md) 导航：

- 系统、Agent 与 RAG 架构：[`Document/architecture/`](Document/architecture/overview.md)
- 普通用户与 RAG API：[`Document/api/`](Document/api/conventions.md)
- 数据库、迁移与 checkpoint：[`Document/database/`](Document/database/overview.md)
- 开发、测试、部署与可观测性：[`Document/development/`](Document/development/setup.md)
- 管理员模块：[`Document/admin/`](Document/admin/README.md)

## 贡献
欢迎提交 Issue 和 Pull Request！

1. Fork 本项目

2. 从 `develop` 新建工作分支，例如 `feat(rag)/cache`

3. 提交信息与 Pull Request 标题使用 `keyword(function):description` 格式

   支持的 keyword 包括 `feat`、`fix`、`docs`、`refactor`、`test`、`chore`、`ci`、`build`、`perf` 和 `revert`，例如 `fix(chat):修复会话删除异常`。

4. 向 `develop` 新建 Pull Request；只有 `develop` 可以向 `main` 发起合并请求

5. 等待 `Python syntax`、`Light tests` 和 `Pull request policy` 检查通过后再合并

新建 Issue 时请使用仓库提供的 [`Issue Form`](.github/ISSUE_TEMPLATE/issue.yml)，按模板填写背景、问题描述、预期结果、复现步骤、验收标准和环境信息。除附件外的字段为 GitHub 原生必填项，但不限制填写内容；普通贡献者不能选择空白 Issue。

## Star History
<a href="https://www.star-history.com/?repos=Heyflyingpig%2FCausalAgent&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=Heyflyingpig/CausalAgent&type=date&theme=dark&legend=top-left&sealed_token=vS9LuCPAcO5HBRJ7MqLOBVKGWvmIC8oGUNMsERduenNH5V5akK0TIWWWQljUSlpxn51m9ROc4eqMCHAEbm0hbW_s66HzGJPzNzE_FxjQXN2e1X7bTiWdq9DKNsjtUwfG6z_5jr-PQcnDsaPoirqPbtSM1xAJvkdffet1KAGVfBKq777hNOA2qhwHt2Hp" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=Heyflyingpig/CausalAgent&type=date&legend=top-left&sealed_token=vS9LuCPAcO5HBRJ7MqLOBVKGWvmIC8oGUNMsERduenNH5V5akK0TIWWWQljUSlpxn51m9ROc4eqMCHAEbm0hbW_s66HzGJPzNzE_FxjQXN2e1X7bTiWdq9DKNsjtUwfG6z_5jr-PQcnDsaPoirqPbtSM1xAJvkdffet1KAGVfBKq777hNOA2qhwHt2Hp" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=Heyflyingpig/CausalAgent&type=date&legend=top-left&sealed_token=vS9LuCPAcO5HBRJ7MqLOBVKGWvmIC8oGUNMsERduenNH5V5akK0TIWWWQljUSlpxn51m9ROc4eqMCHAEbm0hbW_s66HzGJPzNzE_FxjQXN2e1X7bTiWdq9DKNsjtUwfG6z_5jr-PQcnDsaPoirqPbtSM1xAJvkdffet1KAGVfBKq777hNOA2qhwHt2Hp" />
 </picture>
</a>

## 项目结构

```
.
├── CausalAgent.py              # Flask Web 入口
├── Run_causal.py               # Windows WebView2 启动入口
├── app/                        # Web、认证、Job、管理员与 RAG 运行台
│   ├── agent/                  # Job API、SSE 与独立 worker
│   └── rag_eval/               # 隔离摄取、评测与 release 管理
├── Agent/                      # LangGraph、因果工具与知识库
│   ├── causal_agent/           # 父图、节点、路由与子图
│   ├── CausalAgentMCP/         # MCP 因果算法服务
│   └── knowledge_base/         # RAG runtime、多模态索引与评测
├── Database/                   # MySQL、PostgreSQL、迁移与监控
├── observability/              # 结构化日志、事件目录与 Alloy 配置
├── searxng/                    # 联网搜索配置与初始化
├── admin-frontend/             # Vue 管理员前端
├── windows-client/             # Windows 客户端、构建与 smoke 测试
├── config/                     # 应用与 RAG 路径配置
├── deploy/                     # staging/production 部署资源
├── scripts/                    # 发布、验收与诊断脚本
├── Document/                   # 当前技术事实库
├── tests/                      # unit、integration、e2e 与 smoke
├── docker-compose*.yml         # 开发、测试、预发和生产拓扑
└── .github/workflows/          # CI 与 Windows release 工作流
```
