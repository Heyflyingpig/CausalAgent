# RAG 测评框架开发记录

## 现状概览7.11

当前 RAG 测评功能已经形成一个可用的开发者调参工作台，入口是 `http://127.0.0.1:5001/rag_eval`。现阶段主要面向开发者，用来跑通 RAG 测评流程、调整检索和 Ragas 相关参数、查看指标变化、分析坏例，并把验证过的检索配置发布到正式 RAG 调用链路。

已具备能力：

- 测评流程已跑通，默认 pipeline 包含 `validate_datasets -> retrieval_eval -> ragas_eval -> trace_export -> summary`。
- `claim_eval` 当前已从默认链路和前端调参入口屏蔽，必要时只能作为单独人工复核工具使用。
- 支持在网页上调整 retrieval、Ragas、pipeline 阈值等运行时参数。
- 如果只在网页保存配置，这些配置是当前后端进程内生效，重启后会回到代码配置默认值。
- 支持把当前评测中的检索配置发布到正式 RAG 配置文件 `Agent/knowledge_base/rag/runtime/production_rag_config.json`，正式 RAG 查询会读取该文件。
- 需要注意：发布到正式 RAG 的主要是检索配置，不是把所有 Ragas 参数、评测阈值、prompt、embedding 模型都同步成正式配置。
- 测评报告会写入 `Agent/knowledge_base/rag/output/`，包括机器可读 JSON 和 Markdown 报告。
- 每次 pipeline run 会生成独立历史目录，便于回看详情、报告、配置快照和坏例链路。
- 前端支持历史记录分页、删除历史 pipeline、手动选择 baseline 与本次 candidate 做对比。
- 首页能看到 benchmark、向量库、embedding 模型、回答模型、judge 模型等运行状态，方便发现模型/API/本地 embedding 配置缺失。
- 测评完成后页面会给出提示，即使用户切到其他 tab，也可以回到报告或坏例分析。
- 坏例分析目前以 retrieval/Ragas trace 为主，能辅助定位“召回不足、上下文覆盖不足、生成忠实性不足”等问题。

当前优点：

- 已经不只是跑脚本，而是有了面向开发者的网页工作台。
- 调参链路和正式 RAG 配置之间已经建立了基础闭环：评测配置可以发布到正式 RAG 的检索配置文件。
- 有 run 历史、配置快照、报告和坏例 trace，便于复盘不同参数组合的效果。
- 参数有说明、范围提示、保存校验和建议范围 warning，对开发者更友好。
- baseline/candidate 对比比“只看最近两次”更合理，适合做调参实验对照。

当前不足：

- 诊断能力仍处于初级阶段，主要是规则驱动，不是深度自动调参，也没有调用 LLM 动态分析每轮结果。
- 当前发布闭环主要覆盖正式 RAG 的检索配置，生成 prompt、回答模型、embedding provider、知识库构建参数等还没有完整纳入同一个发布体系。
- 网页保存的评测配置不是持久化配置，重启后会丢失，只有发布到正式 RAG 的检索配置会落文件。
- 历史记录主要依赖本地 output 文件目录，还不是数据库化的实验管理系统。
- 测评稳定性依赖外部 judge API、embedding 配置、向量库和 active dataset；Ragas 评测可能受 API 限流、超时、模型波动影响。
- 数据集/知识库/模型虽然已经开始做状态展示，但“热插拔式数据集和模型管理”还没有完全产品化。
- 当前更适合开发者做小样本 smoke、100 条评估和参数对比，不适合直接当作严格的生产级自动评估平台。

总体定位：当前 RAG 测评系统已经实现“可运行、可调参、可对比、可发布检索配置、可复盘报告”的基础闭环；但它还不是完整自动调优系统，诊断、实验管理、配置持久化和多数据集热插拔仍是后续重点。

## 当前结论6.3

当前 active benchmark 是 PubMedQA labeled，processed corpus/eval 均为 1000 条，测试集使用通用 `benchmark_v2` schema。旧 RAGCare 数据不再进入主评测链路，旧向量库备份在 `tmp/RAGCare`。

当前运行时向量库目录仍是 `Agent/knowledge_base/db`。医疗查询与 medical 构建默认 collection 为 `pubmedqa_clean`；`causal_agent_default` 也指向 PubMedQA，但存在重复 chunk，不应作为后续医疗评测的优先口径。

默认 pipeline 现在是：

```text
validate_datasets -> retrieval_eval -> ragas_eval -> trace_export -> summary
```

`claim_eval` 已从默认 pipeline 和前端工作台调参入口屏蔽；坏例链路只统计 retrieval/Ragas 相关问题。人工需要断言级复核时，直接运行 `claim_eval.py`。

当前主要目标不是继续改 prompt，而是观察 Ragas 并行配置的效果：`pubmedqa_eval100` 已从单 worker 调整为 `ragas_max_workers=4`、`ragas_max_retries=3`、`ragas_max_wait=20`。下一次 100 条四指标运行要重点记录 Ragas judge 阶段耗时是否从单 worker 的约 13303 秒明显下降，以及是否出现 API 限流、timeout 或 NaN 增加。

## 数据与路径

| 项目 | 路径 | 说明 |
| --- | --- | --- |
| active corpus | `data/external/pubmedqa/processed/pubmedqa_corpus_docs.jsonl` | PubMedQA evidence corpus |
| active eval dataset | `data/external/pubmedqa/processed/pubmedqa_eval_dataset.json` | PubMedQA `benchmark_v2` 测试集 |
| prepare script | `operation_datasets/prepare_pubmedqa.py` | 生成 PubMedQA corpus/eval |
| runtime vector DB | `../db` | 默认运行时 Chroma 持久化目录，当前已是 PubMedQA |
| preferred medical collection | `pubmedqa_clean` | medical 查询和构建默认 collection |
| old DB backup | `../../../tmp/RAGCare` | 旧 RAGCare 向量库备份，不进入 Git |
| temporary PubMedQA DB | `../../../tmp/pubmedqa_db` | 历史临时构建目录，不是当前主评测入口 |

## 当前配置

### Pipeline

| 字段 | 当前值 |
| --- | --- |
| 默认 steps | `validate_datasets, retrieval_eval, ragas_eval, trace_export, summary` |
| 默认 claim eval | 不运行 |
| claim eval 启用方式 | 已从 pipeline/工作台屏蔽；人工复核时直接运行 `claim_eval.py` |
| latest 结果来源保护 | summary 中 `metric_sources.*.used=true` 的产物才会被 latest results 读取，避免旧 claim 输出混入当前 run |
| 状态原因 | 新 run 的 summary 会包含 `status_reason`，区分 `step_failed`、`threshold_failed`、`threshold_missing` |

### Ragas profiles

| profile | 样本数 | 有效上下文配置 | worker | retries | wait | 用途 |
| --- | ---: | --- | ---: | ---: | ---: | --- |
| `pubmedqa_pipeline` | 30，可动态覆盖 | 继承 base：`ctx6 / context_chars1600 / response_chars1100` | 2 | 3 | 20 | pipeline 调参与快速检查 |
| `pubmedqa_eval100` | 100 | 继承 base：`ctx6 / context_chars1600 / response_chars1100` | 4 | 3 | 20 | 100 条四指标正式评测 |

说明：`max_contexts`、`max_context_chars`、`max_response_chars` 定义在 `RAGAS_BASE_CONFIG`，profile 未覆盖时继承 base 值。

## 当前 latest 运行结果

当前 latest run 是 `2026-07-09_094735_hello_first_100`。这是并行调整前的单 worker 100 条结果，可作为观察并行效果的对照基线。

| 项目 | 值 |
| --- | ---: |
| pipeline status | `fail` |
| 失败原因 | 阈值失败，不是 step 异常 |
| validate_datasets | pass |
| retrieval_eval | pass |
| ragas_eval | pass |
| trace_export | pass |
| retrieval_recall_at_k | 0.9900 |
| retrieval_mrr | 0.9783 |
| retrieval_hit_rate | 0.9900 |
| `retrieval_hit_rate_min` 阈值 | 1.0000 |
| ragas_faithfulness | 0.8372 |
| ragas_answer_relevancy | 0.8063 |
| ragas_context_utilization | 0.8381 |
| ragas_context_recall | 0.5917 |
| bad_case_trace_count | 46 |
| Ragas build_seconds | 2747.102 |
| Ragas eval_seconds | 13302.819 |
| Ragas step seconds | 18686.111 |
| ragas_max_workers | 1 |

这个结果说明：100 条四指标链路能完整跑通，Ragas judge 没有 NaN，但单 worker 代价过高。下一轮并行观察应保持同一 100 条、同一四指标和同一 prompt，重点比较 `eval_seconds`、有效分数数、NaN 数和 API 错误。

## 当前验证结果

`validate_all_datasets()`：

| 项目 | 结果 |
| --- | ---: |
| status | pass |
| errors | 0 |
| warnings | 0 |
| corpus docs | 1000 |
| eval samples | 1000 |

默认运行时向量库：

| 项目 | 结果 |
| --- | ---: |
| persist directory | `Agent/knowledge_base/db` |
| collection | `causal_agent_default` |
| vector_count | 5814 |
| dataset | `pubmedqa` |
| doc_id prefix | `pubmedqa` |

## 现状解释

旧 20 条 smoke 记录仍保留在后面的调参历史中，但不再代表当前 latest。当前 latest 是 100 条 Ragas 四指标运行。

`context_recall` 仍偏低，但当前主要瓶颈已经不是“能否跑通”，而是“Ragas judge 太慢”。并行调整前，100 条四指标中 prepared dataset 构建约 2747 秒，Ragas judge 约 13303 秒；优先观察 `ragas_max_workers=4` 后 judge 阶段耗时是否下降。

如果并行后出现明显限流或失败，先把 `ragas_max_workers` 从 4 降到 2；如果 4 worker 稳定，再考虑是否继续优化 prepared dataset 构建阶段的 retrieval + answer 串行耗时。

## 当前输出

| 文件 | 说明 |
| --- | --- |
| `output/machine/ragas_eval_result.json` | 最新 Ragas 结果；当前 latest 为 100 条单 worker 对照基线 |
| `output/reports/ragas_eval_report.md` | 最新 Ragas Markdown 报告 |
| `output/machine/ragas_low_score_cases.json` | Ragas 低分样本 |
| `output/machine/ragas_cross_metric_bad_cases.json` | retrieval/Ragas 跨指标坏例 |
| `output/machine/claim_eval_result.json` | 旧 claim eval 结果可能不存在或不是当前 run 产物；latest results 不再把 `used=false` 的旧 claim 当作当前指标 |
| `output/reports/claim_eval_report.md` | 仅人工启用 claim eval 后才会生成当前 run 报告 |
| `output/machine/claim_eval_bad_cases.json` | 仅人工启用 claim eval 后才会生成当前 run 坏例 |
| `output/machine/trace.jsonl` | 逐题 trace |
| `output/machine/trace_index.json` | trace 汇总索引 |
| `output/reports/trace_report.md` | trace Markdown 报告 |

## 后续建议

1. 先跑一次同样 100 条四指标，观察 `ragas_max_workers=4` 的实际加速和稳定性。
2. 记录 `eval_seconds`、`metric_validity`、NaN 数、API 错误、timeout 和 retry 情况。
3. 若出现限流或失败，降到 `ragas_max_workers=2` 复测。
4. 若并行稳定但总耗时仍高，再考虑并行化 prepared dataset 构建阶段。

## 调参记录

以后每次 RAG 调参都必须在本节追加一条记录，至少包含：变更日期、目标指标、参数变更、运行样本、是否复用缓存、Ragas 结果、claim/trace 结果、主要 bad case 结论和下一步判断。不要只依赖 latest JSON 输出，因为 latest 会被后续运行覆盖。

### 2026-07-10 PubMedQA eval100 Ragas 并行调参准备

目标：降低 100 条 PubMedQA 四指标 Ragas judge 的运行时间，先不改变指标口径、样本集、prompt 和上下文设置。

问题判断：

- 最新 100 条 run `2026-07-09_094735_hello_first_100` 的 Ragas step 耗时为 18686.111 秒。
- 其中 prepared dataset 构建耗时 2747.102 秒，Ragas judge 耗时 13302.819 秒。
- 该 run 使用 `ragas_max_workers=1`，Ragas 0.4.3 会把样本和指标拆成异步评分任务；单 worker 使约 100 x 4 个指标任务基本串行执行。
- 这次结果四个 Ragas 指标均为 100/100 valid，说明慢主要不是失败重试导致，而是单 worker 评测成本过高。

参数变更：

