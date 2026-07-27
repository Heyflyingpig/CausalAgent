"""冻结的多模态生产默认值与人工检索评测门禁。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from langchain_chroma import Chroma

from .defaults import ROOT, load_production_defaults, production_source_paths
from .index import _embeddings

def load_evaluation_cases(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """读取 20 至 30 条人工核对评测题并验证最小 schema。"""
    config = config or load_production_defaults()
    path = (ROOT / config["evaluation"]["dataset_path"]).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases", [])
    if payload.get("schema_version") != "multimodal_retrieval_eval_v1" or not 20 <= len(cases) <= 30:
        raise ValueError("production evaluation dataset must contain 20 to 30 v1 cases")
    required = {"case_id", "question", "gold_doc_ids", "gold_page_numbers", "expected_modality", "human_reviewed"}
    for case in cases:
        if not required.issubset(case) or not case["gold_doc_ids"] or not case["gold_page_numbers"] or not case["human_reviewed"]:
            raise ValueError(f"incomplete production evaluation case: {case.get('case_id', '<unknown>')}")
    return cases


def evaluate_retrieval_cases(
    cases: list[dict[str, Any]],
    responses: dict[str, list[dict[str, Any]]],
    *,
    k: int = 5,
) -> dict[str, Any]:
    """按精确文档与页码定位计算 Hit@k、MRR、首条引用准确率和空结果率。"""
    hits = 0
    reciprocal_ranks = 0.0
    correct_first_citations = 0
    empty = 0
    rows: list[dict[str, Any]] = []
    for case in cases:
        evidence = responses.get(case["case_id"], [])[:k]
        if not evidence:
            empty += 1
        relevant = [_matches_gold(item, case) for item in evidence]
        rank = next((index for index, matched in enumerate(relevant, 1) if matched), None)
        if rank is not None:
            hits += 1
            reciprocal_ranks += 1 / rank
        if relevant and relevant[0]:
            correct_first_citations += 1
        rows.append(
            {
                "case_id": case["case_id"],
                "hit": rank is not None,
                "first_relevant_rank": rank,
                "empty": not evidence,
                "top_document_id": evidence[0].get("document_id") if evidence else None,
                "top_page_number": evidence[0].get("page_number") if evidence else None,
                "top_modality": evidence[0].get("modality") if evidence else None,
                "expected_modality": case["expected_modality"],
            }
        )
    count = len(cases)
    if not count:
        raise ValueError("at least one evaluation case is required")
    return {
        "case_count": count,
        f"hit_at_{k}": round(hits / count, 6),
        "mrr": round(reciprocal_ranks / count, 6),
        "citation_location_accuracy": round(correct_first_citations / count, 6),
        "empty_result_rate": round(empty / count, 6),
        "cases": rows,
    }


def apply_thresholds(metrics: dict[str, Any], thresholds: dict[str, float]) -> dict[str, Any]:
    """用预先冻结的四项阈值判定生产检索门禁。"""
    failures: list[str] = []
    if metrics["hit_at_5"] < thresholds["min_hit_at_5"]:
        failures.append("hit_at_5_below_minimum")
    if metrics["mrr"] < thresholds["min_mrr"]:
        failures.append("mrr_below_minimum")
    if metrics["citation_location_accuracy"] < thresholds["min_citation_location_accuracy"]:
        failures.append("citation_location_accuracy_below_minimum")
    if metrics["empty_result_rate"] > thresholds["max_empty_result_rate"]:
        failures.append("empty_result_rate_above_maximum")
    return {"passed": not failures, "thresholds": thresholds, "failures": failures}


def evaluate_with_search(
    search: Callable[[str, int], list[dict[str, Any]]],
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """运行冻结题集并返回包含阈值结论的可持久化报告。"""
    config = config or load_production_defaults()
    cases = load_evaluation_cases(config)
    responses = {case["case_id"]: search(case["question"], 5) for case in cases}
    metrics = evaluate_retrieval_cases(cases, responses, k=5)
    return metrics | {"gate": apply_thresholds(metrics, config["evaluation"]["thresholds"])}


def is_production_manifest(manifest: dict[str, Any], config: dict[str, Any] | None = None) -> bool:
    """判断 manifest 是否精确对应冻结的两项正式资料。"""
    config = config or load_production_defaults()
    expected = {(Path(source["path"]).name, source["sha256"]) for source in config["sources"]}
    actual = {(source.get("relative_path"), source.get("content_hash")) for source in manifest.get("sources", [])}
    return actual == expected


def validate_production_manifest(manifest: dict[str, Any], config: dict[str, Any] | None = None) -> list[str]:
    """拒绝正式资料使用未冻结的 parser、远程视觉或 embedding。"""
    config = config or load_production_defaults()
    failures: list[str] = []
    if manifest.get("parser") != config["parser"]:
        failures.append("production_parser_mismatch")
    if manifest.get("build_configuration", {}).get("pdf_parser") != config["pdf_parser"]:
        failures.append("production_pdf_parser_strategy_mismatch")
    if manifest.get("build_configuration", {}).get("vision", {}).get("enabled") != config["vision"]["remote_enabled"]:
        failures.append("production_vision_policy_mismatch")
    actual = manifest.get("embedding", {})
    if any(actual.get(key) != value for key, value in config["embedding"].items()):
        failures.append("production_embedding_mismatch")
    return failures


def evaluate_staged_index(version_dir: Path, collection_name: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """直接评测尚未发布的不可变索引，并在版本目录保存门禁报告。"""
    config = config or load_production_defaults()
    units = {
        unit["unit_id"]: unit
        for line in (version_dir / "units.jsonl").read_text(encoding="utf-8").splitlines()
        if line
        for unit in [json.loads(line)]
    }
    database = Chroma(
        persist_directory=str(version_dir / "chroma"),
        collection_name=collection_name,
        embedding_function=_embeddings(),
    )

    def search(question: str, k: int) -> list[dict[str, Any]]:
        """把 Chroma 结果收缩为评测所需的稳定定位字段。"""
        evidence: list[dict[str, Any]] = []
        for document, _score in database.similarity_search_with_relevance_scores(question, k=k):
            unit = units.get(document.metadata.get("unit_id"), {})
            evidence.append(
                {
                    "unit_id": unit.get("unit_id"),
                    "document_id": unit.get("document_id"),
                    "page_number": unit.get("page_number"),
                    "modality": unit.get("modality"),
                }
            )
        return evidence

    report = evaluate_with_search(search, config=config)
    (version_dir / "production_evaluation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def _matches_gold(evidence: dict[str, Any], case: dict[str, Any]) -> bool:
    """优先匹配可选 unit gold，否则要求文档与页码同时命中。"""
    unit_ids = case.get("gold_unit_ids") or []
    if unit_ids:
        return evidence.get("unit_id") in unit_ids
    return evidence.get("document_id") in case["gold_doc_ids"] and evidence.get("page_number") in case["gold_page_numbers"]
