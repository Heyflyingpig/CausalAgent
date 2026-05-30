import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[4]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from Agent.knowledge_base.rag.operation_datasets.dataset_utils import extract_claims_from_reference
from Agent.knowledge_base.rag.rag_config import RAGCARE_QA_PREPARE_CONFIG


SUPPORTED_RAW_SUFFIXES = {".json", ".jsonl", ".csv"}


def _read_json_file(path: Path) -> List[Dict[str, Any]]:
    """读取 JSON 文件，并兼容 list 或 HuggingFace 常见 split dict 格式。"""
    with path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("rows"), list):
            return [
                {**item["row"], "_hf_row_idx": item.get("row_idx")}
                for item in data["rows"]
                if isinstance(item, dict) and isinstance(item.get("row"), dict)
            ]
        rows: List[Dict[str, Any]] = []
        for value in data.values():
            if isinstance(value, list):
                rows.extend(row for row in value if isinstance(row, dict))
        if rows:
            return rows
    raise ValueError(f"{path} must contain a JSON array or split object.")


def _read_jsonl_file(path: Path) -> List[Dict[str, Any]]:
    """读取 JSONL 文件。"""
    rows = []
    with path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number} must be a JSON object.")
            rows.append(row)
    return rows


def _read_csv_file(path: Path) -> List[Dict[str, Any]]:
    """读取 CSV 文件。"""
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return [dict(row) for row in csv.DictReader(file)]


def _load_raw_rows(raw_dir: Path) -> List[Dict[str, Any]]:
    """从 raw 目录加载 RAGCare-QA 原始数据。"""
    if not raw_dir.exists():
        raise FileNotFoundError(f"raw_dir does not exist: {raw_dir}")

    rows: List[Dict[str, Any]] = []
    for path in sorted(raw_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_RAW_SUFFIXES:
            continue
        if path.suffix.lower() == ".json":
            rows.extend(_read_json_file(path))
        elif path.suffix.lower() == ".jsonl":
            rows.extend(_read_jsonl_file(path))
        elif path.suffix.lower() == ".csv":
            rows.extend(_read_csv_file(path))

    if not rows:
        raise FileNotFoundError(
            f"No supported raw files found in {raw_dir}. "
            f"Supported suffixes: {sorted(SUPPORTED_RAW_SUFFIXES)}"
        )

    deduped: List[Dict[str, Any]] = []
    seen_keys = set()
    for index, row in enumerate(rows):
        row_idx = row.get("_hf_row_idx")
        key = ("hf_row_idx", row_idx) if row_idx is not None else ("row", _get_field(row, ["Question"]), index)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(row)
    return deduped


def _get_field(row: Dict[str, Any], names: Iterable[str]) -> str:
    """兼容读取 RAGCare-QA 字段名的大小写和空格差异。"""
    normalized = {str(key).strip().lower().replace("_", " "): value for key, value in row.items()}
    for name in names:
        value = normalized.get(name.strip().lower().replace("_", " "))
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _build_doc_id(index: int) -> str:
    """生成稳定的医疗 evidence doc_id。"""
    return f"ragcare_{index:06d}"


def _source_row_index(row: Dict[str, Any], fallback_index: int) -> int:
    """读取 Hugging Face row_idx，并退回到当前顺序编号。"""
    raw_index = row.get("_hf_row_idx")
    if raw_index is None:
        return fallback_index
    return int(raw_index) + 1


def _build_corpus_doc(row: Dict[str, Any], index: int, source_dataset: str) -> Dict[str, Any]:
    """把单条 RAGCare-QA 样本转换成仅含 Context 的医疗语料文档。"""
    context = _get_field(row, ["Context"])
    if not context:
        raise ValueError(f"row {index} missing Context.")
    return {
        "doc_id": _build_doc_id(_source_row_index(row, index)),
        "source_dataset": source_dataset,
        "corpus": "medical",
        "dataset": "ragcare_qa",
        "source_row_index": _source_row_index(row, index),
        "reference": _get_field(row, ["Reference"]),
        "page": _get_field(row, ["Page"]),
        "text": context,
    }


def _build_eval_sample(
    row: Dict[str, Any],
    index: int,
    source_dataset: str,
    review_status: str,
) -> Dict[str, Any]:
    """把单条 RAGCare-QA 样本转换成 medical eval schema。"""
    question = _get_field(row, ["Question"])
    reference_answer = _get_field(row, ["Text Answer", "Answer"])
    if not question:
        raise ValueError(f"row {index} missing Question.")
    if not reference_answer:
        raise ValueError(f"row {index} missing Answer/Text Answer.")

    doc_id = _build_doc_id(_source_row_index(row, index))
    claims = extract_claims_from_reference(reference_answer)
    return {
        "question": question,
        "question_type": "medical_rag",
        "expected_corpus": "medical",
        "expected_sources": [doc_id],
        "expected_claims": claims,
        "reference_answer": reference_answer,
        "gold_chunk_ids": [],
        "gold_doc_ids": [doc_id],
        "judge_rubric": {
            "must_cover": claims,
            "avoid": [
                "make diagnosis or treatment claims not supported by the evidence context",
                "add medication dosage or clinical advice that is absent from the evidence context",
                "cite evidence from the causal Pearl knowledge base for a medical QA sample",
            ],
        },
        "notes": f"Converted from {source_dataset}; evidence text uses Context only to avoid answer leakage.",
        "eval_schema_version": "phase1_v1",
        "review_status": review_status,
        "is_smoke_case": False,
    }


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    """写入 JSONL 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_json(path: Path, data: Any) -> None:
    """写入 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare_ragcare_qa_from_config(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """根据配置把 RAGCare-QA 原始数据转换成医疗 corpus 和 eval dataset。"""
    active_config = dict(RAGCARE_QA_PREPARE_CONFIG)
    if config:
        active_config.update(config)

    raw_rows = _load_raw_rows(Path(active_config["raw_dir"]))
    limit = active_config.get("limit")
    if limit is not None:
        raw_rows = raw_rows[: int(limit)]

    corpus_docs = []
    eval_samples = []
    for index, row in enumerate(raw_rows, start=1):
        corpus_docs.append(_build_corpus_doc(row, index, active_config["source_dataset"]))
        eval_samples.append(
            _build_eval_sample(
                row=row,
                index=index,
                source_dataset=active_config["source_dataset"],
                review_status=active_config["review_status"],
            )
        )

    corpus_output_path = Path(active_config["corpus_output_path"])
    eval_output_path = Path(active_config["eval_output_path"])
    _write_jsonl(corpus_output_path, corpus_docs)
    _write_json(eval_output_path, eval_samples)

    return {
        "status": "pass",
        "source_dataset": active_config["source_dataset"],
        "raw_dir": str(Path(active_config["raw_dir"]).resolve()),
        "corpus_output_path": str(corpus_output_path.resolve()),
        "eval_output_path": str(eval_output_path.resolve()),
        "source_row_count": len(raw_rows),
        "corpus_doc_count": len(corpus_docs),
        "eval_sample_count": len(eval_samples),
        "limit": limit,
    }


if __name__ == "__main__":
    result = prepare_ragcare_qa_from_config()
    if RAGCARE_QA_PREPARE_CONFIG.get("print_full_output"):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "corpus_doc_count": result["corpus_doc_count"],
                    "eval_sample_count": result["eval_sample_count"],
                    "corpus_output_path": result["corpus_output_path"],
                    "eval_output_path": result["eval_output_path"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
