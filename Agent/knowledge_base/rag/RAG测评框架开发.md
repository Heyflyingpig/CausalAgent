# RAG 测评框架开发记录

## 当前结论

当前 active benchmark 已切换为 PubMedQA labeled，主测试集和 corpus 都使用通用 `benchmark_v2` 口径。旧 RAGCare 数据、准备脚本和默认输出口径已从主评测链路中移除。

当前默认运行时向量库 `Agent/knowledge_base/db` 已替换为 PubMedQA 医疗知识库，默认 Chroma collection 为 `causal_agent_default`，doc_id 前缀为 `pubmedqa`。旧 RAGCare 向量库没有删除，已按本轮要求备份到 `tmp/RAGCare`。

## 数据与路径

| 项目 | 路径 | 说明 |
| --- | --- | --- |
| active corpus | `data/external/pubmedqa/processed/pubmedqa_corpus_docs.jsonl` | PubMedQA evidence corpus |
| active eval dataset | `data/external/pubmedqa/processed/pubmedqa_eval_dataset.json` | PubMedQA `benchmark_v2` 测试集 |
| prepare script | `operation_datasets/prepare_pubmedqa.py` | 生成 PubMedQA corpus/eval |
| runtime vector DB | `../db` | 默认运行时 Chroma 持久化目录，当前已是 PubMedQA |
| old DB backup | `../../../tmp/RAGCare` | 旧 RAGCare 向量库备份，不进入 Git |
| temporary PubMedQA DB | `../../../tmp/pubmedqa_db` | 本轮用于替换运行时 DB 的临时 PubMedQA 库 |

## 本轮主要修改

1. 数据集与配置
   - 保留 PubMedQA 作为 active benchmark，processed corpus/eval 均为 1000 条。
   - 删除旧 RAGCare raw/processed 数据和 `prepare_ragcare_qa.py`。
   - `dataset_utils.py` 不再把旧 generated 数据集作为默认校验对象，只校验 active benchmark。
   - `rag_config.py` 中 Ragas active profile 调为 `pubmedqa_smoke20`，Ragas context 调为 `max_contexts=5`、`max_context_chars=1200`。

2. 向量库与缓存
   - 将 `Agent/knowledge_base/db` 从 RAGCare 替换为 PubMedQA，验证结果为 `vector_count=5814`、`dataset_counts.pubmedqa=5814`。
   - 发现 Ragas prepared dataset 缓存签名没有包含向量库身份，导致换库后仍可能复用旧 RAGCare retrieval/answer 缓存。
   - 已修复 `ragas_eval.py`：prepared dataset 的 `dataset_build_config` 和兼容性判断都会记录 `get_vector_db_metadata_summary()`，避免向量库变化后复用错误缓存。

3. 输出与报告
   - 重新生成 latest Ragas、claim eval 和 trace 输出。
   - `trace_export.py` 已消费现有 retrieval/Ragas/claim 输出生成 `trace.jsonl`、`trace_index.json` 和 `trace_report.md`。
   - `AGENTS.md` 和 `README.md` 已同步当前本地 DB 是 PubMedQA、旧 RAGCare 备份在 `tmp/RAGCare` 的项目事实。

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

Ragas smoke20，配置为 `5 x 1200` contexts：

| metric | value |
| --- | ---: |
| faithfulness | 0.8015 |
| answer_relevancy | 0.7740 |
| context_utilization | 0.8711 |
| context_recall | 0.4792 |
| valid / total | 20 / 20 |
| NaN | 0 |
| build_seconds | 195.582 |
| eval_seconds | 1604.611 |
| total seconds per sample | 90.010 |

claim eval，消费同一份 Ragas smoke20：

| metric | value |
| --- | ---: |
| status | pass |
| sample_count | 20 |
| judge_failed_count | 0 |
| claim_coverage | 0.3000 |
| evidence_support_rate | 0.3500 |
| unsupported_answer_claim_count | 0.1000 |
| eval_seconds | 146.921 |

trace export：

