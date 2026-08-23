[简体中文](README.md) | [English](README_EN.md)


<p align="center">
<img src="./README/CausalAgent.png" alt="Logo">
</p>

<h1 align="center">
CausalAgent
</h1>

当前 `/rag_eval` 的策略 profile 将 retrieval 与 Ragas 配置统一管理：内置 profile 只读；用户自定义 profile 存储在 MySQL 的 `rag_eval_profiles` 表，可从评测中心另存、保存、删除和发布。正式发布生成 `Agent/knowledge_base/rag/runtime/production_rag_config.json` 快照，历史评测使用各自 `run_manifest.json` 中的完整配置。

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
    - [管理员后台](#管理员后台)
  - [后端单元测试](#后端单元测试)
  - [windows部署](#windows部署)
- [贡献](#贡献)
- [Star 趋势](#star-趋势)
- [项目结构](#项目结构)





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
  <img src="./README/image.png" alt="主程序" width="450">

</p>
<p align="center">
  <img src="./README/image2.png" alt="因果图" width="450">
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
        MCP --> DirectLiNGAM[DirectLiNGAM]
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
  - DirectLiNGAM（面向连续数值数据的线性非高斯无环因果发现，输出因果顺序与带权有向图）。使用结果时需满足误差相互独立、无潜在混杂等模型假设，边权表示模型估计系数，不等同于实验验证。
- **规划中**：
  - FCI 等含潜在混杂的结构学习算法；
  - 因果效应估计（ATE/CATE）与反事实分析等模块。

### 知识库（RAG）
*通过嵌入论文与书籍构建因果推断领域知识库，为报告和问答提供专业支撑*

- **嵌入模型**：目前采用 `bge-small-zh-v1.5` 作为中文向量化模型，兼顾性能与效果。
- **知识来源**：支持 PDF、TXT、Markdown、CSV、XLSX 以及 PNG/JPG/JPEG/WEBP/TIF/TIFF 图片；知识源先经过多模态解析与标准化，再进入统一检索链路，涵盖经典因果图论、干预推断、工具变量、面板因果等主题。
- **典型能力**：
  - 在生成报告时，自动检索相关理论和方法描述，为结论补充严谨的文献背景；
  - 支持面向初学者的「概念解释」，例如“什么是混杂变量”“为什么需要随机试验”等。
- **默认生产链路**：使用 `RagRuntime -> RagService -> rag 普通节点`；该节点直接生成问题、调用 Service 并写回结果，不再经过 RAG ToolNode 子图。`rag_enrichment_search` 仅作为兼容工具入口保留。worker 启动时从多模态 active pointer 初始化共享 Runtime，RAG 问题的默认且唯一 corpus 是 `multimodal`。
- **多模态公共知识库**：维护者可通过 `python -m Agent.knowledge_base.multimodal.cli` 对离线公共文本、表格、图片和已配置解析器支持的 PDF 创建隔离暂存索引。解析层会识别正文、版面、表格、公式和图片等内容，并转为带来源定位的多模态知识单元，再写入同一 collection；新图片链只接受冻结公共来源，Runtime 仍会校验来源、manifest 与 embedding 指纹，漂移时拒绝初始化且绝不回退到 PubMedQA。
- **全量摄取与发布**：正式 PDF 使用 `spawn_per_batch` 的低内存 Docling 批处理，并原子保存到候选版本的 `checkpoints.sqlite3`：其中分表保存经 SHA-256 校验的本地版面解析、页元数据和最终单元，支持按页恢复而不产生大量小文件；默认关闭 Docling 图像/表格生成，页面和 `PictureItem` 图片由 PDF bbox 渲染器生成后进入远程 VLM 链路。传入外部 `outbound_manifest.json` 时，远程运行开始前会把它复制并冻结到候选目录；隔离评测中的两份冻结 Pearl 来源在远程授权开启时可自动生成本次不可变清单，其他来源仍需显式批准清单。只有完整匹配 source/page/图片哈希/context/策略指纹的记录允许外发。远程失败不回退本地 OCR。Chroma 成功构建后才提交，`run` 默认停在 `ready_to_publish`，只有显式发布才切换 active pointer。
- **空表恢复**：Docling 发现但无法导出的空 `TableItem` 会按页面 bbox 裁剪为 `table_recovery` 资产，与同页正文一起进入同一索引；摄取层依赖 provider-neutral 的 `TableRecoveryProvider`，当前 `RemoteVlmTableRecoveryProvider` 复用已存在的远程视觉 adapter，未来可替换为本地 VLM。恢复失败记录阻断 issue，不生成伪表格单元。
- **Checkpoint 查询**：日常使用 `python scripts/query-multimodal-checkpoints.py --checkpoint-db <候选目录>/checkpoints.sqlite3` 输出概要；加 `--document-id <ID> --page-number <页码>` 查询单页，只有需要查看单元详情时再加 `--include-units`。脚本通过 SQLite 只读连接打开文件，不需要图形化数据库工具。
- **图片链路迁移状态（2026-07-31）**：R3a 已完成两份冻结 Pearl PDF 的 `889/889` 页本地发现，275 条冻结记录已人工审核；R3b 已在单独外发授权下构建候选 `mm_587799887fc8efb68409`，其页覆盖、route、unit/vector/asset/hash 链和 270/275 的远程成功记录均已审计。R4 已从“固定 gold 的通用前置条件”调整为“索引可用性与 RAG 评测解耦”：新知识源先通过页覆盖、资产、hash、unit/vector 与解析错误门禁，再在独立 `/rag_eval` 工作流中以已有问题集或真实用户问题运行 Ragas。固定 Pearl 的 24 条人工题仅作为该公共语料的回归集；当前候选在 `why-003` 发现表格内容未进入 `retrieval_text`，故该回归集未通过，未发布。任一来源、图片哈希、context 或远程策略漂移仍须重新发现、审核和取得外发授权。当前 active `mm_74b5aef2f5e7322b5a79` 未改变。
- **隔离评测前端工作台（2026-07-31）**：`/rag_eval` 增加左侧产品导航和“评测中心”面板；面板只绑定当前 staged index，默认先执行 prepare-only 流程，用户显式打开 Ragas judge 后才进入完整评测，报告、事件和产物仍通过隔离 evaluation run 展示。
- **隔离评测前端评测导航（2026-07-31）**：评测中心拆分为“评测配置、流程报告与指标、评测流程事件、对比分析”四个二级页面；对比页提供时间跨度、粒度、时间趋势/运行 A/B/策略对比三种交互和快捷操作流程，但在隔离评测历史接口与测试源确定前不展示伪造指标。工作台改为纵向分区，左侧导航支持收起并持久化用户偏好。
- **隔离评测报告编辑与清理**：报告入口统一命名为“报告编辑”，可在同一页面切换流程、检索和 Ragas Markdown；删除已结束评测后，后端会移除对应 `tmp/rag_eval_isolated_runs/<run_id>/` 目录，历史与对比接口不再返回该运行。对超过无事件活动窗口的失活评测，用户确认后可强制删除；仍有活动迹象的运行禁止删除，摄取运行和 staged index 保留。
- **隔离评测运行配置对比**：对比分析除了指标和样本结果，还会读取两次 evaluation run 各自的 `run_manifest.json`，按路径展示 retrieval、Ragas、策略 profile 和执行步骤的配置差异；不会依赖特定题目或固定 dataset 字段。
- **隔离评测来源页范围（2026-07-31）**：`/rag_eval` 的运行范围支持按每个来源分别设置 1-based、首尾包含的物理页段，并通过 `page_ranges` 传给隔离摄取接口；快速联调/Smoke 的 `max_pages` 仍是按选中来源顺序累计的总上限。范围会写入 staged manifest，不能绕过隔离目录或发布门禁。
- **Docker Docling 模型路径（2026-07-31）**：`docker-compose.replica.yml` 的 `app`、`worker` 与 `rag-eval-worker` 复用工作区 `Agent/knowledge_base/models/docling`，通过 `MULTIMODAL_DOCLING_ARTIFACTS_DIR=/app/Agent/knowledge_base/models/docling` 加载 Docling 模型；宿主机原始缓存保留为回滚副本。
- **隔离评测运行（2026-08-02）**：后端新增 `POST /api/rag_eval/isolated/evaluation-runs`，显式绑定 `ingestion_run_id + index_version`，先把任务写入 `rag_eval_jobs` SQL 队列并由独立 `rag-eval-worker` 执行，不再依赖 Web 进程 daemon 线程。worker 通过 heartbeat 租约保活；进程异常退出后，下一次 worker 启动会将超时的 `running` 任务标记为 `failed`，不自动重跑可能产生外部模型调用的 Ragas。结果与 Markdown/JSON 产物通过评测任务结果和 artifact 接口读取，不复用旧 latest 输出；SSE 从运行目录轮询事件，支持 Web 与 worker 跨进程。
- **隔离评测知识源上传与删除（2026-08-02）**：工作台支持上传 PDF、TXT、Markdown、CSV、XLSX 和 PNG/JPG/JPEG/WEBP/TIF/TIFF 图片；后端通过 `POST /api/rag_eval/isolated/sources` 按解析器已有格式校验、大小、可读性和 SHA-256，并将来源登记到独立的 `tmp/rag_eval_sources/`（可用 `RAG_EVAL_SOURCE_ROOT` 覆盖）。上传不会自动摄取；用户上传来源可通过 `DELETE /api/rag_eval/isolated/sources/<source_id>` 删除，固定来源、运行中的摄取和已生成的 staged index/评测产物不会被删除。来源自定义显示名通过同目录的 `source_metadata.json` 保存，`PATCH /api/rag_eval/isolated/sources/<source_id>` 只更新显示元数据，不改变 source_id、内容 hash 或历史运行。用户选择来源并启动摄取后，隔离评测内测默认开启远程 VLM；设置 `VISION_ALLOW_REMOTE_DATA=false` 可关闭。
- **医疗兼容边界**：PubMedQA 构建、数据和专用评测入口暂时保留，但已退出默认生产与默认测试链路，供后续分阶段清理。
- **正式 RAG 测试集契约**：`rag_eval_v1` 现在区分 `gold_regression`、`generated_candidate` 和 `reference_free` 三类题集。Pearl 题集已转换为 `Agent/knowledge_base/rag/data/eval/pearl_gold_v1.json`（24 条），PubMedQA 保留为独立的 `medical_gold_v1.json`（1000 条），两者不能混作同一条默认回归线。可用 `python -m Agent.knowledge_base.rag.operation_datasets.build_eval_datasets` 从历史源文件重新生成。
- **字段含义**：`reference_answer` 是用于回答质量与 Ragas 对比的规范答案；`expected_claims` 是应覆盖的原子事实列表；`gold_evidence` 是由 Runtime metadata 定位的 locator 列表，按已提供字段做严格匹配，推荐使用 `document_id`、`page_number`、`unit_id`、`modality`、`content_kind`、`asset_uri` 等稳定字段。`gold_regression` 必须同时具备三者；缺少 `gold_evidence` 的题集只能作为 `generated_candidate` 或 `reference_free`，检索指标显示为未评分而不是 0。
- **用户自有知识源**：先为本次知识源保存版本/hash 快照，再用 Ragas 生成候选问题和参考答案。只有候选 context 能通过 metadata 或唯一的原文记录映射到 `gold_evidence` 时才具备自动检索 gold；其余保留为候选或 reference-free 观测，不自动提升为正式回归集。正式发布前仍需做去重、证据蕴含校验和少量人工抽查。
- **候选题集自动扩充**：对完整 staged index 执行 `python -m Agent.knowledge_base.rag.operation_datasets.candidate_generation --index-dir <staged-index> --output <candidate.json>`；入口会只读核对 build state、unit/vector/Chroma 计数和当前 embedding 指纹，再把标准化单元交给 Ragas 0.4.3 `generate_with_chunks()` 生成单跳、多证据和多跳候选问题、参考答案及 claims。输出固定为 `generated_candidate`，带 manifest/units/build-state hash、unit locator 和防碰撞版本号；每个 revision 同时写入 `candidate.json.audit.json`，保存生成错误、重复题、短答案、无法解析 evidence 的拒绝记录、计数摘要和 `rag_candidate_coverage_v1` 覆盖报告。没有候选通过筛选时不会写出空题集，也不会自动改写 gold 或 active pointer。
- **隔离评测长任务执行边界**：隔离摄取、候选题生成、staged index RAG 试跑、完整评测、调参集治理和 Gold 健康治理共享 MySQL `rag_eval_jobs` 队列，由 `rag-eval-worker` 按 `job_kind` 分发；Web 进程只创建、读取和取消任务。各任务均以独立 run 目录保存进度和产物，使用 heartbeat 与 fail-closed 超时收敛。
- **隔离评测生产接口与队列事实（2026-08-21）**：正式通用 run lifecycle 是 `GET /api/rag_eval/isolated/runs/<run_id>`、`/result`、`/artifacts/<artifact_name>`、`/stream` 与 `POST /cancel`；各具体 run 类型的状态/结果/产物/SSE/取消路径仍保留，但会返回 `Deprecation: true` 和指向通用路径的 successor `Link`。本轮不删除接口；仓库内静态审计得到的待审核清单见 `Document/rag_eval_api_inventory.md`，删除前必须结合访问日志、版本公告和弃用窗口，且鉴权不在本轮范围。
- **隔离评测题集、索引与容量门禁**：`rag_eval_datasets` 是不可变注册表，任务以 `dataset_ref` 解析注册版本，共享根目录由 `RAG_EVAL_DATASET_ROOT` 指定；运行前须通过 staged index 的完整身份门禁（运行、index version、manifest/source snapshot、locator 等）。`GET /api/rag_eval/isolated/capacity` 只读汇总容量，不执行 reconcile。默认 `RAG_EVAL_EVALUATION_WORKERS=5`；六类服务端并发上限依次由 `RAG_EVAL_INGESTION_CONCURRENCY_LIMIT`、`RAG_EVAL_CANDIDATE_GENERATION_CONCURRENCY_LIMIT`、`RAG_EVAL_TUNING_DATASET_GOVERNANCE_CONCURRENCY_LIMIT`、`RAG_EVAL_DATASET_GOVERNANCE_CONCURRENCY_LIMIT`、`RAG_EVAL_EVALUATION_CONCURRENCY_LIMIT`、`RAG_EVAL_RAG_QUERY_CONCURRENCY_LIMIT` 控制，默认值为 `1/1/1/1/3/2`。worker 在 MySQL 命名锁内按服务端固定优先级串行 claim。
- **隔离评测验收分层**：`Document/rag_eval_production_acceptance_matrix.json` 与安全 runner 将检查分为 contract、integration、production 三层：contract 仅非破坏性白名单检查，integration 使用临时 fixture，production 仅允许显式确认后的只读 readiness；它们不等同于已执行真实生产摄取、评测或发布。
- **Gold v2 无人值守题目健康治理**：对比分析中选择已完成的 Gold v2 evaluation run 后，可通过 `POST /api/rag_eval/gold-v2/governance` 一次确认并入队。human_reviewed、无 `source.generator` 和其他非生成来源永久保护；低 Ragas 分只触发诊断，生成题必须同时满足 intrinsic 风险、独立结构化 reviewer 的 `replace`/confidence >= 0.8 才退休。新候选复用现有 hard screen，并要求 `accept`/confidence >= 0.8；审核异常、候选不足、题数/schema/index identity/locator 不一致均 fail closed，旧 Gold 不变。有实际替换时在跨进程锁内重新核对源 evaluation 的数据集 SHA，拒绝 stale run 覆盖新 revision，再把旧 revision 归档到 `Agent/knowledge_base/rag/data/eval/history/` 并原子写入新 revision；没有题目通过双重门禁时报告 `no_change`，Gold 文件与 revision 均保持不变。流程不切换 production active index/profile，阶段、计数、逐题原因和恢复信息由治理 run API/SSE 展示。
- **并行检索调优**：隔离评测的 `retrieval` 可附带 `sweep` 和 `sweep_max_workers`（最多 8），对同一 staged index 和题集执行有界并行 retrieval sweep。结果记录每组配置、失败/取消状态、空结果数、样本级退化数，并最多推荐 2 个不低于基线且无样本退化的候选；推荐结果仍需人工确认后再进入 Ragas 或 profile 发布。
- **并行完整策略实验**：评测中心可选择 2–4 个已保存策略 profile，通过 `POST /api/rag_eval/isolated/evaluation-batches` 一次创建独立 evaluation runs；`rag-eval-worker` 在开发、兼容副本和生产 Compose 中均默认启动 5 个 slot，可通过 `RAG_EVAL_EVALUATION_WORKERS` 在 1–16 范围覆盖。前端统一展示批次进度、逐 run 事件和完成后的对比入口，每个 run 仍保存独立题集、配置快照与报告。
- **Ragas 失败关闭**：完整评测若在回答生成阶段遇到模型 API、余额或结构化输出错误，会在首个失败样本立即停止并标记 `answer_generation_failed`，不会继续调用 judge；judge 全部返回 NaN 时标记 `ragas_judge_no_valid_scores`。失败运行仍可打开结果和 Markdown 报告查看脱敏错误摘要。
- **候选题生成与审核闭环**：`/rag_eval` 的“候选题审核”页面调用 `POST /api/rag_eval/isolated/candidate-runs`，默认使用 Ragas 0.4.3 `generate_with_chunks()`；生成进度、取消、逐题编辑和三态审核通过 SSE/隔离产物保存。页面显示用户定义的知识源名称，索引号只显示短别名但保留完整值用于复制和审计；审核门禁位于生成区下方。审核编辑只写新的 reviewed candidate revision，原候选文件拒绝覆盖；`POST /api/rag_eval/gold-v2/freeze` 仅在 Pearl 24 题、候选 48 题和完整 approved 审核清单齐备时冻结 Gold v2。
- **索引绑定调参集治理**：工作台的“索引绑定调参集”入口调用 `POST /api/rag_eval/isolated/tuning-dataset-runs`，在当前 staged index 内只治理自动生成题，人工题保持保护；每轮按单题 Ragas 四指标门槛与 retrieval recall/MRR 门槛淘汰、生成和 AI 证据审核，缺分或审核异常均 fail-closed。通过后仅登记到隔离 run 与 `tmp/rag_eval_tuning_datasets/<index_version>/`，不写正式 evaluation history、报告、Gold 或 active pointer；结果可从 tuning run artifact 接口读取，后续仍需显式 Gold 发布动作。
- **Baseline v2 与 sweep 门禁**：`POST /api/rag_eval/baseline-v2/bind` 只读校验 Gold v2、active pointer/index manifest 和 `active_current` retrieval，不切换 active pointer；评测页面可发送 sweep 配置和 `retrieval_sweep` 步骤，baseline 失败时不会生成推荐。
- PDF 当前默认使用已通过本地 smoke 的 Docling；MinerU 仅保留为显式选择时的兼容回退。原始资料、Docling 原始输出、标准化单元与本地资源 URI/内容哈希都写入版本 manifest，并在发布门禁中回读核验。远程视觉仅接受 `wcode.net` 的 `qwen/qwen3-vl-8b-instruct` 配置和固定 allowlist 资料。

```bash
python -m Agent.knowledge_base.multimodal.cli inspect --source <path>
# 在实际 Docker worker 中准备 R2 固定 12 页清单（推荐）：
.\scripts\prepare-r2-outbound-manifest.ps1 -MaxPages 12
# 2026-08-07 user-approved rebuild: Pearl remote policy covers all 487/402
# physical pages, but remote calls still require the immutable outbound manifest.
# R3a: first run the local-only maintenance preflight, then create the full review manifest.
# Neither command sends images or creates a candidate index.
.\scripts\run-r3-maintenance-preflight.ps1
.\scripts\prepare-r3-outbound-manifest.ps1 -OutputFile tmp\r3-review-manifest.json
# R3b only, after manual approval and a separate data-egress authorization:
.\scripts\run-r3-maintenance-preflight.ps1 -RequireVisionConfiguration
# 经人工审阅和数据外发授权后：
python -m Agent.knowledge_base.multimodal.cli run --source <path> --allow-remote-data --outbound-manifest .\tmp\r2-review-manifest.json --max-images 12 --timeout-seconds 600
python -m Agent.knowledge_base.multimodal.cli run --source <path> --allow-remote-data --outbound-manifest <approved-manifest.json> --reuse-local-checkpoints-from <index-version>
python -m Agent.knowledge_base.multimodal.cli evaluate --index-version <version>
python -m Agent.knowledge_base.multimodal.cli publish --index-version <version>
python -m Agent.knowledge_base.multimodal.cli omnidocbench-audit --root Agent/knowledge_base/multimodal_benchmarks/omnidocbench
python -m Agent.knowledge_base.multimodal.omnidocbench_export --root Agent/knowledge_base/multimodal_benchmarks/omnidocbench --output-dir Agent/knowledge_base/multimodal_benchmarks/omnidocbench/official_export
python -m Agent.knowledge_base.multimodal.cli omnidocbench-export-official --root Agent/knowledge_base/multimodal_benchmarks/omnidocbench --selection-manifest Agent/knowledge_base/multimodal_benchmarks/omnidocbench/production_100/production_100_manifest.json --output-dir Agent/knowledge_base/multimodal_benchmarks/omnidocbench/production_100/official_export_docling
```

OmniDocBench 本地固定子集只用于研究验证，当前覆盖 6 页代表样本；生产抽样的 100 页由 `production_100_manifest.json` 固定版本、页面哈希与标注属性。`omnidocbench_export` 可生成官方 end-to-end 所需的 GT JSON、同名页面 Markdown 和哈希 manifest；传入 `--selection-manifest` 时按生产清单导出。100 页 Docling Markdown 已在官方 Docker 运行时完成 end-to-end 评测（文本 Edit Distance、表格 TEDS、公式 CDM、阅读顺序）；该证据只衡量解析器，不证明知识库索引已通过发布门禁。布局 mAP 尚未运行。当前生产 active 索引已发布为 `mm_74b5aef2f5e7322b5a79`；固定 OmniDocBench 子集始终使用隔离索引，不能作为生产知识源发布。完整开发依赖通过 `requirements.txt` 引入 `requirements-multimodal.txt`；基础生产镜像仍不安装多模态解析与测试依赖。详细开发记录见 `README/开发日志.md`。

### 后处理
*对因果图进行后处理，包括环路检测、边合理性评估等，提高因果结构的可解释性与可靠性*

- **环路检测与修正**：检查学习得到的因果图中是否存在违背 DAG（有向无环图）假设的环路；若发现异常，则调用 LLM 辅助判断合理的断边方案，给出修正建议。
- **边评估与置信度分析**：对每一条因果边进行强度或置信度评估，结合数据统计特征和领域常识，对明显不合理的边进行标记与修正建议。
- **结构约束与业务先验融合**：在后处理阶段支持引入业务先验（如「变量 A 不可能被 B 因果影响」），从而得到更符合领域知识的因果图。

### 报告生成
*根据后处理结果生成面向业务方与研究者的专业报告，并配套交互式可视化*

- **自动生成结构化报告**：围绕「分析背景 → 数据概况 → 方法说明 → 因果发现 → 结论与建议 → 局限性」等章节自动撰写自然语言报告。
- **交互式因果图谱**：基于 vis-network 等前端组件生成可交互的因果图，支持节点拖拽、缩放、查看变量说明、点击追问等操作。

### 隔离评测摄取状态恢复

摄取状态持久化在 tmp/rag_eval_isolated_runs/<ingestion_run_id>/run.json，staged index、图片、Chroma 和 manifest 保存在同一运行目录；页级 checkpoint 使用该 index 下的 checkpoints.sqlite3，便于失败后按页复用。GET /api/rag_eval/isolated/ingestion-runs 会枚举这些状态，页面在 localStorage 丢失、首次请求失败或点击顶部刷新后，都会尝试恢复最近的运行中或 staged 状态。隔离评测长任务的队列状态在 MySQL `rag_eval_jobs`，具体产物仍在各自的 `tmp/rag_eval_isolated_runs/<run_id>/`；运行目录和上传来源目录已加入 Git 忽略，不应提交到仓库。worker 重启后继续领取尚未开始的 queued 任务；已经失联的 running 任务按 heartbeat 超时失败收敛，不自动重放可能产生外部调用的工作。

## 快速开始 | Quick Start
### Docker部署
当前项目已经提供了完整的多阶段 `Dockerfile`，会先用 Node 24 构建管理员 Vue，再生成仅包含 Python 运行时与静态产物的应用镜像；暂未在公网镜像仓库发布官方镜像。
如果你已安装 Docker，可以在本地根据下面的步骤自行构建并运行镜像。


1. 安装docker并且gitclone项目
```bash
git clone https://github.com/Heyflyingpig/CausalAgent
```

2. 创建.env文件
```bash
cp .env.example .env
# Flask 应用密钥（用于会话加密等）
SECRET_KEY=

# API 基础URL（OpenAI官方或第三方兼容接口）
BASE_URL=
MODEL=
# 可选：第三方 OpenAI 兼容接口通常使用 json_mode。
LLM_STRUCTURED_OUTPUT_METHOD=json_mode

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


# LangSmith API 密钥和项目名称（不强制，兼容原有 LANGCHAIN_* 配置）
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=

#可选rag嵌入模型配置
MEDICAL_EMBEDDING_API_KEY=
MEDICAL_EMBEDDING_BASE_URL=
MEDICAL_EMBEDDING_MODEL=
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
> **知识库仍然在构建，所以知识库查询功能暂不可用**

#### 数据库生产化配置

主从开发：

如果你已经启动过 `mysql-primary` 或 `mysql-replica`，修复后要使用新的空 volume 重建；否则 `/docker-entrypoint-initdb.d` 初始化脚本不会重新执行。

主从模式下数据库账号按职责拆分：

- 写账号：`MYSQL_WRITE_USER` / `MYSQL_WRITE_PASSWORD`，用于应用写主库、Alembic 迁移和启动就绪检查；缺失时兼容回退到 `MYSQL_USER` / `MYSQL_PASSWORD`。
- 读账号：`MYSQL_READ_USER` / `MYSQL_READ_PASSWORD`，用于 `get_read_connection()` 的主库强一致读和从库弱一致读；除业务库 `SELECT` 外，仅额外授予 `performance_schema.events_statements_summary_by_digest` 的表级 `SELECT`，供高负载 SQL digest 摘要使用；缺失时兼容回退到 `MYSQL_USER` / `MYSQL_PASSWORD`。
- 复制状态检查账号：`MYSQL_REPLICA_STATUS_USER` / `MYSQL_REPLICA_STATUS_PASSWORD`，只用于读取 `SHOW REPLICA STATUS`；缺失或不可用时，`eventual` 读安全回退主库读连接。
- 复制通道账号：`MYSQL_REPLICATION_USER` / `MYSQL_REPLICATION_PASSWORD`，只用于 MySQL 主从复制链路，不参与应用业务查询。


#### 管理员后台

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

任务详情默认显示 MySQL 节点/任务事件，并可通过单视图选择器切换到 PostgreSQL checkpoint 状态。新
checkpoint 通过 `metadata.job_id` 精确关联任务；迁移前记录缺少该字段时只提示
无法可靠归属，不按时间猜测。checkpoint API 只返回安全摘要，不读取状态正文、
blob 或 pending writes。数据库 quick/deep 审计同时覆盖 PostgreSQL checkpoint
连接、官方 schema/setup 版本、估算统计和有界跨库关系样本。

更深入的数据库治理、读写一致性和恢复规则见 [`setting/database_governance.md`](setting/database_governance.md)。

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

**目前已不支持windows部署**

## 贡献
欢迎提交 Issue 和 Pull Request！

1. Fork 本项目

2. 从 `develop` 新建工作分支，例如 `feat(rag)/cache`

3. 提交信息与 Pull Request 标题使用 `keyword(function):description` 格式

   支持的 keyword 包括 `feat`、`fix`、`docs`、`refactor`、`test`、`chore`、`ci`、`build`、`perf` 和 `revert`，例如 `fix(chat):修复会话删除异常`。

4. 向 `develop` 新建 Pull Request；只有 `develop` 可以向 `main` 发起合并请求

5. 等待 `Python syntax`、`Light tests` 和 `Pull request policy` 检查通过后再合并

新建 Issue 时请使用仓库提供的 [`Issue Form`](.github/ISSUE_TEMPLATE/issue.yml)，按模板填写背景、问题描述、预期结果、复现步骤、验收标准和环境信息。除附件外的字段为 GitHub 原生必填项，但不限制填写内容；普通贡献者不能选择空白 Issue。

## Star 趋势

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
├── CausalAgent.py          # Flask 后端入口
├── Run_causal.py           # 桌面端启动入口（pywebview）
├── requirements.txt        # 完整依赖
├── requirements-base.txt   # 基础依赖（docker/生产使用）
├── requirements-test.txt   # Docker 单元测试依赖
├── Dockerfile
├── docker-compose.yml         # MySQL 主从 + PostgreSQL checkpoint 开发拓扑
├── docker-compose.prod.yml
├── docker-compose.staging.yml # 隔离预发主从 + checkpoint + gateway 拓扑
├── docker-compose.replica.yml # 旧路径兼容副本，不作为默认开发入口
├── docker-compose.test.yml # 按需创建的一次性单元测试环境
├── .github/                 # GitHub Actions 与 Issue 模板
│   ├── workflows/           # GitHub Actions 工作流
│   └── ISSUE_TEMPLATE/      # Issue Form 模板
├── docker-compose.admin-e2e.yml # 3.1/3.2 独立主从 + PostgreSQL 验收覆盖
├── README.md               # 项目说明
├── README/                 # README 图片与更新日志
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
│   ├── admin/              # 管理 API、审计服务与受保护 Vue 入口
│   ├── agent/              # 分析任务 API、队列服务与独立 worker
│   │   ├── routes.py       # Web 进程创建任务与订阅 SSE
│   │   ├── job_service.py  # Web、monitor、worker 共享的任务持久化服务
│   │   ├── core.py         # 不持有运行时状态的兼容导入门面
│   │   └── worker/         # python -m app.agent.worker 包入口
│   │       ├── bootstrap.py        # 启动检查与 slot 编排
│   │       ├── runtime.py          # 显式进程/slot runtime
│   │       ├── execution.py        # 单 job 执行与 heartbeat
│   │       ├── event_writer.py     # 顺序事件持久化
│   │       ├── graph_runner.py     # LangGraph 流式执行
│   │       ├── event_adapter.py    # 内部流到公开事件协议
│   │       └── result_presenter.py # 最终结果展示结构
│   ├── chat/               # 聊天 & 会话相关路由与服务
│   ├── files/              # 文件上传/管理相关路由
│   ├── rag_eval/           # RAG 评测后端与 Vue 前端源码
│   │   └── frontend/       # Vue 3 + Vite + TypeScript 工程
│   └── static/             # 前端静态资源
│       ├── chat.html       # 主聊天界面
│       ├── rag_eval_app/   # RAG 评测生产构建产物
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
│   │   ├── build_knowledge.py # 知识库构建入口，支持 default / medical profile

│   │   ├── rag_runtime.py      # 默认多模态 RAG 重资源初始化与生命周期
│   │   ├── rag_service.py      # 默认 RAG 查询编排与降级服务
│   │   ├── sparse_retriever.py # 默认 BM25s 稀疏索引
│   │   ├── query_rag.py    # 默认 dense/BM25s/rerank/answer 实现
│   │   ├── multimodal/     # 默认资料检查、摄取、索引、发布与检索模块
│   │   ├── db/             # 旧医疗兼容向量库存储

│   │   ├── models/         # 本地嵌入模型，default profile 使用 bge-small-zh-v1.5
│   │   └── rag/            # RAG 测评框架、数据集操作、报告和外部医疗数据
│   │       ├── rag_config.py
│   │       ├── data/
│   │       │   └── external/pubmedqa/
│   │       │       └── processed/
│   │       ├── operation_datasets/
│   │       ├── rag_eval/
│   │       ├── tools/
│   │       └── output/
│   └── tool_node/          # MCP 工具节点封装（task、rag 调用等）
├── Database/               # 数据库初始化与迁移逻辑
│   ├── database_init.py    # MySQL 数据库存在性与连接引导
│   ├── bootstrap.py        # MySQL/Alembic/PostgreSQL 统一初始化入口
│   ├── audit_before_db_upgrade.py # 数据库生产化升级前审计
│   ├── inspection.py       # 管理员看板统一只读检查服务
│   ├── deep_audit.py       # 手动 deep 数据库事实审计
│   ├── lifecycle_repair.py # 孤立关系 dry-run/人工确认修复 CLI
│   ├── checkpoint_setup.py # PostgreSQL LangGraph schema 一次性 setup
│   ├── checkpoint_inspection.py # 管理员 PostgreSQL checkpoint 只读与审计
│   ├── checkpoint_cleanup_worker.py # 跨库 checkpoint cleanup outbox worker
│   ├── monitoring.py       # 共享快照存取、调度与兼容接口
│   ├── monitor_settings.py # 在线配置解析、缓存、校验与事务写入
│   ├── monitor_worker.py   # 数据库看板分层采集进程
│   ├── agent_connect.py    # Langgraph checkpoint 相关数据库支持
│   ├── mysql/              # MySQL 主从配置与初始化脚本
│   └── migrations/         # Alembic 迁移脚本
├── config/                 # 全局配置
│   └── settings.py
├── setting/                # 用户可见文档
│   ├── manual.md           # 用户手册
│   └── Userprivacy.md      # 用户隐私协议
├── tests/                  # 后端测试：unit、integration、e2e
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── openspec/               # 项目规范与变更说明（内部开发用）
```