| 参数 | 调整前 | 调整后 | 说明 |
| --- | ---: | ---: | --- |
| `pubmedqa_eval100.ragas_max_workers` | 1 | 4 | 保守开启 Ragas judge 并发。 |
| `pubmedqa_eval100.ragas_max_retries` | Ragas 默认 10 | 3 | 避免 API 限流或偶发失败时长时间重试。 |
| `pubmedqa_eval100.ragas_max_wait` | Ragas 默认 60 | 20 | 限制指数退避最长等待。 |
| `pubmedqa_pipeline.ragas_max_workers` | 1 | 2 | pipeline 小样本也允许轻量并发。 |

代码同步：

- `ragas_eval.py` 已把 `ragas_max_workers`、`ragas_max_retries`、`ragas_max_wait` 传入 Ragas `RunConfig`。
- Ragas 分数缓存签名已包含 worker/retry/wait，避免不同并发配置误复用旧 score cache。
- 前端配置页和 Ragas Markdown 报告已暴露这些参数。
- `get_latest_results()` 已修复旧 claim 产物混入当前 latest 的问题；只读取 `summary.metric_sources.*.used=true` 的来源。
- 新 run summary 会写入 `status_reason`，用于区分 `threshold_failed` 和真实 step 异常。

验证：

```powershell
D:\Anaconda\envs\CA-py310\python.exe -m py_compile Agent\knowledge_base\rag\rag_config.py Agent\knowledge_base\rag\rag_eval\ragas_eval.py Agent\knowledge_base\rag\rag_eval\run_rag_eval.py Agent\knowledge_base\rag\tools\report_utils.py app\rag_eval\service.py
node --check app\static\js\rag_eval.js
D:\Anaconda\envs\CA-py310\python.exe -m unittest tests.test_rag_pipeline_current_outputs
```

结果：Python 编译、JS 语法检查和 12 个 RAG pipeline 单测均通过。

下一步观察：

- 跑同样 100 条 `pubmedqa_eval100` 四指标，不启用 claim eval。
- 对比并行前基线：`build_seconds=2747.102`、`eval_seconds=13302.819`、Ragas step `seconds=18686.111`。
- 成功标准：`eval_seconds` 明显下降，四个指标仍 100/100 valid，NaN 不增加，未出现大量限流或 timeout。
- 如果出现 429、timeout 或 NaN 增加，先降到 `ragas_max_workers=2` 再复测。

### 2026-06-03 PubMedQA smoke20 evidence length 调参

目标：分析 20 条 bad case 后，优先提升 `context_recall`，同时确认问题是否来自 retrieval miss。

bad case 结论：

- 20 条中 gold doc 基本都进入 final evidence，很多样本 gold doc rank 为 1；当前低 `context_recall` 主要不是检索召回问题。
- 旧 prepared dataset 中 Ragas contexts 多数只有约 420 字符。原因是 `query_rag.py` 的 `RagRetrievalConfig.max_evidence_chars` 默认值为 420，早于 Ragas 的 `max_context_chars=1200` 生效。
- PubMedQA `reference_answer` 较长，420 字符 evidence 容易只覆盖局部 rationale，导致 Ragas `context_recall` 偏低。

参数变更：

| 参数 | 调整前 | 调整后 | 说明 |
| --- | ---: | ---: | --- |
| `RAGAS_ACTIVE_PROFILE` | `pubmedqa_smoke20` | `pubmedqa_smoke20` | 保持 20 条 smoke，不扩大样本。 |
| `limit` | 20 | 20 | 保持同一组样本。 |
| `max_contexts` | 5 | 5 | 不先扩大 context 数，先验证 evidence 截断影响。 |
| `max_context_chars` | 1200 | 1200 | 保持 Ragas 单 context 上限。 |
| `retrieval_config.max_evidence_chars` | 420 | 1200 | 只覆盖 Ragas 评测链路，不改业务默认 RAG 证据长度。 |
| `retrieval_profile` | `active_current` | `active_current` | 检索 profile 不变。 |
| `final_top_k` | 12 | 12 | final evidence 数不变。 |
| `judge_profile` | `pubmedqa_smoke20_ctx5_1200` | `pubmedqa_smoke20_ctx5_1200_evidence1200` | 进入缓存签名，避免误用旧分数。 |
| `ANSWER_BUILD_VERSION` | `answer_fallback_v2` | `answer_fallback_v3` | 让 prepared dataset 缓存感知 answer/evidence 输入变化。 |
| `reuse_prepared_dataset` | True | True | 签名不一致时自动重建，本次实际未复用。 |
| `reuse_score_cache` | False | False | 本次重新 judge。 |

Ragas 结果：

| 指标 | 当前开发记录旧基线 | 现存快照旧基线 | 本次结果 |
| --- | ---: | ---: | ---: |
| `faithfulness` | 0.8015 | 0.7773 | 0.8053 |
| `answer_relevancy` | 0.7740 | 0.7014 | 0.7524 |
| `context_utilization` | 0.8711 | 0.8500 | 0.8169 |
| `context_recall` | 0.4792 | 0.5750 | 0.5917 |

运行细节：

| 项目 | 结果 |
| --- | ---: |
| `sample_count` | 20 |
| `loaded_from_cache` | False |
| `loaded_score_from_cache` | False |
| `build_seconds` | 194.318 |
| `eval_seconds` | 2252.089 |
| `context_recall valid/nan/total` | 20 / 0 / 20 |
| `faithfulness valid/nan/total` | 19 / 1 / 20 |
| `low_score_case_count` | 16 |
| `cross_metric_bad_case_count` | 9 |

claim eval 结果：

| 指标 | 调整前 | 本次结果 |
| --- | ---: | ---: |
| `claim_coverage` | 0.3000 | 0.3500 |
| `evidence_support_rate` | 0.3500 | 0.4500 |
| `unsupported_answer_claim_count` | 0.1000 | 0.1500 |
| `judge_failed_count` | 0 | 0 |
| `eval_seconds` | 146.921 | 183.149 |

trace export 结果：

| 指标 | 调整前 | 本次结果 |
| --- | ---: | ---: |
| `trace_count` | 20 | 20 |
| `bad_case_trace_count` | 15 | 14 |
| `retrieval_eval_trace_count` | 20 | 20 |
| `ragas_eval_trace_count` | 20 | 20 |
| `claim_eval_trace_count` | 20 | 20 |

本次判断：

- `context_recall` 相比当前开发记录旧基线从 0.4792 提升到 0.5917；相比现存 `pubmedqa_smoke20_ragas_result.json` 快照从 0.5750 提升到 0.5917。两个口径都应保留，因为 latest/快照文件可能被后续试跑覆盖。
- 仍有 8 条 `context_recall < 0.5`，典型题号为 1、4、6、8、12、13、14、17。
- 第 10 条出现 1 个 `faithfulness` NaN，属于 Ragas judge 输出解析失败，不影响本次 `context_recall` 统计，但后续正式比较应考虑重复评测或缓存失败样本重跑。
- 下一步不优先扩大样本，优先调 answer prompt：要求回答覆盖 PubMedQA long answer rationale 中的研究设计、关键结果、限制条件和最终 yes/no/maybe 结论，而不是只输出短结论。

### 2026-06-03 PubMedQA smoke20 answer prompt 调参准备

目标：在不改变线上业务 RAG 默认回答风格的前提下，让 Ragas prepared dataset 中的 answer 更完整覆盖 PubMedQA `long_answer` rationale。

参数变更：

| 参数 | 调整前 | 调整后 | 说明 |
| --- | --- | --- | --- |
| `query_rag._answer_question` | 固定使用默认 answer prompt | 增加可选 `answer_prompt` 参数 | 默认值为 None，线上业务调用不变。 |
| `query_rag._invoke_answer_llm_fallback` | 固定使用默认 answer prompt | 增加可选 `answer_prompt` 参数 | 保证 structured output 失败后的 fallback 路径也使用同一评测 prompt。 |
| `ragas_eval._build_ragas_eval_row` | 使用默认 answer prompt | 使用 `_build_pubmedqa_eval_answer_prompt()` | 仅影响 Ragas 评测数据构造。 |
| `ANSWER_BUILD_VERSION` | `answer_fallback_v3` | `answer_fallback_v4_pubmedqa_rationale_prompt` | 让 prepared dataset 缓存感知 prompt 变化。 |
| `judge_profile` | `pubmedqa_smoke20_ctx5_1200_evidence1200` | `pubmedqa_smoke20_ctx5_1200_evidence1200_rationale_prompt` | 让输出和分数缓存标记本轮 prompt 调参。 |

评测专用 prompt 要求：

- 只依据检索证据回答，不引入外部医学结论。
- 对 PubMedQA evidence 覆盖 long-answer rationale，而不是只给 yes/no/maybe。
- 尽量包含研究设计或人群、关键数值或组间差异、有效性/安全性/风险方向、限制条件或不确定性。
- 最后给出 yes/no/maybe/uncertain 的直接方向。

当前状态：

- 已完成代码准备和缓存签名更新。
- 尚未重跑 20 条 Ragas；下一次运行 `ragas_eval.py` 会因为 `ANSWER_BUILD_VERSION` 和 `judge_profile` 变化而重建 prepared dataset 并重新 judge。
- 成功标准：优先观察剩余 8 条 `context_recall < 0.5` 是否改善，同时确认 `faithfulness` NaN 是否不再出现或可通过失败样本重跑处理。

### 2026-06-04 PubMedQA smoke20 rationale prompt 实测与修正

目标：验证 `answer_fallback_v4_pubmedqa_rationale_prompt` 是否能通过更完整 answer 改善剩余低 `context_recall` 样本。

Ragas 实测结果：

| 指标 | evidence length 调参结果 | v4 rationale prompt 结果 | 变化 |
| --- | ---: | ---: | ---: |
| `faithfulness` | 0.8053 | 0.7894 | -0.0159 |
| `answer_relevancy` | 0.7524 | 0.7040 | -0.0484 |
| `context_utilization` | 0.8169 | 0.6794 | -0.1375 |
| `context_recall` | 0.5917 | 0.5833 | -0.0084 |

运行细节：

| 项目 | 结果 |
| --- | ---: |
| `sample_count` | 20 |
| `judge_profile` | `pubmedqa_smoke20_ctx5_1200_evidence1200_rationale_prompt` |
| `ANSWER_BUILD_VERSION` | `answer_fallback_v4_pubmedqa_rationale_prompt` |
| `loaded_from_cache` | False |
| `loaded_score_from_cache` | False |
| `build_seconds` | 273.951 |
| `eval_seconds` | 2759.766 |
| `faithfulness valid/nan/total` | 20 / 0 / 20 |
| `context_recall valid/nan/total` | 20 / 0 / 20 |
| `low_score_case_count` | 20 |
| `cross_metric_bad_case_count` | 10 |

问题诊断：

- v4 prompt 没有改善 `context_recall`，因为 Ragas `context_recall` 主要评估 retrieved contexts 对 reference 的覆盖，answer prompt 不是主杠杆。
- v4 prompt 让 answer 显著变长，题号 1、2、5、7、8、12 的 response 长度接近 `max_response_chars=900`，存在截断风险。
- 题号 3、4、16 出现回答生成失败文本，原因是 structured output 不可用后进入 fallback，但 fallback 模型输出 `confidence="moderate"`，旧校验只接受 `high/medium/low`，导致 `RagAnswer` 校验失败。
- 低 `context_recall < 0.5` 仍是题号 4、6、8、10、12、13、14、17，与上轮高度重合。

本次修正参数：

| 参数 | v4 | v5 修正 | 说明 |
| --- | --- | --- | --- |
| `query_rag._invoke_answer_llm_fallback` confidence 映射 | 不接受 `moderate` | `moderate -> medium` | 修复 fallback 假失败。 |
| `ANSWER_BUILD_VERSION` | `answer_fallback_v4_pubmedqa_rationale_prompt` | `answer_fallback_v5_pubmedqa_compact_rationale_prompt` | 让 prepared dataset 感知修正。 |
| `judge_profile` | `pubmedqa_smoke20_ctx5_1200_evidence1200_rationale_prompt` | `pubmedqa_smoke20_ctx5_1200_evidence1200_compact_rationale_prompt` | 区分下一轮结果。 |
| answer prompt 长度约束 | 只要求覆盖 rationale | 3-4 句，180 英文词或 300 中文字符内 | 避免长 answer 被 900 字符截断。 |
| answer prompt confidence 约束 | 未显式限制 | 必须为 `high` / `medium` / `low` | 降低 fallback 结构化校验失败。 |

当前判断：

- 不建议继续放大样本，也不建议先跑 claim；应先用 v5 compact prompt 再跑 20 条 Ragas，比较 generation failed 是否归零、answer 截断是否减少、`context_utilization` 是否恢复。
- 如果 v5 仍不能提升 `context_recall`，下一步应转向 contexts 侧：例如 gold doc 内相邻 chunk 合并、提高 `max_contexts`，或直接按 doc-level evidence 构造 Ragas contexts，而不是继续加长 answer。

