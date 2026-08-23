"""与知识源和文件格式无关的 RAG 评测输入契约。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


EVAL_SCHEMA_VERSION = "rag_eval_v1"
DATASET_KINDS = {
    "untyped",
    "gold_regression",
    "generated_candidate",
    "reference_free",
}

# 该字段把评测题的 gold locator 绑定到不可变索引版本。它由评测启动前的
# 绑定校验消费，不会也不应写入 Chroma 的每条 Runtime metadata。
_BINDING_ONLY_LOCATOR_FIELDS = frozenset({"bound_index_version"})


def _non_empty_text(value: Any) -> str:
    """将文本字段规范化为非空字符串。"""
    return str(value or "").strip()


def _is_json_scalar(value: Any) -> bool:
    """判断 locator 值是否能稳定参与 JSON 严格匹配。"""
    return value is None or isinstance(value, (str, int, float, bool))


def _sample_from_input(sample: dict[str, Any], row_index: int) -> dict[str, Any]:
    """将用户提供的单条样本规范化为稳定的通用结构。"""
    question = _non_empty_text(sample.get("question"))
    if not question:
        raise ValueError(f"sample {row_index}: question is required")
    sample_id = _non_empty_text(sample.get("sample_id")) or f"row-{row_index:04d}"
    gold_evidence = sample.get("gold_evidence", [])
    if gold_evidence is None:
        gold_evidence = []
    if not isinstance(gold_evidence, list) or any(not isinstance(item, dict) for item in gold_evidence):
        raise ValueError(f"{sample_id}: gold_evidence must be a list of objects")
    if any(not item for item in gold_evidence):
        raise ValueError(f"{sample_id}: gold_evidence locators must not be empty")
    for locator in gold_evidence:
        if any(not _non_empty_text(key) for key in locator):
            raise ValueError(f"{sample_id}: gold_evidence locator keys must be non-empty")
        if any(not _is_json_scalar(value) for value in locator.values()):
            raise ValueError(f"{sample_id}: gold_evidence locator values must be JSON scalars")
    expected_claims = sample.get("expected_claims", []) or []
    if not isinstance(expected_claims, list) or any(not _non_empty_text(item) for item in expected_claims):
        raise ValueError(f"{sample_id}: expected_claims must be a list of non-empty strings")
    source = sample.get("source", {}) or {}
    if not isinstance(source, dict):
        raise ValueError(f"{sample_id}: source must be an object")
    return {
        "sample_id": sample_id,
        "question": question,
        "reference_answer": _non_empty_text(sample.get("reference_answer")),
        "expected_claims": [_non_empty_text(item) for item in expected_claims],
        "gold_evidence": [dict(item) for item in gold_evidence],
        "judge_rubric": dict(sample.get("judge_rubric", {}) or {}),
        "source": source,
    }


def _load_dataset_payload(path: str | Path) -> dict[str, Any]:
    """读取 rag_eval_v1 文档，并为旧数组输入补齐非约束元数据。"""
    dataset_path = Path(path)
    payload = json.loads(dataset_path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        return {
            "schema_version": EVAL_SCHEMA_VERSION,
            "dataset_id": dataset_path.stem,
            "dataset_kind": "untyped",
            "dataset_revision": "",
            "source_snapshot": {},
            "samples": payload,
        }
    if not isinstance(payload, dict):
        raise ValueError("evaluation dataset must be a JSON array or rag_eval_v1 object")
    if payload.get("schema_version") != EVAL_SCHEMA_VERSION:
        raise ValueError(f"unsupported evaluation dataset schema: {payload.get('schema_version')!r}")
    dataset_kind = _non_empty_text(payload.get("dataset_kind")) or "untyped"
    if dataset_kind not in DATASET_KINDS:
        raise ValueError(f"unsupported evaluation dataset kind: {dataset_kind!r}")
    samples = payload.get("samples")
    if not isinstance(samples, list):
        raise ValueError("rag_eval_v1 object must contain a samples list")
    source_snapshot = payload.get("source_snapshot", {}) or {}
    if not isinstance(source_snapshot, dict):
        raise ValueError("source_snapshot must be an object")
    return {
        "schema_version": EVAL_SCHEMA_VERSION,
        "dataset_id": _non_empty_text(payload.get("dataset_id")) or dataset_path.stem,
        "dataset_kind": dataset_kind,
        "dataset_revision": _non_empty_text(payload.get("dataset_revision")),
        "source_snapshot": dict(source_snapshot),
        "samples": samples,
    }


def load_eval_dataset_bundle(path: str | Path) -> dict[str, Any]:
    """读取题集元数据与规范化样本，供校验和运行身份绑定复用。"""
    dataset_path = Path(path)
    payload = _load_dataset_payload(dataset_path)
    samples = []
    seen_ids: set[str] = set()
    for row_index, raw_sample in enumerate(payload["samples"], start=1):
        if not isinstance(raw_sample, dict):
            raise ValueError(f"sample {row_index} must be an object")
        sample = _sample_from_input(raw_sample, row_index)
        if sample["sample_id"] in seen_ids:
            raise ValueError(f"duplicate sample_id: {sample['sample_id']}")
        seen_ids.add(sample["sample_id"])
        samples.append(sample)
    if not samples:
        raise ValueError("evaluation dataset must contain at least one sample")
    return {**payload, "samples": samples}


def load_eval_dataset(path: str | Path) -> list[dict[str, Any]]:
    """读取通用 JSON 评测集，不解释知识源类型或文件格式。"""
    return load_eval_dataset_bundle(path)["samples"]


def _validate_dataset_kind(bundle: dict[str, Any]) -> list[str]:
    """按题集用途检查正式 gold 所需字段，保持 untyped 旧输入兼容。"""
    dataset_kind = bundle["dataset_kind"]
    if dataset_kind not in {"gold_regression", "generated_candidate"}:
        return []
    errors = []
    for index, sample in enumerate(bundle["samples"], start=1):
        prefix = f"{bundle['dataset_id']}[{index}]"
        if not sample["reference_answer"]:
            errors.append(f"{prefix}: reference_answer is required for {dataset_kind}")
        if not sample["expected_claims"]:
            errors.append(f"{prefix}: expected_claims is required for {dataset_kind}")
        if dataset_kind == "gold_regression" and not sample["gold_evidence"]:
            errors.append(f"{prefix}: gold_evidence is required for gold_regression")
    return errors


def validate_eval_dataset(path: str | Path) -> dict[str, Any]:
    """校验通用评测集并返回可持久化的结构摘要。"""
    try:
        bundle = load_eval_dataset_bundle(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {"schema_version": EVAL_SCHEMA_VERSION, "sample_count": 0, "errors": [str(exc)]}
    samples = bundle["samples"]
    errors = _validate_dataset_kind(bundle)
    return {
        "schema_version": EVAL_SCHEMA_VERSION,
        "dataset_id": bundle["dataset_id"],
        "dataset_kind": bundle["dataset_kind"],
        "dataset_revision": bundle["dataset_revision"],
        "sample_count": len(samples),
        "with_reference_answer": sum(bool(sample["reference_answer"]) for sample in samples),
        "with_expected_claims": sum(bool(sample["expected_claims"]) for sample in samples),
        "with_gold_evidence": sum(bool(sample["gold_evidence"]) for sample in samples),
        "unscored_retrieval_samples": sum(not bool(sample["gold_evidence"]) for sample in samples),
        "errors": errors,
    }


def evaluation_identity(path: str | Path) -> dict[str, Any]:
    """返回只绑定题集本身的 identity，不读取或假设任何知识源。"""
    dataset_path = Path(path)
    payload = dataset_path.read_bytes()
    bundle = load_eval_dataset_bundle(dataset_path)
    return {
        "schema_version": EVAL_SCHEMA_VERSION,
        "dataset_id": bundle["dataset_id"],
        "dataset_kind": bundle["dataset_kind"],
        "dataset_revision": bundle["dataset_revision"],
        "dataset_path": str(dataset_path.resolve()),
        "dataset_sha256": hashlib.sha256(payload).hexdigest(),
        "sample_count": len(bundle["samples"]),
    }


def candidate_evidence(metadata: dict[str, Any]) -> dict[str, Any]:
    """原样返回 Runtime metadata，评测层不解释知识源字段。"""
    return dict(metadata)


def locator_matches(candidate: dict[str, Any], expected: dict[str, Any]) -> bool:
    """按可运行时检索的 gold 字段做全字段精确匹配。"""
    normalized_candidate = candidate_evidence(candidate)
    fields = {
        key: value
        for key, value in expected.items()
        if key not in _BINDING_ONLY_LOCATOR_FIELDS and value is not None and value != ""
    }
    return bool(fields) and all(normalized_candidate.get(key) == value for key, value in fields.items())
