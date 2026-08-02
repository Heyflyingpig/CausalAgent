import json
import re
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Dict, List, Optional

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[4]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))  # 将项目根目录添加到 sys.path，以便正确导入模块

from Agent.knowledge_base.query_rag import (
    RagRetrievalConfig,
    build_retrieval_config,
    # build_retrieval_trace 是本评测真正调用知识库检索的入口。
    # 它会走当前 RAG retrieval 链路：dense -> threshold -> MMR -> sparse -> merge/rerank -> final。
    # rag_eval.py 只消费它返回的 trace，不直接操作 FAISS / embedding / sparse index。
    build_retrieval_trace,
    get_vector_db_metadata_summary,
)
from Agent.knowledge_base.rag.rag_eval.contracts import (
    candidate_evidence,
    evaluation_identity,
    load_eval_dataset as load_contract_dataset,
    locator_matches,
)
from Agent.knowledge_base.rag.rag_config import (
    MACHINE_OUTPUT_DIR,
    RAG_EVAL_DATASET_PATH,
    REPORT_OUTPUT_DIR,
    RETRIEVAL_EVAL_CONFIG,
    RETRIEVAL_PROFILES,
    RETRIEVAL_SWEEP_CONFIGS,
    TRACE_STAGE_ORDER,
)
from Agent.knowledge_base.rag.tools.report_utils import (
    build_rag_retrieval_single_markdown_report,
    build_rag_retrieval_sweep_markdown_report,
    write_markdown_file,
)

DEFAULT_DATASET_PATH = str(RAG_EVAL_DATASET_PATH) if RAG_EVAL_DATASET_PATH else ""
DEFAULT_OUTPUT_PATH = MACHINE_OUTPUT_DIR / "rag_eval_result.json"
DEFAULT_SWEEP_OUTPUT_PATH = MACHINE_OUTPUT_DIR / "rag_eval_sweep_result.json"
DEFAULT_REPORT_PATH = REPORT_OUTPUT_DIR / "rag_eval_report.md"
DEFAULT_SWEEP_REPORT_PATH = REPORT_OUTPUT_DIR / "rag_eval_sweep_report.md"

CLAIM_OVERLAP_THRESHOLD = 0.35
EvalEventCallback = Callable[[str, str, Dict[str, Any]], None]
EvalCancelChecker = Callable[[], bool]
RetrievalTraceBuilder = Callable[..., Dict[str, Any]]
VectorSummaryProvider = Callable[[], Dict[str, Any]]


def _cancel_requested(cancel_checker: Optional[EvalCancelChecker]) -> bool:
    """Return whether the caller has requested cooperative cancellation."""
    return bool(cancel_checker and cancel_checker())