### 2026-06-04 PubMedQA smoke20 compact prompt v5 实测

目标：验证 v5 compact rationale prompt 是否修复 v4 的 answer 过长、fallback 假失败和 `context_utilization` 下降问题。

运行前修复：

- `ragas_eval.py` 曾切到 Ragas `metrics.collections`，但当前 `evaluate()` 报错 `All metrics must be initialised metric objects`，与现有 Ragas 0.4.x 运行路径不兼容。
- 已将 `run_ragas_baseline()` 切回此前已验证可跑通的 Ragas 0.4.x legacy metric 对象路径，并清理 `RagasRuntime` / `metrics.collections` 残留代码；保留 v5 prompt 和缓存签名。
- 这次只跑 Ragas，没有跑 claim eval。

Ragas 实测结果：

| 指标 | evidence length 调参结果 | v4 rationale prompt | v5 compact prompt |
| --- | ---: | ---: | ---: |
| `faithfulness` | 0.8053 | 0.7894 | 0.8628 |
| `answer_relevancy` | 0.7524 | 0.7040 | 0.7726 |
| `context_utilization` | 0.8169 | 0.6794 | 0.8503 |
| `context_recall` | 0.5917 | 0.5833 | 0.5667 |

运行细节：

| 项目 | 结果 |
| --- | ---: |
| `sample_count` | 20 |
| `judge_profile` | `pubmedqa_smoke20_ctx5_1200_evidence1200_compact_rationale_prompt` |
| `ANSWER_BUILD_VERSION` | `answer_fallback_v5_pubmedqa_compact_rationale_prompt` |
| `loaded_from_cache` | True |
| `loaded_score_from_cache` | False |
| `build_seconds` | 0.000 |
| `eval_seconds` | 1928.715 |
| `faithfulness valid/nan/total` | 20 / 0 / 20 |
| `context_recall valid/nan/total` | 20 / 0 / 20 |
| `generation_failed` | 0 |
| `answer_len_ge_890` | 0 |
| `low_score_case_count` | 10 |
| `cross_metric_bad_case_count` | 9 |

低 `context_recall < 0.5` 题号：

| 题号 | `context_recall` | 说明 |
| ---: | ---: | --- |
| 4 | 0.3333 | long rationale 覆盖不足。 |
| 6 | 0.0000 | 检索/证据语境与 community setting 结论不匹配。 |
| 8 | 0.3333 | reference 结论与当前 answer/contexts 方向存在冲突。 |
| 12 | 0.0000 | reference 中前瞻研究/治疗策略要点未被 contexts 完整覆盖。 |
| 13 | 0.0000 | reference 认为 markers 不区分 NASH/ASH；当前 answer 倾向可区分，方向冲突。 |
| 14 | 0.3333 | prompt 效果和医生行为变化要点覆盖不足。 |
| 17 | 0.3333 | pediatric LRT/SLT 条件性结论覆盖不足。 |
| 18 | 0.0000 | reference 很短，但 judge 认为 contexts 未覆盖目标要点。 |

本次判断：

- v5 compact prompt 修复了 answer 生成质量问题：`generation_failed` 从 3 降到 0，接近 900 字符截断的 answer 从 6 降到 0。
- v5 也恢复并超过了 `faithfulness`、`answer_relevancy`、`context_utilization`。
- 但 `context_recall` 从 0.5917 降到 0.5667，说明继续调 answer prompt 不是提升 `context_recall` 的主要方向。
- 下一步应停止 prompt 加长/收短试验，转向 contexts 侧：优先做 doc-level 或相邻 chunk 合并的 Ragas contexts，对同一 gold doc 的多个 chunk 拼接后送入 Ragas；再比较 `context_recall` 是否提升。

### 2026-06-04 PubMedQA smoke20 v5 配置同步后复跑

目标：确认 `ragas_eval.py` 已清理到最新版后，以同步后的 `judge_profile` 重新运行 Ragas，避免 v4/v5 缓存和日志口径混杂。

运行前核对：

- `ANSWER_BUILD_VERSION = answer_fallback_v5_pubmedqa_compact_rationale_prompt`。
- `judge_profile = pubmedqa_smoke20_ctx5_1200_evidence1200_compact_rationale_prompt`。
- `ragas_eval.py` 已清理 `RagasRuntime` / `metrics.collections` 残留，实际使用 Ragas 0.4.x legacy metric 路径。
- 这次只跑 Ragas，没有跑 claim eval。

Ragas 实测结果：

| 指标 | evidence length 调参结果 | v5 上次结果 | v5 配置同步后复跑 |
| --- | ---: | ---: | ---: |
| `faithfulness` | 0.8053 | 0.8628 | 0.8944 |
| `answer_relevancy` | 0.7524 | 0.7726 | 0.7983 |
| `context_utilization` | 0.8169 | 0.8503 | 0.8142 |
| `context_recall` | 0.5917 | 0.5667 | 0.6417 |

运行细节：

| 项目 | 结果 |
| --- | ---: |
| `sample_count` | 20 |
| `loaded_from_cache` | True |
| `loaded_score_from_cache` | False |
| `build_seconds` | 0.000 |
| `eval_seconds` | 1765.957 |
| `faithfulness valid/nan/total` | 20 / 0 / 20 |
| `context_recall valid/nan/total` | 20 / 0 / 20 |
| `generation_failed` | 0 |
| `answer_len_ge_890` | 0 |
| `low_score_case_count` | 8 |
| `cross_metric_bad_case_count` | 7 |

低 `context_recall < 0.5` 题号：

| 题号 | `context_recall` | 其他观察 |
| ---: | ---: | --- |
| 4 | 0.3333 | answer 质量高，仍是 context/reference 覆盖问题。 |
| 6 | 0.0000 | answer_relevancy 为 0，community setting 证据方向仍不匹配。 |
| 8 | 0.3333 | answer/relevance 较高，但 reference 对 reporting heterogeneity 的结论方向仍难覆盖。 |
| 13 | 0.0000 | answer 倾向可区分，reference 倾向“不区分但可指导活检/治疗”，方向冲突。 |
| 14 | 0.3333 | family history prompt 的行为改变结论覆盖不足。 |
| 17 | 0.3333 | pediatric LRT/SLT 条件性结论覆盖不足。 |

本次判断：

- 最新有效 Ragas 结果以本节为准：`context_recall=0.6417`，相比 evidence length 调参结果 `0.5917` 有提升。
- v5 compact prompt 现在同时满足：无生成失败、无截断、四项指标无 NaN。
- 仍不建议跑 claim；下一步先针对剩余 6 条低 `context_recall` 做 context 侧诊断，优先看 gold doc 内 chunk 是否覆盖 reference 的关键句，以及是否需要把同一 doc 的相邻 chunk 合并后送入 Ragas。

### 2026-06-04 PubMedQA expected_claims 切分修正

目标：修复 PubMedQA `expected_claims` 几乎等于整段 `reference_answer` 的问题，让 claim eval 能检查细粒度 reference 要点。

问题诊断：

- `reference_answer` 来自 PubMedQA `long_answer`，应保留为完整参考答案。
- `expected_claims` 应是从 `reference_answer` 中拆出的 1-3 条关键 claim，而不是整段 long answer。
- 旧 `extract_claims_from_reference()` 主要按中文标点和分号切分，没有按英文句号切分；PubMedQA 是英文，因此 974/1000 条样本只有 1 条超长 claim。
- 旧逻辑还会给英文 claim 末尾追加中文句号，实际 JSON 中出现了 `ĄŁ` 伪字符。

修正内容：

| 项目 | 修正前 | 修正后 |
| --- | --- | --- |
| 英文句子边界 | 不按 `.` 切分 | 支持英文句号、分号、问号、感叹号和中文标点 |
| 小数处理 | 可能被 `.` 切断 | 保护 `0.05` 这类数字小数 |
| claim 末尾 | 强制追加中文句号 | 保留原句标点 |
| `judge_rubric.must_cover` | 等于旧 claims | 同步为新 claims |

数据更新方式：

- 因 Hugging Face 在线探测在沙箱中被阻塞，`prepare_pubmedqa.py` 未能在限定时间内完成。
- 本次未重建 corpus，也未重建向量库；仅基于现有 `pubmedqa_eval_dataset.json` 的 `reference_answer` 重新生成 `expected_claims` 和 `judge_rubric.must_cover`。
- `pubmedqa_corpus_docs.jsonl` 未改动。

验证结果：

| 项目 | 修正前 | 修正后 |
| --- | ---: | ---: |
| 样本数 | 1000 | 1000 |
| 1 条 claim | 974 | 333 |
| 2 条 claims | 24 | 431 |
| 3 条 claims | 2 | 236 |
| 单条 claim 完全等于 reference | 0 | 331 |
| 含 `ĄŁ` 的 claim | 多条 | 0 |
| `judge_rubric.must_cover == expected_claims` | 1000 | 1000 |
| dataset validation | pass | pass |

当前判断：

- `reference_answer` 和 `expected_claims` 语义一致是正确的；但 `expected_claims` 不应在多数样本中退化成整段 reference。
- 修正后，单句 reference 仍会有 1 条 claim，这是合理的；多句 reference 会拆成最多 3 条核心 claim。
- 这会改变 claim eval 的口径，后续再跑 claim eval 时应在报告中说明本次 claim granularity 已修正，不能直接和旧 claim coverage 做严格同比。

## 运行方式

默认使用当前运行时 PubMedQA DB：

`ragas_eval.py` 和 `claim_eval.py` 已在进程内默认设置 `KMP_DUPLICATE_LIB_OK=TRUE`，下面的命令行环境变量只用于显式覆盖默认值。

```powershell
$env:PYTHONIOENCODING='utf-8'
D:\Anaconda\envs\CA-py310\python.exe Agent\knowledge_base\rag\rag_eval\ragas_eval.py
```

claim eval 消费最新 Ragas 输出：

```powershell
$env:PYTHONIOENCODING='utf-8'
D:\Anaconda\envs\CA-py310\python.exe Agent\knowledge_base\rag\rag_eval\claim_eval.py
```


默认 pipeline 不再运行 claim eval；人工调参可通过 `run_rag_eval.py` 的 CLI 覆盖本次进程配置，不写回 `rag_config.py`：

```powershell
D:\Anaconda\envs\CA-py310\python.exe Agent\knowledge_base\rag\rag_eval\run_rag_eval.py --limit 30 --max-contexts 6 --max-context-chars 1600 --max-evidence-chars 1600
```
trace export 只消费现有输出，不重跑 judge：

```powershell
$env:PYTHONIOENCODING='utf-8'
D:\Anaconda\envs\CA-py310\python.exe Agent\knowledge_base\rag\rag_eval\trace_export.py
```

## 防护

`rag_eval.py` 在检索前会检查 benchmark `gold_doc_ids` 前缀和当前向量库 `doc_id` 前缀是否匹配。不匹配时直接失败，避免用错误向量库生成无效分数。

`ragas_eval.py` 的 prepared dataset 缓存签名现在包含向量库摘要。换库后旧 prepared dataset 不应再被误复用。

## 2026-07-08 baseline30 精简审核记录

本次已清理旧 `output` 后重跑 30 样本基线，run_id 为 `2026-07-08_183155_baseline30`，默认链路为：

```text
validate_datasets -> retrieval_eval -> ragas_eval -> trace_export -> summary
```

结果状态为 `pass`，核心指标如下：

| 指标 | 值 |
| --- | ---: |
| retrieval_recall_at_k | 1.0 |
| retrieval_mrr | 0.9611 |
| retrieval_hit_rate | 1 |
| ragas_faithfulness | 0.8345 |
| ragas_answer_relevancy | 0.8175 |
| ragas_context_utilization | 0.8306 |
| ragas_context_recall | 0.5833 |
| bad_case_trace_count | 13 |

### baseline30 主链路必须保留

