"""把历史题集转换为正式的 rag_eval_v1 gold 题集。"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
from typing import Any, Dict, List

from config.rag_eval_paths import RAG_EVAL_LEGACY_ROOT

from Agent.knowledge_base.rag.rag_eval.contracts import EVAL_SCHEMA_VERSION


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PEARL_SOURCE = ROOT / "Agent" / "knowledge_base" / "multimodal" / "production_eval_v1.json"
DEFAULT_PEARL_OUTPUT = RAG_EVAL_LEGACY_ROOT / "datasets" / "pearl_gold_v1.json"
DEFAULT_PUBMED_SOURCE = ROOT / "Agent" / "knowledge_base" / "rag" / "data" / "external" / "pubmedqa" / "processed" / "pubmedqa_eval_dataset.json"
DEFAULT_PUBMED_OUTPUT = RAG_EVAL_LEGACY_ROOT / "datasets" / "medical_gold_v1.json"


def _read_json(path: Path) -> Any:
    """读取 UTF-8 JSON 输入。"""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    """计算源题集 hash，写入输出 provenance。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    """写入正式题集 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _gold_locators(case: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把多模态题集的文档、页码和模态转换为通用 locator。"""
    documents = [str(value).strip() for value in case.get("gold_doc_ids", []) if str(value).strip()]
    pages = [value for value in case.get("gold_page_numbers", []) if value not in (None, "")]
    if not documents or not pages:
        raise ValueError(f"{case.get('case_id', '<unknown>')}: gold document and page are required")

    pairs = zip(documents, pages) if len(documents) == len(pages) else itertools.product(documents, pages)
    locators: List[Dict[str, Any]] = []
    for document_id, page_number in pairs:
        locator = {
            "document_id": document_id,
            "page_number": page_number,
        }
        modality = str(case.get("expected_modality") or "").strip()
        if modality:
            locator["modality"] = modality
        locators.append(locator)

    unit_ids = [str(value).strip() for value in case.get("gold_unit_ids", []) if str(value).strip()]
    if unit_ids:
        for locator, unit_id in zip(locators, unit_ids):
            locator["unit_id"] = unit_id
    return locators


def build_pearl_gold_dataset(source_path: Path = DEFAULT_PEARL_SOURCE) -> Dict[str, Any]:
    """构造 Pearl 多模态公共语料的正式 gold 回归集。"""
    payload = _read_json(source_path)
    if payload.get("schema_version") != "multimodal_retrieval_eval_v1":
        raise ValueError("unexpected Pearl evaluation schema")

    samples = []
    for row_index, case in enumerate(payload.get("cases", []), start=1):
        if not case.get("human_reviewed"):
            raise ValueError(f"{case.get('case_id', row_index)}: human_reviewed is required")
        claims = [str(value).strip() for value in case.get("key_facts", []) if str(value).strip()]
        reference_answer = str(case.get("reference_answer") or "").strip()
        if not reference_answer or not claims:
            raise ValueError(f"{case.get('case_id', row_index)}: reference_answer and key_facts are required")
        samples.append(
            {
                "sample_id": str(case["case_id"]),
                "question": str(case["question"]).strip(),
                "reference_answer": reference_answer,
                "expected_claims": claims,
                "gold_evidence": _gold_locators(case),
                "judge_rubric": {
                    "must_cover": claims,
                    "avoid": ["不得引入检索证据之外的事实"],
                },
                "source": {
                    "dataset": payload["schema_version"],
                    "row_index": row_index,
                    "origin": "human_reviewed",
                    "source_revision": payload.get("reviewed_at", ""),
                },
            }
        )

    return {
        "schema_version": EVAL_SCHEMA_VERSION,
        "dataset_id": "pearl_gold_v1",
        "dataset_kind": "gold_regression",
        "dataset_revision": payload.get("reviewed_at", ""),
        "source_snapshot": {
            "dataset": payload["schema_version"],
            "source_sha256": _sha256(source_path),
        },
        "samples": samples,
    }


def build_pubmed_gold_dataset(source_path: Path = DEFAULT_PUBMED_SOURCE) -> Dict[str, Any]:
    """把 PubMedQA legacy doc gold 转换为独立医疗 gold 题集。"""
    rows = _read_json(source_path)
    if not isinstance(rows, list):
        raise ValueError("PubMedQA evaluation input must be a JSON array")

    samples = []
    for row_index, row in enumerate(rows, start=1):
        doc_ids = [str(value).strip() for value in row.get("gold_doc_ids", []) if str(value).strip()]
        if not doc_ids:
            raise ValueError(f"PubMedQA row {row_index}: gold_doc_ids is required")
        sample = dict(row)
        sample["gold_evidence"] = [{"doc_id": doc_id} for doc_id in doc_ids]
        sample["source"] = {
            **dict(row.get("source") or {}),
            "origin": "imported_gold",
            "source_revision": "pubmedqa_labeled",
        }
        sample.pop("gold_doc_ids", None)
        samples.append(sample)

    return {
        "schema_version": EVAL_SCHEMA_VERSION,
        "dataset_id": "medical_gold_v1",
        "dataset_kind": "gold_regression",
        "dataset_revision": "pubmedqa_labeled",
        "source_snapshot": {
            "dataset": "pubmed_qa/pqa_labeled",
            "source_sha256": _sha256(source_path),
        },
        "samples": samples,
    }


def build_all(output_dir: Path | None = None) -> Dict[str, str]:
    """生成 Pearl 与 PubMedQA 两条独立正式 gold 题集。"""
    target_dir = output_dir or DEFAULT_PEARL_OUTPUT.parent
    pearl_output = target_dir / DEFAULT_PEARL_OUTPUT.name
    pubmed_output = target_dir / DEFAULT_PUBMED_OUTPUT.name
    _write_json(pearl_output, build_pearl_gold_dataset())
    _write_json(pubmed_output, build_pubmed_gold_dataset())
    return {"pearl": str(pearl_output.resolve()), "medical": str(pubmed_output.resolve())}


def main() -> None:
    """提供可重复的本地 gold 题集转换命令。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    print(json.dumps(build_all(args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
