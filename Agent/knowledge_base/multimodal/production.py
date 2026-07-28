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
    modality_totals: dict[str, dict[str, float]] = {}
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
        modality = case["expected_modality"]
        grouped = modality_totals.setdefault(modality, {"count": 0, "hits": 0, "reciprocal_ranks": 0.0, "correct_first": 0, "empty": 0})
        grouped["count"] += 1
        grouped["hits"] += int(rank is not None)
        grouped["reciprocal_ranks"] += 1 / rank if rank is not None else 0
        grouped["correct_first"] += int(bool(relevant and relevant[0]))
        grouped["empty"] += int(not evidence)
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
    by_modality = {
        modality: {
            "case_count": int(values["count"]),
            f"hit_at_{k}": round(values["hits"] / values["count"], 6),
            "mrr": round(values["reciprocal_ranks"] / values["count"], 6),
            "citation_location_accuracy": round(values["correct_first"] / values["count"], 6),
            "empty_result_rate": round(values["empty"] / values["count"], 6),
        }
        for modality, values in modality_totals.items()
    }
    return {
        "case_count": count,
        f"hit_at_{k}": round(hits / count, 6),
        "mrr": round(reciprocal_ranks / count, 6),
        "citation_location_accuracy": round(correct_first_citations / count, 6),
        "empty_result_rate": round(empty / count, 6),
        "by_modality": by_modality,
        "cases": rows,
    }


def audit_production_coverage(
    units: list[dict[str, Any]],
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """在检索前校验每个 gold 页及其期望模态均已进入索引。"""
    locators = {
        (unit.get("document_id"), unit.get("page_number"), unit.get("modality"))
        for unit in units
    }
    page_locators = {(document_id, page_number) for document_id, page_number, _ in locators}
    total_gold_pages = 0
    covered_gold_pages = 0
    missing_page_cases: list[str] = []
    missing_modality_cases: list[str] = []
    modality_counts: dict[str, int] = {"text": 0, "image": 0, "table": 0}
    for case in cases:
        expected = case["expected_modality"]
        gold = {
            (document_id, page_number)
            for document_id in case["gold_doc_ids"]
            for page_number in case["gold_page_numbers"]
        }
        total_gold_pages += len(gold)
        covered = gold & page_locators
        covered_gold_pages += len(covered)
        if covered != gold:
            missing_page_cases.append(case["case_id"])
        if not all((document_id, page_number, expected) in locators for document_id, page_number in gold):
            missing_modality_cases.append(case["case_id"])
        else:
            modality_counts[expected] = modality_counts.get(expected, 0) + 1
    return {
        "passed": not missing_page_cases and not missing_modality_cases,
        "case_count": len(cases),
        "total_gold_pages": total_gold_pages,
        "covered_gold_pages": covered_gold_pages,
        "missing_page_cases": missing_page_cases,
        "missing_modality_cases": missing_modality_cases,
        "covered_cases_by_modality": modality_counts,
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
    if manifest.get("build_configuration", {}).get("vision", {}).get("local_ocr_enabled") != config["vision"]["local_ocr_enabled"]:
        failures.append("production_local_ocr_policy_mismatch")
    actual = manifest.get("embedding", {})
    if any(actual.get(key) != value for key, value in config["embedding"].items()):
        failures.append("production_embedding_mismatch")
    return failures


def evaluate_staged_index(version_dir: Path, collection_name: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """直接评测尚未发布的不可变索引，并在版本目录保存门禁报告。"""
    from Agent.knowledge_base import query_rag
    from Agent.knowledge_base.sparse_retriever import Bm25sSparseRetriever

    config = config or load_production_defaults()
    units = {
        unit["unit_id"]: unit
        for line in (version_dir / "units.jsonl").read_text(encoding="utf-8").splitlines()
        if line
        for unit in [json.loads(line)]
    }
    embedding = _embeddings()
    database = Chroma(
        persist_directory=str(version_dir / "chroma"),
        collection_name=collection_name,
        embedding_function=embedding,
    )
    sparse_retriever = Bm25sSparseRetriever.from_vector_db(database)
    retrieval_config = query_rag._load_production_rag_config()[0]

    def search(question: str, k: int) -> list[dict[str, Any]]:
        """把正式 Runtime 检索 trace 收缩为评测所需的稳定定位字段。"""
        trace = query_rag._build_retrieval_trace_with_resources(
            question,
            retrieval_config,
            vector_db=database,
            embedding_function=embedding,
            sparse_retriever=sparse_retriever,
        )
        evidence: list[dict[str, Any]] = []
        for candidate in trace["stages"]["final"][:k]:
            metadata = candidate["metadata"]
            unit = units.get(metadata.get("unit_id") or metadata.get("chunk_id"), {})
            evidence.append(
                {
                    "unit_id": unit.get("unit_id") or metadata.get("unit_id") or metadata.get("chunk_id"),
                    "document_id": unit.get("document_id") or metadata.get("document_id") or metadata.get("doc_id"),
                    "page_number": unit.get("page_number") or metadata.get("page_number") or metadata.get("page"),
                    "modality": unit.get("modality") or metadata.get("modality"),
                }
            )
        return evidence

    cases = load_evaluation_cases(config)
    coverage = audit_production_coverage(list(units.values()), cases)
    if coverage["passed"]:
        report = evaluate_with_search(search, config=config)
    else:
        report = {
            "case_count": len(cases),
            "hit_at_5": 0.0,
            "mrr": 0.0,
            "citation_location_accuracy": 0.0,
            "empty_result_rate": 1.0,
            "cases": [],
            "gate": {
                "passed": False,
                "thresholds": config["evaluation"]["thresholds"],
                "failures": ["production_coverage_failed"],
            },
        }
    report["coverage"] = coverage
    (version_dir / "production_evaluation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def _matches_gold(evidence: dict[str, Any], case: dict[str, Any]) -> bool:
    """优先匹配可选 unit gold，否则要求文档与页码同时命中。"""
    if evidence.get("modality") != case["expected_modality"]:
        return False
    unit_ids = case.get("gold_unit_ids") or []
    if unit_ids:
        return evidence.get("unit_id") in unit_ids
    return evidence.get("document_id") in case["gold_doc_ids"] and evidence.get("page_number") in case["gold_page_numbers"]
