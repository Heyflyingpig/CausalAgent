# RAG Eval Dataset 说明

本目录保存 Phase1 后的 RAG 评测数据集。拆分原则是：不同数据集服务不同工程决策。

## 文件用途

- `rag_eval_smoke.json`
  - 快速冒烟测试集。
  - 只包含已有 `gold_chunk_ids` 的核心样本。
  - 默认供 `rag_eval/rag_eval.py` 使用，用来检查 retrieval 链路是否明显退化。

- `rag_eval_auto.json`
  - 自动化评测主数据集。
  - 包含 `expected_claims`、`reference_answer`、`judge_rubric`。
  - 后续供 `rag_eval/ragas_eval.py`、`rag_eval/claim_eval.py` 使用。

- `rag_eval_regression.json`
  - 正式回归数据集。
  - 当前暂时与 `rag_eval_auto.json` 相同。
  - 等样本稳定后再精选成发版 / 汇报用 benchmark。

## 字段说明

- `question`：评测问题。
- `eval_schema_version`：数据结构版本。当前为 `phase1_v1`。
- `review_status`：人工复查状态。当前新生成样本默认为 `pending_human_review`。
- `is_smoke_case`：是否属于 smoke case。通常等价于是否有稳定 `gold_chunk_ids`。
- `question_type`：题型，例如 `definition`、`comparison`、`method`、`criterion`、`limitation`、`application`。
- `expected_corpus`：期望证据来源类型，例如 `official`、`project_note`、`mixed`。
- `expected_sources`：期望证据来自哪些文档，文档级来源比 chunk id 更稳定。
- `expected_claims`：回答应该覆盖的核心知识点，是后续自动评估的主要语义标准。
- `reference_answer`：参考答案，用于 Ragas / LLM judge / claim coverage。
- `gold_chunk_ids`：可选的 chunk 级 gold，只用于 smoke test 和少量强基准。
- `gold_doc_ids`：兼容旧流程的文档级 gold。
- `judge_rubric`：自动评估时的判分标准，包含 `must_cover` 和 `avoid`。
- `notes`：人工标注说明、复查提示和 bad case 分析提示。

## review_status 建议值

- `pending_human_review`：机器辅助生成后尚未人工复查。
- `reviewed`：已经人工复查，语义标准可以用于自动评估。
- `needs_revision`：发现问题，需要修改 expected claims 或 rubric。

当前 Phase1 的目标是先把结构搭好，因此大多数样本会先标记为 `pending_human_review`。你复查通过后，再逐条改为 `reviewed`。

## 维护原则

- 不再大规模人工维护 `gold_chunk_ids`。
- 新问题优先补 `expected_claims`、`reference_answer`、`judge_rubric`。
- `gold_chunk_ids` 只给最核心、最稳定的 smoke case 使用。
- 知识库扩充后，优先复查 `expected_claims` 是否仍然合理，而不是重新找所有 chunk id。
