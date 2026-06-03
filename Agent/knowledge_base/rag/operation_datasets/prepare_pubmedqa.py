import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[4]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from datasets import Dataset, load_dataset

from Agent.knowledge_base.rag.operation_datasets.dataset_utils import extract_claims_from_reference
from Agent.knowledge_base.rag.rag_config import PUBMEDQA_PREPARE_CONFIG


def _build_doc_id(pubid: Any, fallback_index: int) -> str:
    """生成稳定的 PubMedQA evidence doc_id。"""
    normalized_pubid = str(pubid).strip() if pubid is not None else ""
    if normalized_pubid:
        return f"pubmedqa_{normalized_pubid}"
    return f"pubmedqa_row_{fallback_index:06d}"


def _context_to_text(context: Any) -> str:
    """把 PubMedQA context 字段转换成单个 evidence 文本。"""
    if isinstance(context, dict):
        contexts = context.get("contexts") or []
        if isinstance(contexts, list):
            return "\n\n".join(str(item).strip() for item in contexts if str(item).strip())
    if isinstance(context, list):
        return "\n\n".join(str(item).strip() for item in context if str(item).strip())
    return str(context or "").strip()


def _build_corpus_doc(row: Dict[str, Any], index: int, source_dataset: str) -> Dict[str, Any]:
    """把单条 PubMedQA 样本转换为 evidence corpus 文档。"""
    doc_id = _build_doc_id(row.get("pubid"), index)
    text = _context_to_text(row.get("context"))
    if not text:
        raise ValueError(f"row {index} missing context.")
    return {
        "doc_id": doc_id,
        "source_dataset": source_dataset,
        "corpus": "medical",
        "dataset": "pubmedqa",
        "source_row_index": index,
        "pubid": row.get("pubid"),
        "reference": f"PubMed PMID {row.get('pubid')}" if row.get("pubid") else "",
        "page": "",
        "text": text,
    }


def _build_eval_sample(row: Dict[str, Any], index: int, source_dataset: str) -> Dict[str, Any]:
    """把单条 PubMedQA 样本转换为 benchmark_v2 评测样本。"""
    question = str(row.get("question") or "").strip()
    reference_answer = str(row.get("long_answer") or "").strip()
    if not question:
        raise ValueError(f"row {index} missing question.")
    if not reference_answer:
        raise ValueError(f"row {index} missing long_answer.")

    doc_id = _build_doc_id(row.get("pubid"), index)
    claims = extract_claims_from_reference(reference_answer)
    return {
        "sample_id": doc_id,
        "question": question,
        "reference_answer": reference_answer,
        "expected_claims": claims,
        "gold_doc_ids": [doc_id],
        "judge_rubric": {
            "must_cover": claims,
            "final_decision": row.get("final_decision", ""),
            "avoid": [
                "make biomedical claims not supported by the PubMedQA context",
                "ignore the long_answer rationale",
                "answer only yes/no/maybe without explaining the evidence",
            ],
        },
        "source": {
            "dataset": source_dataset,
            "row_index": index,
            "pubid": row.get("pubid"),
        },
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


def prepare_pubmedqa_from_config(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """根据配置下载并转换 PubMedQA labeled 子集为 corpus 和 benchmark_v2。"""
    active_config = dict(PUBMEDQA_PREPARE_CONFIG)
    if config:
        active_config.update(config)

    cache_arrow_path = str(active_config.get("cache_arrow_path") or "").strip()
    if cache_arrow_path:
        dataset = Dataset.from_file(cache_arrow_path)
    else:
        dataset = load_dataset(
            active_config["dataset_name"],
            active_config["subset_name"],
            split=active_config["split"],
        )
    limit = active_config.get("limit")
    if limit is not None:
        dataset = dataset.select(range(min(int(limit), len(dataset))))

    corpus_docs = []
    eval_samples = []
    for index, row in enumerate(dataset, start=1):
        row_dict = dict(row)
        corpus_docs.append(_build_corpus_doc(row_dict, index, active_config["source_dataset"]))
        eval_samples.append(_build_eval_sample(row_dict, index, active_config["source_dataset"]))

    corpus_output_path = Path(active_config["corpus_output_path"])
    eval_output_path = Path(active_config["eval_output_path"])
    _write_jsonl(corpus_output_path, corpus_docs)
    _write_json(eval_output_path, eval_samples)

    return {
        "status": "pass",
        "source_dataset": active_config["source_dataset"],
        "dataset_name": active_config["dataset_name"],
        "subset_name": active_config["subset_name"],
        "split": active_config["split"],
        "cache_arrow_path": cache_arrow_path,
        "corpus_output_path": str(corpus_output_path.resolve()),
        "eval_output_path": str(eval_output_path.resolve()),
        "source_row_count": len(dataset),
        "corpus_doc_count": len(corpus_docs),
        "eval_sample_count": len(eval_samples),
        "limit": limit,
    }


if __name__ == "__main__":
    result = prepare_pubmedqa_from_config()
    if PUBMEDQA_PREPARE_CONFIG.get("print_full_output"):
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
