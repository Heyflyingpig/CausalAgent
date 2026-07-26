import unittest
from unittest.mock import patch

from Agent.knowledge_base.rag.operation_datasets.dataset_utils import validate_benchmark_v2_dataset
from Agent.knowledge_base.rag.rag_eval import rag_eval, trace_export
from Agent.knowledge_base import query_rag


class RagEvalCoreLogicTests(unittest.TestCase):
    def test_benchmark_v2_schema_rejects_missing_gold_doc(self):
        sample = {
            "sample_id": "s1",
            "question": "Does treatment work?",
            "reference_answer": "It may work in the studied population.",
            "expected_claims": ["It may work."],
            "gold_doc_ids": ["missing_doc"],
            "source": {"dataset": "unit", "row_index": 1},
        }

        result = validate_benchmark_v2_dataset([sample], available_doc_ids={"doc1"}, dataset_name="unit")

        self.assertTrue(result["errors"])
        self.assertTrue(any("gold_doc_ids not found" in error for error in result["errors"]))

    def test_retrieval_metric_uses_doc_level_gold_when_chunk_gold_absent(self):
        candidates = [
            {"metadata": {"chunk_id": "other#p0#c0", "doc_id": "other"}},
            {"metadata": {"chunk_id": "doc1#p0#c0", "doc_id": "doc1"}},
        ]

        metrics = rag_eval._collect_stage_metrics(candidates, gold_chunk_ids=set(), gold_doc_ids={"doc1"})

        self.assertEqual(metrics["match_mode"], "doc")
        self.assertEqual(metrics["recall"], 1.0)
        self.assertEqual(metrics["reciprocal_rank"], 0.5)
        self.assertEqual(metrics["matched_doc_ids"], ["doc1"])

    def test_retrieval_cancels_after_current_sample_and_emits_progress(self):
        dataset = [
            {"sample_id": "s1", "question": "q1", "gold_doc_ids": ["doc1"]},
            {"sample_id": "s2", "question": "q2", "gold_doc_ids": ["doc2"]},
        ]
        candidate = {"metadata": {"chunk_id": "doc1#p0#c0", "doc_id": "doc1"}, "page_content": "ctx"}
        trace = {
            "stages": {stage: [candidate] for stage in rag_eval.TRACE_STAGE_ORDER},
            "timings_ms": {},
            "evidence_payload": [],
        }
        events = []

        with patch.object(rag_eval, "_validate_vector_store_matches_dataset", return_value={}), \
            patch.object(rag_eval, "build_retrieval_trace", return_value=trace):
            result = rag_eval.evaluate_retrieval(
                dataset,
                event_callback=lambda event_type, message, data: events.append((event_type, data)),
                cancel_checker=lambda: bool(events),
            )

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["sample_count"], 1)
        self.assertEqual(result["cancelled_after_samples"], 1)
        self.assertEqual([event_type for event_type, _data in events], ["step_progress", "step_progress"])
        self.assertEqual(events[0][1]["current"], 1)
        self.assertEqual(events[0][1]["total"], 2)

    def test_ragas_dataset_cancels_after_current_sample_and_emits_progress(self):
        from Agent.knowledge_base.rag.rag_eval import ragas_eval

        dataset = [
            {"sample_id": "s1", "question": "q1", "gold_doc_ids": ["doc1"], "reference_answer": "a1"},
            {"sample_id": "s2", "question": "q2", "gold_doc_ids": ["doc2"], "reference_answer": "a2"},
        ]
        events = []

        def fake_row(sample, *_args, **_kwargs):
            return {
                "ragas_row": {"user_input": sample["question"], "response": "answer", "retrieved_contexts": []},
                "metadata": {"sample_id": sample["sample_id"], "question": sample["question"]},
            }

        with patch.object(ragas_eval, "load_eval_dataset", return_value=dataset), \
            patch.object(ragas_eval, "_build_ragas_eval_row", side_effect=fake_row), \
            patch.object(ragas_eval, "_sha256_file", return_value="unit"), \
            patch.object(ragas_eval, "get_vector_db_metadata_summary", return_value={}):
            result = ragas_eval.build_ragas_dataset(
                dataset_path="unused.json",
                event_callback=lambda event_type, message, data: events.append((event_type, data)),
                cancel_checker=lambda: bool(events),
            )

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["sample_count"], 1)
        self.assertEqual(result["cancelled_after_samples"], 1)
        self.assertEqual([event_type for event_type, _data in events], ["step_progress", "step_progress"])
        self.assertEqual(events[0][1]["phase"], "build_dataset")
        self.assertEqual(events[0][1]["current"], 1)

    def test_trace_rows_align_retrieval_ragas_and_claim_by_question(self):
        config = {
            "retrieval_result_path": "unused_retrieval.json",
            "ragas_result_path": "unused_ragas.json",
            "claim_result_path": "unused_claim.json",
            "ragas_low_cases_path": "unused_low.json",
            "ragas_cross_cases_path": "unused_cross.json",
            "claim_bad_cases_path": "unused_claim_bad.json",
            "context_preview_chars": 120,
            "answer_preview_chars": 120,
        }
        payloads = {
            "unused_retrieval.json": {
                "details": [{"question": "q1", "recall": 1.0, "reciprocal_rank": 1.0, "stage_results": {}}]
            },
            "unused_ragas.json": {
                "ragas_rows": [{"user_input": "q1", "response": "a1", "retrieved_context_ids": ["c1"], "retrieved_contexts": ["ctx"]}],
                "metadata": [{"question": "q1", "expected_claims": ["claim"], "citations": ["E1"]}],
                "score_records": [{"user_input": "q1", "faithfulness": 1.0, "answer_relevancy": 0.9}],
            },
            "unused_claim.json": {"details": [{"question": "q1", "claim_coverage": 1.0}]},
            "unused_low.json": {"cases": []},
            "unused_cross.json": {"cases": []},
            "unused_claim_bad.json": {"bad_cases": []},
        }

        with patch.object(trace_export, "_load_json_object", side_effect=lambda path, default=None: payloads.get(path.name, default or {})):
            rows = trace_export._build_trace_rows(config)

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["data_availability"]["has_retrieval_eval"])
        self.assertTrue(rows[0]["data_availability"]["has_ragas_eval"])
        self.assertFalse(rows[0]["data_availability"]["has_claim_eval"])
        self.assertEqual(rows[0]["generation"]["retrieved_context_ids"], ["c1"])

    def test_get_rag_response_uses_published_retrieval_config(self):
        published_config = query_rag.RagRetrievalConfig(final_top_k=7, max_evidence_chars=1234)
        candidate = {
            "metadata": {
                "chunk_id": "doc#c1",
                "doc_id": "doc",
                "source_name": "unit",
                "title": "unit",
            },
            "page_content": "x" * 2000,
        }
        captured = {}

        def fake_retrieve(_question, config=None):
            captured["config"] = config
            return [candidate]

        def fake_answer(_question_payload, evidence_payloads, **_kwargs):
            captured["evidence_len"] = len(evidence_payloads[0]["content"])
            return {"answer": "ok", "retrieved_docs": evidence_payloads}

        with patch.object(query_rag, "_load_production_rag_config", return_value=(published_config, "published_config")), \
            patch.object(query_rag, "_retrieve_candidates", side_effect=fake_retrieve), \
            patch.object(query_rag, "_answer_question", side_effect=fake_answer), \
            patch.object(query_rag, "format_rag_summary_for_prompt", return_value="summary"):
            result = query_rag.get_rag_response(["q"])

        self.assertTrue(result["success"])
        self.assertEqual(captured["config"], published_config)
        self.assertEqual(captured["evidence_len"], 1234)


if __name__ == "__main__":
    unittest.main()
