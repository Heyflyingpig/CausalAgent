"""多模态生产默认配置与人工检索集契约测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from Agent.knowledge_base.multimodal.production import (
    audit_production_coverage,
    evaluate_retrieval_cases,
    is_production_manifest,
    load_production_defaults,
    production_source_paths,
)


class MultimodalProductionDefaultsTests(unittest.TestCase):
    """锁定 P0 的来源、embedding、评测 schema 与首轮门槛。"""

    def test_frozen_defaults_match_local_files_and_embedding_contract(self) -> None:
        """默认配置必须固定本地 embedding 并校验全部必需来源的哈希。"""
        config = load_production_defaults()

        self.assertEqual(
            config["embedding"],
            {
                "provider": "huggingface",
                "model": "bge-small-zh-v1.5",
                "dimension": 512,
                "normalized": True,
            },
        )
        self.assertFalse(config["vision"]["remote_enabled"])
        self.assertEqual(config["parser"], "docling")
        self.assertEqual(
            config["pdf_parser"],
            {"page_range_mode": "single_page", "process_isolation": "spawn_per_page", "page_timeout_seconds": 900},
        )
        self.assertEqual(len(config["sources"]), 2)
        self.assertTrue(all(source["required"] for source in config["sources"]))
        self.assertTrue(all(path.is_file() for path in production_source_paths(config)))

    def test_manual_evaluation_set_has_24_complete_reviewed_cases(self) -> None:
        """首轮评测集必须是 20 至 30 条且具备截图要求的人工字段。"""
        config = load_production_defaults()
        dataset_path = Path(__file__).parents[1] / config["evaluation"]["dataset_path"]
        payload = json.loads(dataset_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], "multimodal_retrieval_eval_v1")
        self.assertEqual(len(payload["cases"]), 24)
        for case in payload["cases"]:
            self.assertTrue(case["question"])
            self.assertTrue(case["gold_doc_ids"])
            self.assertTrue(case["gold_page_numbers"])
            self.assertIn(case["expected_modality"], {"text", "table", "image"})
            self.assertTrue(case["reference_answer"] or case["key_facts"])
            self.assertTrue(case["human_reviewed"])

    def test_retrieval_metrics_use_exact_document_and_page_locator(self) -> None:
        """Hit、MRR 和引用定位不得退化成仅匹配两本书的文档级指标。"""
        cases = [
            {
                "case_id": "case-1",
                "question": "q1",
                "gold_doc_ids": ["doc-a"],
                "gold_page_numbers": [7],
                "expected_modality": "text",
            },
            {
                "case_id": "case-2",
                "question": "q2",
                "gold_doc_ids": ["doc-b"],
                "gold_page_numbers": [3],
                "expected_modality": "table",
            },
        ]
        responses = {
            "case-1": [
                {"document_id": "doc-a", "page_number": 6, "modality": "text"},
                {"document_id": "doc-a", "page_number": 7, "modality": "text"},
            ],
            "case-2": [],
        }

        result = evaluate_retrieval_cases(cases, responses, k=5)

        self.assertEqual(result["case_count"], 2)
        self.assertEqual(result["hit_at_5"], 0.5)
        self.assertEqual(result["mrr"], 0.25)
        self.assertEqual(result["citation_location_accuracy"], 0.0)
        self.assertEqual(result["empty_result_rate"], 0.5)

    def test_retrieval_metrics_require_expected_modality(self) -> None:
        """同页正文不能冒充评测题要求的图片或表格证据。"""
        cases = [{
            "case_id": "image-case",
            "question": "q",
            "gold_doc_ids": ["doc-a"],
            "gold_page_numbers": [7],
            "expected_modality": "image",
        }]
        responses = {
            "image-case": [
                {"document_id": "doc-a", "page_number": 7, "modality": "text"},
                {"document_id": "doc-a", "page_number": 7, "modality": "image"},
            ]
        }

        result = evaluate_retrieval_cases(cases, responses, k=5)

        self.assertEqual(result["hit_at_5"], 1.0)
        self.assertEqual(result["mrr"], 0.5)
        self.assertEqual(result["citation_location_accuracy"], 0.0)

    def test_production_coverage_requires_every_gold_page_and_modality(self) -> None:
        """正式检索前必须证明 gold 页存在对应模态的可索引单元。"""
        cases = [
            {"case_id": "text", "gold_doc_ids": ["doc-a"], "gold_page_numbers": [1], "expected_modality": "text"},
            {"case_id": "image", "gold_doc_ids": ["doc-a"], "gold_page_numbers": [2], "expected_modality": "image"},
        ]
        units = [
            {"document_id": "doc-a", "page_number": 1, "modality": "text"},
            {"document_id": "doc-a", "page_number": 2, "modality": "text"},
        ]

        coverage = audit_production_coverage(units, cases)

        self.assertFalse(coverage["passed"])
        self.assertEqual(coverage["covered_gold_pages"], 2)
        self.assertEqual(coverage["total_gold_pages"], 2)
        self.assertEqual(coverage["missing_modality_cases"], ["image"])

    def test_threshold_gate_reports_each_failed_metric(self) -> None:
        """固定阈值必须逐项阻止不合格评测结果。"""
        from Agent.knowledge_base.multimodal.production import apply_thresholds

        metrics = {
            "hit_at_5": 0.69,
            "mrr": 0.49,
            "citation_location_accuracy": 0.59,
            "empty_result_rate": 0.11,
        }
        thresholds = {
            "min_hit_at_5": 0.70,
            "min_mrr": 0.50,
            "min_citation_location_accuracy": 0.60,
            "max_empty_result_rate": 0.10,
        }

        gate = apply_thresholds(metrics, thresholds)

        self.assertFalse(gate["passed"])
        self.assertEqual(
            gate["failures"],
            [
                "hit_at_5_below_minimum",
                "mrr_below_minimum",
                "citation_location_accuracy_below_minimum",
                "empty_result_rate_above_maximum",
            ],
        )

    def test_benchmark_sources_cannot_satisfy_the_production_source_contract(self) -> None:
        """OmniDocBench 等测试来源不得被误判为冻结的正式知识源。"""
        config = load_production_defaults()
        production_manifest = {
            "sources": [
                {"relative_path": Path(source["path"]).name, "content_hash": source["sha256"]}
                for source in config["sources"]
            ]
        }

        self.assertTrue(is_production_manifest(production_manifest, config))
        self.assertFalse(
            is_production_manifest(
                {"sources": [{"relative_path": "images/benchmark.png", "content_hash": "a" * 64}]},
                config,
            )
        )


if __name__ == "__main__":
    unittest.main()
