"""索引绑定的调参题集治理。

本模块只负责“替换直到通过”的循环及其纯策略辅助函数，不发布 Gold、
不修改 active pointer，也不写入正式评测历史。

证据复用语义（宽松模式）：同一 staged index 的早期逐题结论可以在检索或
judge 配置不同的情况下为后续运行提供初始结果。原始指标值会被保存，阈值
在读取时应用；每条复用记录都带有 provenance，以便识别混合配置结果。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence


TUNING_METRICS = ("faithfulness", "answer_relevancy", "context_utilization", "context_recall")


@dataclass(frozen=True)
class TuningPolicy:
    target_count: int = 48
    minimum_metric: float = 0.2
    minimum_recall: float = 0.75
    minimum_mrr: float = 0.65
    max_rounds: int = 8


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def question_hash(question: Any) -> str:
    """返回规范化问题文本的稳定短哈希。"""
    normalized = " ".join(str(question or "").split()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def passing_sample_ids(
    score_records: Sequence[Mapping[str, Any]],
    *,
    minimum_metric: float,
) -> set[str]:
    """返回通过逐题 fail-closed 指标门槛的样本 ID。"""
    passed: set[str] = set()
    for record in score_records:
        sample_id = str(record.get("sample_id") or "").strip()
        if not sample_id or any(
            (value := _number(record.get(metric))) is None or value < minimum_metric
            for metric in TUNING_METRICS
        ):
            continue
        passed.add(sample_id)
    return passed


def retrieval_passes(summary: Mapping[str, Any], policy: TuningPolicy) -> bool:
    """检查集合级检索门槛，不把缺失值当作零分。"""
    recall = _number(summary.get("recall_at_k"))
    mrr = _number(summary.get("mrr"))
    return recall is not None and mrr is not None and recall >= policy.minimum_recall and mrr >= policy.minimum_mrr


def build_ledger(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """按样本 ID 合并逐题证据记录。

    调用方应按评测顺序传入记录；后面的记录作为最新结论覆盖前者。
    没有样本 ID 的记录会被忽略。
    """
    ledger: dict[str, dict[str, Any]] = {}
    for record in records:
        sample_id = str(record.get("sample_id") or "").strip()
        if not sample_id:
            continue
        ledger[sample_id] = dict(record)
    return ledger


def partition_by_ledger(
    samples: Sequence[Mapping[str, Any]],
    ledger: Mapping[str, Mapping[str, Any]],
    *,
    minimum_metric: float,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[str]]:
    """使用缓存的逐题证据拆分基线样本。

    返回 ``(passed, unknown, failed_ids)``。只有当样本 ID 存在对应台账记录、
    问题哈希匹配，且四个原始指标都存在并达到 ``minimum_metric`` 时，样本才
    会被预先判定为通过。低于阈值的数值表示缓存失败（删除并替换）；缺失或
    非数值分数表示没有可靠证据，因此样本保持 unknown 并重新评测。
    """
    passed: dict[str, dict[str, Any]] = {}
    unknown: list[dict[str, Any]] = []
    failed: list[str] = []
    for sample in samples:
        item = dict(sample)
        sample_id = str(item.get("sample_id") or "").strip()
        record = ledger.get(sample_id) if sample_id else None
        if (
            not isinstance(record, Mapping)
            or str(record.get("question_hash") or "") != question_hash(item.get("question"))
        ):
            unknown.append(item)
            continue
        values = [_number(record.get(metric)) for metric in TUNING_METRICS]
        if any(value is None for value in values):
            unknown.append(item)
            continue
        if min(value for value in values) >= minimum_metric:
            passed[sample_id] = dict(record)
        else:
            failed.append(sample_id)
    return passed, unknown, failed


def aggregate_retrieval(records: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    """根据合并后的逐题数值重新计算集合级检索指标。"""
    recalls = [value for record in records if (value := _number(record.get("recall"))) is not None]
    rrs = [value for record in records if (value := _number(record.get("reciprocal_rank"))) is not None]
    return {
        "recall_at_k": round(sum(recalls) / len(recalls), 4) if recalls else None,
        "mrr": round(sum(rrs) / len(rrs), 4) if rrs else None,
    }


def run_tuning_loop(
    initial_samples: Sequence[Mapping[str, Any]],
    *,
    policy: TuningPolicy = TuningPolicy(),
    generate: Callable[[int, int, Mapping[str, Any]], Sequence[Mapping[str, Any]]],
    review: Callable[[Sequence[Mapping[str, Any]], int], Sequence[Mapping[str, Any]]],
    evaluate: Callable[[Sequence[Mapping[str, Any]], int], Mapping[str, Any]],
    precomputed_evidence: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """逐轮替换失败问题，并返回与索引绑定的题集。

    Adapters perform generation, AI review, and isolated evaluation. All three
    receive the same 1-based loop iteration number so their artifacts share
    one ``round_NNN`` namespace. The evaluate adapter receives only the
    samples that still lack usable evidence and returns ``score_records``
    plus ``retrieval_records`` covering exactly those samples; every evaluated
    question is cached in-run and never re-evaluated by a later round. A
    missing score, review failure, duplicate question, or failed retrieval
    summary is rejected; no partial result is returned as publishable. Rounds
    that cannot change the outcome fail fast: a full passing set under a
    failed retrieval gate cannot recover, and zero accepted replacements
    means the gap can no longer shrink.
    """
    current = [dict(item) for item in initial_samples]
    evidence: dict[str, dict[str, Any]] = {
        str(key): dict(value) for key, value in (precomputed_evidence or {}).items()
    }
    rounds: list[dict[str, Any]] = []
    for round_number in range(1, policy.max_rounds + 1):
        pending = [item for item in current if str(item.get("sample_id") or "") not in evidence]
        if pending:
            report = dict(evaluate(pending, round_number))
            fresh_retrieval = {
                str(record.get("sample_id") or "").strip(): record
                for record in report.get("retrieval_records") or []
                if isinstance(record, Mapping)
            }
            for raw_record in report.get("score_records") or []:
                if not isinstance(raw_record, Mapping):
                    continue
                sample_id = str(raw_record.get("sample_id") or "").strip()
                if not sample_id:
                    continue
                entry = evidence.setdefault(sample_id, {"sample_id": sample_id})
                for key, value in raw_record.items():
                    if key != "sample_id":
                        entry[key] = value
                retrieval = fresh_retrieval.get(sample_id) or {}
                if "recall" in retrieval:
                    entry["recall"] = retrieval.get("recall")
                if "reciprocal_rank" in retrieval:
                    entry["reciprocal_rank"] = retrieval.get("reciprocal_rank")

        records: list[dict[str, Any]] = []
        for item in current:
            sample_id = str(item.get("sample_id") or "")
            record = evidence.get(sample_id)
            if record is None:
                raise ValueError(f"missing evaluation evidence for sample {sample_id}")
            records.append(dict(record))
        passing = passing_sample_ids(records, minimum_metric=policy.minimum_metric)
        retrieval_summary = aggregate_retrieval(records)
        retrieval_ok = retrieval_passes(retrieval_summary, policy)
        by_id = {str(item.get("sample_id") or ""): item for item in current}
        kept = [item for item in current if str(item.get("sample_id") or "") in passing]
        missing = max(0, policy.target_count - len(kept))
        rounds.append({
            "round": round_number,
            "input_count": len(current),
            "evaluated_count": len(pending),
            "reused_count": len(current) - len(pending),
            "kept_count": len(kept),
            "missing_count": missing,
            "retrieval_summary": retrieval_summary,
            "retrieval_pass": retrieval_ok,
        })
        if missing == 0 and retrieval_ok:
            final_ids = {str(item.get("sample_id") or "") for item in kept[: policy.target_count]}
            return {
                "status": "passed",
                "samples": kept[: policy.target_count],
                "rounds": rounds,
                "evidence": {key: value for key, value in evidence.items() if key in final_ids},
            }
        if missing == 0:
            return {
                "status": "failed",
                "samples": [],
                "rounds": rounds,
                "error_code": "retrieval_gate_failed",
                "error": (
                    f"all {len(kept)} questions pass the per-question gate but the set-level "
                    "retrieval gate failed; further rounds cannot change this outcome"
                ),
            }
        context = {"kept": kept, "failed_ids": sorted(set(by_id) - passing)}
        replacements = [dict(item) for item in review(generate(missing, round_number, context), round_number)]
        seen = {str(item.get("question") or "").strip().casefold() for item in kept}
        added = 0
        for item in replacements:
            question_key = str(item.get("question") or "").strip().casefold()
            sample_id = str(item.get("sample_id") or "").strip()
            if sample_id and question_key and question_key not in seen and sample_id not in by_id:
                kept.append(item)
                seen.add(question_key)
                by_id[sample_id] = item
                added += 1
        rounds[-1]["added_count"] = added
        if added == 0:
            return {
                "status": "failed",
                "samples": [],
                "rounds": rounds,
                "error_code": "replacement_generation_exhausted",
                "error": f"{missing} replacement questions are required but no reviewed candidate was accepted",
            }
        current = kept
    return {
        "status": "failed",
        "samples": [],
        "rounds": rounds,
        "error_code": "max_rounds_exhausted",
        "error": "tuning dataset did not pass within max_rounds",
    }