| 文件 | 主要模块/函数 | 原因 |
| --- | --- | --- |
| `rag_eval/run_rag_eval.py` | `run_pipeline_from_code_config` | pipeline 总入口，负责 step 编排、输出 freshness 检查和 summary。 |
| `rag_config.py` | `RETRIEVAL_EVAL_CONFIG`、`RAGAS_RUN_CONFIG`、`RUN_PIPELINE_CONFIG` | baseline 的配置来源。 |
| `operation_datasets/dataset_utils.py` | `validate_all_datasets`、`write_dataset_validation_outputs` | baseline 第一步数据集校验。 |
| `rag_eval/rag_eval.py` | `run_from_code_config`、`evaluate_retrieval` | retrieval_eval 主逻辑。 |
| `query_rag.py` | `RagRetrievalConfig`、`build_retrieval_trace`、`get_vector_db_metadata_summary` | 实际访问 Chroma 知识库并生成检索 trace。 |
| `rag_eval/ragas_eval.py` | `run_ragas_eval_from_code_config`、`build_ragas_dataset`、`run_repeated_ragas_baseline` | Ragas dataset 构造、answer 生成与四项指标评测。 |
| `rag_eval/trace_export.py` | `run_trace_export_from_code_config` | 汇总 retrieval/Ragas 输出为 trace JSONL 和 trace report。 |
| `tools/report_utils.py` | dataset/retrieval/Ragas/trace/summary report builder | 生成本次 baseline 所需 Markdown 报告。 |
| `data/external/pubmedqa/processed/*` | `pubmedqa_corpus_docs.jsonl`、`pubmedqa_eval_dataset.json` | 固定 30 样本 baseline 的 active corpus/eval 来源。 |

### 候选删除/归档：离线生成与观测工具

以下文件不属于 baseline30 主链路。它们可逐项审核后归档；不要直接批量删除。

| 文件 | 主要模块/函数 | 不属于主链路的原因 |
| --- | --- | --- |
| `operation_datasets/prepare_pubmedqa.py` | `_build_doc_id`、`_context_to_text`、`_build_corpus_doc`、`_build_eval_sample`、`prepare_pubmedqa_from_config` | 用于重新生成 PubMedQA corpus/eval；baseline30 只读取已处理数据。 |
| `operation_datasets/ragas_testset_generate.py` | `run_preflight_check`、`_build_generator`、`_generate_raw_testset`、`_convert_raw_rows`、`run_ragas_testset_generation_from_code_config` | 用于生成新测试集；baseline30 使用固定 PubMedQA eval dataset。 |
| `operation_datasets/generate_rag_candidates.py` | `CANDIDATE_RUN_CONFIG`、`generate_candidate_file`、`run_candidate_generation_from_code_config` | 用于离线 top-k 候选表；baseline30 直接跑 retrieval trace。 |
| `operation_datasets/export_metadata.py` | `_resolve_faiss_index_directory`、`_load_vector_store`、`export_chunk_metadata` | 旧 FAISS/metadata 导出工具；当前 baseline 使用 Chroma `pubmedqa_clean`。 |
| `operation_datasets/validate_eval_datasets.py` | `validate_all` | 独立 CLI wrapper；baseline 实际使用 `dataset_utils.py`。 |
| `rag_eval/phoenix_export.py` | `PHOENIX_EXPORT_CONFIG`、`_export_single_trace`、`export_traces_to_phoenix_from_code_config` | Phoenix/OpenTelemetry 观测导出，不参与本地 JSON/Markdown baseline。 |
| `Ragas论文带读教程.md` | 文档 | 学习材料，不参与执行。 |
| `RAG测评框架开发.md` | 文档 | 开发记录，不参与执行；可保留为项目历史。 |
| `**/__pycache__/` | `.pyc` 缓存 | Python 可重建缓存，不是源码。 |

### 可选但不建议直接删

| 文件 | 主要模块/函数 | 建议 |
| --- | --- | --- |
| `rag_eval/claim_eval.py` | `CLAIM_EVAL_CONFIG`、`ClaimJudgement`、`ClaimEvalLLMResult`、`_run_claim_judge_with_retries`、`run_claim_eval_from_code_config` | baseline30 默认不跑，且已从 pipeline/工作台屏蔽；如需断言级复核，单独运行该脚本。 |
| `tools/report_utils.py` 中 `build_claim_eval_markdown_report`、`build_rag_retrieval_sweep_markdown_report` | claim/sweep 报告函数 | 同文件中也有 baseline 必需报告函数，不建议直接删文件；若要瘦身，应做函数级拆分。 |
| `build_knowledge.py` | `build(profile=..., allow_append=...)` | 不参与复跑 baseline30，但负责重建知识库；向量库损坏或 corpus 更新时仍需要。 |
| `app/rag_eval/` 与 `app/static/rag_eval.*` | 前端调参和结果查看接口/页面 | 不参与 CLI baseline，但若保留 Web 控制台就不能删。 |

完整审核表见：`Agent/knowledge_base/rag/output/baseline30_module_audit.md`。

## 2026-07-08 RAG 前端调参与后端配置同步思路

### 当前接口边界

前端控制台面向开发者，不直接修改 `rag_config.py`，而是通过 HTTP 把调参值同步到当前 Flask 进程内的配置对象。

| 接口 | 用途 | 配置同步行为 |
| --- | --- | --- |
| `GET /api/rag_eval/status` | 读取 benchmark、向量库和最新 run 状态 | 只读。 |
| `GET /api/rag_eval/config` | 拉取当前可调参数、retrieval profiles、Ragas 参数、pipeline 参数 | 只读，前端用它初始化表单。 |
| `PUT /api/rag_eval/config` | 保存前端修改的运行时配置 | 写入当前 Python 进程内的 `RETRIEVAL_PROFILES`、`RETRIEVAL_EVAL_CONFIG`、`RAGAS_RUN_CONFIG`、`RUN_PIPELINE_CONFIG` 等 dict；不写回源码文件，重启恢复默认。 |
| `POST /api/rag_eval/run` | 启动 pipeline | 使用当前前端已保存的运行时配置，然后后台线程运行 pipeline。 |
| `GET /api/rag_eval/run-state` | 读取当前进程内 pipeline 运行状态 | 只读，用于页面刷新后恢复 run_id、状态和已记录事件；可选 `run_id` 查询指定运行。 |
| `GET /api/rag_eval/runs/<run_id>/stream` | SSE 进度流 | 只读，用于前端显示 pipeline 进度。 |
| `GET /api/rag_eval/results/latest`、`GET /api/rag_eval/runs`、`GET /api/rag_eval/runs/<run_id>` | 查询结果和历史 run | 只读，读取 `output` 下 JSON/summary。 |
| `GET /api/rag_eval/analysis/latest`、`GET /api/rag_eval/runs/<run_id>/analysis` | 查询报告、trace 索引和坏例明细 | 只读，聚合 `trace.jsonl`、`trace_index.json`、Ragas bad cases 和 Markdown 报告。 |

### 前端修改信息后的同步流程

推荐的前端交互流程：

```text
1. 页面加载
   -> GET /api/rag_eval/config
   -> 用返回值填充 retrieval / Ragas / pipeline 参数表单

2. 用户修改表单
   -> 前端只维护本地 draft，不立刻触发评测
   -> 做基本类型转换：数字、布尔、null、数组

3. 用户点击“保存配置”
   -> PUT /api/rag_eval/config
   -> body 中包含局部 overrides，例如：
      {
        "retrieval_eval": {"limit": 30},
        "ragas": {"max_contexts": 6, "max_context_chars": 1600},
        "pipeline": {"steps": ["validate_datasets", "retrieval_eval", "ragas_eval", "trace_export", "summary"]}
      }
   -> 后端校验并合并到当前进程配置 dict
   -> 返回 updated_fields / warnings
   -> 前端再次 GET /api/rag_eval/config 或用返回值刷新表单状态

4. 用户点击“运行”
   -> POST /api/rag_eval/run
   -> 可以只发 run 请求，使用已保存的进程内配置
   -> 后端启动线程，生成 run_id

5. 前端订阅 SSE
   -> GET /api/rag_eval/runs/<run_id>/stream
   -> 展示 step_start / step_done / pipeline_done
   -> 若页面刷新，前端先 GET /api/rag_eval/run-state 恢复已有事件，再重新订阅同一个 run_id 的 SSE

6. 运行结束
   -> GET /api/rag_eval/results/latest
   -> GET /api/rag_eval/runs/<run_id>
   -> GET /api/rag_eval/analysis/latest
   -> 展示指标、报告内容、坏例 trace、证据链和 config_snapshot
```

### 后端配置如何同步

当前实现的“配置同步”不是数据库持久化，也不是改源码，而是内存态同步：

```text
前端表单
  -> JSON overrides
  -> app/rag_eval/routes.py
  -> app/rag_eval/service.py:update_rag_eval_config()
  -> 修改已 import 的 rag_config / rag_eval / ragas_eval 中的 module-level dict
```

这种方式适合本地开发和单进程 Flask：

- 优点：简单、不会误改 `rag_config.py`、不会把临时调参固化进仓库。
- 缺点：服务重启后配置丢失；多进程 gunicorn 下不同 worker 的内存配置不共享；多个用户同时调参可能互相覆盖。

这里的“全局 mutable dict”指的是 Python 模块级配置对象，例如 `RAGAS_RUN_CONFIG`、`RETRIEVAL_EVAL_CONFIG`、`RUN_PIPELINE_CONFIG`。`rag_config.py` 里的 profile 只是源码默认值；当前端 `PUT /api/rag_eval/config` 保存后，后端改的是当前 Flask 进程已经 import 的这些 dict。用户 A 和用户 B 即使都从同一套本地 profile 初始化，只要连到同一个 Flask 进程，保存后的运行时配置也是共享的，后保存的人会覆盖前一个人的内存态配置。服务重启后又会回到源码默认 profile。

### 更稳的后续演进

如果要把前端调参做成长期能力，建议改成“每次 run 都有独立配置快照”，不要依赖全局 mutable dict：

1. 前端始终发送完整 run config 或 profile id。
2. 后端做 schema 校验和默认值合并，生成不可变 `run_config_snapshot`。
3. pipeline runner 接收 config object，而不是直接读取/修改全局 `RAGAS_RUN_CONFIG`。
4. `output/runs/<run_id>/config_snapshot.json` 作为该 run 的唯一事实来源。
5. 若需要持久化用户配置，再单独引入 `saved_profiles.json` 或数据库表；不要写回 `rag_config.py`。

### 安全边界

- 前端可以暴露 retrieval/Ragas/pipeline 调参。
- 不建议直接暴露“清空向量库”“重建知识库”“允许 append”等高风险按钮。
- `build_knowledge.py --allow-append` 属于高风险知识库追加写入，真正执行前必须单独确认。
- 删除 output、清理缓存、删除候选模块仍按危险操作流程逐项确认。

## 2026-07-08 RAG 前端接口够用性评估

当前暴露给前端的 RAG 评测接口，足够支撑第一版“开发者控制台”，但还不足以支撑完整的评测分析页面。

### 当前已够用的范围

如果第一版页面定位为开发者控制台，目标是查看状态、调整参数、启动 baseline、观察进度、查看汇总指标和历史 run，那么现有接口基本够用：

| 能力 | 现有接口 |
| --- | --- |
| 查看 benchmark / 向量库 / 最新 run 状态 | `GET /api/rag_eval/status` |
| 读取运行时配置 | `GET /api/rag_eval/config` |
| 保存运行时配置 | `PUT /api/rag_eval/config` |
| 启动 pipeline | `POST /api/rag_eval/run` |
| 订阅 pipeline 实时进度 | `GET /api/rag_eval/runs/<run_id>/stream` |
| 查看最新汇总结果 | `GET /api/rag_eval/results/latest` |
| 查看历史 run 列表和基础详情 | `GET /api/rag_eval/runs`、`GET /api/rag_eval/runs/<run_id>` |
| 查看最新报告、坏例和 trace 明细 | `GET /api/rag_eval/analysis/latest` |
| 查看指定 run 的报告、坏例和 trace 明细 | `GET /api/rag_eval/runs/<run_id>/analysis` |

### 当前不足的范围

如果页面要面向论文展示、人工复核、坏例定位或实验对比，需要补充以下接口能力：

1. Bad case / trace 明细接口
   - 当前已补最小只读接口：`GET /api/rag_eval/analysis/latest` 和 `GET /api/rag_eval/runs/<run_id>/analysis`。
   - 第一版可按题展示失败样本、失败原因、检索证据、Ragas 分数、原问题、生成回答和参考答案。
   - 后续如果样本量变大，应补分页、筛选和单 trace 按需读取，避免一次返回过大。

2. 报告内容接口
   - 当前已由 analysis 接口聚合 `summary.md`、`dataset_validation_report.md`、`rag_eval_report.md`、`ragas_eval_report.md`、`trace_report.md`。
   - 报告内容会做长度截断，避免前端一次加载过大 Markdown。

3. 历史 run 详情接口
   - 当前 `GET /api/rag_eval/runs/<run_id>` 已附带轻量 `analysis` 字段。
   - 若只需要分析产物，应优先使用 `GET /api/rag_eval/runs/<run_id>/analysis`。

4. 多 run 对比接口
   - 如果要比较 baseline30 和后续实验的指标变化，需要后端提供 compare 接口，或前端逐个拉取 run 后自行聚合。

5. 运行控制接口
   - 当前可以启动 pipeline，但缺少取消运行、查询运行中状态和重复启动防护。
   - Ragas 阶段耗时较长，前端只靠 SSE 等待，交互上不够完整。

