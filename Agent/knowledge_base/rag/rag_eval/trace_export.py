import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from Agent.knowledge_base.rag.tools.report_utils import (
        build_trace_markdown_report,
        write_markdown_file,
    )
except ModuleNotFoundError:
    project_root = Path(__file__).resolve().parents[4]
    import sys

    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from Agent.knowledge_base.rag.tools.report_utils import build_trace_markdown_report, write_markdown_file


RAG_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = RAG_DIR / "output"
MACHINE_OUTPUT_DIR = OUTPUT_DIR / "machine"
REPORT_OUTPUT_DIR = OUTPUT_DIR / "reports"

DEFAULT_RETRIEVAL_RESULT_PATH = MACHINE_OUTPUT_DIR / "rag_eval_result.json"
DEFAULT_RAGAS_RESULT_PATH = MACHINE_OUTPUT_DIR / "ragas_eval_result.json"
DEFAULT_CLAIM_RESULT_PATH = MACHINE_OUTPUT_DIR / "claim_eval_result.json"
DEFAULT_RAGAS_LOW_CASES_PATH = MACHINE_OUTPUT_DIR / "ragas_low_score_cases.json"
DEFAULT_RAGAS_CROSS_CASES_PATH = MACHINE_OUTPUT_DIR / "ragas_cross_metric_bad_cases.json"
DEFAULT_CLAIM_BAD_CASES_PATH = MACHINE_OUTPUT_DIR / "claim_eval_bad_cases.json"
DEFAULT_TRACE_JSONL_PATH = MACHINE_OUTPUT_DIR / "trace.jsonl"
DEFAULT_TRACE_INDEX_PATH = MACHINE_OUTPUT_DIR / "trace_index.json"
DEFAULT_REPORT_PATH = REPORT_OUTPUT_DIR / "trace_report.md"

TRACE_STAGE_ORDER = [
    "dense_raw",
    "dense_thresholded",
    "dense_mmr",
    "sparse",
    "merged_before_rerank",
    "reranked",
    "final",
]

# 本地手动运行时优先改这里。
# trace_export.py 只消费现有评测输出，不重新调用知识库、不调用 LLM judge。
TRACE_EXPORT_CONFIG = {
    "retrieval_result_path": str(DEFAULT_RETRIEVAL_RESULT_PATH),
    "ragas_result_path": str(DEFAULT_RAGAS_RESULT_PATH),
    "claim_result_path": str(DEFAULT_CLAIM_RESULT_PATH),
    "ragas_low_cases_path": str(DEFAULT_RAGAS_LOW_CASES_PATH),
    "ragas_cross_cases_path": str(DEFAULT_RAGAS_CROSS_CASES_PATH),
    "claim_bad_cases_path": str(DEFAULT_CLAIM_BAD_CASES_PATH),
    "trace_jsonl_path": str(DEFAULT_TRACE_JSONL_PATH),
    "trace_index_path": str(DEFAULT_TRACE_INDEX_PATH),
    "report_path": str(DEFAULT_REPORT_PATH),
    "context_preview_chars": 240,
    "answer_preview_chars": 360,
    "save_output": True,
    "save_markdown": True,
}


def _ensure_parent_dir(path: Path) -> None:
    """确保输出文件所在目录存在。"""
    path.parent.mkdir(parents=True, exist_ok=True)