def _emit_sample_progress(
    event_callback: Optional[EvalEventCallback],
    step_name: str,
    phase: str,
    current: int,
    total: int,
    sample: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit sample-level progress for long RAG evaluation loops."""
    if event_callback is None:
        return
    sample = sample or {}
    event_callback(
        "step_progress",
        f"{step_name} {phase}: {current}/{total}",
        {
            "step": step_name,
            "phase": phase,
            "current": current,
            "total": total,
            "sample_id": sample.get("sample_id", ""),
            "question": sample.get("question", ""),
        },
    )

# 本地手动运行时，优先改这里。
# mode="single" 跑一组配置；mode="sweep" 跑下面的 SWEEP_CONFIGS 参数对比。
# single 模式默认使用 query_rag.py 里的 RagRetrievalConfig() 默认值。
# 只有 top_k 不为 None 时，才会临时覆盖 final_top_k。
# 评测题集必须由 RAG_EVAL_DATASET_PATH 显式提供；没有 gold_evidence 时检索指标为未评分。
EVAL_RUN_CONFIG = RETRIEVAL_EVAL_CONFIG

# 内部调参用的候选配置。name 只是实验标签，config 会传给 RagRetrievalConfig。
# baseline_current 是把 single 模式实际使用的默认检索参数显式写出来，
# 方便在 sweep 报告中和其他参数组横向对比。
SWEEP_CONFIGS = RETRIEVAL_SWEEP_CONFIGS


def load_eval_dataset(dataset_path: str) -> List[Dict[str, Any]]:
    """
    加载评测数据集

    这里只读取人工维护的 benchmark 样本，不会调用知识库，也不会触发 RAG 检索。

    Args:
        dataset_path (str): 评测数据集文件路径

    Returns:
        List[Dict[str, Any]]: 返回评测数据列表，每个元素是一个包含评测样本的字典

    Raises:
        ValueError: 当 JSON 文件内容不是数组格式时抛出异常
    """
    if not str(dataset_path or "").strip():
        raise ValueError("RAG_EVAL_DATASET_PATH is not configured.")
    return load_contract_dataset(dataset_path)


def _collect_stage_metrics(
    stage_candidates: List[Dict[str, Any]],
    gold_evidence: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """按通用 evidence locator 统计一个检索阶段的命中情况。"""
    retrieved_evidence = [
        candidate_evidence(candidate.get("metadata", {}))
        for candidate in stage_candidates
    ]
    gold_evidence = list(gold_evidence or [])
    if not gold_evidence:
        return {
            "match_mode": "unscored",
            "retrieved_evidence": retrieved_evidence,
            "matched_evidence": [],
            "recall": None,
            "reciprocal_rank": None,
            "first_relevant_rank": None,
            "hit": None,
        }

    matched_flags = [
        any(locator_matches(candidate, expected) for expected in gold_evidence)
        for candidate in retrieved_evidence
    ]
    matched = [
        candidate
        for candidate, matched_flag in zip(retrieved_evidence, matched_flags)
        if matched_flag
    ]
    first_relevant_rank = next(
        (index for index, matched_flag in enumerate(matched_flags, start=1) if matched_flag),
        None,
    )
    reciprocal_rank = 1.0 / first_relevant_rank if first_relevant_rank else 0.0
    matched_gold = [
        expected
        for expected in gold_evidence
        if any(locator_matches(candidate, expected) for candidate in retrieved_evidence)
    ]
    recall = len(matched_gold) / len(gold_evidence)
    return {
        "match_mode": "locator",
        "retrieved_evidence": retrieved_evidence,
        "matched_evidence": matched,
        "recall": recall,
        "reciprocal_rank": reciprocal_rank,
        "first_relevant_rank": first_relevant_rank,
        "hit": 1 if matched else 0,
    }


def _summarize_stage_metrics(stage_details: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    汇总多个样本在同一检索阶段上的平均指标

    Args:
        stage_details (List[Dict[str, Any]]): 单阶段、跨样本的统计结果列表

    Returns:
        Dict[str, Any]: 平均 recall、MRR 和 hit rate
    """
    scored = [detail for detail in stage_details if detail.get("match_mode") != "unscored"]
    if not scored:
        return {"recall": None, "mrr": None, "hit_rate": None, "match_mode": "unscored"}

    return {
        "recall": round(mean(detail["recall"] for detail in scored), 4),
        "mrr": round(mean(detail["reciprocal_rank"] for detail in scored), 4),
        "hit_rate": round(mean(detail["hit"] for detail in scored), 4),
        "match_mode": "locator",
        "scored_sample_count": len(scored),
        "unscored_sample_count": len(stage_details) - len(scored),
    }


def _summarize_prefix_metrics(prefix_metric_buckets: Dict[int, List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """汇总 final evidence 前 N 条的命中情况，用于评估 Ragas contexts 输入质量。"""
    return {
        f"top{prefix_k}": _summarize_stage_metrics(stage_details)
        for prefix_k, stage_details in prefix_metric_buckets.items()
    }


def _collect_gold_rank_summary(
    stage_results: Dict[str, Dict[str, Any]],
    gold_evidence: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """记录通用 evidence 在各阶段的排名位置。"""
    gold_evidence = list(gold_evidence or [])
    summary: Dict[str, Any] = {}
    for stage_name, stage_result in stage_results.items():
        if not gold_evidence:
            summary[stage_name] = {
                "match_mode": "unscored",
                "matched_count": 0,
                "best_rank": None,
                "gold_ranks": [],
            }
            continue
        ranks = [
            index
            for index, candidate in enumerate(stage_result.get("retrieved_evidence", []), start=1)
            if any(locator_matches(candidate, expected) for expected in gold_evidence)
        ]
        summary[stage_name] = {
            "match_mode": "locator",
            "matched_count": len(stage_result.get("matched_evidence", [])),
            "best_rank": min(ranks) if ranks else None,
            "gold_ranks": ranks,
        }
    return summary


def _tokenize_for_claim_overlap(text: str) -> set[str]:
    """
    用轻量规则抽取 claim / evidence 的匹配 token。

    这是 Phase2 的可观测性辅助，不作为严格自动评分；严格 claim 支撑性会在后续
    Phase4 交给 LLM judge 或更稳定的语义评测。
    """
    text = text.lower()
    segments = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9_]+", text)
    tokens: set[str] = set()
    for segment in segments:
        if re.fullmatch(r"[\u4e00-\u9fff]+", segment):
            tokens.update(segment[index : index + 2] for index in range(max(len(segment) - 1, 0)))
            tokens.update(segment[index : index + 3] for index in range(max(len(segment) - 2, 0)))
        else:
            tokens.update(part for part in segment.split("_") if len(part) >= 2)
    return {token for token in tokens if len(token) >= 2}


def _collect_claim_diagnostics(
    expected_claims: List[str],
    trace: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    给 expected_claims 生成启发式检索诊断。

    这里不判断回答是否忠于证据，只观察 claim 的关键词/短语是否在各阶段候选文本中出现。
    它的作用是帮助定位“claim 可能在哪个阶段被召回或丢失”，不是最终自动评测分数。
    """
    diagnostics: List[Dict[str, Any]] = []
    if not expected_claims:
        return diagnostics

    stage_texts = {
        stage_name: "\n".join(candidate.get("page_content", "") for candidate in trace["stages"].get(stage_name, []))
        for stage_name in TRACE_STAGE_ORDER
    }
    stage_tokens = {
        stage_name: _tokenize_for_claim_overlap(text)
        for stage_name, text in stage_texts.items()
    }

    for claim in expected_claims:
        claim_tokens = _tokenize_for_claim_overlap(claim)
        stage_overlaps: Dict[str, float] = {}
        matched_stages: List[str] = []
        for stage_name in TRACE_STAGE_ORDER:
            overlap = len(claim_tokens & stage_tokens[stage_name]) / len(claim_tokens) if claim_tokens else 0.0
            stage_overlaps[stage_name] = round(overlap, 4)
            if overlap >= CLAIM_OVERLAP_THRESHOLD:
                matched_stages.append(stage_name)

        first_seen_stage = matched_stages[0] if matched_stages else None
        final_overlap = stage_overlaps.get("final", 0.0)
        diagnostics.append(
            {
                "claim": claim,
                "heuristic": "token_overlap",
                "threshold": CLAIM_OVERLAP_THRESHOLD,
                "first_seen_stage": first_seen_stage,
                "final_status": "possible_supported_by_final_evidence"
                if final_overlap >= CLAIM_OVERLAP_THRESHOLD
                else "not_observed_in_final_evidence",
                "possible_loss_stage": None
                if final_overlap >= CLAIM_OVERLAP_THRESHOLD or not matched_stages
                else matched_stages[-1],
                "stage_overlaps": stage_overlaps,
            }
        )
    return diagnostics


def _summarize_timings(timing_details: List[Dict[str, float]]) -> Dict[str, float]:
    """汇总 build_retrieval_trace 返回的阶段耗时。"""
    if not timing_details:
        return {}
    timing_keys = sorted({key for timings in timing_details for key in timings})
    return {
        key: round(mean(float(timings.get(key, 0.0)) for timings in timing_details), 3)
        for key in timing_keys
    }


def _validate_vector_store_matches_dataset(
    dataset: List[Dict[str, Any]],
    vector_summary_provider: Optional[VectorSummaryProvider] = None,
) -> Dict[str, Any]:
    """只记录 Runtime 提供的向量库身份，不根据题集猜测知识源是否匹配。"""
    return (vector_summary_provider or get_vector_db_metadata_summary)()


def _detect_loss_reasons(stage_results: Dict[str, Dict[str, Any]]) -> List[str]:
    """根据已评分的各阶段结果标记检索链路中的丢失位置。"""
    if any(result.get("match_mode") == "unscored" for result in stage_results.values()):
        return []
    reasons: List[str] = []
    if not stage_results["dense_raw"]["matched_evidence"]:
        reasons.append("dense_missing")
    if stage_results["dense_raw"]["matched_evidence"] and not stage_results["dense_thresholded"]["matched_evidence"]:
        reasons.append("dense_threshold_drop")
    if stage_results["dense_thresholded"]["matched_evidence"] and not stage_results["dense_mmr"]["matched_evidence"]:
        reasons.append("dense_mmr_drop")
    if not stage_results["dense_mmr"]["matched_evidence"] and stage_results["sparse"]["matched_evidence"]:
        reasons.append("sparse_recovered")
    if (
        stage_results["dense_mmr"]["matched_evidence"] or stage_results["sparse"]["matched_evidence"]
    ) and not stage_results["merged_before_rerank"]["matched_evidence"]:
        reasons.append("merge_drop")
    if stage_results["merged_before_rerank"]["matched_evidence"] and not stage_results["reranked"]["matched_evidence"]:
        reasons.append("rerank_drop")
    if stage_results["reranked"]["matched_evidence"] and not stage_results["final"]["matched_evidence"]:
        reasons.append("final_filter_or_topk_drop")
    if not reasons and stage_results["final"]["matched_evidence"]:
        reasons.append("final_hit")
    return reasons


def evaluate_retrieval(
    dataset: List[Dict[str, Any]],
    top_k: Optional[int] = None,
    retrieval_config: Optional[RagRetrievalConfig] = None,
    event_callback: Optional[EvalEventCallback] = None,
    cancel_checker: Optional[EvalCancelChecker] = None,
    step_name: str = "retrieval_eval",
    retrieval_trace_builder: Optional[RetrievalTraceBuilder] = None,
    vector_summary_provider: Optional[VectorSummaryProvider] = None,
) -> Dict[str, Any]:
    """
    评估 RAG 检索链路在给定数据集上的表现

    该函数不评估最终生成答案质量，只关注检索阶段本身：
    gold 是否被召回、在哪个阶段被召回、以及最终 top-k 的命中表现。

    这里是 retrieval benchmark 真正走完整 RAG 检索链路的地方。
    每道题都会调用 build_retrieval_trace(question, config=config)，
    因此会读取当前本地知识库并执行 query_rag.py 中定义的检索流程。
    注意：这里不会调用 LLM 生成最终回答，只评估检索 trace。

    Args:
        dataset (List[Dict[str, Any]]): 评测样本列表
        top_k (Optional[int]): 可选的最终 top-k 覆盖值；为 None 时使用默认配置
        retrieval_config (Optional[RagRetrievalConfig]): 自定义检索配置

    Returns:
        Dict[str, Any]: 包含总体指标、分阶段指标、丢失原因统计和逐题详情的结果字典
    """
    config = retrieval_config or RagRetrievalConfig()
    if top_k is not None:
        config = RagRetrievalConfig(
            dense_fetch_k=config.dense_fetch_k,
            dense_mmr_k=config.dense_mmr_k,
            sparse_fetch_k=config.sparse_fetch_k,
            final_top_k=top_k,
            dense_score_threshold=config.dense_score_threshold,
            final_rerank_threshold=config.final_rerank_threshold,
            mmr_lambda=config.mmr_lambda,
            max_evidence_chars=config.max_evidence_chars,
        )
    if not dataset:
        return {
            "sample_count": 0,
            "recall_at_k": None,
            "mrr": None,
            "hit_rate": None,
            "avg_timings_ms": {},
            "stage_metrics": {},
            "loss_reason_counts": {},
            "config": config.to_dict(),
        }

    vector_db_summary = _validate_vector_store_matches_dataset(
        dataset,
        vector_summary_provider=vector_summary_provider,
    )
    details: List[Dict[str, Any]] = []
    stage_metric_buckets: Dict[str, List[Dict[str, Any]]] = {
        "dense_raw": [],
        "dense_thresholded": [],
        "dense_mmr": [],
        "sparse": [],
        "merged_before_rerank": [],
        "reranked": [],
        "final": [],
    }
    loss_reason_counts: Dict[str, int] = {}
    timing_details: List[Dict[str, float]] = []
    final_prefix_metric_buckets: Dict[int, List[Dict[str, Any]]] = {4: [], 5: []}

    total_count = len(dataset)
    cancelled = False

    # 逐题执行检索追踪，并记录每个阶段相对 gold 的命中情况
    for sample_index, sample in enumerate(dataset, start=1):
        if _cancel_requested(cancel_checker):
            cancelled = True
            _emit_sample_progress(event_callback, step_name, "cancelled", sample_index - 1, total_count, sample)
            break
        question = sample["question"]
        gold_evidence = sample.get("gold_evidence", [])
        trace = (retrieval_trace_builder or build_retrieval_trace)(question, config=config)
        timing_details.append(trace.get("timings_ms", {}))
        stage_results = {
            stage_name: _collect_stage_metrics(stage_candidates, gold_evidence)
            for stage_name, stage_candidates in trace["stages"].items()
        }
        for prefix_k in final_prefix_metric_buckets:
            final_prefix_metric_buckets[prefix_k].append(
                _collect_stage_metrics(trace["stages"]["final"][:prefix_k], gold_evidence)
            )
        for stage_name, stage_result in stage_results.items():
            stage_metric_buckets[stage_name].append(stage_result)

        final_result = stage_results["final"]
        loss_reasons = _detect_loss_reasons(stage_results)
        gold_rank_summary = _collect_gold_rank_summary(stage_results, gold_evidence)
        claim_diagnostics = _collect_claim_diagnostics(sample.get("expected_claims", []), trace)
        for reason in loss_reasons:
            loss_reason_counts[reason] = loss_reason_counts.get(reason, 0) + 1

        details.append(
            {
                "sample_id": sample.get("sample_id", ""),
                "question": question,
                "source": sample.get("source", {}),
                "expected_claims": sample.get("expected_claims", []),
                "reference_answer": sample.get("reference_answer", ""),
                "judge_rubric": sample.get("judge_rubric", {}),
                "gold_evidence": gold_evidence,
                "retrieval_match_mode": final_result.get("match_mode", ""),
                "retrieved_evidence": final_result["retrieved_evidence"],
                "matched_evidence": final_result["matched_evidence"],
                "recall": final_result["recall"],
                "reciprocal_rank": final_result["reciprocal_rank"],
                "stage_results": stage_results,
                "gold_rank_summary": gold_rank_summary,
                "trace_timings_ms": trace.get("timings_ms", {}),
                "final_evidence_payload": trace.get("evidence_payload", []),
                "retrieved_locators": [candidate_evidence(evidence.get("metadata", evidence)) for evidence in trace.get("stages", {}).get("final", [])],
                "claim_diagnostics": claim_diagnostics,
                "loss_reasons": loss_reasons,
            }
        )
        _emit_sample_progress(event_callback, step_name, "retrieval", sample_index, total_count, sample)
        if _cancel_requested(cancel_checker):
            cancelled = True
            _emit_sample_progress(event_callback, step_name, "cancelled", sample_index, total_count, sample)
            break

    sample_count = len(details)
    final_metrics = _summarize_stage_metrics(stage_metric_buckets["final"])
    result = {
        "status": "cancelled" if cancelled else "pass",
        "sample_count": sample_count,
        "source_sample_count": total_count,
        "config": config.to_dict(),
        "recall_at_k": final_metrics["recall"],
        "mrr": final_metrics["mrr"],
        "hit_rate": final_metrics["hit_rate"],
        "avg_timings_ms": _summarize_timings(timing_details),
        "vector_db_summary": vector_db_summary,
        "stage_metrics": {
            stage_name: _summarize_stage_metrics(stage_details)
            for stage_name, stage_details in stage_metric_buckets.items()
        },
        "final_prefix_metrics": _summarize_prefix_metrics(final_prefix_metric_buckets),
        "loss_reason_counts": loss_reason_counts,
        "details": details,
    }
    if cancelled:
        result["cancelled_after_samples"] = sample_count
    return result


def run_eval(dataset_path: str) -> Dict[str, Any]:
    """
    使用默认配置运行完整检索评测

    Args:
        dataset_path (str): 评测数据集文件路径

    Returns:
        Dict[str, Any]: 检索评测结果
    """
    dataset = load_eval_dataset(dataset_path)
    result = evaluate_retrieval(dataset)
    return result


def run_eval_with_options(
    dataset_path: str,
    limit: Optional[int] = None,
    top_k: Optional[int] = None,
    event_callback: Optional[EvalEventCallback] = None,
    cancel_checker: Optional[EvalCancelChecker] = None,
    step_name: str = "retrieval_eval",
) -> Dict[str, Any]:
    """
    使用命令行选项风格运行检索评测

    该函数本身只负责读取数据集、截断 limit、传递 top_k。
    真正调用知识库并走完整 RAG 检索链路的是 evaluate_retrieval()。

    Args:
        dataset_path (str): 评测数据集文件路径
        limit (Optional[int]): 只评测前 N 条样本；为 None 时处理全部样本
        top_k (Optional[int]): 覆盖默认 final_top_k 的评测值

    Returns:
        Dict[str, Any]: 检索评测结果
    """
    dataset = load_eval_dataset(dataset_path)
    if limit is not None:
        dataset = dataset[:limit]
    return evaluate_retrieval(
        dataset,
        top_k=top_k,
        event_callback=event_callback,
        cancel_checker=cancel_checker,
        step_name=step_name,
    )


def sweep_retrieval_configs(
    dataset: List[Dict[str, Any]],
    config_specs: List[Dict[str, Any]],
    retrieval_trace_builder: Optional[RetrievalTraceBuilder] = None,
    vector_summary_provider: Optional[VectorSummaryProvider] = None,
) -> Dict[str, Any]:
    """
    对多组检索参数配置执行批量评测。

    config_specs 支持两种格式：
    1. 直接传 RagRetrievalConfig 字段字典；
    2. 传 {"name": "实验名", "config": {...}}，便于长期记录实验标签。
    """
    runs: List[Dict[str, Any]] = []
    for index, config_spec in enumerate(config_specs, start=1):
        run_name = config_spec.get("name", f"run_{index}")
        raw_config = config_spec.get("config", config_spec)
        config = build_retrieval_config(raw_config)
        result = evaluate_retrieval(
            dataset,
            retrieval_config=config,
            retrieval_trace_builder=retrieval_trace_builder,
            vector_summary_provider=vector_summary_provider,
        )
        runs.append(
            {
                "run_id": index,
                "name": run_name,
                "config": config.to_dict(),
                "metrics": {
                    "recall_at_k": result["recall_at_k"],
                    "mrr": result["mrr"],
                    "hit_rate": result["hit_rate"],
                    "avg_timings_ms": result.get("avg_timings_ms", {}),
                    "stage_metrics": result["stage_metrics"],
                    "final_prefix_metrics": result.get("final_prefix_metrics", {}),
                    "loss_reason_counts": result["loss_reason_counts"],
                },
            }
        )

    runs.sort(
        key=lambda item: (
            item["metrics"]["recall_at_k"] if item["metrics"]["recall_at_k"] is not None else -1.0,
            item["metrics"]["mrr"] if item["metrics"]["mrr"] is not None else -1.0,
        ),
        reverse=True,
    )
    return {
        "sample_count": len(dataset),
        "run_count": len(runs),
        "runs": runs,
    }

def _ensure_parent_dir(path: Path) -> None:
    """确保输出文件所在目录存在。"""
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_json_file(path: Path, data: Dict[str, Any]) -> None:
    """写入 JSON 结果文件。"""
    _ensure_parent_dir(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _require_dataset_path(dataset_path: str) -> str:
    """确保评测入口使用显式题集路径。"""
    if not str(dataset_path or "").strip():
        raise ValueError("RAG_EVAL_DATASET_PATH is not configured.")
    return dataset_path


def run_eval_from_code_config(
    event_callback: Optional[EvalEventCallback] = None,
    cancel_checker: Optional[EvalCancelChecker] = None,
) -> Dict[str, Any]:
    """
    使用文件顶部的 EVAL_RUN_CONFIG 运行单组检索评测。

    single 模式的执行路径：
    EVAL_RUN_CONFIG -> run_eval_with_options() -> evaluate_retrieval() -> build_retrieval_trace()
    其中 build_retrieval_trace() 是实际访问知识库的地方。

    Returns:
        Dict[str, Any]: 检索评测结果。
    """
    retrieval_profile = EVAL_RUN_CONFIG.get("retrieval_profile", "active_current")
    dataset_path = _require_dataset_path(EVAL_RUN_CONFIG.get("dataset_path", ""))
    eval_identity = evaluation_identity(dataset_path)
    top_k = EVAL_RUN_CONFIG.get("top_k")
    if top_k is None and retrieval_profile:
        dataset = load_eval_dataset(dataset_path)
        limit = EVAL_RUN_CONFIG.get("limit")
        if limit is not None:
            dataset = dataset[:limit]
        result = evaluate_retrieval(
            dataset,
            retrieval_config=build_retrieval_config(RETRIEVAL_PROFILES[retrieval_profile]),
            event_callback=event_callback,
            cancel_checker=cancel_checker,
        )
    else:
        result = run_eval_with_options(
            dataset_path=dataset_path,
            limit=EVAL_RUN_CONFIG["limit"],
            top_k=top_k,
            event_callback=event_callback,
            cancel_checker=cancel_checker,
        )
    result["evaluation_identity"] = eval_identity
    if EVAL_RUN_CONFIG.get("save_output"):
        _write_json_file(Path(EVAL_RUN_CONFIG["output_path"]), result)
    if EVAL_RUN_CONFIG.get("save_markdown"):
        write_markdown_file(
            Path(EVAL_RUN_CONFIG["report_path"]),
            build_rag_retrieval_single_markdown_report(result),
        )
    return result


def run_sweep_from_code_config() -> Dict[str, Any]:
    """
    使用文件顶部的 SWEEP_CONFIGS 执行多组检索参数对比。

    sweep 模式会对每组 SWEEP_CONFIGS 都调用一次 evaluate_retrieval()。
    因此每组参数都会独立走完整 RAG 检索链路，并分别访问知识库生成 trace。

    Returns:
        Dict[str, Any]: 多组配置的指标对比结果。
    """
    dataset_path = _require_dataset_path(EVAL_RUN_CONFIG.get("dataset_path", ""))
    eval_identity = evaluation_identity(dataset_path)
    dataset = load_eval_dataset(dataset_path)
    limit = EVAL_RUN_CONFIG.get("limit")
    if limit is not None:
        dataset = dataset[:limit]

    result = sweep_retrieval_configs(dataset, SWEEP_CONFIGS)
    result["dataset_path"] = str(Path(dataset_path).resolve())
    result["limit"] = limit
    result["evaluation_identity"] = eval_identity

    if EVAL_RUN_CONFIG.get("save_output"):
        _write_json_file(Path(EVAL_RUN_CONFIG["sweep_output_path"]), result)
    if EVAL_RUN_CONFIG.get("save_markdown"):
        write_markdown_file(
            Path(EVAL_RUN_CONFIG["sweep_report_path"]),
            build_rag_retrieval_sweep_markdown_report(result),
        )
    return result


def run_from_code_config(
    event_callback: Optional[EvalEventCallback] = None,
    cancel_checker: Optional[EvalCancelChecker] = None,
) -> Dict[str, Any]:
    """根据 EVAL_RUN_CONFIG["mode"] 选择 single 或 sweep。"""
    mode = EVAL_RUN_CONFIG.get("mode", "single")
    if mode == "single":
        return run_eval_from_code_config(event_callback=event_callback, cancel_checker=cancel_checker)
    if mode == "sweep":
        return run_sweep_from_code_config()
    raise ValueError(f"Unsupported EVAL_RUN_CONFIG mode: {mode}")