6. 每次 run 独立配置快照
   - 当前配置同步是全局内存态，适合本地单进程开发。
   - 如果前端强调“每次实验配置可追溯”，建议让 run 接收完整配置对象，并以该 run 的 `config_snapshot.json` 作为事实来源。

### 前端开发建议

第一版前端可以优先基于现有接口完成：

```text
总览 -> 参数配置 -> 运行 Pipeline -> SSE 进度 -> 汇总指标 -> 历史 run
```

如果设计稿包含以下模块，应同步补最小必要后端接口：

- 坏例分析 / trace 详情
- Markdown 报告阅读
- 多 run 指标对比
- 单次 run 的完整机器结果浏览
- 运行取消或运行中状态管理

最容易踩的坑是把“能启动 pipeline”和“能分析评测结果”混为一谈。当前接口已经能跑和看总分，但真正支持定位问题样本、查看证据链和分析失败归因的接口还需要补齐。

## 2026-07-09 RAG 前端运行控制与日志优化计划

### Pipeline 可中断运行

后续目标：允许用户在前端随时停止当前 pipeline，回到配置页调整参数，再重新运行。

建议采用“温和取消”，不要强杀 Python 线程或强行中断正在进行的 HTTP 请求：

```text
点击停止
-> run 状态变为 cancelling
-> 当前 step 或当前样本级调用返回后检查取消标记
-> 停止后续 step
-> 发送 pipeline_cancelled 事件
-> 前端按钮恢复，允许用户修改配置并重新运行
```

最小可行接口与状态：

| 能力 | 建议接口/状态 |
| --- | --- |
| 请求取消当前 run | `POST /api/rag_eval/runs/<run_id>/cancel` |
| 查询运行状态 | 复用或扩展 `GET /api/rag_eval/run-state` |
| 运行状态 | `running`、`cancelling`、`cancelled`、`pass`、`fail` |
| 前端事件 | `pipeline_cancel_requested`、`pipeline_cancelled` |

实现边界：

1. 后端为每个 run 维护 cancel flag。
2. pipeline 每个 step 之间必须检查 cancel flag。
3. 对 `ragas_eval` 这类长阶段，后续应在样本级循环里增加取消检查。
4. 正在执行中的单次 embedding / answer / judge API 请求不做强杀；等当前请求返回后再停止。
5. 被取消的 run 应标记为 incomplete / cancelled，避免被误认为完整评测结果。
6. 如果 cancelled run 已产生部分 output，前端要明确提示“结果不完整”。

不建议的做法：

- 不建议强杀线程。
- 不建议直接删除正在写入的 output 文件。
- 不建议把取消动作设计成“清空结果”或“重建配置”，取消只负责停止后续执行。

### 长 API 调用日志优化

当前 Docker 日志能看到 embedding / DS API 请求，但前端实时事件粒度偏粗。后续需要让用户在前端知道“不是卡住了，而是在等待长时间 API”。

优化目标：

1. 在长 API 调用前发送等待提示事件。
2. 在 API 调用返回后发送完成事件，带耗时。
3. 对 retrieval / Ragas 阶段显示样本进度，例如 `样本 6/10`。
4. 对长时间无事件的阶段发送 heartbeat，并显示当前阶段说明。
5. 对 timeout / retry / fallback 明确显示为 warning，而不是让用户只看浏览器静默等待。

建议事件示例：

```text
api_call_start: 正在请求 embedding：样本 3/10
api_call_done: embedding 完成，用时 2.4s
api_call_start: 正在请求 answer model：样本 6/10
api_call_waiting: Ragas judge 已等待 60s，仍在运行
api_call_retry: judge 请求失败，准备第 2 次重试
step_progress: ragas_eval 样本 7/10
```

前端展示建议：

- 运行页保留实时事件日志。
- 增加当前阶段摘要：当前 step、当前样本、当前 API 类型、已等待时间。
- 长 API 调用超过阈值后显示柔和提示，而不是标红失败。
- 只有异常、重试耗尽或 pipeline_error 才显示失败态。

优先级建议：

1. 先做 pipeline 可取消和 run-state 状态恢复的完整闭环。
2. 再补 step 级 / 样本级 progress 事件。
3. 最后补长 API 调用的 waiting / retry / timeout 细粒度提示。

## 2026-07-09 Ragas 版本导入探针

新增临时验证脚本：`Agent/knowledge_base/rag/tools/probe_ragas_versions.py`。

验证目标：在不改当前 conda / Docker 环境的前提下，用临时 venv 测试候选 Ragas 版本与当前 LangChain 栈的导入兼容性，重点区分：

- `ragas` core 公开入口：`from ragas import EvaluationDataset, evaluate`
- Ragas wrapper 公开入口：`ragas.llms`、`ragas.embeddings`
- 当前 legacy 内部 metric 入口：`ragas.metrics._xxx`
- 0.4.x 推荐的公开 metric class 入口：`ragas.metrics.collections`

本次候选版本：`0.4.3`、`0.4.0`、`0.3.7`、`0.2.15`、`0.1.21`。

探针结果：

| Ragas 版本 | 安装结果 | plain 导入 | 加 VertexAI shim 后 | 结论 |
| --- | --- | --- | --- | --- |
| `0.4.3` | ok | 失败，缺 `langchain_community.chat_models.vertexai` | core / wrapper / collections / 当前内部 metric 均可导入 | 当前优先锁定版本 |
| `0.4.0` | ok | 失败，缺 `langchain_community.chat_models.vertexai` | core / wrapper / collections / 当前内部 metric 均可导入 | 可作为 0.4.x 备选 |
| `0.3.7` | ok | 失败，缺 `langchain_community.chat_models.vertexai` | core / wrapper / 当前内部 metric 可导入，`metrics.collections` 不可用 | 不适合改公开 collections API |
| `0.2.15` | ok | 失败，缺 `langchain_community.chat_models.vertexai` | core / wrapper / 当前内部 metric 可导入，`metrics.collections` 不可用 | 不适合改公开 collections API |
| `0.1.21` | fail | 与 `langchain-community==0.4.2` 依赖冲突 | 未测试 | 不建议使用 |

当前判断：

1. 单纯“换低版本 Ragas”不能解决当前 LangChain 栈下的 VertexAI 导入问题，0.2.15 到 0.4.3 都会遇到同类断点。
2. `ragas==0.4.3` 仍是当前最合适的锁定版本，因为它已在 baseline30 跑通过，并且具备 `ragas.metrics.collections` 公开 class 入口。
3. 现阶段 Docker 需要先补 `ragas==0.4.3` 并重建镜像；如果后续要减少内部 API 依赖，应基于 0.4.3 逐步迁移到 `metrics.collections`，同时适配其 modern LLM / embedding 组件。
4. 短期最小修复仍是保留 `ragas_eval.py` 里的 VertexAI shim 和当前已验证的 legacy metric 路径，先恢复 pipeline 可跑；公开 API 迁移作为后续技术债处理。

完整机器结果已写入：`Agent/knowledge_base/rag/output/machine/ragas_import_probe.json`。

## 2026-07-09 Ragas 依赖失败日志优化补充

后续做前端日志优化时，需要把 Ragas 包导入和版本兼容问题纳入日志事件体系，不能只把它归类为笼统的 `ragas_eval` 失败。

建议在进入 `ragas_eval` judge 前增加轻量 preflight，并通过 SSE / run event 暴露给前端：

```text
dependency_check_start: 正在检查 Ragas / LangChain 依赖
dependency_check_done: Ragas 依赖检查通过，版本 0.4.3
dependency_check_failed: Ragas 导入失败，缺少 ragas 包
dependency_compat_failed: Ragas 与当前 LangChain 栈兼容失败，缺 langchain_community.chat_models.vertexai
dependency_check_detail: ragas=0.4.3, langchain=1.3.1, langchain-community=0.4.2
```

前端展示建议按失败类型区分：

| 类型 | 典型错误 | 用户提示 |
| --- | --- | --- |
| 缺包 | `No module named 'ragas'` | 当前 Docker 镜像缺少 `ragas==0.4.3`，需要重建镜像后再运行。 |
| 版本兼容 | `No module named 'langchain_community.chat_models.vertexai'` | Ragas 与当前 LangChain 栈存在导入兼容断点；当前代码依赖 VertexAI shim。 |
| judge/API 运行期失败 | timeout、retry exhausted、LLM 返回异常 | 归入长 API 等待、重试、超时和失败日志。 |

实现建议：

1. 在 `ragas_eval` 阶段开始前调用依赖 preflight，不触发真实 judge API。
2. preflight 检查 `ragas`、`EvaluationDataset`、`evaluate`、`LangchainLLMWrapper`、`LangchainEmbeddingsWrapper`、当前 metric 导入路径。
3. 记录 `ragas` / `langchain` / `langchain-community` / `langchain-core` / `langchain-openai` 版本，写入 run event 和最终报告。
4. 缺包和兼容失败应直接标记为 dependency 级失败，不继续进入长时间 Ragas judge。
5. 如果错误命中已知模式，前端显示明确修复建议；未知导入错误保留完整异常摘要。

本次 Docker 复跑注意：

- `requirements.txt` 已包含 `ragas==0.4.3`。
- 如果当前容器镜像是在补依赖前构建的，仅重启容器可能不会安装新依赖；应重建 app 镜像后再启动。
- 推荐复跑前先在容器内验证：

```bash
docker-compose -f docker-compose.replica.yml build app
docker-compose -f docker-compose.replica.yml up -d app
docker-compose -f docker-compose.replica.yml exec app python -c "import ragas; print(ragas.__version__)"
```
## 2026-07-09 开发还需要处理的问题
1. 每次跑的进程的名字可以自定义。

## 2026-07-09 前端闭环实现记录

本轮目标是把 RAG 测评从“能跑通”推进到“前端可观察、可恢复、可保存、可回看”。

已落地：

1. Run 命名
   - 原始命名逻辑在 `run_rag_eval.py`：`YYYY-MM-DD_HH-MM-SS` + `RUN_PIPELINE_CONFIG["run_name"]`。
   - 默认形态为 `2026-07-09_07-37-52_active_benchmark_full_pipeline`；旧 run 的 `073752` 表示 `07:37:52`，仍可回看。
   - 前端新增 Run Name 输入框；为空时使用 `active_benchmark_full_pipeline`，有输入时作为 run_id 后缀，并做文件名安全清洗。

2. step 事件与刷新恢复
   - `run_pipeline_from_code_config()` 支持 `event_callback`，实际执行每个 step 时发送 `step_start`、`step_done`、`step_error`、`step_cancelled`。
   - 前端通过 `GET /api/rag_eval/run-state` 恢复当前进程内 run 的事件缓存，再重新订阅 SSE。
   - 修复前端 `startSSE()` 误引用局部变量和误禁用按钮的问题，避免刷新后实时事件被前端 JS 中断。

3. Pipeline 温和取消
   - 新增 `POST /api/rag_eval/runs/<run_id>/cancel`。
   - 后端为 run 维护 `cancel_requested`，状态会变为 `cancelling`。
   - Pipeline 在 step 开始前和 step 返回后检查取消标记，被取消后写入 `cancelled` 状态。
   - `retrieval_eval`、`ragas_eval` 的可控样本循环已接入样本级取消；点击停止后会在当前样本的检索/回答生成返回后停止后续样本。
   - 当前不强杀正在执行的单次 HTTP/API 请求；Ragas `evaluate()` 内部 judge 执行仍只能在 repeat 轮次前后检查取消。

4. 长 API 等待提示
   - 对 `retrieval_eval`、`ragas_eval`、`claim_eval` 发送 `api_call_start`。
   - 长阶段每 30 秒发送 `api_call_waiting`，前端状态显示“等待长时间 API”，告诉用户不是卡住。
   - 阶段完成后发送 `api_call_done`。
   - `retrieval_eval`、`ragas_eval` 会发送 `step_progress`，前端阶段进度条显示 `样本 current/total` 和当前 phase；实时事件列表默认不刷屏展示每条样本进度。

5. 报告保存与历史报告
   - 报告页可保存当前选中的 Markdown 报告。
   - 历史记录增加“报告”按钮，可打开指定 run 的报告和分析数据。
   - 运行开始后报告页会自动刷新，运行结束后停止自动刷新。

6. 报告可视化
   - `analysis` 接口增加 `summary`，前端报告页可直接读取本次 run 的状态、关键指标和步骤结果。
   - 报告页新增结构化概览：Run、Recall@K、Faithfulness、Bad Cases、步骤耗时/状态。
   - Markdown 不再作为纯文本显示，而是在前端渲染为标题、表格、列表、代码块等可读结构；保存按钮仍下载原始 Markdown。