| metric | value |
| --- | ---: |
| trace_count | 20 |
| bad_case_trace_count | 15 |
| retrieval_eval_trace_count | 20 |
| ragas_eval_trace_count | 20 |
| claim_eval_trace_count | 20 |

## 现状解释

这次 20 条 smoke 说明链路已经能完整跑通：retrieval、answer build、Ragas judge、claim judge、trace export 都能生成输出，且 Ragas/claim judge 没有 NaN 或 judge failed。

`context_recall` 仍偏低，但这次不是检索库错配，也不是 Ragas 输入 context 数没有生效。当前 final evidence 已全部来自 `pubmedqa`，20 条 metadata 字段也齐全。更可能的原因是 PubMedQA 的 `reference_answer` / `expected_claims` 较长，Ragas 的 `context_recall` 会按 reference 要点严格判断，而当前 answer 和 evidence 只覆盖了部分 long answer rationale。

当前不建议直接扩大到 100 条 Ragas。按本轮 20 条耗时估算，Ragas 每条约 90 秒，50 条约 75 分钟，100 条约 150 分钟；claim eval 每条约 7.3 秒，100 条约 12 分钟。扩大样本前更应该先处理 bad case 中的 generation/context_recall 问题。

## 当前输出

| 文件 | 说明 |
| --- | --- |
| `output/machine/ragas_eval_result.json` | 最新 PubMedQA smoke20 Ragas 结果 |
| `output/reports/ragas_eval_report.md` | 最新 Ragas Markdown 报告 |
| `output/machine/ragas_low_score_cases.json` | Ragas 低分样本 |
| `output/machine/ragas_cross_metric_bad_cases.json` | retrieval/Ragas 跨指标坏例 |
| `output/machine/claim_eval_result.json` | 最新 claim eval 结果 |
| `output/reports/claim_eval_report.md` | 最新 claim eval 报告 |
| `output/machine/claim_eval_bad_cases.json` | claim eval 坏例 |
| `output/machine/trace.jsonl` | 逐题 trace |
| `output/machine/trace_index.json` | trace 汇总索引 |
| `output/reports/trace_report.md` | trace Markdown 报告 |

## 后续建议

1. 不要立刻跑 100 条 Ragas；先分析 20 条 bad case。
2. 优先看 `retrieval_ok_ragas_bad` 样本，判断是 answer prompt 没充分使用 evidence，还是 PubMedQA reference/claim 太长导致 Ragas `context_recall` 不稳定。
3. 如果继续调参，优先试：
   - `max_contexts=8`
   - `max_context_chars=1500`
   - answer prompt 明确要求覆盖 PubMedQA long answer rationale，而不是只给 yes/no 结论。
4. 如果要跑 50/100，先确认 Ragas prepared dataset 会重新计算或命中正确的 PubMedQA vector DB 签名。

## 调参记录

以后每次 RAG 调参都必须在本节追加一条记录，至少包含：变更日期、目标指标、参数变更、运行样本、是否复用缓存、Ragas 结果、claim/trace 结果、主要 bad case 结论和下一步判断。不要只依赖 latest JSON 输出，因为 latest 会被后续运行覆盖。

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

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:KMP_DUPLICATE_LIB_OK='TRUE'
D:\Anaconda\envs\CA-py310\python.exe Agent\knowledge_base\rag\rag_eval\ragas_eval.py
```

claim eval 消费最新 Ragas 输出：

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:KMP_DUPLICATE_LIB_OK='TRUE'
D:\Anaconda\envs\CA-py310\python.exe Agent\knowledge_base\rag\rag_eval\claim_eval.py
```

trace export 只消费现有输出，不重跑 judge：

```powershell
$env:PYTHONIOENCODING='utf-8'
D:\Anaconda\envs\CA-py310\python.exe Agent\knowledge_base\rag\rag_eval\trace_export.py
```

## 防护

`rag_eval.py` 在检索前会检查 benchmark `gold_doc_ids` 前缀和当前向量库 `doc_id` 前缀是否匹配。不匹配时直接失败，避免用错误向量库生成无效分数。

`ragas_eval.py` 的 prepared dataset 缓存签名现在包含向量库摘要。换库后旧 prepared dataset 不应再被误复用。
