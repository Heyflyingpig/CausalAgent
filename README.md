[简体中文](README.md) | [English](README_EN.md)


<p align="center">
<img src="./readme_img/CausalAgent.png" alt="Logo">
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
- [展示](#展示)
- [核心功能](#核心功能)
  - [Agent 总览](#agent-总览)
  - [预处理](#预处理)
  - [因果分析（MCP）](#因果分析mcp)
  - [知识库（RAG）](#知识库rag)
  - [后处理](#后处理)
  - [报告生成](#报告生成)
- [快速开始 | Quick Start](#快速开始--quick-start)
  - [Docker部署](#docker部署)
    - [数据库生产化配置](#数据库生产化配置)
  - [windows部署](#windows部署)
- [贡献](#贡献)
- [Star 趋势](#star-趋势)
- [项目结构](#项目结构)
- [更新日志](#更新日志)





## WHAT IS CausalAgent

**新一代因果分析智能体**: CausalAgent 是一个集成了AGENT的因果分析工具，它能够自动识别因果关系，生成专业的分析报告，并提供可交互的因果图谱。

**缩减因果分析门槛**：什么是因果？为什么需要因果分析？简单来说，[因果分析](https://zh.wikipedia.org/wiki/%E5%9B%A0%E6%9E%9C%E6%8E%A8%E6%96%B7)就是对真实世界数据进行逻辑分析。

## WHY CausalAgent

| 特性 | 说明 |
| :--- | :--- |
| **Agent 驱动** | 基于 LangGraph 的多智能体协作，自动路由任务，无需人工干预算法细节。 |
|  **动态图谱** | 摒弃静态图片，生成可交互的 Network 图谱，支持节点拖拽、点击追问。 |
|  **MCP 架构** | 采用 **Model Context Protocol**，将核心逻辑与工具解耦，极易扩展新算法。 |
|  **RAG 增强** | 内置因果推断领域的专业知识库，确保生成的分析报告学术性与严谨性并存。 |
## 技术栈

| 类别 | 技术组件 |
| :--- | :--- |
| **Core AI** | ![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?style=flat-square&logo=langchain&logoColor=white) ![LangGraph](https://img.shields.io/badge/LangGraph-FF4B4B?style=flat-square) ![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=flat-square&logo=openai&logoColor=white) |
| **Backend** | ![Flask](https://img.shields.io/badge/Flask-000000?style=flat-square&logo=flask&logoColor=white) ![MySQL](https://img.shields.io/badge/MySQL-4479A1?style=flat-square&logo=mysql&logoColor=white) ![Alembic](https://img.shields.io/badge/Alembic-F7F7F7?style=flat-square&logo=python&logoColor=black) |
| **Frontend** | ![HTML5](https://img.shields.io/badge/HTML5-E34F26?style=flat-square&logo=html5&logoColor=white) ![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?style=flat-square&logo=javascript&logoColor=black) ![PyWebview](https://img.shields.io/badge/PyWebview-FFD43B?style=flat-square&logo=python&logoColor=blue) |
| **Tools** | ![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white) ![Git](https://img.shields.io/badge/Git-F05032?style=flat-square&logo=git&logoColor=white) |
## 展示
<p align="center">
  <img src="./readme_img/image.png" alt="主程序" width="450">

</p>
<p align="center">
  <img src="./readme_img/image2.png" alt="因果图" width="450">
</p>

## 核心功能

CausalAgent 的整体因果分析流程可以抽象为：**用户上传数据 → 预处理与数据体检 → 因果结构学习 → 后处理与质量提升 → 报告与可视化输出**。下面按模块进行说明。

### Agent 总览
```mermaid
graph TD;
    subgraph "User Interaction"
        Human((User)) <--> UI[Web/Desktop UI]
    end

    subgraph "Agent Core (LangGraph)"
        UI --> Router{Router Agent}
        Router -->|Need Info| Pre[数据预处理 Agent]
        Router -->|Analysis| Causal[因果分析 Agent]
        Router -->|Report| Writer[报告生成 Agent]
        Router -->|Q&A| Chat[普通对话]

        Causal <--> MCP[MCP Tool Server]
        Writer <--> RAG((RAG Knowledge Base))
    end

    subgraph "Tools & Data"
        MCP --> PC[PC Algorithm]
        MCP --> FCI[FCI Algorithm]
        Pre --> Data[(MySQL/Files)]
    end

```

- **Router Agent**：根据用户意图在「预处理 / 因果分析 / 知识库问答 / 报告生成」等节点之间自动路由，无需用户关心底层算法。
- **Causal Agent**：负责与 MCP 因果算法工具交互（如 PC、FCI 等），完成因果结构学习与干预效应估计的核心推理。
- **Writer Agent**：结合因果结果与 RAG 知识库，自动撰写结构化专业报告（背景、方法、结果、结论与局限性）。
- **Chat Agent**：面向一般问答与解释型对话，为非专业用户提供自然语言解释与操作指引。

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
- **规划中**：
  - FCI 等含潜在混杂的结构学习算法；
  - 因果效应估计（ATE/CATE）与反事实分析等模块。

### 知识库（RAG）
*通过嵌入论文与书籍构建因果推断领域知识库，为报告和问答提供专业支撑*

- **嵌入模型**：目前采用 `bge-small-zh-v1.5` 作为中文向量化模型，兼顾性能与效果。
- **知识来源**：使用大量因果推断相关书籍与论文的 PDF / TXT 文档构建，涵盖经典因果图论、干预推断、工具变量、面板因果等主题。
- **典型能力**：
  - 在生成报告时，自动检索相关理论和方法描述，为结论补充严谨的文献背景；
  - 支持面向初学者的「概念解释」，例如“什么是混杂变量”“为什么需要随机试验”等。

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
### Docker部署
当前项目已经提供了完整的 `Dockerfile`，支持通过 Docker 运行后端服务，但暂未在公网镜像仓库发布官方镜像。
如果你已安装 Docker，可以在本地根据下面的步骤自行构建并运行镜像。


1. 安装docker并且gitclone项目
```bash
git clone https://github.com/Heyflyingpig/CausalAgent
```

2. 创建.env文件,并在文件中键入以下值
```bash
# Flask 应用密钥（用于会话加密等）
SECRET_KEY=

# API 基础URL（OpenAI官方或第三方兼容接口）
BASE_URL=
MODEL=

# OpenAI API 密钥或兼容 API 的密钥
API_KEY=
# Docker环境：使用服务名 'mysql'
# 本地开发：使用 'localhost' 或 '127.0.0.1'
MYSQL_HOST=mysql

# 旧版兼容账号。未配置拆分账号时，写/读连接会回退使用它。
MYSQL_USER=pyramid

MYSQL_ROOT_PASSWORD=
MYSQL_PASSWORD=

# 数据库名称
MYSQL_DATABASE=

# 应用写账号：用于主库写入、迁移和数据库就绪检查。
MYSQL_WRITE_USER=pyramid_writer
MYSQL_WRITE_PASSWORD=

# 应用读账号：用于主库/从库业务查询，建议只授予业务库 SELECT。
MYSQL_READ_USER=pyramid_reader
MYSQL_READ_PASSWORD=

# 复制状态检查账号：只用于 SHOW REPLICA STATUS，缺失时 eventual 读会回退主库。
MYSQL_REPLICA_STATUS_USER=replica_status
MYSQL_REPLICA_STATUS_PASSWORD=

# 复制通道账号：只用于从库拉取主库 binlog。
MYSQL_REPLICATION_USER=replica
MYSQL_REPLICATION_PASSWORD=

MYSQL_WRITE_HOST=mysql-primary
MYSQL_READ_HOSTS=mysql-replica

MYSQL_PORT=3306
MYSQL_POOL_SIZE_WRITE=5
MYSQL_POOL_SIZE_READ=5
MYSQL_REPLICA_MAX_LAG_SECONDS=2
MYSQL_QUERY_WARN_MS=500

# Web/后台任务并发配置
WEB_WORKERS=1
WEB_THREADS=12
WEB_TIMEOUT=120
JOB_WORKERS=2
JOB_HEARTBEAT_INTERVAL_SECONDS=10
JOB_STALE_AFTER_SECONDS=120
JOB_MAX_ATTEMPTS=3

MAX_UPLOAD_SIZE_MB=20


# LangSmith API 密钥(不强制)
LANGCHAIN_API_KEY=

# LangSmith 项目名称（不强制）
LANGCHAIN_PROJECT=

```
3. 在项目根目录运行docker-compose
```bash
docker-compose -f docker-compose.replica.yml up -d
```

4. 运行数据库迁移
```bash
docker-compose -f docker-compose.replica.yml run --rm app python Database/database_init.py
docker-compose -f docker-compose.replica.yml run --rm app alembic upgrade head
```

如果是已有旧数据、准备做生产化升级，再额外先执行：

```bash
docker-compose -f docker-compose.replica.yml run --rm app python Database/audit_before_db_upgrade.py
```

> [!IMPORTANT]
> **知识库仍然在构建，所以知识库查询功能暂不可用**

#### 数据库生产化配置

主从开发：

如果你已经启动过 `mysql-primary` 或 `mysql-replica`，修复后要使用新的空 volume 重建；否则 `/docker-entrypoint-initdb.d` 初始化脚本不会重新执行。

主从模式下数据库账号按职责拆分：

- 写账号：`MYSQL_WRITE_USER` / `MYSQL_WRITE_PASSWORD`，用于应用写主库、Alembic 迁移和启动就绪检查；缺失时兼容回退到 `MYSQL_USER` / `MYSQL_PASSWORD`。
- 读账号：`MYSQL_READ_USER` / `MYSQL_READ_PASSWORD`，用于 `get_read_connection()` 的主库强一致读和从库弱一致读；缺失时兼容回退到 `MYSQL_USER` / `MYSQL_PASSWORD`。
- 复制状态检查账号：`MYSQL_REPLICA_STATUS_USER` / `MYSQL_REPLICA_STATUS_PASSWORD`，只用于读取 `SHOW REPLICA STATUS`；缺失或不可用时，`eventual` 读安全回退主库读连接。
- 复制通道账号：`MYSQL_REPLICATION_USER` / `MYSQL_REPLICATION_PASSWORD`，只用于 MySQL 主从复制链路，不参与应用业务查询。

管理接口：

- `GET /api/admin/db/health`
- `GET /api/admin/db/slow-queries`
- `GET /api/admin/jobs/workers`



### windows部署

**不推荐使用windows部署，会有意想不到的问题**

项目采用前后端分离的设计，需要同时运行后端服务和前端应用。

首先推荐创建一个环境，具体创建方式请自行查阅

1. 打开命令行工具。

2. 导航到您想要存放项目的目录。 （例如，如果您想放在 D 盘的 Projects 文件夹下，可以输入 cd /d D:\Projects）

3. 克隆仓库: 输入以下命令并按回车：

  git clone https://github.com/Heyflyingpig/CausalAgent
  这将在当前目录下创建一个名为 CausalAgent 的文件夹，并下载所有项目文件。

*备选方案：您也可以在 GitHub 页面上点击 "Code" -> "Download ZIP" 下载项目的压缩包，然后手动解压。*


4.  **Python 环境**: 确保你已安装 Python 3.11+。

5.  **MySQL 数据库**: 你需要一个正在运行的 MySQL 8.0+ 实例。请预先创建一个数据库（例如，名为 `causal_chat_db`）并准备好其访问凭据（主机、用户名、密码）。

6.  **安装 Python 依赖**:
    克隆项目后，在项目根目录运行以下命令：
    ```bash
    pip install -r requirements.txt
    ```

7. 项目配置

在首次运行前，你必须在项目根目录下创建一个 `.env` 文件，用于存放所有敏感配置信息。

-   创建 `.env` 文件。
-   将以下模板内容复制到文件中，并填入你自己的真实信息。

    ```bash
    # Flask 应用密钥（用于会话加密等）
    SECRET_KEY=

    # API 基础URL（OpenAI官方或第三方兼容接口）
    BASE_URL=
    MODEL=

    # OpenAI API 密钥或兼容 API 的密钥
    API_KEY=
    # Docker环境：使用服务名 'mysql'
    # 本地开发：使用 'localhost' 或 '127.0.0.1'
    MYSQL_HOST=mysql

    # 旧版兼容账号。未配置拆分账号时，写/读连接会回退使用它。
    MYSQL_USER=

    MYSQL_ROOT_PASSWORD=
    MYSQL_PASSWORD=

    # 数据库名称
    MYSQL_DATABASE=

    # 应用写账号
    MYSQL_WRITE_USER=
    MYSQL_WRITE_PASSWORD=

    # 应用读账号
    MYSQL_READ_USER=
    MYSQL_READ_PASSWORD=

    # 复制状态检查账号。缺失时 eventual 读回退主库。
    MYSQL_REPLICA_STATUS_USER=
    MYSQL_REPLICA_STATUS_PASSWORD=

    # 复制通道账号
    MYSQL_REPLICATION_USER=replica
    MYSQL_REPLICATION_PASSWORD=

    # LangSmith API 密钥(不强制)
    LANGCHAIN_API_KEY=

    # LangSmith 项目名称（不强制）
    LANGCHAIN_PROJECT=

    ```

8. 启动数据库
需要预先安装mysql数据库
在项目根目录下打开一个终端，运行以下命令：
```bash
python Database/database_init.py
alembic upgrade head
```
`Database/database_init.py` 负责确保数据库存在和连接可用；业务表结构由 Alembic 迁移脚本维护。全新空库直接执行 `alembic upgrade head` 即可；已有历史数据的环境应先执行审计脚本，确认无孤立消息、孤立附件和非法附件类型后再升级。

9. 启动后端服务

在项目根目录下打开一个终端，运行 Web 层：

```bash
python Causalchat.py
```

再打开一个终端，运行后台 worker：

```bash
python -m app.agent.worker
```

首次运行时，Web 层会检查数据库表结构。Agent/MCP 初始化只在 worker 中执行；如果没有 worker，前端可以创建任务但不会得到最终分析结果。请保持 Web 和 worker 两个终端窗口持续运行。

10. 启动前端应用

再打开一个 **新的终端窗口**，同样在项目根目录下，运行以下命令：

```bash
python Run_causal.py
```

稍等片刻，一个标题为 "CausalAgent" 的桌面应用窗口将会出现，并加载应用的登录界面。现在，你可以注册并开始使用了。

11. rag和知识库部分
> [!IMPORTANT]
> **知识库仍然在构建，所以知识库查询功能暂不可用**

## 贡献
欢迎提交 Issue 和 Pull Request！

1. Fork 本项目

2. 新建 Feat_xxx 分支

3. 提交代码

4. 新建 Pull Request

## Star 趋势

[![Star History Chart](https://api.star-history.com/svg?repos=Heyflyingpig/CausalAgent&type=Date)](https://star-history.com/#Heyflyingpig/CausalAgent&Date)


## 项目结构

```
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
│   ├── chat/               # 聊天 & 会话相关路由与服务
│   ├── files/              # 文件上传/管理相关路由
│   └── static/             # 前端静态资源
│       ├── chat.html       # 主聊天界面
│       ├── css/
│       ├── js/
│       └── generated_graphs/ # 因果图等生成图像
├── Agent/                  # 因果分析与智能体核心逻辑
│   ├── causal/             # 底层因果发现算法
│   ├── causal_agent/       # langgraph/agent 状态、节点定义
│   ├── Processing/         # 数据预处理、折叠验证、可视化
│   ├── Postprocessing/     # 后处理
│   ├── Report/             # 报告生成逻辑
│   ├── knowledge_base/     # RAG 知识库
│   │   ├── build_knowledge.py
|   |   ├── query_rag.py
│   │   ├── db/             # 向量知识库存储
│   │   └── models/         # 嵌入模型
│   └── tool_node/          # MCP 工具节点封装（task、rag 调用等）
├── Database/               # 数据库初始化与迁移逻辑
│   ├── database_init.py    # 数据库初始化引导脚本
│   ├── audit_before_db_upgrade.py # 数据库生产化升级前审计
│   ├── monitoring.py       # 数据库轻量监控查询
│   ├── agent_connect.py    # Langgraph checkpoint 相关数据库支持
│   ├── mysql/              # MySQL 主从配置与初始化脚本
│   └── migrations/         # Alembic 迁移脚本
├── config/                 # 全局配置
│   └── settings.py
├── setting/                # 用户可见文档
│   ├── manual.md           # 用户手册
│   └── Userprivacy.md      # 用户隐私协议
├── openspec/               # 项目规范与变更说明（内部开发用）
```

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