仍需后续优化：

1. retry / timeout / fallback 事件：把长 API 的重试、超时和 fallback 明确显示为 warning。
2. 如果 app 进程重启，内存态 run-state 会丢失；历史 run 仍可从 `output/runs/<run_id>` 回看，但“正在运行的实时恢复”只保证同一 Flask 进程内页面刷新。
3. 如果后续多人或多 worker 同时使用前端调参，需要把当前进程内配置升级为每个 run 独立 config snapshot，避免全局 mutable dict 互相覆盖。

## 2026-07-09 PubMedQA 100 样本前端预设

本轮将 100 条样本评测配置固化到后端配置，避免每次在前端手动填字段。

新增可选 profile：

| 类型 | profile | 说明 |
| --- | --- | --- |
| 检索 | `pubmedqa_eval100` | 100 条正式评测检索预设，沿用 `active_current` 的低噪音 top4 检索口径。 |
| Ragas | `pubmedqa_eval100` | 100 条四指标评测，`ctx6 / context_chars1600 / response_chars1100 / timeout3600 / worker4 / retries3 / wait20`。 |

前端下拉可见项已收敛：

- 检索 profile 只显示 `active_current`、`pubmedqa_eval100`。
- Ragas profile 只显示 `pubmedqa_pipeline`、`pubmedqa_eval100`。

切换行为：

- 前端选择 `pubmedqa_eval100` 检索 profile 时，检索 `Limit` 自动带出 `100`。
- 前端选择 `pubmedqa_eval100` Ragas profile 时，生成质量参数自动带出 `limit=100`、四项核心指标和当前 100 样本默认上下文配置。
- 保存配置时会提交 `active_ragas_profile`，后端会重置当前进程内 `RAGAS_RUN_CONFIG` 到该 profile，避免“下拉已切换但后端仍跑旧 profile”。

保留但不在前端显示的内部配置：

- 旧 `baseline_current`、`candidate_top20`、`more_diverse_mmr` 以及 active candidate/debug profile 暂不从源码硬删，因为离线 candidate/sweep 工具仍有兼容引用。
- 用户侧前端不再暴露这些旧/调参 profile，减少误选。

## 2026-07-09 本聊天窗口开发汇总

本节汇总本次聊天窗口内完成的 RAG 测评开发工作，作为后续继续开发和排错的入口索引。

### 1. Ragas 依赖与 Docker 复跑

问题背景：

- Docker app 容器里一开始缺少可用 Ragas 依赖，`ragas` 导入链遇到 `langchain_community.chat_models.vertexai` 兼容断点。
- 后续用户重建容器后确认 Ragas 阶段已经跑过，说明依赖链和当前 legacy metric 路径可用。

本轮处理：

- `requirements.txt` 中保留 `ragas==0.4.3`。
- 新增候选版本导入探针脚本：`Agent/knowledge_base/rag/tools/probe_ragas_versions.py`。
- 探针结论是 `ragas==0.4.3` 当前最适合锁定；短期继续保留 `ragas_eval.py` 的 VertexAI shim 和 legacy metric 路径，公开 API 迁移后续再做。
- 开发记录中补充 Ragas 依赖失败日志优化计划：后续要把缺包、版本兼容、judge/API 失败区分为不同前端事件。

### 2. RAG 测评前端工作台入口

新增页面入口：

| 路径 | 说明 |
| --- | --- |
| `/rag_eval` | RAG 测评工作台主入口 |
| `/rag-eval` | 同一个页面的短横线别名 |
| `/static/rag_eval.html` | 静态文件原始路径，仍可访问 |

相关文件：

| 文件 | 说明 |
| --- | --- |
| `app/main/routes.py` | 增加 `/rag_eval`、`/rag-eval` 页面路由 |
| `app/static/rag_eval.html` | 工作台页面 |
| `app/static/js/rag_eval.js` | 工作台交互逻辑 |
| `app/static/css/rag_eval.css` | 工作台样式 |
| `README.md`、`AGENTS.md` | 同步页面访问路径和项目事实 |

### 3. Pipeline 闭环：事件、刷新恢复、取消

后端能力：

- `run_pipeline_from_code_config()` 支持 `event_callback` 和 `cancel_checker`。
- 每个 step 会发送：
  - `step_start`
  - `step_done`
  - `step_error`
  - `step_cancelled`
- 长阶段会发送：
  - `api_call_start`
  - `api_call_waiting`
  - `api_call_done`
- 新增取消接口：

```text
POST /api/rag_eval/runs/<run_id>/cancel
```

前端能力：

- 刷新页面后通过 `GET /api/rag_eval/run-state` 恢复当前进程内 run 的事件缓存。
- SSE 断线后可重新订阅当前 run。
- 运行中可点“停止”，后端进入 `cancelling`；`retrieval_eval` 和 Ragas dataset 构建/refresh 会在当前样本结束后温和停止，其他 step 在 step 边界停止。
- 长 API 阶段前端显示“等待长时间 API”，避免用户误以为卡死。
- `step_progress` 用于更新阶段进度条，展示样本 `current/total`，默认不进入流水日志列表。

当前边界：

- 不强杀正在执行的单次 HTTP/API 请求。
- Ragas judge 的单次 `evaluate()` 调用由 Ragas 内部调度，当前只能在 judge repeat 轮次前后检查取消，不能中途强杀。
- app 进程重启会丢失内存态 `run-state`；历史报告仍可从 `output/runs/<run_id>` 查看。

### 4. Run 命名

原始 run_id 规则：

```text
YYYY-MM-DD_HH-MM-SS + "_" + RUN_PIPELINE_CONFIG["run_name"]
```

示例：

```text
2026-07-09_07-37-52_active_benchmark_full_pipeline
```

本轮实现：

- 前端运行页新增 Run Name 输入框。
- 用户不填时使用默认后缀 `active_benchmark_full_pipeline`。
- 用户填写时作为 run_id 后缀，并通过后端 `_safe_run_name()` 做文件名安全清洗。
- 前端当前推荐 100 条评测 run name：

```text
pubmedqa_eval100_ctx6_1600_v1
```

### 5. 报告保存、历史报告与报告可视化

报告页增强：

- `GET /api/rag_eval/analysis/latest` 和 `GET /api/rag_eval/runs/<run_id>/analysis` 返回报告、trace、坏例和 `summary`。
- 报告页新增结构化概览：
  - Run
  - Recall@K
  - Faithfulness
  - Bad Cases
  - step 状态和耗时
- Markdown 不再作为纯文本显示，前端会渲染为：
  - 标题
  - 表格
  - 列表
  - 代码块
  - 行内代码 / 加粗
- “保存报告”按钮下载当前选中的原始 Markdown。
- 历史记录增加“报告”按钮，可打开指定 run 的报告。
- Pipeline 运行期间报告页自动刷新；运行结束后停止自动刷新。

### 6. 100 样本后端预设

用户最终决定先跑 100 条，而不是 1000 条。已固化后端 profile，避免每次手动填字段。

新增检索 profile：

```text
pubmedqa_eval100
```

参数：

| 字段 | 值 |
| --- | ---: |
| dense_fetch_k | 10 |
| dense_mmr_k | 10 |
| sparse_fetch_k | 8 |
| final_top_k | 4 |
| dense_score_threshold | 0.45 |
| final_rerank_threshold | 0 |
| mmr_lambda | 0.7 |
| official_only_when_available | false |
| retrieval_eval.limit | 100 |

新增 Ragas profile：

```text
pubmedqa_eval100
```

参数：

下表是 `pubmedqa_eval100` 的有效运行参数；其中 `max_contexts`、`max_context_chars`、`max_response_chars` 来自 `RAGAS_BASE_CONFIG` 继承值，profile 本身没有重复覆盖。

| 字段 | 值 |
| --- | --- |
| limit | 100 |
| selected_metrics | `faithfulness, answer_relevancy, context_utilization, context_recall` |
| max_contexts | 6 |
| max_context_chars | 1600 |
| max_response_chars | 1100 |
| ragas_timeout | 3600 |
| ragas_max_workers | 4 |
| ragas_max_retries | 3 |
| ragas_max_wait | 20 |
| repeat_count | 1 |
| low_score_threshold | 0.5 |
| retrieval_recall_low_threshold | 0.67 |
| retrieval_mrr_low_threshold | 0.5 |
| judge_profile | `pubmedqa_eval100_ctx6_1600_evidence1600_pubmedqa_prompt_v6` |

前端下拉收敛：

- 检索参数只显示：
  - `active_current`
  - `pubmedqa_eval100`
- 生成质量参数只显示：
  - `pubmedqa_pipeline`
  - `pubmedqa_eval100`

说明：

- 旧 `baseline_current`、`candidate_top20`、`more_diverse_mmr` 和 active candidate/debug profile 暂不从源码硬删，因为离线 candidate/sweep 工具仍有兼容引用。
- 用户侧前端已不再暴露这些旧/调参 profile，避免误选。
- 保存配置时新增提交 `active_ragas_profile`，后端会把当前进程内 `RAGAS_RUN_CONFIG` 重置为选中 profile，解决“下拉切了但后端仍跑旧 profile”的问题。这个配置仍是进程级共享状态，不是用户级私有 profile。

当时已在浏览器中验证 100 条预设可以保存到 app 进程：

```text
active_retrieval_profile = pubmedqa_eval100
retrieval_eval.limit = 100
ragas.active_profile = pubmedqa_eval100
ragas.limit = 100
ragas.max_contexts = 6
ragas.max_context_chars = 1600
```

注意：这条是当时的验证记录，不代表当前 app 进程重启后仍保留该内存态配置；当前默认值以 `rag_config.py` 中的 profile 为准。

### 7. 验证记录

本聊天窗口内做过的主要验证：

```text
node --check app/static/js/rag_eval.js
D:\Anaconda\envs\CA-py310\python.exe -m py_compile app/main/routes.py app/rag_eval/service.py app/rag_eval/routes.py Agent/knowledge_base/rag/rag_eval/run_rag_eval.py
D:\Anaconda\envs\CA-py310\python.exe -m unittest tests.test_rag_eval_core_logic tests.test_rag_pipeline_current_outputs
```

已观察结果：

- JS 语法检查通过。
- Python 编译检查通过。
- RAG 相关 unittest 从 9 个扩展到 11 个，最终 `OK`。
- 浏览器打开 `/rag_eval` 成功。
- 报告页确认渲染出摘要卡、标题和 Markdown 表格。
- 配置页确认下拉只剩当前可用 profile。
- 切到 `pubmedqa_eval100` 后，前端字段自动带出 `retrieval limit=100`、`ragas limit=100`、`max_contexts=6`、`max_context_chars=1600`、`ragas_timeout=3600`、`ragas_max_workers=4`、`ragas_max_retries=3`、`ragas_max_wait=20`。
- `GET /api/rag_eval/config` 当时确认 app 进程已保存 100 条预设；这是进程内状态，不是持久化用户配置。

### 7.1 实时事件时间戳与 run_id 可读性修复

本次修复两个前端可读性问题：

- 实时事件刷新后时间戳混乱：前端实时 SSE 事件现在使用后端事件自带的 `timestamp`，不再在浏览器端用当前时间补位；后端事件时间戳改为带本地时区偏移的 ISO 时间，避免 Docker / 浏览器时区口径不一致。
- run_id 中的紧凑时间 `094735` 实际表示 `09:47:35`。新生成的 run_id 改为 `YYYY-MM-DD_HH-MM-SS_run_name`，例如 `2026-07-09_09-47-35_hello_first_100`；旧 run 名仍可正常回看。

本次补充验证：

```text
node --check app/static/js/rag_eval.js
D:\Anaconda\envs\CA-py310\python.exe -m py_compile app/rag_eval/service.py app/rag_eval/routes.py Agent/knowledge_base/rag/rag_eval/run_rag_eval.py
D:\Anaconda\envs\CA-py310\python.exe -m unittest tests.test_rag_eval_core_logic tests.test_rag_pipeline_current_outputs
```

结果：JS 语法检查、Python 编译检查通过；RAG 相关 unittest 为 13 个，最终 `OK`。

### 7.2 实时事件降噪与阶段进度条

本次把实时事件区从“流水日志”调整为“高信号事件 + 阶段进度”：

- `api_call_waiting` 仍由后端每 30 秒发送，但前端不再逐条追加到实时事件列表，只用于更新阶段进度条的“已等待 Ns”。
- 实时事件列表保留启动、完成、取消、失败，以及依赖/import 检查失败等需要人工注意的事件。
- 实时事件下方新增线性阶段进度条，按 pipeline step 展示等待、运行中、完成、失败、取消、跳过状态，并显示开始时间、结束时间、耗时和当前阶段消息。
- `ragas_eval` 进入真实 judge 前新增 Ragas / LangChain dependency preflight；缺包、兼容断点或 metric 导入失败会通过 `dependency_check_failed` / `dependency_compat_failed` 暴露到实时事件和阶段进度，不再只表现为笼统的 Ragas step 失败。

