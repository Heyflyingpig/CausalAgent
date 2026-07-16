---
status: accepted
date: 2026-07-16
decision-makers:
  - CausalChat maintainers
---

# ADR-0001：在检索前文本化多模态知识

## 背景

CausalChat 当前接收文字查询，使用文本 embedding、Chroma、文字证据生成和既有 RAG 评测链路。CSV 作为用户因果分析输入的现有行为不属于本决策；本决策处理的是由开发者维护、进入共享知识库的资料。

首版资料不敏感、不包含医疗隐私，也不开放普通用户上传。部署机器能力不一致，因此本地 CPU 必须可用，GPU 只能是可选加速。PDF、图片和表格中的内容可能依赖版面、单元格、公式、图表或有向因果关系，单纯抽取连续文本会丢失证据定位和结构语义。

当前知识库还区分 `default` 因果语料和 `medical` PubMedQA 语料。文件模态不能成为新的 profile，也不能削弱两套 benchmark 与索引的隔离。

## 决策

1. PDF、常见图片、TXT、Markdown、CSV 和 XLSX 在摄取阶段统一转换为可追溯的 `KnowledgeFragment`，再生成纯文本 chunk 交给现有 embedding 与 Chroma 检索链路。首版不写入原生图片向量。
2. 每个片段必须保留逻辑资料 ID、内容版本、提取器指纹、内容类型和可验证定位。表格保留行列语义；因果图保留节点、有向边和条件。方向不明确的因果边进入人工复核，不产生可发布的猜测片段。
3. 维护能力实现为深模块：`KnowledgeBaseMaintenance.execute(MaintenanceCommand) -> MaintenanceResult`。首版 CLI 与第二版页面的 HTTP adapter 都调用该接口。解析器、OCR、视觉模型、embedding 和 Chroma 是内部 adapter，不得把第三方对象泄漏给调用方。
4. TXT、Markdown、CSV、XLSX 使用确定性解析；PDF 和图片的默认解析/OCR 路径由 P01S 使用同一 fixture 实测 Docling、PaddleOCR PP-StructureV3 和 PyMuPDF 后确定。最终只允许一个默认生产路径和一个触发条件明确的 fallback。
5. 本地 OCR 是基础路径。CPU 是支持基线，GPU 可用于加速或可选本地视觉模型，但不得改变公共数据契约。远程视觉描述默认关闭，启用时必须显式允许数据外发并设置图片调用次数硬上限。
6. 首版只提供开发者/维护者 CLI，不增加管理页面或数据库表。第二版接入现有 `/rag_eval` 页面，页面只作为同一深模块的 HTTP adapter；长任务由独立 worker 与持久化 run/event 模型执行。页面和相关接口必须登录，摄取、评测、发布和回滚还必须通过维护者授权；索引版本发布与检索配置发布是两个独立动作。
7. 发布单元是 profile 权威 source root 的完整、不可变快照。每个 `index_version` 使用独立 persist directory/collection，构建后评测，评测通过才通过原子注册表切换活动版本。首版不向活动索引 append/upsert，不自动删除任何旧版本或现有索引。
8. 活动注册表按 profile 维护，版本路径相对 `RAG_INDEX_VERSION_ROOT` 保存，确保 Windows CLI、Docker Web 和 worker 解释一致。临时 smoke 覆盖必须成对提供 `RAG_VECTOR_DB_DIR` 和 `RAG_COLLECTION_NAME`。
9. 发布报告必须绑定确切的 index version、benchmark、检索配置、语料指纹和 embedding 指纹。`default` 与 `medical`/PubMedQA 的不匹配防护不可绕过；collection 名称本身不能作为语料一致性的证明。

## 范围与非目标

首版支持 TXT、Markdown、CSV、XLSX、PDF、PNG、JPG/JPEG、WebP、TIF/TIFF。DOC/DOCX、PPT/PPTX、旧 XLS、SVG、音视频、压缩包和加密 PDF 不在范围内。

下列能力不是首版目标：

- 图片查询或原生图文联合向量检索；
- 普通用户上传和管理页面；
- 对活动 collection 的增量 append/upsert；
- 在未验证供应商价格契约时承诺精确货币预算；
- 自动删除旧索引或覆盖现有 `Agent/knowledge_base/db/`。

## 后果

正面后果：

- 复用现有文本 embedding、Chroma、证据生成和 RAG 评测，首版改动范围较小。
- 解析工具可以替换，CLI 和第二版页面不需要理解第三方对象或各自实现摄取流程。
- 完整快照、原子活动指针和绑定报告使发布、回滚及复现具有明确语义。
- 来源定位和结构片段允许检索结果回指原页、表格区域或因果关系。

负面后果：

- 图片转文本会损失部分视觉信息；如果未来出现高价值图片查询，需要新 ADR 评估原生多模态索引。
- 完整快照比增量写入占用更多构建时间和磁盘空间，旧版本清理需要单独的、显式批准的生命周期策略。
- OCR、表格、公式和因果图质量依赖 fixture 与人工 gold；P01S 完成前不能承诺最终解析器或吞吐指标。
- 无法可靠判断的因果边需要人工复核，会降低全自动摄取率，但避免把猜测关系发布为事实。

## 被否决的替代方案

- **首版直接使用原生图片向量**：查询、rerank、证据和评测仍是文字链路，新增复杂度不能由当前需求证明。
- **让一个“全能解析框架”成为公共接口**：会把第三方数据结构扩散到 CLI、查询和页面，增加替换成本。
- **所有 PDF 强制 OCR**：会使数字 PDF 变慢，并可能降低已有文本质量。
- **直接 append/upsert 当前 collection**：不能完整表达源删除、半成品发布、embedding 变化和可靠回滚。
- **页面调用 CLI 子进程或复制摄取逻辑**：会形成第二套行为和脆弱的进程协议。
- **复用页面进程内线程或 `analysis_jobs` 表执行第二版摄取**：进程内状态无法可靠恢复，而 `analysis_jobs` 绑定现有 user/session 业务语义；第二版应复用任务模式而不是复用该业务表。

## 实施约束

- 默认版本根目录为 `Agent/knowledge_base/db/versions/`，活动注册表默认为 `Agent/knowledge_base/db/active_indexes.json`；注册表内不得保存宿主机绝对路径。
- `source_id` 由 profile 与规范化相对路径或显式 manifest ID 产生，跨内容更新保持稳定。路径统一斜杠和 Unicode NFC，保留大小写，并拒绝仅大小写不同的冲突；`source_version_id` 绑定内容 SHA-256。
- 临时 `--source` 覆盖默认不可发布；只有 profile 的完整权威 source root 快照可以进入发布流程。
- 页码及行列范围使用从 1 开始的闭区间；bbox 使用左上角原点的 `[0,1]` 归一化坐标并保留原始尺寸。
- embedding 指纹包括 provider、模型、版本、向量维度和归一化方式，不包括 CPU/GPU 设备。
- 实现、指标和任务拆分以[多模态知识摄取开发规划](../../Agent/knowledge_base/rag/多模态知识摄取开发规划.md)为准；候选工具依据见[多模态知识摄取技术调研](../../Agent/knowledge_base/rag/多模态知识摄取技术调研.md)。
