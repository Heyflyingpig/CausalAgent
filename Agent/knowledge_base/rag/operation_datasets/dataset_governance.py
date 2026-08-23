"""对已冻结 RAG 题集执行 fail-closed 的替换治理。

该模块只处理内存中的 JSON 兼容对象，不读写 Gold、active pointer 或生产 profile。
调用方负责把质量报告、候选题和可注入的独立审核器传入；因此单测无需联网。
"""

from __future__ import annotations

import copy
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence


Reviewer = Callable[..., Mapping[str, Any]]


def _normalized_question(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _is_human_reviewed(sample: Mapping[str, Any]) -> bool:
    source = sample.get("source") or {}
    return isinstance(source, Mapping) and str(source.get("origin") or "").strip() == "human_reviewed"


def _is_generated_candidate(sample: Mapping[str, Any]) -> bool:
    """只有带生成器 provenance 的题目允许进入自动退休判断。"""
    source = sample.get("source") or {}
    return isinstance(source, Mapping) and bool(str(source.get("generator") or "").strip())


def _review_result(
    reviewer: Reviewer,
    sample: Mapping[str, Any],
    purpose: str,
    review_context: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    review_payload = copy.deepcopy(dict(sample))
    if review_context:
        review_payload["_governance_review_context"] = copy.deepcopy(dict(review_context))
    try:
        result = reviewer(review_payload, purpose=purpose)
    except Exception as exc:
        return None, f"reviewer_error:{type(exc).__name__}"
    if not isinstance(result, Mapping):
        return None, "reviewer_invalid_result"
    verdict = str(result.get("verdict") or "").strip().lower()
    confidence = result.get("confidence")
    if verdict not in {"replace", "retain", "accept", "reject"}:
        return None, "reviewer_invalid_verdict"
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(float(confidence)):
        return None, "reviewer_invalid_confidence"
    if not 0.0 <= float(confidence) <= 1.0:
        return None, "reviewer_invalid_confidence"
    return {
        "verdict": verdict,
        "confidence": float(confidence),
        "reason": str(result.get("reason") or "").strip(),
    }, None


def _identity_candidates(dataset: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    snapshots: list[Mapping[str, Any]] = []
    bindings: list[Mapping[str, Any]] = []
    top_snapshot = dataset.get("source_snapshot")
    if isinstance(top_snapshot, Mapping):
        snapshots.append(top_snapshot)
        candidate_review = top_snapshot.get("candidate_review")
        if isinstance(candidate_review, Mapping) and isinstance(candidate_review.get("index_binding"), Mapping):
            bindings.append(candidate_review["index_binding"])
    dataset_binding = dataset.get("index_binding")
    if isinstance(dataset_binding, Mapping):
        bindings.append(dataset_binding)
    for sample in dataset.get("samples") or []:
        if not isinstance(sample, Mapping):
            continue
        source = sample.get("source") or {}
        if isinstance(source, Mapping):
            if isinstance(source.get("source_snapshot"), Mapping):
                snapshots.append(source["source_snapshot"])
            if isinstance(source.get("index_binding"), Mapping):
                bindings.append(source["index_binding"])
    return snapshots, bindings


def _candidate_identity_matches(candidate: Mapping[str, Any], dataset: Mapping[str, Any]) -> bool:
    expected_snapshots, expected_bindings = _identity_candidates(dataset)
    source = candidate.get("source") or {}
    candidate_snapshot = candidate.get("source_snapshot")
    if not isinstance(candidate_snapshot, Mapping) and isinstance(source, Mapping):
        candidate_snapshot = source.get("source_snapshot")
    candidate_binding = candidate.get("index_binding")
    if not isinstance(candidate_binding, Mapping) and isinstance(source, Mapping):
        candidate_binding = source.get("index_binding")

    if expected_snapshots:
        if not isinstance(candidate_snapshot, Mapping):
            return False
        if not any(dict(candidate_snapshot) == dict(expected) for expected in expected_snapshots):
            return False
    elif isinstance(candidate_snapshot, Mapping):
        return False

    if expected_bindings:
        if not isinstance(candidate_binding, Mapping):
            return False
        candidate_index_version = str(candidate_binding.get("index_version") or "")
        if not candidate_index_version or not any(
            candidate_index_version == str(expected.get("index_version") or "")
            for expected in expected_bindings
        ):
            return False
    elif isinstance(candidate_binding, Mapping):
        return False
    return True


def _candidate_is_complete(candidate: Mapping[str, Any]) -> bool:
    question = str(candidate.get("question") or candidate.get("user_input") or "").strip()
    reference_answer = str(candidate.get("reference_answer") or "").strip()
    claims = candidate.get("expected_claims")
    evidence = candidate.get("gold_evidence")
    return bool(
        question
        and reference_answer
        and isinstance(claims, list)
        and claims
        and isinstance(evidence, list)
        and evidence
        and _is_generated_candidate(candidate)
    )


def _new_revision(old_revision: Any) -> str:
    prefix = str(old_revision or "unversioned").strip() or "unversioned"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{prefix}_governed_{timestamp}_{uuid.uuid4().hex[:8]}"


def govern_dataset(
    dataset: Mapping[str, Any],
    quality_report: Mapping[str, Any],
    replacement_candidates: Sequence[Mapping[str, Any]],
    reviewer: Reviewer,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """根据质量报告和独立审核结果生成一个等题数的新题集。

    `reviewer` 必须接受 ``reviewer(sample, purpose="retire"|"accept")``，并返回
    ``{"verdict": str, "confidence": number, "reason": str}``。任何异常或非法
    结果都按拒绝处理。候选数量不足时在返回前抛出异常，输入对象不会被修改。
    """

    if not isinstance(dataset, Mapping) or not isinstance(quality_report, Mapping):
        raise TypeError("dataset and quality_report must be mappings")
    if not callable(reviewer):
        raise TypeError("reviewer must be callable")
    original_samples = dataset.get("samples")
    if not isinstance(original_samples, list) or not original_samples:
        raise ValueError("dataset.samples must be a non-empty list")
    if dataset.get("schema_version") != "rag_eval_v1" or dataset.get("dataset_kind") != "gold_regression":
        raise ValueError("governance requires a rag_eval_v1 gold_regression dataset")
    if any(not isinstance(sample, Mapping) or not str(sample.get("sample_id") or "").strip() for sample in original_samples):
        raise ValueError("dataset.samples contain an invalid sample")

    samples = list(original_samples)
    by_id = {str(sample.get("sample_id") or ""): sample for sample in samples}
    if len(by_id) != len(samples):
        raise ValueError("dataset.samples contain duplicate sample_id")
    quality_items = quality_report.get("items")
    if not isinstance(quality_items, list):
        raise ValueError("quality_report.items must be a list")

    protected_count = sum(1 for sample in samples if _is_human_reviewed(sample))
    diagnosed: list[dict[str, Any]] = []
    item_reports: list[dict[str, Any]] = []
    retire_ids: list[str] = []

    for item in quality_items:
        if not isinstance(item, Mapping):
            continue
        sample_id = str(item.get("sample_id") or "").strip()
        sample = by_id.get(sample_id)
        if sample is None:
            continue
        if _is_human_reviewed(sample):
            item_reports.append({"sample_id": sample_id, "action": "protected", "reasons": ["human_reviewed_protected"]})
            continue
        if not _is_generated_candidate(sample):
            item_reports.append({"sample_id": sample_id, "action": "retained", "reasons": ["non_generated_protected"]})
            continue
        flags = [str(flag) for flag in item.get("flags") or [] if str(flag).strip()]
        intrinsic_flags = [flag for flag in flags if not flag.startswith("ragas_")]
        if not intrinsic_flags:
            item_reports.append({
                "sample_id": sample_id,
                "action": "retained",
                "reasons": ["ragas_low_score_without_intrinsic_flag"] if flags else ["no_intrinsic_quality_flag"],
            })
            continue
        diagnosed.append({"sample_id": sample_id, "sample": sample, "flags": intrinsic_flags})
        review_sample = copy.deepcopy(dict(sample))
        review_sample["_governance_review"] = {
            "intrinsic_flags": intrinsic_flags,
            "quality_item": copy.deepcopy(dict(item)),
        }
        result, error = _review_result(reviewer, review_sample, "retire")
        if error:
            reasons = [*intrinsic_flags, error, "retain_fail_closed"]
            item_reports.append({"sample_id": sample_id, "action": "retained", "reasons": reasons})
            continue
        if result["verdict"] == "replace" and result["confidence"] >= 0.8:
            retire_ids.append(sample_id)
            item_reports.append({"sample_id": sample_id, "action": "retire_approved", "reasons": intrinsic_flags, "review": result})
        else:
            item_reports.append({"sample_id": sample_id, "action": "retained", "reasons": [*intrinsic_flags, "retire_review_not_approved"], "review": result})

    rejected_candidate_count = 0
    accepted_candidates: list[Mapping[str, Any]] = []
    seen_candidate_ids: set[str] = set()
    seen_questions = {_normalized_question(sample.get("question")) for sample in samples}
    for candidate in replacement_candidates:
        if len(accepted_candidates) >= len(retire_ids):
            break
        if not isinstance(candidate, Mapping):
            rejected_candidate_count += 1
            continue
        candidate_id = str(candidate.get("sample_id") or "")
        question_key = _normalized_question(candidate.get("question"))
        if (
            not _candidate_is_complete(candidate)
            or not _candidate_identity_matches(candidate, dataset)
            or candidate_id in seen_candidate_ids
            or not question_key
            or question_key in seen_questions
        ):
            rejected_candidate_count += 1
            continue
        seen_candidate_ids.add(candidate_id)
        result, error = _review_result(reviewer, candidate, "accept")
        if error or result["verdict"] != "accept" or result["confidence"] < 0.8:
            rejected_candidate_count += 1
            continue
        accepted_candidates.append(candidate)
        seen_questions.add(question_key)

    if len(accepted_candidates) < len(retire_ids):
        raise ValueError(
            f"replacement candidates are insufficient: required={len(retire_ids)}, accepted={len(accepted_candidates)}"
        )

    replacements = dict(zip(retire_ids, accepted_candidates))
    new_samples: list[dict[str, Any]] = []
    for sample in samples:
        sample_id = str(sample.get("sample_id") or "")
        replacement = replacements.get(sample_id)
        if replacement is None:
            new_samples.append(copy.deepcopy(dict(sample)))
            continue
        replaced = copy.deepcopy(dict(replacement))
        replacement_source = dict(replaced.get("source") or {})
        replaced["sample_id"] = sample_id
        replaced["source"] = {
            **replacement_source,
            "origin": "governance_replacement",
            "review_status": "governance_accepted",
            "replaced_sample_id": sample_id,
        }
        new_samples.append(replaced)

    result_dataset = copy.deepcopy(dict(dataset))
    changed = bool(retire_ids)
    result_dataset["dataset_revision"] = (
        _new_revision(dataset.get("dataset_revision"))
        if changed
        else str(dataset.get("dataset_revision") or "")
    )
    result_dataset["schema_version"] = "rag_eval_v1"
    result_dataset["samples"] = new_samples
    report = {
        "schema_version": "rag_dataset_governance_v1",
        "dataset_id": str(dataset.get("dataset_id") or ""),
        "old_revision": str(dataset.get("dataset_revision") or ""),
        "new_revision": result_dataset["dataset_revision"],
        "changed": changed,
        "publish_status": "pending" if changed else "no_change",
        "protected_count": protected_count,
        "diagnosed_count": len(diagnosed),
        "replaced_count": len(retire_ids),
        "rejected_candidate_count": rejected_candidate_count,
        "items": item_reports,
        "per_item_reasons": item_reports,
    }
    return result_dataset, report


__all__ = ["Reviewer", "govern_dataset"]