本次补充验证：

```text
node --check app/static/js/rag_eval.js
D:\Anaconda\envs\CA-py310\python.exe -m py_compile app/rag_eval/service.py app/rag_eval/routes.py Agent/knowledge_base/rag/rag_eval/run_rag_eval.py Agent/knowledge_base/rag/rag_eval/ragas_eval.py
D:\Anaconda\envs\CA-py310\python.exe -m unittest tests.test_rag_eval_core_logic tests.test_rag_pipeline_current_outputs
```

结果：JS 语法检查、Python 编译检查通过；相关 unittest 通过。

### 8. 后续仍建议处理

1. 在 `ragas_eval` 内部补样本级 `step_progress` 和样本级 cancel 检查。
2. 把 retry / timeout / fallback 做成 warning 事件，不只写 Docker 日志。
3. 如果后续要多人或多 worker 使用前端调参，需要把“当前进程内配置”升级为“每个 run 独立 config snapshot”，避免全局 mutable dict 互相覆盖。

## 2026-07-10 调参诊断优化方案记录

当前状态：

- 前端已经有“调参诊断”卡片，后端基于 `summary`、`trace_index`、`ragas_cross_metric_bad_cases.json` 做规则诊断。
- 当前诊断能识别类似“retrieval recall 已满但 context_recall 低”的模式，并给出 `max_contexts`、`max_evidence_chars`、`final_top_k` 等下一步建议。
- 这套建议目前是单 run 规则模板，优点是稳定、低成本、可解释；缺点是如果连续几轮都是同类坏例，建议会显得重复。

本轮决策：

- 暂时不把调参诊断默认接入 LLM/API。
- 原因：自动每次调 API 会增加成本、延迟和不稳定性，而且如果输入仍只是单次 run 指标，LLM 也很可能重复给出相似建议。
- 更合适的方向是：规则诊断为主，历史对比为辅，LLM/API 只作为开发者手动触发的“复盘解释”能力。

后续推荐分层实现：

1. 规则层：稳定归因。
   - 保留代码规则，用于判断主瓶颈类型：`retrieval_miss`、`rerank_loss`、`context_coverage`、`generation_mismatch`、`judge_or_reference_issue`。
   - 规则层必须输出结构化字段，而不是只输出文案：主瓶颈、证据、坏例分布、建议实验参数。

2. 历史层：避免重复建议。
   - 诊断输入不应只看 latest run，还应看 baseline run、run diff、config delta、bad case delta 和已尝试参数。
   - 如果上一轮已经尝试扩大 `max_contexts` / `max_evidence_chars` 但 `context_recall` 没提升，就不要继续重复推荐同一动作。
   - 如果 `context_recall` 提升但 `faithfulness` 或 `context_utilization` 下降，应提示上下文噪音增加，建议回调 `final_top_k` 或优化 rerank。
   - 如果坏例长期集中在同一批 question，应建议人工复核 reference、gold doc、chunk 粒度或 doc-level context，而不是继续盲目调参数。

3. 可选 API 层：手动 AI 复盘。
   - 后续可加按钮“AI 复盘本轮调参”，只在开发者主动点击时调用 LLM/API。
   - API 输入应是结构化摘要，不直接塞完整报告：

```json
{
  "current_metrics": {},
  "baseline_metrics": {},
  "metric_deltas": [],
  "bad_case_delta": {},
  "config_deltas": [],
  "top_bad_case_patterns": [],
  "already_tried_experiments": []
}
```

   - API 输出也应固定 JSON schema，避免自由文本不可控：

```json
{
  "primary_diagnosis": "",
  "why": [],
  "do_not_retry": [],
  "next_experiments": [],
  "risk": ""
}
```

下一步优先级：

1. 先把当前规则诊断升级为“当前 run + baseline run + config delta + bad case delta + 已尝试参数”的诊断。
2. 再在前端展示“不要重复尝试”的提示，例如“上轮已试 `max_contexts=8`，context_recall 无提升”。
3. 最后再考虑手动 API 复盘按钮，并把结果缓存到 run 目录，避免每次打开页面重复调用。

## 2026-07-11 前端体验与进度修复记录

本轮目标：提升 RAG 测评工作台长任务期间的可感知性，避免用户切页后错过完成状态，同时修复阶段进度误显示。

已完成：

- 完成提示：导航下方新增全局 `run-notice`，pipeline 完成、未达阈值、取消或失败后持续显示，并提供“查看报告 / 查看坏例 / 关闭”操作。
- 标签页提醒：运行中和完成后会更新 `document.title`，例如 `[运行中] RAG 评测工作台`、`[测评完成] RAG 评测工作台`、`[需调参] RAG 评测工作台`。
- 连接状态修复：顶部连接状态只以 `/api/rag_eval/status` 判断后端是否可达；`results/latest` 或 `analysis/latest` 暂时失败不会误显示“连接失败”。
- 交互动效：前端新增原生点击粒子、鼠标轨迹和刷新按钮打击感，不引入 npm / Python 依赖；移动端和 `prefers-reduced-motion` 下自动降级。
- Ragas 进度修复：`ragas_eval` 样本构建完成后进入 judge 阶段时，judge 的 `1/1` 不再覆盖样本进度 `20/20`；前端单独保留 `sampleCurrent/sampleTotal`，只把 retrieval / build_dataset / cancelled 或带题目信息的事件视作样本进度。

涉及文件：

| 文件 | 说明 |
| --- | --- |
| `app/static/rag_eval.html` | 新增全局完成提示条结构。 |
| `app/static/css/rag_eval.css` | 新增提示条样式、交互动效、刷新打击感和降级样式。 |
| `app/static/js/rag_eval.js` | 新增完成提示逻辑、标题提醒、连接状态容错、交互动效和 Ragas 样本进度保护。 |

验证：

```powershell
node --check app\static\js\rag_eval.js
```

结果：JS 语法检查通过。

## 2026-07-11 运行配置与发布保护补充记录

本轮目标：避免调参失败被误判为算法参数问题，并确保“运行 / 发布”实际使用的配置与前端表单一致。

问题背景：

- 20 样本 Ragas run 出现 `threshold_failed`，但排查后发现 retrieval 指标已过，Ragas 低分来自 answer response 中的 `Error code: 402 / Insufficient Balance`，即答案生成失败。
- 前端“本次运行配置预览”和 run `config_snapshot` 曾不一致，原因是 `/api/rag_eval/run` 之前只应用旧兼容字段，完整表单参数必须先点“保存配置”才会进入后端内存。
- “发布当前评测配置”之前只传 `source_run_id`，后端从当前内存/default retrieval config 发布，导致发布结果仍显示默认参数，而不是当前表单或运行预览参数。

已完成：

- Ragas 答案健康检查：
  - `ragas_eval.py` 在进入 Ragas judge 前检查 prepared dataset 的 `response`。
  - 如果发现空回答、`回答生成失败`、`Insufficient Balance`、`Error code:`、`fallback_failed` 等生成失败标记，直接返回 `status=fail`、`status_reason=answer_generation_failed`。
  - 这样 pipeline 会显示 step failed，不再继续 judge 并产出误导性的 `faithfulness=0.0`。

- 运行时应用完整表单配置：
  - `/api/rag_eval/run` 改为先调用 `update_rag_eval_config(overrides)`，应用完整 `retrieval_profiles`、`ragas`、`pipeline` 等表单覆盖值。
  - 前端运行按钮现在直接提交当前表单参数；用户改完参数后直接运行，也会写入本次 run 的 `config_snapshot.json`。
  - 运行控制区新增“本次运行配置预览”，展示 active profile、limit、关键 retrieval 参数、Ragas workers 和 steps。

- 发布配置一致性：
  - 发布按钮现在随请求发送当前表单的 `config_overrides`。
  - 后端 `publish_current_config_to_production()` 优先从 `config_overrides` 提取正式 RAG 检索配置；未传时才回退到当前后端内存配置。
  - 验证过模拟表单参数 `dense_fetch_k=8`、`dense_mmr_k=7`、`final_top_k=3` 时，发布出的 `production_rag_config.json` 会同步这些值，并保留 `max_evidence_chars=1600`。

涉及文件：

| 文件 | 说明 |
| --- | --- |
| `Agent/knowledge_base/rag/rag_eval/ragas_eval.py` | 增加 `_find_invalid_ragas_answers()` 和 Ragas judge 前的答案生成失败拦截。 |
| `Agent/knowledge_base/rag/rag_eval/run_rag_eval.py` | 非 pass step 的 message 会带上 `result.error` / `status_reason`，方便前端显示真实失败原因。 |
| `app/rag_eval/service.py` | `/run` 应用完整表单配置；发布接口支持 `config_overrides` 并从中提取 production retrieval config。 |
| `app/static/rag_eval.html` | 运行控制区新增本次运行配置预览容器。 |
| `app/static/css/rag_eval.css` | 新增运行配置预览样式。 |
| `app/static/js/rag_eval.js` | 运行前渲染配置预览；运行和发布均提交当前表单配置。 |

验证：

```powershell
node --check app\static\js\rag_eval.js
```

Python 只读语法检查：

```text
syntax_ok Agent/knowledge_base/rag/rag_eval/ragas_eval.py
syntax_ok Agent/knowledge_base/rag/rag_eval/run_rag_eval.py
syntax_ok app/rag_eval/service.py
```

函数级验证：

- `_find_invalid_ragas_answers()` 能识别 `Insufficient Balance`。
- `_retrieval_config_from_overrides()` 能从前端表单 payload 中提取发布配置，避免回退到默认 `10 / 10 / 4`。

已知事项：

- `tests.test_rag_eval_core_logic` 中仍有旧测试期望 `claim_eval` trace 存在；当前产品决策已屏蔽 `claim_eval`，后续需要同步更新测试预期。

## 2026-07-11 数据集热插拔解耦方向记录

目标：后续更换 benchmark / 数据集 / 向量库 collection 时，RAG 测评工作台的前端标识、后端状态、评测链路和历史 run 快照应自动跟随 active dataset，不再把 `PubMedQA` 这类具体数据集名散落写死在前后端代码里。

当前现状：

- 主页中部 `Benchmark` 和 `Vector Store` 卡片大部分已经来自 `/api/rag_eval/status`：
  - `benchmark.name`、`dataset_path`、`sample_count` 来自后端 `get_rag_eval_status()`。
  - 后端当前从 `rag_config.py` 的 `ACTIVE_BENCHMARK_NAME`、`ACTIVE_EVAL_DATASET_PATH`、`VECTOR_DB_DIR` 等常量读取 active 配置。
  - 因此如果只是修改 `rag_config.py` 并重启后端，中部卡片会跟随变化。
- 但左上角 `PubMedQA RAG Eval` chip 仍是 `app/static/rag_eval.html` 中的静态文案。
- 当前还不是真正热插拔：active dataset 仍依赖 Python 常量，retrieval profile、Ragas profile、prompt / judge profile、向量库 collection 等仍和 PubMedQA 有较强耦合。

建议方向：

1. 建立 dataset registry
   - 可先使用 `dataset_registry.json` 或 Python registry。
   - 每个数据集声明 `id`、`display_name`、`eval_dataset_path`、`corpus_path`、`vector_db_dir`、`collection_name`、默认 retrieval profile、默认 Ragas profile、样本 schema / benchmark schema。
   - 业务代码只读 `active_dataset_id`，再从 registry resolve 实际路径和配置。

2. 后端统一输出 UI metadata
   - `/api/rag_eval/status` 增加类似结构：

```json
{
  "workspace": {
    "title": "RAG 评测工作台",
    "tag": "PubMedQA",
    "subtitle": "RAG Eval"
  },
  "benchmark": {},
  "vector_db": {}
}
```

   - 前端 header、chip、卡片标题和可变文案都从接口渲染，不再写死具体数据集名。

3. 运行时记录 dataset snapshot
   - 每次 pipeline run 的 `summary.json` 或 `config_snapshot.json` 中保存当时的 `dataset_id`、`display_name`、`eval_dataset_path`、`corpus_path`、`collection_name`、active retrieval / Ragas profile。
   - 历史记录和 baseline/candidate 对比需要显示 dataset 是否一致；不同 dataset 的 run 默认不建议直接做指标对比。

4. 将 profile 与 dataset 绑定
   - retrieval profile、Ragas profile、sample limit 默认值应通过 dataset registry 或 dataset-specific profile 选择。
   - 避免切换数据集后仍沿用 PubMedQA 的 `pubmedqa_pipeline`、`pubmedqa_eval100`、PubMedQA prompt 标签等配置。

