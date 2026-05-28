import json
import re
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[4]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))  # 将项目根目录添加到 sys.path，以便正确导入模块

from Agent.knowledge_base.rag.query_rag import (
    RagRetrievalConfig,
    # build_retrieval_trace 是本评测真正调用知识库检索的入口。
    # 它会走当前 RAG retrieval 链路：dense -> threshold -> MMR -> sparse -> merge/rerank -> final。
    # rag_eval.py 只消费它返回的 trace，不直接操作 FAISS / embedding / sparse index。
    build_retrieval_trace,
)
from Agent.knowledge_base.rag.tools.report_utils import (
    build_rag_retrieval_single_markdown_report,
    build_rag_retrieval_sweep_markdown_report,
    write_markdown_file,
)

RAG_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = RAG_DIR / "data"
DEFAULT_DATASET_PATH = DATA_DIR / "rag_eval_smoke.json"
OUTPUT_DIR = RAG_DIR / "output"
MACHINE_OUTPUT_DIR = OUTPUT_DIR / "machine"
REPORT_OUTPUT_DIR = OUTPUT_DIR / "reports"
DEFAULT_OUTPUT_PATH = MACHINE_OUTPUT_DIR / "rag_eval_result.json"
DEFAULT_SWEEP_OUTPUT_PATH = MACHINE_OUTPUT_DIR / "rag_eval_sweep_result.json"
DEFAULT_REPORT_PATH = REPORT_OUTPUT_DIR / "rag_eval_report.md"
DEFAULT_SWEEP_REPORT_PATH = REPORT_OUTPUT_DIR / "rag_eval_sweep_report.md"

TRACE_STAGE_ORDER = [
    "dense_raw",
    "dense_thresholded",
    "dense_mmr",
    "sparse",
    "merged_before_rerank",
    "reranked",
    "final",
]

CLAIM_OVERLAP_THRESHOLD = 0.35

# 本地手动运行时，优先改这里。
# mode="single" 跑一组配置；mode="sweep" 跑下面的 SWEEP_CONFIGS 参数对比。
# single 模式默认使用 query_rag.py 里的 RagRetrievalConfig() 默认值。
# 只有 top_k 不为 None 时，才会临时覆盖 final_top_k。
# 默认数据集使用 data/rag_eval_smoke.json，只包含有 gold_chunk_ids 的核心样本。
# 原始 rag_eval_sample.json 暂时保留为兼容入口，不作为默认 retrieval gold benchmark。
EVAL_RUN_CONFIG = {
    "mode": "sweep", 
    "dataset_path": str(DEFAULT_DATASET_PATH),
    "output_path": str(DEFAULT_OUTPUT_PATH),
    "sweep_output_path": str(DEFAULT_SWEEP_OUTPUT_PATH),
    "report_path": str(DEFAULT_REPORT_PATH),
    "sweep_report_path": str(DEFAULT_SWEEP_REPORT_PATH),
    "limit": None,
    "top_k": None,  # None 表示不覆盖默认 final_top_k；single 会使用当前 RAG 链路默认配置。
    "save_output": True,
    "save_markdown": True,
}

# 内部调参用的候选配置。name 只是实验标签，config 会传给 RagRetrievalConfig。
# baseline_current 是把 single 模式实际使用的默认检索参数显式写出来，
# 方便在 sweep 报告中和其他参数组横向对比。
SWEEP_CONFIGS = [
    {
        "name": "baseline_current",
        "config": {
            "dense_fetch_k": 10,
            "dense_mmr_k": 6,
            "sparse_fetch_k": 8,
            "final_top_k": 4,
            "dense_score_threshold": 0.45,
            "final_rerank_threshold": 0.18,
            "mmr_lambda": 0.7,
            "official_only_when_available": True,
        },
    },
    {
        "name": "wider_top20_no_threshold",
        "config": {
            "dense_fetch_k": 80,
            "dense_mmr_k": 40,
            "sparse_fetch_k": 80,
            "final_top_k": 20,
            "dense_score_threshold": 0.0,
            "final_rerank_threshold": 0.0,
            "mmr_lambda": 0.7,
            "official_only_when_available": True,
        },
    },
    {
        "name": "more_diverse_mmr",
        "config": {
            "dense_fetch_k": 80,
            "dense_mmr_k": 40,
            "sparse_fetch_k": 80,
            "final_top_k": 20,
            "dense_score_threshold": 0.0,
            "final_rerank_threshold": 0.0,
            "mmr_lambda": 0.4,
            "official_only_when_available": True,
        },
    },
]


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
    path = Path(dataset_path)
    with path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError("评测数据必须是 JSON 数组。")
    return data


