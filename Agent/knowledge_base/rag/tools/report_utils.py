import math
from pathlib import Path
from typing import Any, Dict, List


TERM_TRANSLATIONS = {
    "All Traces": "全部链路记录",
    "Average Timings": "平均耗时",
    "Bad Case Traces": "问题样本链路",
    "Claim Eval Report": "断言评测报告",
    "Cross Metric Bad Cases": "跨指标问题样本",
    "Datasets": "数据集",
    "Errors": "错误",
    "Judge Failed Cases": "评测器失败样本",
    "Low Coverage Cases": "低覆盖样本",
    "Low Score / NaN Cases": "低分或空值样本",
    "Loss Reason Counts": "损失原因统计",
    "Loss Reasons": "损失原因",
    "Notes": "说明",
    "Overall": "整体指标",
    "Per Question": "逐题详情",
    "RAG Eval Dataset Validation Report": "RAG 评测数据集校验报告",
    "RAG Retrieval Eval Report": "RAG 检索评测报告",
    "RAG Retrieval Sweep Report": "RAG 检索参数扫描报告",
    "RAG Trace Report": "RAG 链路追踪报告",
    "RAG Evaluation Pipeline Summary": "RAG 评测流水线总报告",
    "Ragas Baseline Report": "Ragas 基线报告",
    "Runs": "运行组",
    "Run Info": "运行信息",
    "Score Summary": "分数汇总",
    "Stage Metrics": "阶段指标",
    "Summary": "汇总",
    "Step Results": "步骤结果",
    "Threshold Checks": "阈值检查",
    "Key Metrics": "核心指标",
    "Unsupported answer claims": "回答中未被证据支撑的断言",
    "active_profile": "启用配置",
    "actual": "实际值",
    "answer_covered": "回答是否覆盖",
    "answer_confidence": "回答置信度",
    "answer_preview": "回答预览",
    "answer_relevancy": "回答相关性",
    "answer_relevancy_strictness": "回答相关性严格度",
    "answer_status": "回答状态",
    "avg_ms": "平均毫秒",
    "avg_total_ms": "平均总耗时毫秒",
    "bad_case_trace_count": "问题样本链路数",
    "build_seconds": "构建耗时秒数",
    "categories": "类别",
    "claim": "断言",
    "claim_coverage": "断言覆盖率",
    "claim_eval_status": "断言评测状态",
    "claim_eval_trace_count": "断言评测链路数",
    "context_recall": "上下文召回率",
    "context_count": "上下文数量",
    "context_utilization": "上下文利用率",
    "count": "数量",
    "dataset": "数据集",
    "dataset_path": "数据集路径",
    "dense_fetch_k": "dense 召回数",
    "dense_mmr_k": "MMR 保留数",
    "error_count": "错误数",
    "eval_seconds": "评测耗时秒数",
    "evidence_ids": "证据 ID",
    "evidence_support_rate": "证据支撑率",
    "evidence_supported": "证据是否支撑",
    "faithfulness": "忠实性",
    "field": "字段",
    "final_gold_rank": "最终 gold 排名",
    "final_top_k": "最终返回数",
    "has_retrieval_eval": "是否有检索评测",
    "hit_rate": "命中率",
    "judge_profile": "评测器配置",
    "judge_failed_count": "评测器失败数",
    "judge_model": "评测模型",
    "message": "信息",
    "limit": "样本上限",
    "metric": "指标",
    "mean": "均值",
    "missing_claims": "缺失断言",
    "mmr_lambda": "MMR lambda",
    "mrr": "平均倒数排名",
    "nan": "空值数",
    "nan_ragas": "Ragas 空值指标",
    "q": "题号",
    "question": "问题",
    "question_type": "问题类型",
    "question_types": "问题类型分布",
    "ragas_eval_trace_count": "Ragas 评测链路数",
    "ragas_max_retries": "Ragas 最大重试次数",
    "ragas_max_wait": "Ragas 最长重试等待秒数",
    "ragas_max_workers": "Ragas 最大并发数",
    "ragas_timeout": "Ragas 超时秒数",
    "ragas_version": "Ragas 版本",
    "ragas_answer_relevancy": "Ragas 回答相关性",
    "ragas_context_recall": "Ragas 上下文召回率",
    "ragas_context_utilization": "Ragas 上下文利用率",
    "ragas_faithfulness": "Ragas 忠实性",
    "rank": "排名",
    "recall": "召回率",
    "recall_at_k": "Top-K 召回率",
    "reason": "原因",
    "reciprocal_rank": "倒数排名",
    "retrieval_eval": "检索评测",
    "retrieval_eval_trace_count": "检索评测链路数",
    "retrieval_hit_rate": "检索命中率",
    "retrieval_mrr": "检索 MRR",
    "retrieval_only_count": "仅检索样本数",
    "retrieval_recall": "检索召回率",
    "retrieval_recall_at_k": "检索 Top-K 召回率",
    "run": "运行组",
    "run_count": "运行组数量",
    "repeat_count": "重复评测次数",
    "shared_count": "共同样本数",
    "run_llm_judge": "是否运行 LLM 评测器",
    "sample_count": "样本数",
    "step_name": "步骤名称",
    "samples": "样本数",
    "source_sample_count": "源样本数",
    "loaded_from_cache": "是否读取数据集缓存",
    "loaded_score_from_cache": "是否读取分数缓存",
    "low_score_threshold": "低分阈值",
    "sources": "来源",
    "sparse_fetch_k": "sparse 召回数",
    "stage": "阶段",
    "std": "标准差",
    "step": "步骤",
    "status": "状态",
    "status_reason": "状态原因",
    "threshold": "阈值",
    "threshold_name": "阈值名称",
    "claim_coverage_min": "断言覆盖率下限",
    "evidence_support_rate_min": "证据支撑率下限",
    "judge_failed_count_max": "评测器失败数上限",
    "ragas_faithfulness_min": "Ragas 忠实性下限",
    "retrieval_hit_rate_min": "检索命中率下限",
    "retrieval_recall_at_k_min": "检索 Top-K 召回率下限",
    "total": "总数",
    "trace_count": "链路记录数",
    "trace_id": "链路 ID",
    "unsupported_answer_claim_count": "未支撑回答断言数",
    "valid_sample_count": "有效样本数",
    "value": "值",
    "with_claims": "含断言样本数",
    "with_gold": "含 gold 标注样本数",
}


