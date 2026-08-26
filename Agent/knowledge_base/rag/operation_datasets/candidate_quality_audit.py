"""候选题质量审查：汇总文本规则、证据结构与已完成评测的坏例。"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from Agent.knowledge_base.rag.operation_datasets.benchmark_v2 import _question_quality_flags
from Agent.knowledge_base.rag.rag_eval.contracts import load_eval_dataset_bundle
from observability.cli import write_cli_output


QUALITY_METRICS = (
    "faithfulness",
    "answer_relevancy",
    "context_utilization",
    "context_recall",
)
LOW_SCORE_THRESHOLD = 0.5


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def _is_generated_candidate(sample: dict[str, Any]) -> bool:
    return bool((sample.get("source") or {}).get("generator"))


def _numeric(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _performance_by_sample(evaluation_dir: Path | None) -> dict[str, dict[str, float]]:
    if evaluation_dir is None:
        return {}
    result_path = Path(evaluation_dir) / "machine" / "ragas_eval_result.json"
    if not result_path.is_file():
        return {}
    payload = _read_json(result_path)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), list) else []
    records = payload.get("score_records") if isinstance(payload.get("score_records"), list) else []
    scores: dict[str, dict[str, float]] = {}
    for meta, record in zip(metadata, records):
        if not isinstance(meta, dict) or not isinstance(record, dict):
            continue
        sample_id = str(meta.get("sample_id") or "").strip()
        if not sample_id:
            continue
        values = {metric: value for metric in QUALITY_METRICS if (value := _numeric(record.get(metric))) is not None}
        if values:
            scores[sample_id] = values
    return scores


def _intrinsic_flags(sample: dict[str, Any]) -> list[str]:
    flags = list(_question_quality_flags(str(sample.get("question") or "")))
    claims = sample.get("expected_claims") if isinstance(sample.get("expected_claims"), list) else []
    evidence = sample.get("gold_evidence") if isinstance(sample.get("gold_evidence"), list) else []
    reference = str(sample.get("reference_answer") or "").strip()
    if len(claims) >= 2 and len(evidence) <= 1:
        flags.append("single_locator_for_multi_claim")
    if len(reference) > 800:
        flags.append("reference_answer_overly_long")
    documents = {str(item.get("document_id") or item.get("doc_id") or "") for item in evidence if isinstance(item, dict)}
    documents.discard("")
    if len(documents) > 1:
        flags.append("multi_document_evidence_requires_review")
    return sorted(set(flags))


def _severity(flags: list[str], scores: dict[str, float]) -> str:
    low_metrics = sum(value < LOW_SCORE_THRESHOLD for value in scores.values())
    blocking_flags = {
        "ambiguous_reference",
        "obvious_typo_or_informal_wording",
        "question_overly_compound",
        "single_locator_for_multi_claim",
    }
    if any(flag in blocking_flags for flag in flags) and low_metrics >= 1:
        return "blocker"
    if low_metrics >= 2 or flags:
        return "review"
    return "pass"


def audit_candidate_quality(
    dataset_path: Path,
    *,
    evaluation_dir: Path | None = None,
) -> dict[str, Any]:
    """审计一个 rag_eval_v1 数据集中的生成候选题，不改写任何输入文件。"""
    dataset = load_eval_dataset_bundle(Path(dataset_path))
    scores_by_sample = _performance_by_sample(evaluation_dir)
    items: list[dict[str, Any]] = []
    flag_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()

    for sample in dataset.get("samples") or []:
        if not isinstance(sample, dict) or not _is_generated_candidate(sample):
            continue
        sample_id = str(sample.get("sample_id") or "").strip()
        scores = scores_by_sample.get(sample_id, {})
        flags = _intrinsic_flags(sample)
        for metric, value in scores.items():
            if value < LOW_SCORE_THRESHOLD:
                flags.append(f"ragas_{metric}_low")
        flags = sorted(set(flags))
        severity = _severity(flags, scores)
        flag_counts.update(flags)
        severity_counts.update([severity])
        items.append({
            "sample_id": sample_id,
            "severity": severity,
            "flags": flags,
            "question": str(sample.get("question") or ""),
            "reference_answer_length": len(str(sample.get("reference_answer") or "")),
            "expected_claim_count": len(sample.get("expected_claims") or []),
            "gold_evidence_count": len(sample.get("gold_evidence") or []),
            "ragas_scores": scores,
        })

    severity_rank = {"blocker": 0, "review": 1, "pass": 2}
    items.sort(key=lambda item: (severity_rank[item["severity"]], -len(item["flags"]), item["sample_id"]))
    return {
        "schema_version": "rag_candidate_quality_audit_v1",
        "dataset_id": dataset.get("dataset_id", ""),
        "dataset_revision": dataset.get("dataset_revision", ""),
        "evaluation_dir": str(Path(evaluation_dir).resolve()) if evaluation_dir else "",
        "summary": {
            "candidate_sample_count": len(items),
            "severity_counts": dict(severity_counts),
            "flag_counts": dict(flag_counts),
            "low_score_threshold": LOW_SCORE_THRESHOLD,
        },
        "items": items,
    }


def build_candidate_quality_audit_markdown(report: dict[str, Any]) -> str:
    """把机器审计摘要转换为可人工逐题复核的 Markdown。"""
    def cell(value: Any) -> str:
        return str(value or "").replace("|", "\\|").replace("\n", " ").strip()

    summary = report.get("summary") or {}
    lines = [
        "# Candidate Quality Audit",
        "",
        f"- dataset: `{cell(report.get('dataset_id'))}`",
        f"- revision: `{cell(report.get('dataset_revision'))}`",
        f"- candidate samples: {summary.get('candidate_sample_count', 0)}",
        "",
        "## Summary",
        "",
        "| severity | count |",
        "| --- | ---: |",
    ]
    for severity, count in (summary.get("severity_counts") or {}).items():
        lines.append(f"| {cell(severity)} | {count} |")
    lines.extend(["", "| flag | count |", "| --- | ---: |"])
    for flag, count in sorted((summary.get("flag_counts") or {}).items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| `{cell(flag)}` | {count} |")
    lines.extend([
        "",
        "## Items",
        "",
        "自动 `blocker` 只表示应优先人工复核，不等于自动拒绝；`review` 表示存在结构或指标风险，`pass` 表示当前规则未发现明显问题。",
        "",
        "| severity | sample_id | flags | claims/evidence | Ragas scores | question |",
        "| --- | --- | --- | ---: | --- | --- |",
    ])
    for item in report.get("items") or []:
        score_text = ", ".join(f"{key}={value:.3f}" for key, value in (item.get("ragas_scores") or {}).items())
        lines.append(
            f"| {cell(item.get('severity'))} | `{cell(item.get('sample_id'))}` | "
            f"{cell(', '.join(item.get('flags') or []))} | "
            f"{item.get('expected_claim_count', 0)}/{item.get('gold_evidence_count', 0)} | "
            f"{cell(score_text)} | {cell(item.get('question'))} |"
        )
    lines.extend([
        "",
        "## Reusable review rule",
        "",
        "1. 先跑结构规则：题目长度、歧义/拼写、复合问题、文档导航问题。",
        "2. 再跑证据结构：expected_claims 与 gold_evidence 数量是否匹配、是否跨文档。",
        "3. 最后合并同一 Gold revision 的 Ragas 低分样本，按 blocker/review/pass 排序。",
        "4. 自动审计只生成复核队列，不自动修改候选题或冻结 Gold。",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="审计生成候选题质量，不修改输入数据集")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--evaluation-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    report = audit_candidate_quality(args.dataset, evaluation_dir=args.evaluation_dir)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        write_cli_output(payload)
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(build_candidate_quality_audit_markdown(report), encoding="utf-8")


if __name__ == "__main__":
    main()