def _collect_stage_metrics(
    stage_candidates: List[Dict[str, Any]],
    gold_chunk_ids: set[str],
) -> Dict[str, Any]:
    """
    统计单个检索阶段相对 gold 的命中情况

    Args:
        stage_candidates (List[Dict[str, Any]]): 某一阶段返回的候选列表
        gold_chunk_ids (set[str]): 当前问题对应的 gold chunk id 集合

    Returns:
        Dict[str, Any]: 包含召回、MRR、命中与命中 chunk 列表的统计结果
    """
       # 提取检索到的所有chunk IDs
    retrieved_chunk_ids = [candidate["metadata"]["chunk_id"] for candidate in stage_candidates]
    # 找出检索结果中匹配gold标准的chunk IDs
    matched = [chunk_id for chunk_id in retrieved_chunk_ids if chunk_id in gold_chunk_ids]
    
    # 计算Reciprocal Rank (倒数排名): 第一个相关文档的位置的倒数
    reciprocal_rank = 0.0
    for index, chunk_id in enumerate(retrieved_chunk_ids, start=1):
        if chunk_id in gold_chunk_ids:
            reciprocal_rank = 1.0 / index
            break
 
    # 计算召回率: 检索到的相关文档数量 / 所有相关文档数量
    recall = len(matched) / len(gold_chunk_ids) if gold_chunk_ids else 0.0
    return {
        "retrieved_chunk_ids": retrieved_chunk_ids,
        "matched_chunk_ids": matched,
        "recall": recall,
        "reciprocal_rank": reciprocal_rank,
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
    if not stage_details:
        return {"recall": 0.0, "mrr": 0.0, "hit_rate": 0.0}

    return {
        "recall": round(mean(detail["recall"] for detail in stage_details), 4),
        "mrr": round(mean(detail["reciprocal_rank"] for detail in stage_details), 4), #MRR - Mean Reciprocal Rank
        "hit_rate": round(mean(detail["hit"] for detail in stage_details), 4),
    }


def _collect_gold_rank_summary(stage_results: Dict[str, Dict[str, Any]], gold_chunk_ids: set[str]) -> Dict[str, Any]:
    """记录 gold chunk 在各阶段中的排名位置，便于观察 rerank / final 截断影响。"""
    summary: Dict[str, Any] = {}
    for stage_name, stage_result in stage_results.items():
        ranks = {
            chunk_id: index
            for index, chunk_id in enumerate(stage_result["retrieved_chunk_ids"], start=1)
            if chunk_id in gold_chunk_ids
        }
        summary[stage_name] = {
            "matched_count": len(ranks),
            "best_rank": min(ranks.values()) if ranks else None,
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


def _detect_loss_reasons(stage_results: Dict[str, Dict[str, Any]]) -> List[str]:
    """
    根据各阶段命中情况，粗略标记当前问题可能的丢失原因

    这些标签主要用于内部调参时快速定位问题落在哪一段链路，
    例如 dense 没召回、MMR 去重误伤，或 merge/rerank 阶段掉点。
    """
    reasons: List[str] = []
    # 检查密集检索原始阶段是否未找到匹配项
    if not stage_results["dense_raw"]["matched_chunk_ids"]:
        reasons.append("dense_missing")
    # 检查密集检索是否因阈值过滤而丢弃了匹配项
    if stage_results["dense_raw"]["matched_chunk_ids"] and not stage_results["dense_thresholded"]["matched_chunk_ids"]:
        reasons.append("dense_threshold_drop")
    # 检查密集检索经MMR去重后是否丢弃了匹配项
    if stage_results["dense_thresholded"]["matched_chunk_ids"] and not stage_results["dense_mmr"]["matched_chunk_ids"]:
        reasons.append("dense_mmr_drop")
    # 检查稀疏检索是否找到了密集检索遗漏的匹配项（稀疏检索恢复）
    if not stage_results["dense_mmr"]["matched_chunk_ids"] and stage_results["sparse"]["matched_chunk_ids"]:
        reasons.append("sparse_recovered")
    # 检查 dense/sparse 合并及官方语料过滤后是否丢失匹配项
    if (
        stage_results["dense_mmr"]["matched_chunk_ids"] or stage_results["sparse"]["matched_chunk_ids"]
    ) and not stage_results["merged_before_rerank"]["matched_chunk_ids"]:
        reasons.append("merge_drop")
    # 检查 rerank 阶段是否让匹配项消失。正常情况下 rerank 只排序不删除；如果出现该标签，说明 trace 逻辑异常。
    if stage_results["merged_before_rerank"]["matched_chunk_ids"] and not stage_results["reranked"]["matched_chunk_ids"]:
        reasons.append("rerank_drop")
    # 检查 final threshold 或 final_top_k 是否导致匹配项丢失。
    if stage_results["reranked"]["matched_chunk_ids"] and not stage_results["final"]["matched_chunk_ids"]:
        reasons.append("final_filter_or_topk_drop")
    # 如果没有发现丢失原因但最终有匹配项，则标记为最终命中
    if not reasons and stage_results["final"]["matched_chunk_ids"]:
        reasons.append("final_hit")
    return reasons


def evaluate_retrieval(
    dataset: List[Dict[str, Any]],
    top_k: Optional[int] = None,
    retrieval_config: Optional[RagRetrievalConfig] = None,
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
            official_only_when_available=config.official_only_when_available,
        )
    if not dataset:
        return {
            "sample_count": 0,
        "recall_at_k": 0.0,
        "mrr": 0.0,
        "hit_rate": 0.0,
        "avg_timings_ms": {},
        "stage_metrics": {},
        "loss_reason_counts": {},
        "config": config.to_dict(),
        }

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

    # 逐题执行检索追踪，并记录每个阶段相对 gold 的命中情况
    for sample in dataset:
        question = sample["question"]
        gold_chunk_ids = set(sample.get("gold_chunk_ids", []))
        # 调用知识库检索入口：这里会真正访问本地向量库 / 稀疏检索资源，
        # 并返回各阶段候选结果。后续指标只基于这个 trace 和 gold_chunk_ids 计算。
        trace = build_retrieval_trace(question, config=config)
        timing_details.append(trace.get("timings_ms", {}))
        stage_results = {
            stage_name: _collect_stage_metrics(stage_candidates, gold_chunk_ids)
            for stage_name, stage_candidates in trace["stages"].items()
        }
        for stage_name, stage_result in stage_results.items():
            stage_metric_buckets[stage_name].append(stage_result)

        final_result = stage_results["final"]
        loss_reasons = _detect_loss_reasons(stage_results)
        gold_rank_summary = _collect_gold_rank_summary(stage_results, gold_chunk_ids)
        claim_diagnostics = _collect_claim_diagnostics(sample.get("expected_claims", []), trace)
        for reason in loss_reasons:
            loss_reason_counts[reason] = loss_reason_counts.get(reason, 0) + 1

        details.append(
            {
                "question": question,
                "question_type": sample.get("question_type", ""),
                "expected_corpus": sample.get("expected_corpus", ""),
                "expected_sources": sample.get("expected_sources", sample.get("gold_doc_ids", [])),
                "expected_claims": sample.get("expected_claims", []),
                "reference_answer": sample.get("reference_answer", ""),
                "judge_rubric": sample.get("judge_rubric", {}),
                "gold_chunk_ids": list(gold_chunk_ids),
                "gold_doc_ids": sample.get("gold_doc_ids", []),
                "retrieved_chunk_ids": final_result["retrieved_chunk_ids"],
                "matched_chunk_ids": final_result["matched_chunk_ids"],
                "recall": final_result["recall"],
                "reciprocal_rank": final_result["reciprocal_rank"],
                "stage_results": stage_results,
                "gold_rank_summary": gold_rank_summary,
                "trace_timings_ms": trace.get("timings_ms", {}),
                "final_evidence_payload": trace.get("evidence_payload", []),
                "claim_diagnostics": claim_diagnostics,
                "loss_reasons": loss_reasons,
            }
        )

    sample_count = len(dataset)
    final_metrics = _summarize_stage_metrics(stage_metric_buckets["final"])
    return {
        "sample_count": sample_count,
        "config": config.to_dict(),
        "recall_at_k": final_metrics["recall"],
        "mrr": final_metrics["mrr"],
        "hit_rate": final_metrics["hit_rate"],
        "avg_timings_ms": _summarize_timings(timing_details),
        "stage_metrics": {
            stage_name: _summarize_stage_metrics(stage_details)
            for stage_name, stage_details in stage_metric_buckets.items()
        },
        "loss_reason_counts": loss_reason_counts,
        "details": details,
    }


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
    return evaluate_retrieval(dataset, top_k=top_k)


def sweep_retrieval_configs(
    dataset: List[Dict[str, Any]],
    config_specs: List[Dict[str, Any]],
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
        config = RagRetrievalConfig(**raw_config)
        result = evaluate_retrieval(dataset, retrieval_config=config)
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
                    "loss_reason_counts": result["loss_reason_counts"],
                },
            }
        )

    runs.sort(key=lambda item: (item["metrics"]["recall_at_k"], item["metrics"]["mrr"]), reverse=True)
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