def report_label(term: str) -> str:
    """返回英文术语 + 中文翻译，便于 Markdown 报告给项目组阅读。"""
    translation = TERM_TRANSLATIONS.get(term)
    if not translation:
        return term
    return f"{term}（{translation}）"


def format_metric(value: Any) -> str:
    """把指标值格式化为 Markdown 表格文本。"""
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        return f"{value:.4f}"
    if value is None:
        return ""
    return str(value)


def escape_markdown_cell(value: Any) -> str:
    """转义 Markdown 表格单元格中的竖线，并统一 None 展示。"""
    if value is None:
        return ""
    return str(value).replace("|", " ")


def write_markdown_file(path: Path, content: str) -> None:
    """写入人工可读 Markdown。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_dataset_validation_markdown_report(result: Dict[str, Any]) -> str:
    """生成数据集校验 Markdown 报告。"""
    lines = [
        f"# {report_label('RAG Eval Dataset Validation Report')}",
        "",
        f"- {report_label('status')}: {result['status']}",
        f"- {report_label('error_count')}: {result['error_count']}",
        f"- warning_count: {result.get('warning_count', 0)}",
        "",
        f"## {report_label('Datasets')}",
        "",
        f"| {report_label('dataset')} | {report_label('samples')} | {report_label('with_gold')} | "
        f"{report_label('with_claims')} |",
        "| --- | ---: | ---: | ---: |",
    ]
    for dataset_name, detail in result["datasets"].items():
        with_gold = detail.get("with_gold_evidence", 0)
        lines.append(
            f"| {dataset_name} | {detail['sample_count']} | {with_gold} | "
            f"{detail.get('with_expected_claims', 0)} |"
        )

    lines.extend(["", f"## {report_label('Errors')}", ""])
    if result["errors"]:
        lines.extend(f"- {error}" for error in result["errors"])
    else:
        lines.append("No validation errors.")

    warnings = result.get("warnings", [])
    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("No validation warnings.")

    benchmark_corpus = result.get("benchmark_corpus", result.get("medical_corpus", {}))
    if benchmark_corpus:
        lines.extend(["", "## Benchmark Corpus", ""])
        lines.extend(
            [
                f"- exists: {benchmark_corpus.get('exists')}",
                f"- doc_count: {benchmark_corpus.get('doc_count', 0)}",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_pipeline_summary_markdown_report(summary: Dict[str, Any]) -> str:
    """生成 RAG 评测流水线总报告。"""
    lines = [
        f"# {report_label('RAG Evaluation Pipeline Summary')}",
        "",
        f"## {report_label('Run Info')}",
        "",
        f"| {report_label('field')} | {report_label('value')} |",
        "| --- | --- |",
        f"| {report_label('status')} | {summary.get('status', '')} |",
        f"| {report_label('status_reason')} | {summary.get('status_reason', '')} |",
        f"| run_id | {summary.get('run_id', '')} |",
        f"| run_dir | {escape_markdown_cell(summary.get('run_dir', ''))} |",
        f"| started_at | {summary.get('started_at', '')} |",
        f"| finished_at | {summary.get('finished_at', '')} |",
        "",
        f"## {report_label('Step Results')}",
        "",
        f"| {report_label('step_name')} | {report_label('status')} | {report_label('message')} |",
        "| --- | --- | --- |",
    ]
    for step in summary.get("steps", []):
        lines.append(
            f"| {step.get('name', '')} | {step.get('status', '')} | "
            f"{escape_markdown_cell(step.get('message', ''))} |"
        )

    lines.extend(
        [
            "",
            f"## {report_label('Key Metrics')}",
            "",
            f"| {report_label('metric')} | {report_label('value')} |",
            "| --- | ---: |",
        ]
    )
    for metric_name, value in summary.get("key_metrics", {}).items():
        lines.append(f"| {report_label(metric_name)} | {format_metric(value)} |")

    lines.extend(
        [
            "",
            f"## {report_label('Threshold Checks')}",
            "",
            f"| {report_label('threshold_name')} | {report_label('status')} | "
            f"{report_label('actual')} | {report_label('threshold')} |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    checks = summary.get("threshold_checks", [])
    if checks:
        for check in checks:
            lines.append(
                f"| {report_label(check.get('name', ''))} | {check.get('status', '')} | "
                f"{format_metric(check.get('actual'))} | {format_metric(check.get('threshold'))} |"
            )
    else:
        lines.append("| None | skipped |  |  |")

    dataset_fingerprints = summary.get("dataset_fingerprints", {})
    lines.extend(["", "## Dataset Fingerprints（数据集指纹）", ""])
    if dataset_fingerprints:
        lines.extend(["| dataset | sha256 | bytes |", "| --- | --- | ---: |"])
        for dataset_name, fingerprint in dataset_fingerprints.items():
            lines.append(
                f"| {dataset_name} | {fingerprint.get('sha256', '')} | {fingerprint.get('bytes', '')} |"
            )
    else:
        lines.append("No dataset fingerprints recorded.")

    lines.extend(["", f"## {report_label('Notes')}", ""])
    lines.append("- 当前默认 pipeline 会按 `rag_config.py` 中的步骤运行完整 RAG 测评；大样本运行耗时取决于 embedding、answer 和 judge API。")
    lines.append("- `runs/` 目录保存本次机器结果、人工报告、配置快照和 summary，便于后续和 baseline 对比。")
    return "\n".join(lines).rstrip() + "\n"


def build_rag_retrieval_single_markdown_report(result: Dict[str, Any]) -> str:
    """生成单组 RAG 检索评测报告。"""
    lines = [
        f"# {report_label('RAG Retrieval Eval Report')}",
        "",
        f"## {report_label('Overall')}",
        "",
        f"| {report_label('metric')} | {report_label('value')} |",
        "| --- | ---: |",
        f"| {report_label('sample_count')} | {result.get('sample_count', 0)} |",
        f"| {report_label('recall_at_k')} | {format_metric(result.get('recall_at_k', 0.0))} |",
        f"| {report_label('mrr')} | {format_metric(result.get('mrr', 0.0))} |",
        f"| {report_label('hit_rate')} | {format_metric(result.get('hit_rate', 0.0))} |",
        "",
        f"## {report_label('Average Timings')}",
        "",
    ]

    avg_timings = result.get("avg_timings_ms", {})
    if avg_timings:
        lines.extend([f"| {report_label('step')} | {report_label('avg_ms')} |", "| --- | ---: |"])
        for step, avg_ms in avg_timings.items():
            lines.append(f"| {escape_markdown_cell(step)} | {format_metric(avg_ms)} |")
    else:
        lines.append("No timing data recorded.")

    lines.extend(
        [
            "",
            f"## {report_label('Stage Metrics')}",
            "",
            f"| {report_label('stage')} | {report_label('recall')} | {report_label('mrr')} | "
            f"{report_label('hit_rate')} |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for stage_name, metrics in result.get("stage_metrics", {}).items():
        lines.append(
            f"| {escape_markdown_cell(stage_name)} | {format_metric(metrics.get('recall', 0.0))} | "
            f"{format_metric(metrics.get('mrr', 0.0))} | {format_metric(metrics.get('hit_rate', 0.0))} |"
        )

    lines.extend(["", f"## {report_label('Loss Reasons')}", ""])
    loss_reason_counts = result.get("loss_reason_counts", {})
    if loss_reason_counts:
        lines.extend([f"| {report_label('reason')} | {report_label('count')} |", "| --- | ---: |"])
        for reason, count in sorted(loss_reason_counts.items()):
            lines.append(f"| {escape_markdown_cell(reason)} | {count} |")
    else:
        lines.append("No loss reasons recorded.")

    lines.extend(["", f"## {report_label('Per Question')}", ""])
    for index, detail in enumerate(result.get("details", []), start=1):
        lines.extend(
            [
                f"### Q{index}. {escape_markdown_cell(detail.get('question', ''))}",
                "",
                f"- sample_id: {detail.get('sample_id', '')}",
                f"- {report_label('recall')}: {format_metric(detail.get('recall', 0.0))}",
                f"- {report_label('reciprocal_rank')}: {format_metric(detail.get('reciprocal_rank', 0.0))}",
                f"- matched_evidence_count: {len(detail.get('matched_evidence', []))}",
                f"- expected_claims: {'; '.join(detail.get('expected_claims', [])) or 'None'}",
                f"- loss_reasons: {', '.join(detail.get('loss_reasons', [])) or 'None'}",
                f"- final_evidence_count: {len(detail.get('final_evidence_payload', []))}",
                f"- total_trace_ms: {format_metric(detail.get('trace_timings_ms', {}).get('total', 0.0))}",
                "- best_gold_rank_by_stage: "
                + ", ".join(
                    f"{stage}={rank_detail.get('best_rank')}"
                    for stage, rank_detail in detail.get("gold_rank_summary", {}).items()
                ),
                "",
            ]
        )
        claim_diagnostics = detail.get("claim_diagnostics", [])
        if claim_diagnostics:
            lines.extend(
                [
                    "| claim | final_status | first_seen_stage | possible_loss_stage | final_overlap |",
                    "| --- | --- | --- | --- | ---: |",
                ]
            )
            for claim_detail in claim_diagnostics:
                stage_overlaps = claim_detail.get("stage_overlaps", {})
                lines.append(
                    f"| {escape_markdown_cell(claim_detail.get('claim', ''))} | "
                    f"{claim_detail.get('final_status', '')} | "
                    f"{claim_detail.get('first_seen_stage')} | "
                    f"{claim_detail.get('possible_loss_stage')} | "
                    f"{format_metric(stage_overlaps.get('final', 0.0))} |"
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_rag_retrieval_sweep_markdown_report(result: Dict[str, Any]) -> str:
    """生成多组参数 sweep 报告。"""
    lines = [
        f"# {report_label('RAG Retrieval Sweep Report')}",
        "",
        f"- {report_label('sample_count')}: {result.get('sample_count', 0)}",
        f"- {report_label('run_count')}: {result.get('run_count', 0)}",
        f"- {report_label('limit')}: {result.get('limit')}",
        "",
        f"## {report_label('Runs')}",
        "",
        f"| {report_label('rank')} | name | {report_label('recall')} | {report_label('mrr')} | "
        f"{report_label('hit_rate')} | top4 recall | top4 mrr | top5 recall | top5 mrr | "
        f"{report_label('avg_total_ms')} | {report_label('final_top_k')} | "
        f"{report_label('dense_fetch_k')} | {report_label('dense_mmr_k')} | {report_label('sparse_fetch_k')} | "
        f"{report_label('mmr_lambda')} |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for rank, run in enumerate(result.get("runs", []), start=1):
        metrics = run.get("metrics", {})
        config = run.get("config", {})
        avg_timings = metrics.get("avg_timings_ms", {})
        prefix_metrics = metrics.get("final_prefix_metrics", {})
        top4_metrics = prefix_metrics.get("top4", {})
        top5_metrics = prefix_metrics.get("top5", {})
        lines.append(
            f"| {rank} | {escape_markdown_cell(run.get('name', run.get('run_id', '')))} | "
            f"{format_metric(metrics.get('recall_at_k', 0.0))} | "
            f"{format_metric(metrics.get('mrr', 0.0))} | "
            f"{format_metric(metrics.get('hit_rate', 0.0))} | "
            f"{format_metric(top4_metrics.get('recall', 0.0))} | "
            f"{format_metric(top4_metrics.get('mrr', 0.0))} | "
            f"{format_metric(top5_metrics.get('recall', 0.0))} | "
            f"{format_metric(top5_metrics.get('mrr', 0.0))} | "
            f"{format_metric(avg_timings.get('total', 0.0))} | "
            f"{config.get('final_top_k', '')} | {config.get('dense_fetch_k', '')} | "
            f"{config.get('dense_mmr_k', '')} | {config.get('sparse_fetch_k', '')} | "
            f"{config.get('mmr_lambda', '')} |"
        )

    lines.extend(["", f"## {report_label('Loss Reason Counts')}", ""])
    for run in result.get("runs", []):
        metrics = run.get("metrics", {})
        loss_reason_counts = metrics.get("loss_reason_counts", {})
        loss_text = ", ".join(f"{key}: {value}" for key, value in sorted(loss_reason_counts.items()))
        lines.append(f"- {run.get('name', run.get('run_id', ''))}: {loss_text or 'None'}")

    lines.extend(
        [
            "",
            f"## {report_label('Stage Metrics')}",
            "",
            f"| {report_label('run')} | {report_label('stage')} | {report_label('recall')} | "
            f"{report_label('mrr')} | {report_label('hit_rate')} |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for run in result.get("runs", []):
        metrics = run.get("metrics", {})
        for stage_name, stage_metrics in metrics.get("stage_metrics", {}).items():
            lines.append(
                f"| {escape_markdown_cell(run.get('name', run.get('run_id', '')))} | "
                f"{escape_markdown_cell(stage_name)} | {format_metric(stage_metrics.get('recall', 0.0))} | "
                f"{format_metric(stage_metrics.get('mrr', 0.0))} | "
                f"{format_metric(stage_metrics.get('hit_rate', 0.0))} |"
            )

    lines.extend(
        [
            "",
            f"## {report_label('Average Timings')}",
            "",
            f"| {report_label('run')} | {report_label('step')} | {report_label('avg_ms')} |",
            "| --- | --- | ---: |",
        ]
    )
    for run in result.get("runs", []):
        metrics = run.get("metrics", {})
        for step, avg_ms in metrics.get("avg_timings_ms", {}).items():
            lines.append(
                f"| {escape_markdown_cell(run.get('name', run.get('run_id', '')))} | "
                f"{escape_markdown_cell(step)} | {format_metric(avg_ms)} |"
            )
    return "\n".join(lines).rstrip() + "\n"


def build_ragas_markdown_report(result: Dict[str, Any]) -> str:
    """生成 Ragas baseline Markdown 报告。"""
    lines = [
        f"# {report_label('Ragas Baseline Report')}",
        "",
        f"## {report_label('Run Info')}",
        "",
        f"| {report_label('field')} | {report_label('value')} |",
        "| --- | --- |",
        f"| {report_label('status')} | {result.get('status', '')} |",
        f"| {report_label('ragas_version')} | {result.get('ragas_version', '')} |",
        f"| {report_label('judge_model')} | {result.get('judge_model', '')} |",
        f"| {report_label('judge_profile')} | {result.get('judge_profile', '')} |",
        f"| {report_label('active_profile')} | {result.get('active_profile', '')} |",
        f"| {report_label('dataset_path')} | {escape_markdown_cell(result.get('dataset_path', ''))} |",
        f"| {report_label('sample_count')} | {result.get('sample_count', 0)} |",
        f"| {report_label('source_sample_count')} | {result.get('source_sample_count', 0)} |",
        f"| {report_label('build_seconds')} | {format_metric(result.get('build_seconds', 0.0))} |",
        f"| {report_label('eval_seconds')} | {format_metric(result.get('eval_seconds', 0.0))} |",
        f"| {report_label('repeat_count')} | {result.get('repeat_count', '')} |",
        f"| {report_label('loaded_from_cache')} | {result.get('loaded_from_cache', False)} |",
        f"| {report_label('loaded_score_from_cache')} | {result.get('loaded_score_from_cache', False)} |",
        f"| {report_label('ragas_timeout')} | {result.get('ragas_timeout', '')} |",
        f"| {report_label('ragas_max_workers')} | {result.get('ragas_max_workers', '')} |",
        f"| {report_label('ragas_max_retries')} | {result.get('ragas_max_retries', '')} |",
        f"| {report_label('ragas_max_wait')} | {result.get('ragas_max_wait', '')} |",
        f"| {report_label('answer_relevancy_strictness')} | "
        f"{result.get('answer_relevancy_strictness', '')} |",
        f"| {report_label('low_score_threshold')} | {result.get('low_score_threshold', '')} |",
        "",
        f"## {report_label('Score Summary')}",
        "",
    ]

    score_summary = result.get("score_summary", {})
    if score_summary:
        score_stddev = result.get("score_stddev", {})
        metric_validity = result.get("metric_validity", {})
        lines.extend(
            [
                f"| {report_label('metric')} | {report_label('mean')} | {report_label('std')} | "
                f"valid | {report_label('nan')} | {report_label('total')} |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for metric_name, score in score_summary.items():
            validity = metric_validity.get(metric_name, {})
            lines.append(
                f"| {report_label(metric_name)} | {format_metric(score)} | "
                f"{format_metric(score_stddev.get(metric_name, 0.0))} | "
                f"{validity.get('valid_count', '')} | {validity.get('nan_count', '')} | "
                f"{validity.get('total_count', '')} |"
            )
    else:
        lines.append("No Ragas scores were produced.")

    low_score_cases = result.get("low_score_cases", [])
    if low_score_cases:
        lines.extend(
            [
                "",
                f"## {report_label('Low Score / NaN Cases')}",
                "",
                f"| {report_label('q')} | {report_label('metric')} | score | {report_label('reason')} | "
                f"{report_label('question')} |",
                "| ---: | --- | ---: | --- | --- |",
            ]
        )
        for case in low_score_cases[:40]:
            lines.append(
                f"| {case.get('question_index', '')} | {report_label(case.get('metric', ''))} | "
                f"{format_metric(case.get('score'))} | {escape_markdown_cell(case.get('reason', ''))} | "
                f"{escape_markdown_cell(case.get('question', ''))} |"
            )

    cross_metric = result.get("cross_metric_bad_cases", {})
    if cross_metric:
        lines.extend(["", f"## {report_label('Cross Metric Bad Cases')}", ""])
        if not cross_metric.get("available"):
            lines.append(f"Cross metric analysis unavailable: {cross_metric.get('warning', '')}")
        else:
            summary = cross_metric.get("summary", {})
            thresholds = cross_metric.get("thresholds", {})
            lines.extend(
                [
                    f"| {report_label('field')} | {report_label('value')} |",
                    "| --- | --- |",
                    f"| {report_label('shared_count')} | {summary.get('shared_count', 0)} |",
                    f"| ragas_only_count | {summary.get('ragas_only_count', 0)} |",
                    f"| {report_label('retrieval_only_count')} | {summary.get('retrieval_only_count', 0)} |",
                    f"| bad_case_count | {summary.get('bad_case_count', 0)} |",
                    f"| ragas_low_threshold | {thresholds.get('ragas_low_threshold', '')} |",
                    f"| retrieval_recall_low_threshold | "
                    f"{thresholds.get('retrieval_recall_low_threshold', '')} |",
                    f"| retrieval_mrr_low_threshold | {thresholds.get('retrieval_mrr_low_threshold', '')} |",
                    "",
                ]
            )
            cases = cross_metric.get("cases", [])
            if cases:
                lines.extend(
                    [
                        f"| {report_label('q')} | {report_label('retrieval_recall')} | "
                        f"{report_label('retrieval_mrr')} | {report_label('final_gold_rank')} | "
                        f"low_ragas | {report_label('nan_ragas')} | {report_label('categories')} | "
                        f"{report_label('question')} |",
                        "| ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
                    ]
                )
                for case in cases[:40]:
                    lines.append(
                        f"| {case.get('question_index', '')} | "
                        f"{format_metric(case.get('retrieval_recall'))} | "
                        f"{format_metric(case.get('retrieval_mrr'))} | "
                        f"{format_metric(case.get('final_best_gold_rank'))} | "
                        f"{', '.join(case.get('low_ragas_metrics', [])) or 'None'} | "
                        f"{', '.join(case.get('nan_ragas_metrics', [])) or 'None'} | "
                        f"{escape_markdown_cell(', '.join(case.get('categories', [])) or 'None')} | "
                        f"{escape_markdown_cell(case.get('question', ''))} |"
                    )
            else:
                lines.append("No cross metric bad cases under current thresholds.")

    if result.get("error"):
        lines.extend(["", "## Error", "", f"```text\n{result['error']}\n```"])
    if result.get("warning"):
        lines.extend(["", "## Warning", "", result["warning"]])

    lines.extend(["", f"## {report_label('Per Question')}", ""])
    records = result.get("score_records", [])
    metadata_rows = result.get("metadata", [])
    for index, metadata in enumerate(metadata_rows, start=1):
        score_record = records[index - 1] if index - 1 < len(records) else {}
        metric_parts = [
            f"{metric}={format_metric(score_record.get(metric))}"
            for metric in result.get("metrics", [])
            if metric in score_record
        ]
        ragas_rows = result.get("ragas_rows", [])
        fallback_answer = ragas_rows[index - 1].get("response", "") if index - 1 < len(ragas_rows) else ""
        answer = score_record.get("response") or fallback_answer
        answer_preview = str(answer).replace("\n", " ")[:160]
        lines.extend(
            [
                f"### Q{index}. {escape_markdown_cell(metadata.get('question', ''))}",
                "",
                f"- {report_label('question_type')}: {metadata.get('question_type', '')}",
                f"- {report_label('context_count')}: {metadata.get('context_count', 0)}",
                f"- {report_label('answer_status')}: {metadata.get('answer_status', '')}",
                f"- {report_label('answer_confidence')}: {metadata.get('answer_confidence', '')}",
                f"- citations: {', '.join(metadata.get('citations', [])) or 'None'}",
                f"- scores: {', '.join(metric_parts) or 'None'}",
                f"- {report_label('answer_preview')}: {escape_markdown_cell(answer_preview)}",
                "",
            ]
        )

    lines.extend(
        [
            f"## {report_label('Notes')}",
            "",
            "- Ragas baseline 评估的是 RAG 生成回答和 final evidence 的关系，不替代 Phase2 的 retrieval trace 诊断。",
            "- `context_recall` 依赖 `reference_answer`，当前数据集的 reference 仍需要持续人工复查。",
            "- 当前 Ragas judge prompt 主要是通用提示；中文因果领域样本需要后续人工抽查来校准可信度。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def build_claim_eval_markdown_report(result: Dict[str, Any]) -> str:
    """生成 claim eval Markdown 报告。"""
    lines = [
        f"# {report_label('Claim Eval Report')}",
        "",
        f"## {report_label('Run Info')}",
        "",
        f"| {report_label('field')} | {report_label('value')} |",
        "| --- | --- |",
        f"| {report_label('status')} | {result.get('status', '')} |",
        f"| {report_label('judge_model')} | {result.get('judge_model', '')} |",
        f"| {report_label('sample_count')} | {result.get('sample_count', 0)} |",
        f"| {report_label('valid_sample_count')} | {result.get('valid_sample_count', 0)} |",
        f"| {report_label('judge_failed_count')} | {result.get('judge_failed_count', 0)} |",
        f"| {report_label('limit')} | {result.get('limit')} |",
        f"| {report_label('run_llm_judge')} | {result.get('run_llm_judge')} |",
        f"| {report_label('eval_seconds')} | {format_metric(result.get('eval_seconds', 0.0))} |",
        "",
        f"## {report_label('Score Summary')}",
        "",
        f"| {report_label('metric')} | {report_label('value')} |",
        "| --- | ---: |",
    ]
    for metric_name, value in result.get("score_summary", {}).items():
        lines.append(f"| {report_label(metric_name)} | {format_metric(value)} |")

    lines.extend(["", f"## {report_label('Low Coverage Cases')}", ""])
    low_cases = result.get("low_coverage_cases", [])
    if low_cases:
        lines.extend(
            [
                f"| {report_label('q')} | {report_label('claim_coverage')} | "
                f"{report_label('evidence_support_rate')} | {report_label('question')} |",
                "| ---: | ---: | ---: | --- |",
            ]
        )
        for case in low_cases:
            lines.append(
                f"| {case.get('question_index', '')} | "
                f"{format_metric(case.get('claim_coverage'))} | "
                f"{format_metric(case.get('evidence_support_rate'))} | "
                f"{escape_markdown_cell(case.get('question', ''))} |"
            )
    else:
        lines.append("No low coverage cases under current threshold.")

    lines.extend(["", f"## {report_label('Judge Failed Cases')}", ""])
    failed_cases = result.get("judge_failed_cases", [])
    if failed_cases:
        lines.extend(
            [
                f"| {report_label('q')} | {report_label('question')} | {report_label('reason')} |",
                "| ---: | --- | --- |",
            ]
        )
        for case in failed_cases:
            lines.append(
                f"| {case.get('question_index', '')} | "
                f"{escape_markdown_cell(case.get('question', ''))} | "
                f"{escape_markdown_cell(case.get('overall_notes', ''))} |"
            )
    else:
        lines.append("No judge failed cases.")

    lines.extend(["", f"## {report_label('Per Question')}", ""])
    for detail in result.get("details", []):
        lines.extend(
            [
                f"### Q{detail.get('question_index')}. {escape_markdown_cell(detail.get('question', ''))}",
                "",
                f"- {report_label('question_type')}: {detail.get('question_type', '')}",
                f"- {report_label('claim_eval_status')}: {detail.get('claim_eval_status', '')}",
                f"- {report_label('claim_coverage')}: {format_metric(detail.get('claim_coverage'))}",
                f"- {report_label('evidence_support_rate')}: {format_metric(detail.get('evidence_support_rate'))}",
                f"- {report_label('unsupported_answer_claim_count')}: "
                f"{detail.get('unsupported_answer_claim_count', 0)}",
                f"- {report_label('missing_claims')}: {'; '.join(detail.get('missing_claims', [])) or 'None'}",
                "",
                f"| {report_label('claim')} | {report_label('answer_covered')} | "
                f"{report_label('evidence_supported')} | {report_label('evidence_ids')} | "
                f"{report_label('reason')} |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for claim_result in detail.get("claim_results", []):
            lines.append(
                f"| {escape_markdown_cell(claim_result.get('claim', ''))} | "
                f"{claim_result.get('answer_covered')} | "
                f"{claim_result.get('evidence_supported')} | "
                f"{', '.join(claim_result.get('evidence_ids', [])) or 'None'} | "
                f"{escape_markdown_cell(claim_result.get('reason', ''))} |"
            )
        if detail.get("unsupported_answer_claims"):
            lines.extend(["", f"{report_label('Unsupported answer claims')}:"])
            lines.extend(f"- {claim}" for claim in detail["unsupported_answer_claims"])
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_trace_markdown_report(trace_index: Dict[str, Any]) -> str:
    """生成 trace export Markdown 报告。"""
    lines = [
        f"# {report_label('RAG Trace Report')}",
        "",
        f"## {report_label('Summary')}",
        "",
        f"| {report_label('field')} | {report_label('value')} |",
        "| --- | ---: |",
        f"| {report_label('trace_count')} | {trace_index['trace_count']} |",
        f"| {report_label('bad_case_trace_count')} | {trace_index['bad_case_trace_count']} |",
        f"| {report_label('retrieval_eval_trace_count')} | {trace_index['retrieval_eval_trace_count']} |",
        f"| {report_label('ragas_eval_trace_count')} | {trace_index['ragas_eval_trace_count']} |",
        f"| {report_label('claim_eval_trace_count')} | {trace_index['claim_eval_trace_count']} |",
        "",
        f"## {report_label('Bad Case Traces')}",
        "",
    ]

    bad_rows = [row for row in trace_index["traces"] if row["is_bad_case"]]
    if bad_rows:
        lines.extend(
            [
                f"| {report_label('trace_id')} | {report_label('q')} | {report_label('sources')} | "
                f"{report_label('claim_coverage')} | {report_label('evidence_support_rate')} | "
                f"{report_label('faithfulness')} | {report_label('context_recall')} | "
                f"{report_label('question')} |",
                "| --- | ---: | --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for row in bad_rows:
            lines.append(
                f"| {row['trace_id']} | "
                f"{row['question_index']} | "
                f"{escape_markdown_cell(', '.join(row['bad_case_sources']))} | "
                f"{format_metric(row.get('claim_coverage'))} | "
                f"{format_metric(row.get('evidence_support_rate'))} | "
                f"{format_metric(row.get('faithfulness'))} | "
                f"{format_metric(row.get('context_recall'))} | "
                f"{escape_markdown_cell(row['question'])} |"
            )
    else:
        lines.append("No bad case traces.")

    lines.extend(["", f"## {report_label('All Traces')}", ""])
    lines.extend(
        [
            f"| {report_label('trace_id')} | {report_label('q')} | "
            f"{report_label('retrieval_eval')} | {report_label('claim_coverage')} | "
            f"{report_label('evidence_support_rate')} | {report_label('question')} |",
            "| --- | ---: | --- | ---: | ---: | --- |",
        ]
    )
    for row in trace_index["traces"]:
        lines.append(
            f"| {row['trace_id']} | "
            f"{row['question_index']} | "
            f"{row['has_retrieval_eval']} | "
            f"{format_metric(row.get('claim_coverage'))} | "
            f"{format_metric(row.get('evidence_support_rate'))} | "
            f"{escape_markdown_cell(row['question'])} |"
        )
    return "\n".join(lines).rstrip() + "\n"
