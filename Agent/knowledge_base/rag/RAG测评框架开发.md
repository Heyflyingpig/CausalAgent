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