def run_eval_from_code_config() -> Dict[str, Any]:
    """
    使用文件顶部的 EVAL_RUN_CONFIG 运行单组检索评测。

    single 模式的执行路径：
    EVAL_RUN_CONFIG -> run_eval_with_options() -> evaluate_retrieval() -> build_retrieval_trace()
    其中 build_retrieval_trace() 是实际访问知识库的地方。

    Returns:
        Dict[str, Any]: 检索评测结果。
    """
    result = run_eval_with_options(
        dataset_path=EVAL_RUN_CONFIG["dataset_path"],
        limit=EVAL_RUN_CONFIG["limit"],
        top_k=EVAL_RUN_CONFIG["top_k"],
    )
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
    dataset = load_eval_dataset(EVAL_RUN_CONFIG["dataset_path"])
    limit = EVAL_RUN_CONFIG.get("limit")
    if limit is not None:
        dataset = dataset[:limit]

    result = sweep_retrieval_configs(dataset, SWEEP_CONFIGS)
    result["dataset_path"] = str(Path(EVAL_RUN_CONFIG["dataset_path"]).resolve())
    result["limit"] = limit

    if EVAL_RUN_CONFIG.get("save_output"):
        _write_json_file(Path(EVAL_RUN_CONFIG["sweep_output_path"]), result)
    if EVAL_RUN_CONFIG.get("save_markdown"):
        write_markdown_file(
            Path(EVAL_RUN_CONFIG["sweep_report_path"]),
            build_rag_retrieval_sweep_markdown_report(result),
        )
    return result


def run_from_code_config() -> Dict[str, Any]:
    """根据 EVAL_RUN_CONFIG["mode"] 选择 single 或 sweep。"""
    mode = EVAL_RUN_CONFIG.get("mode", "single")
    if mode == "single":
        return run_eval_from_code_config()
    if mode == "sweep":
        return run_sweep_from_code_config()
    raise ValueError(f"Unsupported EVAL_RUN_CONFIG mode: {mode}")


if __name__ == "__main__":
    result = run_from_code_config()
    print(json.dumps(result, ensure_ascii=False, indent=2))