def _load_json_object(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """读取 JSON object；文件不存在时返回 default。"""
    if not path.exists():
        return default or {}
    with path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object.")
    return data


def _write_json_file(path: Path, data: Dict[str, Any]) -> None:
    """写入机器可读 JSON。"""
    _ensure_parent_dir(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl_file(path: Path, rows: List[Dict[str, Any]]) -> None:
    """写入 JSONL trace，每行对应一个 question。"""
    _ensure_parent_dir(path)
    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(content + ("\n" if content else ""), encoding="utf-8")


def _truncate_text(text: Any, max_chars: int) -> str:
    """生成单行预览文本，避免 trace report 过长。"""
    if text is None:
        return ""
    normalized = str(text).replace("\n", " ").strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3] + "..."


def _question_key(question: str) -> str:
    """生成用于跨文件对齐的 question key。"""
    return " ".join(question.strip().split())


def _build_trace_id(index: int, question: str) -> str:
    """生成稳定可检索 trace id。"""
    digest = hashlib.md5(question.encode("utf-8")).hexdigest()[:8]
    return f"q{index:03d}_{digest}"


def _index_by_question(rows: List[Dict[str, Any]], question_field: str = "question") -> Dict[str, Dict[str, Any]]:
    """把逐题结果按 question 建索引。"""
    indexed = {}
    for row in rows:
        question = row.get(question_field, "")
        if question:
            indexed[_question_key(question)] = row
    return indexed


def _index_ragas_scores(ragas_result: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """从 Ragas score_records 中抽取逐题指标。"""
    indexed = {}
    for row in ragas_result.get("score_records", []):
        question = row.get("user_input", "")
        if not question:
            continue
        indexed[_question_key(question)] = {
            "faithfulness": row.get("faithfulness"),
            "answer_relevancy": row.get("answer_relevancy"),
            "context_utilization": row.get("context_utilization"),
            "context_recall": row.get("context_recall"),
            "metric_run_values": row.get("metric_run_values", {}),
        }
    return indexed


def _index_ragas_rows(ragas_result: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """把 Ragas prepared rows 和 metadata 合并为生成链路输入。"""
    indexed = {}
    metadata_rows = ragas_result.get("metadata", [])
    ragas_rows = ragas_result.get("ragas_rows", [])
    for index, row in enumerate(ragas_rows):
        metadata = metadata_rows[index] if index < len(metadata_rows) else {}
        question = metadata.get("question") or row.get("user_input", "")
        if not question:
            continue
        indexed[_question_key(question)] = {
            "question_index": index + 1,
            "question": question,
            "question_type": metadata.get("question_type", ""),
            "expected_claims": metadata.get("expected_claims", []),
            "reference_answer": metadata.get("reference_answer", row.get("reference", "")),
            "answer": row.get("response", ""),
            "answer_status": metadata.get("answer_status", ""),
            "answer_confidence": metadata.get("answer_confidence", ""),
            "retrieved_context_ids": row.get("retrieved_context_ids", []),
            "retrieved_contexts": row.get("retrieved_contexts", []),
            "final_evidence_payload": metadata.get("final_evidence_payload", []),
            "trace_timings_ms": metadata.get("trace_timings_ms", {}),
            "citations": metadata.get("citations", []),
        }
    return indexed


def _index_case_reasons(case_result: Dict[str, Any], reason_prefix: str) -> Dict[str, List[Dict[str, Any]]]:
    """把 bad case 文件按 question 聚合。"""
    indexed: Dict[str, List[Dict[str, Any]]] = {}
    for case in case_result.get("cases", []) + case_result.get("bad_cases", []):
        question = case.get("question", "")
        if not question:
            continue
        normalized = dict(case)
        normalized["source"] = reason_prefix
        indexed.setdefault(_question_key(question), []).append(normalized)
    return indexed


def _summarize_stage_results(stage_results: Dict[str, Any]) -> List[Dict[str, Any]]:
    """压缩 retrieval stage trace，保留每阶段 top ids 和命中信息。"""
    summarized = []
    for stage_name in TRACE_STAGE_ORDER:
        stage = stage_results.get(stage_name)
        if not isinstance(stage, dict):
            continue
        summarized.append(
            {
                "stage": stage_name,
                "retrieved_chunk_ids": stage.get("retrieved_chunk_ids", []),
                "matched_chunk_ids": stage.get("matched_chunk_ids", []),
                "recall": stage.get("recall"),
                "reciprocal_rank": stage.get("reciprocal_rank"),
                "hit": stage.get("hit"),
            }
        )
    return summarized


def _build_retrieval_trace(retrieval_row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """构造单题 retrieval eval trace；没有 gold 评测时返回可识别空对象。"""
    if not retrieval_row:
        return {"has_retrieval_eval": False}
    return {
        "has_retrieval_eval": True,
        "gold_chunk_ids": retrieval_row.get("gold_chunk_ids", []),
        "gold_doc_ids": retrieval_row.get("gold_doc_ids", []),
        "retrieved_chunk_ids": retrieval_row.get("retrieved_chunk_ids", []),
        "matched_chunk_ids": retrieval_row.get("matched_chunk_ids", []),
        "recall": retrieval_row.get("recall"),
        "reciprocal_rank": retrieval_row.get("reciprocal_rank"),
        "loss_reasons": retrieval_row.get("loss_reasons", []),
        "gold_rank_summary": retrieval_row.get("gold_rank_summary", {}),
        "stage_results": _summarize_stage_results(retrieval_row.get("stage_results", {})),
        "trace_timings_ms": retrieval_row.get("trace_timings_ms", {}),
    }


def _build_generation_trace(row: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """构造单题 generation / final evidence trace。"""
    context_preview_chars = int(config["context_preview_chars"])
    answer_preview_chars = int(config["answer_preview_chars"])
    contexts = row.get("retrieved_contexts", [])
    return {
        "answer_status": row.get("answer_status", ""),
        "answer_confidence": row.get("answer_confidence", ""),
        "answer": row.get("answer", ""),
        "answer_preview": _truncate_text(row.get("answer", ""), answer_preview_chars),
        "retrieved_context_ids": row.get("retrieved_context_ids", []),
        "context_count": len(contexts),
        "context_previews": [_truncate_text(context, context_preview_chars) for context in contexts],
        "final_evidence_payload": row.get("final_evidence_payload", []),
        "trace_timings_ms": row.get("trace_timings_ms", {}),
        "citations": row.get("citations", []),
    }


def _build_claim_trace(claim_row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """构造单题 claim eval trace。"""
    if not claim_row:
        return {"has_claim_eval": False}
    return {
        "has_claim_eval": True,
        "claim_eval_status": claim_row.get("claim_eval_status", ""),
        "judge_failed": claim_row.get("judge_failed", False),
        "claim_coverage": claim_row.get("claim_coverage"),
        "evidence_support_rate": claim_row.get("evidence_support_rate"),
        "missing_claims": claim_row.get("missing_claims", []),
        "unsupported_expected_claims": claim_row.get("unsupported_expected_claims", []),
        "unsupported_answer_claims": claim_row.get("unsupported_answer_claims", []),
        "unsupported_answer_claim_count": claim_row.get("unsupported_answer_claim_count", 0),
        "claim_results": claim_row.get("claim_results", []),
        "overall_notes": claim_row.get("overall_notes", ""),
    }


def _collect_cases(question_key: str, *case_indexes: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """收集某个 question 对应的全部 bad case 记录。"""
    cases = []
    for case_index in case_indexes:
        cases.extend(case_index.get(question_key, []))
    return cases


def _build_trace_rows(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """读取所有评测输出并按 question 对齐为 trace rows。"""
    retrieval_result = _load_json_object(Path(config["retrieval_result_path"]))
    ragas_result = _load_json_object(Path(config["ragas_result_path"]))
    ragas_low_cases = _load_json_object(Path(config["ragas_low_cases_path"]))
    ragas_cross_cases = _load_json_object(Path(config["ragas_cross_cases_path"]))

    retrieval_by_question = _index_by_question(retrieval_result.get("details", []))
    ragas_rows_by_question = _index_ragas_rows(ragas_result)
    ragas_scores_by_question = _index_ragas_scores(ragas_result)
    claim_by_question: Dict[str, Dict[str, Any]] = {}
    ragas_low_by_question = _index_case_reasons(ragas_low_cases, "ragas_low_score")
    ragas_cross_by_question = _index_case_reasons(ragas_cross_cases, "ragas_cross_metric")

    trace_rows = []
    for question_key, ragas_row in ragas_rows_by_question.items():
        question_index = int(ragas_row.get("question_index", len(trace_rows) + 1))
        bad_cases = _collect_cases(question_key, ragas_low_by_question, ragas_cross_by_question)
        trace_rows.append(
            {
                "trace_id": _build_trace_id(question_index, ragas_row.get("question", "")),
                "question_index": question_index,
                "question": ragas_row.get("question", ""),
                "question_type": ragas_row.get("question_type", ""),
                "expected_claims": ragas_row.get("expected_claims", []),
                "reference_answer": ragas_row.get("reference_answer", ""),
                "data_availability": {
                    "has_retrieval_eval": question_key in retrieval_by_question,
                    "has_ragas_eval": question_key in ragas_scores_by_question,
                    "has_claim_eval": question_key in claim_by_question,
                },
                "retrieval_eval": _build_retrieval_trace(retrieval_by_question.get(question_key)),
                "generation": _build_generation_trace(ragas_row, config),
                "ragas_scores": ragas_scores_by_question.get(question_key, {}),
                "claim_eval": _build_claim_trace(claim_by_question.get(question_key)),
                "bad_case": {
                    "is_bad_case": bool(bad_cases),
                    "case_count": len(bad_cases),
                    "cases": bad_cases,
                },
            }
        )
    return sorted(trace_rows, key=lambda row: row["question_index"])


def _build_trace_index(trace_rows: List[Dict[str, Any]], config: Dict[str, Any]) -> Dict[str, Any]:
    """生成 trace 索引，供人工和后续工具快速定位问题样本。"""
    bad_case_rows = [row for row in trace_rows if row["bad_case"]["is_bad_case"]]
    retrieval_rows = [row for row in trace_rows if row["data_availability"]["has_retrieval_eval"]]
    return {
        "trace_count": len(trace_rows),
        "bad_case_trace_count": len(bad_case_rows),
        "retrieval_eval_trace_count": len(retrieval_rows),
        "ragas_eval_trace_count": sum(1 for row in trace_rows if row["data_availability"]["has_ragas_eval"]),
        "claim_eval_trace_count": sum(1 for row in trace_rows if row["data_availability"]["has_claim_eval"]),
        "source_paths": {
            "retrieval_result_path": str(Path(config["retrieval_result_path"]).resolve()),
            "ragas_result_path": str(Path(config["ragas_result_path"]).resolve()),
            "claim_result_path": str(Path(config["claim_result_path"]).resolve()),
        },
        "traces": [
            {
                "trace_id": row["trace_id"],
                "question_index": row["question_index"],
                "question": row["question"],
                "question_type": row["question_type"],
                "is_bad_case": row["bad_case"]["is_bad_case"],
                "bad_case_sources": sorted({case.get("source", "") for case in row["bad_case"]["cases"]}),
                "has_retrieval_eval": row["data_availability"]["has_retrieval_eval"],
                "claim_coverage": row["claim_eval"].get("claim_coverage"),
                "evidence_support_rate": row["claim_eval"].get("evidence_support_rate"),
                "faithfulness": row["ragas_scores"].get("faithfulness"),
                "context_recall": row["ragas_scores"].get("context_recall"),
            }
            for row in trace_rows
        ],
    }


def run_trace_export_from_code_config() -> Dict[str, Any]:
    """根据 TRACE_EXPORT_CONFIG 导出 RAG 评测 trace。"""
    trace_rows = _build_trace_rows(TRACE_EXPORT_CONFIG)
    trace_index = _build_trace_index(trace_rows, TRACE_EXPORT_CONFIG)

    if TRACE_EXPORT_CONFIG.get("save_output"):
        _write_jsonl_file(Path(TRACE_EXPORT_CONFIG["trace_jsonl_path"]), trace_rows)
        _write_json_file(Path(TRACE_EXPORT_CONFIG["trace_index_path"]), trace_index)
    if TRACE_EXPORT_CONFIG.get("save_markdown"):
        write_markdown_file(Path(TRACE_EXPORT_CONFIG["report_path"]), build_trace_markdown_report(trace_index))

    return {
        "status": "pass",
        "trace_jsonl_path": str(Path(TRACE_EXPORT_CONFIG["trace_jsonl_path"]).resolve()),
        "trace_index_path": str(Path(TRACE_EXPORT_CONFIG["trace_index_path"]).resolve()),
        "report_path": str(Path(TRACE_EXPORT_CONFIG["report_path"]).resolve()),
        **{key: trace_index[key] for key in trace_index if key.endswith("_count")},
    }