5. 增加 mismatch 防护
   - 运行前检查 active benchmark、向量库 collection、gold doc 前缀 / corpus metadata 是否一致。
   - 如果发现数据集与向量库不匹配，应阻止运行并给出明确提示，而不是生成误导性指标。

分阶段落地建议：

1. 第一阶段：只把前端 header chip 从写死改成 `/api/rag_eval/status.workspace` 动态渲染。
2. 第二阶段：抽出 dataset registry，让 `ACTIVE_BENCHMARK_NAME`、`ACTIVE_EVAL_DATASET_PATH`、collection name 从 registry resolve。
3. 第三阶段：run snapshot 记录 dataset metadata，并在历史对比中提示 dataset mismatch。
4. 第四阶段：将 retrieval / Ragas / prompt profile 做 dataset-aware 选择，完成真正热插拔。

风险提醒：

- 只改前端文案不是热插拔；真正关键是评测链路、向量库 collection、profile、prompt、run snapshot 必须同时指向同一个 active dataset。
- 不同数据集之间的指标通常不可直接横向对比，baseline/candidate 对比需要默认限制在同一 dataset 和同一 schema 下。

## 2026-07-11 历史记录与调参交互补充记录

本节补记近期已完成但此前日志未完整覆盖的 RAG 工作台交互更新。

已完成：

- 历史记录分页：
  - `GET /api/rag_eval/runs` 保持旧调用兼容，不带参数时仍返回全量 run 数组。
  - 新增分页参数：`GET /api/rag_eval/runs?page=1&page_size=10`。
  - 后端分页返回 `items`、`page`、`page_size`、`total`、`total_pages`。
  - 前端历史页默认按 10 条展示，超过 10 条显示上一页 / 下一页和总数。
  - 该分页依赖后端新接口生效；后端未重启时仍可能拿到旧格式全量数组。

- 删除 pipeline：
  - 历史列表每条 run 增加“删除”操作。
  - 前端删除前会确认：删除会同步移除本地 `Agent/knowledge_base/rag/output/runs/<run_id>` 下该 run 的文件。
  - 后端只允许删除 `RUNS_DIR` 的直属子目录：
    - 校验 `run_id` 非空。
    - 拒绝 `/`、`\`、`..` 等路径穿越输入。
    - `resolve()` 后要求目标目录父级等于 `RUNS_DIR.resolve()`。
  - 正在运行 / 取消中的 run 不允许删除，避免删掉仍在写入的目录。
  - 删除不会清理 `output/machine`、`output/reports` 这类 latest 输出，也不会触碰知识库或模型目录。

- baseline 手动选择对比：
  - 历史页的“最近两次对比”已改为“选择基线对比”。
  - Baseline 由开发者在下拉框中手动选择。
  - Candidate 使用当前选中的 run；从历史报告进入时，会把该 run 设为 candidate。
  - 对比接口支持 `base_run_id` 和 `candidate_run_id` 查询参数，用于返回指标 delta、坏例变化和配置变化。

- 参数说明与范围校验：
  - 调参表单中的参数名旁边增加说明入口，用于解释参数含义、影响方向、允许范围和建议范围。
  - 保存 / 运行 / 发布前都会做前端校验：
    - 超出允许范围：直接拦截。
    - 超出建议范围但仍合法：给 warning，但允许保存 / 运行 / 发布。
  - `ragas_timeout` 允许范围已放宽到 1 到 3600 秒。
  - `ragas_max_workers` 允许范围已支持到 16，避免低于 Ragas 官方并发参数示例上限。

- claim_eval 展示屏蔽：
  - 默认 pipeline 和前端调参入口不再展示 `claim_eval`。
  - 坏例链路聚合会过滤 claim 相关坏例，避免 `claim_eval_bad_case` 混入开发者当前调参视角。
  - 如需断言级人工复核，仍保留单独运行 `claim_eval.py` 的路径。

涉及文件：

| 文件 | 说明 |
| --- | --- |
| `app/rag_eval/service.py` | 新增 `list_runs_page()`、`delete_run()`、run 目录安全解析和 claim 坏例过滤。 |
| `app/rag_eval/routes.py` | `/runs` 支持分页参数，新增 `DELETE /runs/<run_id>`。 |
| `app/static/rag_eval.html` | 历史页新增分页容器、baseline 下拉选择区域。 |
| `app/static/css/rag_eval.css` | 新增分页、提示、warning/error 等交互样式。 |
| `app/static/js/rag_eval.js` | 历史分页渲染、删除确认、手动 baseline 对比、参数 tooltip 与校验逻辑。 |

验证记录：

```powershell
node --check app\static\js\rag_eval.js
```

Python 只读语法检查：

```text
syntax_ok app/rag_eval/service.py
syntax_ok app/rag_eval/routes.py
```

注意事项：

- 删除功能是代码能力，不代表已执行删除；开发过程中没有实际删除已有 run 目录。
- 如果页面仍显示 `第 1 / 1 页 · 共 18 条`，通常是后端服务尚未重启，仍返回旧格式全量数组；重启后端后分页接口才会返回 `total_pages=2`。

## 2026-07-11 首页模型运行状态补充记录

目标：让开发者在 RAG 测评工作台首页直观看到当前 embedding、回答模型和 Ragas judge 模型是否配置完整，避免因为 API key、本地 embedding 模型或 base URL 缺失而误判为 RAG 参数问题。

已完成：

- `/api/rag_eval/status` 新增 `models` 字段：
  - `models.embedding`：展示当前查询侧 embedding 模式、模型名、collection、API key 是否配置、base URL 是否配置、本地路径是否存在。
  - `models.answer`：展示正式 RAG 回答生成模型、endpoint 摘要、API key 是否配置。
  - `models.judge`：展示 Ragas / 评测 judge 模型、judge profile、endpoint 摘要、API key 是否配置。
- 首页新增 `Model Runtime / 模型运行状态` 卡片，按 `Embedding / Answer / Judge` 三列展示。
- 状态只做配置和路径检查，不发真实 API 请求，不会增加首页加载成本或消耗模型额度。
- 不展示任何密钥原文；前端只显示 `已配置 / 未配置`，base URL 只展示不含 query 的 endpoint 摘要。
- embedding 展示不再按 collection 名称猜测，而是读取共享 provider resolver；该 resolver 同时被 `query_rag.py` 和 `build_knowledge.py --profile medical` 使用，避免首页显示和真实查询/构建链路不一致。

涉及文件：

| 文件 | 说明 |
| --- | --- |
| `app/rag_eval/service.py` | 新增模型运行时状态聚合函数，并接入 `get_rag_eval_status()`。 |
| `app/static/rag_eval.html` | 首页新增模型运行状态卡片容器。 |
| `app/static/css/rag_eval.css` | 新增模型状态卡片、ready / missing 样式和移动端布局。 |
| `app/static/js/rag_eval.js` | 渲染 `status.models`，展示模型、模式、endpoint、API key 配置状态和提示信息。 |

验证记录：

```powershell
node --check app\static\js\rag_eval.js
```

Python 只读语法检查：

```text
syntax_ok app/rag_eval/service.py
syntax_ok app/rag_eval/routes.py
```

补充说明：

- 曾尝试直接调用 `get_rag_eval_status()` 做只读结构验证，但本地导入链 / Chroma metadata 扫描在 20 秒内未返回，因此未继续拉长等待；本次未触发任何真实模型调用。

## 2026-07-11 Embedding provider 本地/API 闭环记录

目标：支持同一套 RAG / RAG 评测链路在本地 embedding 模型和 OpenAI-compatible API embedding 之间显式切换，并确保知识库构建、正式查询、Ragas 评测和首页 Model Runtime 展示使用同一套 provider 规则。

新增环境变量：

| 环境变量 | 说明 |
| --- | --- |
| `RAG_EMBEDDING_PROVIDER` | embedding provider 选择。支持 `auto`、`local`、`openai_compatible`；`api` / `openai` 作为 `openai_compatible` 别名。 |
| `RAG_LOCAL_EMBEDDING_MODEL_PATH` | 本地 HuggingFace embedding 模型路径；未配置时默认 `Agent/knowledge_base/models/bge-small-zh-v1.5`。 |
| `MEDICAL_EMBEDDING_API_KEY` | API embedding key；只判断是否配置，不在前端展示原文。 |
| `MEDICAL_EMBEDDING_BASE_URL` | API embedding endpoint。 |
| `MEDICAL_EMBEDDING_MODEL` | API embedding 模型名；未配置时默认 `text-embedding-3-small`。 |

provider 规则：

- `RAG_EMBEDDING_PROVIDER=local`
  - 强制使用本地 embedding。
  - `query_rag.py` 查询侧、`build_knowledge.py --profile medical` 构建侧、首页 `Model Runtime` 都显示并使用本地模型路径。
  - 如果本地模型目录不存在，首页显示 `missing`。

- `RAG_EMBEDDING_PROVIDER=openai_compatible`
  - 强制使用 OpenAI-compatible API embedding。
  - 必须配置 `MEDICAL_EMBEDDING_API_KEY` 和 `MEDICAL_EMBEDDING_BASE_URL`。
  - 如果缺配置，首页显示 `missing`，查询/构建侧会给出明确缺失项错误。

- `RAG_EMBEDDING_PROVIDER=auto`
  - 兼容旧行为。
  - 如果存在 `MEDICAL_EMBEDDING_API_KEY` 或 `KNOWLEDGE_BUILD_PROFILE=medical`，使用 API embedding。
  - 否则使用本地 embedding。

闭环实现：

- 新增 `Agent/knowledge_base/embedding_runtime.py`
  - 只负责解析 provider、模型名、路径、API 配置状态。
  - 不导入 Flask / settings，不加载模型，不发 API 请求。
- `Agent/knowledge_base/query_rag.py`
  - `_get_embedding_function()` 改为读取 `resolve_embedding_runtime_config()`。
  - 正式 RAG 查询侧实际使用的 provider 与首页展示一致。
- `Agent/knowledge_base/build_knowledge.py`
  - `--profile medical` 改为读取同一套 provider resolver。
  - 这样 PubMedQA / medical corpus 可以用 API embedding 构建，也可以用本地 embedding 构建。
  - `--profile default` 仍保留原本固定本地 embedding 行为，避免旧因果库构建被环境变量意外影响。
- `app/rag_eval/service.py`
  - 首页 `models.embedding` 改为读取同一套 resolver。
  - 不再根据 `pubmedqa_clean` collection 名称猜测 API / local。

使用示例：

```env
# 本地 embedding
RAG_EMBEDDING_PROVIDER=local
RAG_LOCAL_EMBEDDING_MODEL_PATH=Agent/knowledge_base/models/bge-small-zh-v1.5
```

```env
# API embedding
RAG_EMBEDDING_PROVIDER=openai_compatible
MEDICAL_EMBEDDING_API_KEY=...
MEDICAL_EMBEDDING_BASE_URL=https://...
MEDICAL_EMBEDDING_MODEL=text-embedding-3-small
```

注意事项：

- 切换 provider 后，必须确认向量库是用同一个 embedding provider 和模型构建的；否则查询向量和库内向量不在同一向量空间，检索指标会失真。
- 切换 provider 通常需要重建对应 Chroma collection。不要在未确认的情况下清空 `Agent/knowledge_base/db`；如需删除旧 collection / 目录，必须先按危险操作流程确认。

## 2026-07-11 Pipeline 展示名与 run_id 解耦记录

背景：历史记录里的 `run_id` 以 `yyyy-mm-dd_hh-mm-ss_用户名` 作为目录名，时间部分可能来自容器或进程时区，直接展示给用户会造成“为什么不是北京时间”的疑惑；同时这段时间前缀对开发者调参对比没有直接价值。

实现原则：

- 底层 `run_id` 和 `output/runs/<run_id>` 目录名不变，继续作为详情、删除、报告、对比接口的稳定定位字段。
- 后端历史列表、详情页、分析 payload 新增 `display_name`、`display_time`、`display_subtitle`：
  - `display_name`：从 `run_id` 中去掉时间前缀，仅保留用户创建 pipeline 时填写的名字。
  - 如果用户没有填写名字，则回退到默认 pipeline 名。
  - `display_subtitle` 保留完整 `run_id`，用于详情和 tooltip 追溯。
- 前端历史列表、最近结果、报告摘要、详情标题、baseline/candidate 对比和删除确认优先显示 `display_name`。
- 完整 `run_id` 仍在历史列表单元格 `title`、详情概览的 `Run ID` 字段、接口参数中保留，避免为了可读性破坏系统定位能力。

收益：

- 用户看到的是自己取的调参实验名，不再被日期和时区干扰。
- 开发者仍可在详情中定位真实 run 目录，删除和对比逻辑不变。
