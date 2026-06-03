# Dataset Decision Report

## 当前结论

当前主 benchmark 已替换为 PubMedQA labeled。PubMedQA 更适合当前 RAG 检索、证据使用和开放式回答质量评测。

## Active Benchmark

| 项目 | 结果 |
| --- | --- |
| active benchmark | `pubmedqa` |
| corpus | `rag/data/external/pubmedqa/processed/pubmedqa_corpus_docs.jsonl` |
| eval dataset | `rag/data/external/pubmedqa/processed/pubmedqa_eval_dataset.json` |
| corpus doc count | 1000 |
| eval sample count | 1000 |
| schema | `benchmark_v2` |
| schema errors | 0 |

## Retrieval Smoke20

| stage | recall | mrr | hit_rate |
| --- | ---: | ---: | ---: |
| dense_raw | 1.0000 | 0.9750 | 1.0000 |
| dense_thresholded | 1.0000 | 0.9750 | 1.0000 |
| dense_mmr | 1.0000 | 0.9750 | 1.0000 |
| sparse | 0.9500 | 0.9500 | 0.9500 |
| final | 1.0000 | 0.9667 | 1.0000 |

## Retrieval Pilot100

| metric | score |
| --- | ---: |
| final recall_at_k | 0.9900 |
| final mrr | 0.9783 |
| final hit_rate | 0.9900 |
| dense_raw hit_rate | 0.9900 |

唯一 final 未命中样本是极短欠定问题，归类为 `dataset/query_bad`，不是系统性 retrieval 问题。

## Ragas Smoke20

| metric | score | valid | nan |
| --- | ---: | ---: | ---: |
| faithfulness | 0.7773 | 20 | 0 |
| answer_relevancy | 0.7014 | 20 | 0 |
| context_utilization | 0.8500 | 20 | 0 |
| context_recall | 0.5750 | 20 | 0 |

## 后续建议

1. 不优先调 dense/sparse 检索参数。
2. 下一轮优先调 generation prompt，减少证据充分时的 `insufficient_evidence`。
3. 下一轮优先调 Ragas context 配置，例如 `max_contexts=5` 或 `max_context_chars=1200`。
4. 正式运行前应将 `Agent/knowledge_base/db` 重建为 PubMedQA 向量库，或显式设置 `RAG_VECTOR_DB_DIR` 和 `RAG_COLLECTION_NAME`。
