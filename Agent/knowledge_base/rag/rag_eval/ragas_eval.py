import json
import math
import hashlib
import sys
import time
from pathlib import Path
from statistics import mean, stdev
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

from langchain_openai import ChatOpenAI

from config.settings import settings
from Agent.knowledge_base.query_rag import (
    RagRetrievalConfig,
    _answer_question,
    _get_embedding_function,
    _normalize_question_payload,
    build_retrieval_trace,
)
from Agent.knowledge_base.rag.rag_config import (
    DATA_DIR,
    EVAL_DATASET_PATH,
    MACHINE_OUTPUT_DIR,
    RAGAS_RUN_CONFIG,
    REPORT_OUTPUT_DIR,
    RETRIEVAL_PROFILES,
)
from Agent.knowledge_base.rag.rag_eval.rag_eval import load_eval_dataset
from Agent.knowledge_base.rag.tools.report_utils import build_ragas_markdown_report, write_markdown_file

DEFAULT_DATASET_PATH = EVAL_DATASET_PATH
DEFAULT_RAGAS_DATASET_PATH = MACHINE_OUTPUT_DIR / "ragas_eval_dataset.json"
DEFAULT_OUTPUT_PATH = MACHINE_OUTPUT_DIR / "ragas_eval_result.json"
DEFAULT_REPORT_PATH = REPORT_OUTPUT_DIR / "ragas_eval_report.md"
DEFAULT_SCORE_CACHE_PATH = MACHINE_OUTPUT_DIR / "ragas_eval_score_cache.json"
DEFAULT_RETRIEVAL_EVAL_PATH = MACHINE_OUTPUT_DIR / "rag_eval_result.json"
DEFAULT_LOW_SCORE_CASES_PATH = MACHINE_OUTPUT_DIR / "ragas_low_score_cases.json"
DEFAULT_CROSS_METRIC_CASES_PATH = MACHINE_OUTPUT_DIR / "ragas_cross_metric_bad_cases.json"
ANSWER_BUILD_VERSION = "answer_fallback_v2"

# 本地手动运行时优先改这里。
# Phase3 默认读取 ragas_testset_generate.py 生成的统一测试集。
# Ragas 的部分指标会触发多轮 judge 调用；确认链路稳定后，再把 limit 和指标逐步放大。
# 为了控制耗时，默认会复用已落盘的 ragas_eval_dataset.json；如果修改了检索参数、
# context 截断策略或样本数量，脚本会自动重建。
# selected_metrics 中：
# - faithfulness：回答是否忠于检索证据。
# - answer_relevancy：回答是否切题。
# - context_utilization：回答是否有效利用检索上下文。
# - context_recall：final contexts 是否覆盖 reference_answer 中的要点，需要 reference 字段。
#
# RAGAS_ACTIVE_PROFILE 在 rag_config.py 中控制本次运行模式，不需要命令行传参。
# 当前 profile：
# - quick_cached：1 条样本，优先验证流程，允许复用 Ragas 分数缓存。
# - reviewed_5_core_metrics：5 条样本，跑当前接入的 Ragas 核心指标。
# - reviewed_all_core_metrics：统一 generated 测试集全量核心指标。
# - reviewed_all_prepare_only：只构造 Ragas dataset，不调用 Ragas judge。
# - strict_generated_repeat3：统一 generated 测试集，四指标重复 3 次。
def _ensure_parent_dir(path: Path) -> None:
    """确保输出文件所在目录存在。"""
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_json_file(path: Path, data: Dict[str, Any]) -> None:
    """写入 JSON 文件。"""
    _ensure_parent_dir(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _truncate_for_eval(text: str, max_chars: Optional[int]) -> str:
    """限制进入 Ragas judge 的文本长度，降低评测耗时和 token 成本。"""
    if max_chars is None or max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _build_retrieval_config(raw_config: Optional[Dict[str, Any]] = None) -> RagRetrievalConfig:
    """构造 Ragas baseline 使用的检索配置。"""
    if not raw_config:
        profile_name = RAGAS_RUN_CONFIG.get("retrieval_profile", "baseline_current")
        return RagRetrievalConfig(**RETRIEVAL_PROFILES[profile_name])
    return RagRetrievalConfig(**raw_config)


def _build_ragas_eval_row(
    sample: Dict[str, Any],
    retrieval_config: RagRetrievalConfig,
    max_contexts: Optional[int] = None,
    max_context_chars: Optional[int] = None,
    max_response_chars: Optional[int] = None,
) -> Dict[str, Any]:
    """
    将单条项目评测样本转换成 Ragas 单轮评测样本。

    这里会真正调用本地知识库检索，并用当前 RAG 生成链路生成 answer。
    """
    question = sample.get("question", "").strip()
    trace = build_retrieval_trace(question, config=retrieval_config)
    evidence_payloads = trace.get("evidence_payload", [])
    ragas_evidence_payloads = evidence_payloads[:max_contexts] if max_contexts else evidence_payloads
    answer_result = _answer_question(_normalize_question_payload(sample), evidence_payloads)

    retrieved_contexts = [
        _truncate_for_eval(evidence.get("content", ""), max_context_chars)
        for evidence in ragas_evidence_payloads
    ]
    retrieved_context_ids = [evidence.get("chunk_id", "") for evidence in ragas_evidence_payloads]
    reference = sample.get("reference_answer", "")
    response = _truncate_for_eval(answer_result.get("answer", ""), max_response_chars)

    ragas_row: Dict[str, Any] = {
        "user_input": question,
        "response": response,
        "retrieved_contexts": retrieved_contexts,
        "retrieved_context_ids": retrieved_context_ids,
    }
    if reference:
        ragas_row["reference"] = reference

    metadata = {
        "sample_id": sample.get("sample_id", ""),
        "question": question,
        "source": sample.get("source", {}),
        "gold_doc_ids": sample.get("gold_doc_ids", []),
        "question_type": sample.get("question_type", ""),
        "expected_corpus": sample.get("expected_corpus", ""),
        "expected_sources": sample.get("expected_sources", sample.get("gold_doc_ids", [])),
        "expected_claims": sample.get("expected_claims", []),
        "reference_answer": reference,
        "judge_rubric": sample.get("judge_rubric", {}),
        "answer_status": answer_result.get("status", ""),
        "answer_confidence": answer_result.get("confidence", ""),
        "citations": answer_result.get("citations", []),
        "context_count": len(retrieved_contexts),
        "full_context_count": len(evidence_payloads),
        "ragas_context_count": len(ragas_evidence_payloads),
        "ragas_max_context_chars": max_context_chars,
        "ragas_max_response_chars": max_response_chars,
        "trace_timings_ms": trace.get("timings_ms", {}),
        "final_evidence_payload": evidence_payloads,
    }

    return {
        "ragas_row": ragas_row,
        "metadata": metadata,
    }


def filter_eval_samples(
    dataset: List[Dict[str, Any]],
    sample_filter: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """按评测配置筛选样本；v2 benchmark 不要求旧 review/question_type 字段。"""
    if not sample_filter:
        return dataset

    sample_ids = set(sample_filter.get("sample_ids") or [])
    source_datasets = set(sample_filter.get("source_datasets") or [])
    row_range = sample_filter.get("source_row_range") or []
    review_statuses = set(sample_filter.get("review_statuses") or [])
    question_types = set(sample_filter.get("question_types") or [])
    is_smoke_case = sample_filter.get("is_smoke_case")

    filtered = []
    for sample in dataset:
        source = sample.get("source") or {}
        row_index = source.get("row_index")
        if sample_ids and sample.get("sample_id") not in sample_ids:
            continue
        if source_datasets and source.get("dataset") not in source_datasets:
            continue
        if len(row_range) == 2 and isinstance(row_index, int):
            if row_index < int(row_range[0]) or row_index > int(row_range[1]):
                continue
        if review_statuses and sample.get("review_status") not in review_statuses:
            continue
        if question_types and sample.get("question_type") not in question_types:
            continue
        if is_smoke_case is not None and bool(sample.get("is_smoke_case")) != bool(is_smoke_case):
            continue
        filtered.append(sample)
    return filtered


def build_ragas_dataset(
    dataset_path: str,
    limit: Optional[int] = None,
    retrieval_config: Optional[RagRetrievalConfig] = None,
    max_contexts: Optional[int] = None,
    max_context_chars: Optional[int] = None,
    max_response_chars: Optional[int] = None,
    sample_filter: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    生成 Ragas 评测输入数据。

    该函数只负责准备数据，不依赖 Ragas 包本身；即使 Ragas 暂时不可用，也可以先落盘复查。
    """
    dataset = load_eval_dataset(dataset_path)
    dataset = filter_eval_samples(dataset, sample_filter=sample_filter)
    if limit is not None:
        dataset = dataset[:limit]

    config = retrieval_config or RagRetrievalConfig()
    rows: List[Dict[str, Any]] = []
    metadata_rows: List[Dict[str, Any]] = []
    started_at = time.perf_counter()

    for sample in dataset:
        if not sample.get("question", "").strip():
            continue
        converted = _build_ragas_eval_row(
            sample,
            config,
            max_contexts=max_contexts,
            max_context_chars=max_context_chars,
            max_response_chars=max_response_chars,
        )
        rows.append(converted["ragas_row"])
        metadata_rows.append(converted["metadata"])

    dataset_build_config = {
        "limit": limit,
        "dataset_sha256": _sha256_file(dataset_path),
        "retrieval_config": config.to_dict(),
        "max_contexts": max_contexts,
        "max_context_chars": max_context_chars,
        "max_response_chars": max_response_chars,
        "sample_filter": sample_filter or {},
        "answer_model": settings.MODEL,
        "answer_base_url": settings.BASE_URL,
        "answer_build_version": ANSWER_BUILD_VERSION,
    }
    return {
        "dataset_path": str(Path(dataset_path).resolve()),
        "sample_count": len(rows),
        "source_sample_count": len(load_eval_dataset(dataset_path)),
        "config": config.to_dict(),
        "dataset_build_config": dataset_build_config,
        "build_seconds": round(time.perf_counter() - started_at, 3),
        "ragas_rows": rows,
        "metadata": metadata_rows,
    }


def _load_json_file(path: Path) -> Dict[str, Any]:
    """读取 JSON 文件。"""
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def _stable_json_dumps(data: Any) -> str:
    """生成稳定 JSON 字符串，用于计算缓存签名。"""
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(text: str) -> str:
    """计算文本 SHA256。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: str) -> str:
    """计算文件 SHA256，用于让 prepared dataset 缓存感知数据内容变化。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _expected_dataset_build_config(
    dataset_path: str,
    limit: Optional[int],
    retrieval_config: RagRetrievalConfig,
    max_contexts: Optional[int],
    max_context_chars: Optional[int],
    max_response_chars: Optional[int],
    sample_filter: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """生成用于判断 prepared dataset 缓存是否可复用的配置签名。"""
    return {
        "limit": limit,
        "dataset_sha256": _sha256_file(dataset_path),
        "retrieval_config": retrieval_config.to_dict(),
        "max_contexts": max_contexts,
        "max_context_chars": max_context_chars,
        "max_response_chars": max_response_chars,
        "sample_filter": sample_filter or {},
        "answer_model": settings.MODEL,
        "answer_base_url": settings.BASE_URL,
        "answer_build_version": ANSWER_BUILD_VERSION,
    }


def load_prepared_dataset_if_compatible(
    dataset_path: str,
    cache_path: str,
    limit: Optional[int],
    retrieval_config: RagRetrievalConfig,
    max_contexts: Optional[int],
    max_context_chars: Optional[int],
    max_response_chars: Optional[int],
    sample_filter: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """如果已落盘的 Ragas dataset 与当前配置一致，则直接复用。"""
    path = Path(cache_path)
    if not path.exists():
        return None
    cached = _load_json_file(path)
    expected_config = _expected_dataset_build_config(
        dataset_path=dataset_path,
        limit=limit,
        retrieval_config=retrieval_config,
        max_contexts=max_contexts,
        max_context_chars=max_context_chars,
        max_response_chars=max_response_chars,
        sample_filter=sample_filter,
    )
    if cached.get("dataset_build_config") != expected_config:
        return None
    cached["loaded_from_cache"] = True
    cached["build_seconds"] = 0.0
    return cached


def _load_ragas_components(
    metric_names: List[str],
    include_reference_metrics: bool,
    answer_relevancy_strictness: int = 1,
) -> Dict[str, Any]:
    """按当前安装的 Ragas 版本加载评测组件。"""
    import ragas
    from ragas import EvaluationDataset, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics._answer_relevance import answer_relevancy
    from ragas.metrics._context_precision import context_utilization
    from ragas.metrics._context_recall import context_recall
    from ragas.metrics._faithfulness import faithfulness
    from ragas.run_config import RunConfig

    registry = {
        "faithfulness": faithfulness,
        "answer_relevancy": answer_relevancy,
        "context_utilization": context_utilization,
        "context_recall": context_recall,
    }
    if "answer_relevancy" in metric_names:
        # DeepSeek 兼容接口当前只支持 n=1；Ragas 默认 strictness=3 会触发 n=3。
        answer_relevancy.strictness = answer_relevancy_strictness
    reference_metrics = {"context_recall"}
    metrics = []
    for metric_name in metric_names:
        if metric_name in reference_metrics and not include_reference_metrics:
            continue
        if metric_name not in registry:
            raise ValueError(f"Unsupported Ragas metric: {metric_name}")
        metrics.append(registry[metric_name])

    return {
        "ragas": ragas,
        "EvaluationDataset": EvaluationDataset,
        "evaluate": evaluate,
        "RunConfig": RunConfig,
        "LangchainLLMWrapper": LangchainLLMWrapper,
        "LangchainEmbeddingsWrapper": LangchainEmbeddingsWrapper,
        "metrics": metrics,
    }


def _build_ragas_judge_llm() -> Any:
    """构造 Ragas judge LLM，复用项目当前 LLM 配置，但不暴露 API key。"""
    return ChatOpenAI(
        api_key=settings.API_KEY,
        base_url=settings.BASE_URL,
        model_name=settings.MODEL,
        temperature=0,
    )


def _extract_score_records(evaluation_result: Any) -> List[Dict[str, Any]]:
    """把 Ragas EvaluationResult 转成普通 JSON records。"""
    dataframe = evaluation_result.to_pandas()
    dataframe = dataframe.where(dataframe.notnull(), None)
    return dataframe.to_dict("records")


def _is_valid_metric_value(value: Any) -> bool:
    """判断一个 Ragas 指标值是否是有效数字。"""
    return isinstance(value, (int, float)) and not math.isnan(float(value))


def _summarize_scores(records: List[Dict[str, Any]], metric_names: List[str]) -> Dict[str, float]:
    """汇总 Ragas 逐题分数。"""
    summary: Dict[str, float] = {}
    for metric_name in metric_names:
        values = [
            float(record[metric_name])
            for record in records
            if metric_name in record and _is_valid_metric_value(record[metric_name])
        ]
        if values:
            summary[metric_name] = round(mean(values), 4)
    return summary


def _build_metric_validity(records: List[Dict[str, Any]], metric_names: List[str]) -> Dict[str, Dict[str, int]]:
    """统计每个指标的有效值和 NaN / 缺失数量。"""
    validity: Dict[str, Dict[str, int]] = {}
    for metric_name in metric_names:
        valid_count = sum(1 for record in records if _is_valid_metric_value(record.get(metric_name)))
        total_count = len(records)
        validity[metric_name] = {
            "valid_count": valid_count,
            "nan_count": total_count - valid_count,
            "total_count": total_count,
        }
    return validity


def run_ragas_baseline(
    prepared_dataset: Dict[str, Any],
    metric_names: List[str],
    include_reference_metrics: bool = True,
    timeout: int = 180,
    max_workers: int = 2,
    show_progress: bool = True,
    answer_relevancy_strictness: int = 1,
) -> Dict[str, Any]:
    """运行 Ragas baseline，并返回结构化结果。"""
    components = _load_ragas_components(
        metric_names,
        include_reference_metrics,
        answer_relevancy_strictness=answer_relevancy_strictness,
    )
    metric_objects = components["metrics"]
    effective_metric_names = [metric.name for metric in metric_objects]

    evaluation_dataset = components["EvaluationDataset"].from_list(prepared_dataset["ragas_rows"])
    judge_llm = components["LangchainLLMWrapper"](_build_ragas_judge_llm())
    embeddings = None
    if "answer_relevancy" in effective_metric_names:
        embeddings = components["LangchainEmbeddingsWrapper"](_get_embedding_function())
    run_config = components["RunConfig"](timeout=timeout, max_workers=max_workers)

    started_at = time.perf_counter()
    evaluation_result = components["evaluate"](
        evaluation_dataset,
        metrics=metric_objects,
        llm=judge_llm,
        embeddings=embeddings,
        run_config=run_config,
        raise_exceptions=False,
        show_progress=show_progress,
    )
    records = _extract_score_records(evaluation_result)
    summary = _summarize_scores(records, effective_metric_names)
    metric_validity = _build_metric_validity(records, effective_metric_names)
    status = "pass" if summary else "ragas_no_valid_scores"

    return {
        "status": status,
        "ragas_version": getattr(components["ragas"], "__version__", "unknown"),
        "judge_model": settings.MODEL,
        "judge_base_url": settings.BASE_URL,
        "metrics": effective_metric_names,
        "eval_seconds": round(time.perf_counter() - started_at, 3),
        "ragas_timeout": timeout,
        "ragas_max_workers": max_workers,
        "answer_relevancy_strictness": answer_relevancy_strictness,
        "score_summary": summary,
        "score_stddev": {metric_name: 0.0 for metric_name in summary},
        "metric_validity": metric_validity,
        "score_records": records,
        "warning": ""
        if summary
        else "Ragas finished but produced no numeric metric scores. Check LLM/API connectivity and score_records.",
    }


def _aggregate_repeated_score_records(
    run_results: List[Dict[str, Any]],
    metric_names: List[str],
) -> List[Dict[str, Any]]:
    """把多次 Ragas 逐题结果聚合为逐题均值，并保留每个指标的 run values。"""
    if not run_results:
        return []

    base_records = run_results[0].get("score_records", [])
    aggregated_records: List[Dict[str, Any]] = []
    for record_index, base_record in enumerate(base_records):
        aggregate = dict(base_record)
        metric_run_values: Dict[str, List[Any]] = {}
        for metric_name in metric_names:
            values = []
            for run_result in run_results:
                records = run_result.get("score_records", [])
                value = records[record_index].get(metric_name) if record_index < len(records) else None
                values.append(value)
            metric_run_values[metric_name] = values
            valid_values = [float(value) for value in values if _is_valid_metric_value(value)]
            aggregate[metric_name] = round(mean(valid_values), 4) if valid_values else math.nan
        aggregate["metric_run_values"] = metric_run_values
        aggregated_records.append(aggregate)
    return aggregated_records


def _aggregate_repeated_score_summary(
    run_results: List[Dict[str, Any]],
    metric_names: List[str],
) -> Dict[str, Dict[str, Any]]:
    """汇总多次 Ragas 运行的均值、标准差和有效运行次数。"""
    summary: Dict[str, Dict[str, Any]] = {}
    for metric_name in metric_names:
        values = [
            float(run_result.get("score_summary", {}).get(metric_name))
            for run_result in run_results
            if _is_valid_metric_value(run_result.get("score_summary", {}).get(metric_name))
        ]
        summary[metric_name] = {
            "mean": round(mean(values), 4) if values else math.nan,
            "std": round(stdev(values), 4) if len(values) > 1 else 0.0 if values else math.nan,
            "valid_runs": len(values),
            "total_runs": len(run_results),
        }
    return summary


def _aggregate_repeated_validity(
    run_results: List[Dict[str, Any]],
    metric_names: List[str],
) -> Dict[str, Dict[str, int]]:
    """汇总多次运行的有效指标数量。"""
    records_per_run = len(run_results[0].get("score_records", [])) if run_results else 0
    validity: Dict[str, Dict[str, int]] = {}
    for metric_name in metric_names:
        valid_count = 0
        total_count = 0
        for run_result in run_results:
            for record in run_result.get("score_records", []):
                total_count += 1
                if _is_valid_metric_value(record.get(metric_name)):
                    valid_count += 1
        validity[metric_name] = {
            "valid_count": valid_count,
            "nan_count": total_count - valid_count,
            "total_count": total_count,
            "runs": len(run_results),
            "records_per_run": records_per_run,
        }
    return validity


def _build_low_score_cases(
    records: List[Dict[str, Any]],
    metadata_rows: List[Dict[str, Any]],
    metric_names: List[str],
    threshold: float,
) -> List[Dict[str, Any]]:
    """列出低分或 NaN 的逐题指标，辅助 bad case 分析。"""
    cases: List[Dict[str, Any]] = []
    for index, record in enumerate(records):
        metadata = metadata_rows[index] if index < len(metadata_rows) else {}
        for metric_name in metric_names:
            value = record.get(metric_name)
            is_nan = not _is_valid_metric_value(value)
            if is_nan or float(value) < threshold:
                cases.append(
                    {
                        "question_index": index + 1,
                        "question": metadata.get("question", record.get("user_input", "")),
                        "question_type": metadata.get("question_type", ""),
                        "metric": metric_name,
                        "score": None if is_nan else round(float(value), 4),
                        "reason": "nan_or_missing" if is_nan else "below_threshold",
                        "threshold": threshold,
                    }
                )
    return cases


def _load_retrieval_eval_details(path: str) -> Dict[str, Any]:
    """读取 Phase2 retrieval eval 输出，并按 question 建索引。"""
    retrieval_path = Path(path)
    if not retrieval_path.exists():
        return {
            "available": False,
            "path": str(retrieval_path),
            "details_by_question": {},
            "sample_count": 0,
            "warning": "retrieval eval result file not found",
        }

    payload = _load_json_file(retrieval_path)
    details = payload.get("details", [])
    details_by_question = {
        detail.get("question", "").strip(): detail
        for detail in details
        if detail.get("question", "").strip()
    }
    return {
        "available": True,
        "path": str(retrieval_path),
        "details_by_question": details_by_question,
        "sample_count": len(details),
        "summary": {
            "recall_at_k": payload.get("recall_at_k"),
            "mrr": payload.get("mrr"),
            "hit_rate": payload.get("hit_rate"),
            "loss_reason_counts": payload.get("loss_reason_counts", {}),
        },
        "warning": "",
    }


def _classify_cross_metric_case(
    retrieval_detail: Dict[str, Any],
    score_record: Dict[str, Any],
    metric_names: List[str],
    ragas_low_threshold: float,
    retrieval_recall_low_threshold: float,
    retrieval_mrr_low_threshold: float,
) -> Dict[str, Any]:
    """判断单题是否存在 retrieval 与 Ragas 跨指标 bad case。"""
    retrieval_recall = retrieval_detail.get("recall")
    retrieval_mrr = retrieval_detail.get("reciprocal_rank")
    retrieval_recall_low = (
        _is_valid_metric_value(retrieval_recall)
        and float(retrieval_recall) < retrieval_recall_low_threshold
    )
    retrieval_mrr_low = (
        _is_valid_metric_value(retrieval_mrr)
        and float(retrieval_mrr) < retrieval_mrr_low_threshold
    )

    low_ragas_metrics = []
    nan_ragas_metrics = []
    for metric_name in metric_names:
        value = score_record.get(metric_name)
        if not _is_valid_metric_value(value):
            nan_ragas_metrics.append(metric_name)
        elif float(value) < ragas_low_threshold:
            low_ragas_metrics.append(metric_name)

    retrieval_bad = bool(retrieval_recall_low or retrieval_mrr_low)
    ragas_bad = bool(low_ragas_metrics or nan_ragas_metrics)
    categories = []
    if retrieval_bad and ragas_bad:
        categories.append("retrieval_and_generation_bad")
    elif retrieval_bad:
        categories.append("retrieval_bad_ragas_ok")
    elif ragas_bad:
        categories.append("retrieval_ok_ragas_bad")
    if nan_ragas_metrics:
        categories.append("ragas_nan")
    if retrieval_detail.get("loss_reasons"):
        categories.extend([f"loss:{reason}" for reason in retrieval_detail.get("loss_reasons", [])])

    return {
        "retrieval_recall": retrieval_recall,
        "retrieval_mrr": retrieval_mrr,
        "retrieval_recall_low": retrieval_recall_low,
        "retrieval_mrr_low": retrieval_mrr_low,
        "low_ragas_metrics": low_ragas_metrics,
        "nan_ragas_metrics": nan_ragas_metrics,
        "categories": categories,
        "is_bad_case": bool(retrieval_bad or ragas_bad),
    }


def build_cross_metric_bad_cases(
    result: Dict[str, Any],
    retrieval_eval_path: str,
    ragas_low_threshold: float,
    retrieval_recall_low_threshold: float,
    retrieval_mrr_low_threshold: float,
) -> Dict[str, Any]:
    """对照 Phase2 retrieval 指标和 Ragas 分数，生成跨指标 bad case 表。"""
    retrieval_eval = _load_retrieval_eval_details(retrieval_eval_path)
    if not retrieval_eval["available"]:
        return {
            "available": False,
            "retrieval_eval_path": retrieval_eval["path"],
            "summary": {
                "shared_count": 0,
                "ragas_only_count": len(result.get("metadata", [])),
                "retrieval_only_count": 0,
                "bad_case_count": 0,
            },
            "cases": [],
            "warning": retrieval_eval["warning"],
        }

    metric_names = result.get("metrics", [])
    metadata_rows = result.get("metadata", [])
    score_records = result.get("score_records", [])
    retrieval_by_question = retrieval_eval["details_by_question"]
    ragas_questions = {metadata.get("question", "").strip() for metadata in metadata_rows}
    cases = []
    shared_count = 0

    for index, metadata in enumerate(metadata_rows):
        question = metadata.get("question", "").strip()
        if not question or question not in retrieval_by_question:
            continue
        shared_count += 1
        retrieval_detail = retrieval_by_question[question]
        score_record = score_records[index] if index < len(score_records) else {}
        classification = _classify_cross_metric_case(
            retrieval_detail=retrieval_detail,
            score_record=score_record,
            metric_names=metric_names,
            ragas_low_threshold=ragas_low_threshold,
            retrieval_recall_low_threshold=retrieval_recall_low_threshold,
            retrieval_mrr_low_threshold=retrieval_mrr_low_threshold,
        )
        if not classification["is_bad_case"]:
            continue

        final_rank = (
            retrieval_detail.get("gold_rank_summary", {})
            .get("final", {})
            .get("best_rank")
        )
        cases.append(
            {
                "question_index": index + 1,
                "question": question,
                "question_type": metadata.get("question_type", ""),
                "retrieval_recall": classification["retrieval_recall"],
                "retrieval_mrr": classification["retrieval_mrr"],
                "retrieval_loss_reasons": retrieval_detail.get("loss_reasons", []),
                "final_best_gold_rank": final_rank,
                "ragas_scores": {
                    metric_name: score_record.get(metric_name)
                    for metric_name in metric_names
                },
                "low_ragas_metrics": classification["low_ragas_metrics"],
                "nan_ragas_metrics": classification["nan_ragas_metrics"],
                "categories": classification["categories"],
            }
        )

    retrieval_questions = set(retrieval_by_question)
    return {
        "available": True,
        "retrieval_eval_path": retrieval_eval["path"],
        "retrieval_summary": retrieval_eval.get("summary", {}),
        "thresholds": {
            "ragas_low_threshold": ragas_low_threshold,
            "retrieval_recall_low_threshold": retrieval_recall_low_threshold,
            "retrieval_mrr_low_threshold": retrieval_mrr_low_threshold,
        },
        "summary": {
            "shared_count": shared_count,
            "ragas_only_count": len(ragas_questions - retrieval_questions),
            "retrieval_only_count": len(retrieval_questions - ragas_questions),
            "bad_case_count": len(cases),
        },
        "cases": cases,
        "warning": "",
    }


def run_repeated_ragas_baseline(
    prepared_dataset: Dict[str, Any],
    metric_names: List[str],
    include_reference_metrics: bool = True,
    timeout: int = 180,
    max_workers: int = 2,
    show_progress: bool = True,
    answer_relevancy_strictness: int = 1,
    repeat_count: int = 1,
    judge_profile: str = "standard_single",
    low_score_threshold: float = 0.5,
) -> Dict[str, Any]:
    """运行一次或多次 Ragas，并聚合 judge 稳定性统计。"""
    effective_repeat_count = max(int(repeat_count), 1)
    run_results: List[Dict[str, Any]] = []
    started_at = time.perf_counter()

    for run_index in range(effective_repeat_count):
        run_result = run_ragas_baseline(
            prepared_dataset=prepared_dataset,
            metric_names=metric_names,
            include_reference_metrics=include_reference_metrics,
            timeout=timeout,
            max_workers=max_workers,
            show_progress=show_progress,
            answer_relevancy_strictness=answer_relevancy_strictness,
        )
        run_result["run_index"] = run_index + 1
        run_results.append(run_result)

    effective_metric_names = run_results[0].get("metrics", metric_names) if run_results else metric_names
    aggregated_records = _aggregate_repeated_score_records(run_results, effective_metric_names)
    repeated_summary = _aggregate_repeated_score_summary(run_results, effective_metric_names)
    score_summary = {
        metric_name: values["mean"]
        for metric_name, values in repeated_summary.items()
        if _is_valid_metric_value(values.get("mean"))
    }
    score_stddev = {
        metric_name: values["std"]
        for metric_name, values in repeated_summary.items()
        if _is_valid_metric_value(values.get("std"))
    }
    metric_validity = _aggregate_repeated_validity(run_results, effective_metric_names)
    status = "pass" if score_summary else "ragas_no_valid_scores"

    return {
        "status": status,
        "ragas_version": run_results[0].get("ragas_version", "unknown") if run_results else "unknown",
        "judge_model": settings.MODEL,
        "judge_base_url": settings.BASE_URL,
        "judge_profile": judge_profile,
        "repeat_count": effective_repeat_count,
        "metrics": effective_metric_names,
        "eval_seconds": round(time.perf_counter() - started_at, 3),
        "ragas_timeout": timeout,
        "ragas_max_workers": max_workers,
        "answer_relevancy_strictness": answer_relevancy_strictness,
        "low_score_threshold": low_score_threshold,
        "score_summary": score_summary,
        "score_stddev": score_stddev,
        "repeated_score_summary": repeated_summary,
        "metric_validity": metric_validity,
        "score_records": aggregated_records,
        "run_results": run_results,
        "warning": ""
        if score_summary
        else "Ragas finished but produced no numeric metric scores. Check LLM/API connectivity and run_results.",
    }


def _build_score_cache_signature(
    prepared_dataset: Dict[str, Any],
    metric_names: List[str],
    include_reference_metrics: bool,
    timeout: int,
    max_workers: int,
    answer_relevancy_strictness: int,
    repeat_count: int,
    judge_profile: str,
) -> str:
    """为 Ragas judge 输入和配置生成精确签名。"""
    payload = {
        "ragas_rows": prepared_dataset.get("ragas_rows", []),
        "dataset_build_config": prepared_dataset.get("dataset_build_config", {}),
        "metric_names": metric_names,
        "include_reference_metrics": include_reference_metrics,
        "timeout": timeout,
        "max_workers": max_workers,
        "answer_relevancy_strictness": answer_relevancy_strictness,
        "repeat_count": repeat_count,
        "judge_profile": judge_profile,
        "judge_model": settings.MODEL,
        "judge_base_url": settings.BASE_URL,
    }
    return _sha256_text(_stable_json_dumps(payload))


def _load_score_cache_if_compatible(cache_path: str, signature: str) -> Optional[Dict[str, Any]]:
    """如果 Ragas 分数缓存与当前精确输入一致，则直接复用。"""
    path = Path(cache_path)
    if not path.exists():
        return None
    cached = _load_json_file(path)
    if cached.get("score_cache_signature") != signature:
        return None
    cached["loaded_score_from_cache"] = True
    cached["eval_seconds"] = 0.0
    return cached


def _write_score_cache(cache_path: str, signature: str, result: Dict[str, Any]) -> None:
    """写入 Ragas 分数缓存。"""
    cache_payload = {
        key: result.get(key)
        for key in [
            "status",
            "ragas_version",
            "judge_model",
            "judge_base_url",
            "metrics",
            "eval_seconds",
            "ragas_timeout",
            "ragas_max_workers",
            "answer_relevancy_strictness",
            "judge_profile",
            "repeat_count",
            "low_score_threshold",
            "score_summary",
            "score_stddev",
            "repeated_score_summary",
            "metric_validity",
            "score_records",
            "run_results",
            "warning",
        ]
    }
    cache_payload["score_cache_signature"] = signature
    _write_json_file(Path(cache_path), cache_payload)


def run_ragas_eval_from_code_config() -> Dict[str, Any]:
    """根据 RAGAS_RUN_CONFIG 准备数据、运行 Ragas，并写入输出文件。"""
    retrieval_config = _build_retrieval_config(RAGAS_RUN_CONFIG.get("retrieval_config"))
    sample_filter = RAGAS_RUN_CONFIG.get("sample_filter")
    prepared_dataset = None
    if RAGAS_RUN_CONFIG.get("reuse_prepared_dataset"):
        prepared_dataset = load_prepared_dataset_if_compatible(
            dataset_path=RAGAS_RUN_CONFIG["dataset_path"],
            cache_path=RAGAS_RUN_CONFIG["ragas_dataset_path"],
            limit=RAGAS_RUN_CONFIG["limit"],
            retrieval_config=retrieval_config,
            max_contexts=RAGAS_RUN_CONFIG["max_contexts"],
            max_context_chars=RAGAS_RUN_CONFIG["max_context_chars"],
            max_response_chars=RAGAS_RUN_CONFIG["max_response_chars"],
            sample_filter=sample_filter,
        )
    if prepared_dataset is None:
        prepared_dataset = build_ragas_dataset(
            dataset_path=RAGAS_RUN_CONFIG["dataset_path"],
            limit=RAGAS_RUN_CONFIG["limit"],
            retrieval_config=retrieval_config,
            max_contexts=RAGAS_RUN_CONFIG["max_contexts"],
            max_context_chars=RAGAS_RUN_CONFIG["max_context_chars"],
            max_response_chars=RAGAS_RUN_CONFIG["max_response_chars"],
            sample_filter=sample_filter,
        )

    if RAGAS_RUN_CONFIG.get("save_dataset"):
        _write_json_file(Path(RAGAS_RUN_CONFIG["ragas_dataset_path"]), prepared_dataset)

    result: Dict[str, Any] = {
        "status": "dataset_prepared",
        "active_profile": RAGAS_RUN_CONFIG.get("active_profile", ""),
        "judge_profile": RAGAS_RUN_CONFIG.get("judge_profile", ""),
        "repeat_count": RAGAS_RUN_CONFIG.get("repeat_count", 0),
        "low_score_threshold": RAGAS_RUN_CONFIG.get("low_score_threshold", 0.5),
        "retrieval_eval_path": RAGAS_RUN_CONFIG.get("retrieval_eval_path", ""),
        "retrieval_recall_low_threshold": RAGAS_RUN_CONFIG.get("retrieval_recall_low_threshold", 0.67),
        "retrieval_mrr_low_threshold": RAGAS_RUN_CONFIG.get("retrieval_mrr_low_threshold", 0.5),
        "dataset_path": prepared_dataset["dataset_path"],
        "sample_count": prepared_dataset["sample_count"],
        "source_sample_count": prepared_dataset.get("source_sample_count", prepared_dataset["sample_count"]),
        "config": prepared_dataset["config"],
        "sample_filter": sample_filter or {},
        "build_seconds": prepared_dataset["build_seconds"],
        "loaded_from_cache": prepared_dataset.get("loaded_from_cache", False),
        "dataset_build_config": prepared_dataset.get("dataset_build_config", {}),
        "ragas_rows": prepared_dataset["ragas_rows"],
        "metadata": prepared_dataset["metadata"],
        "metrics": RAGAS_RUN_CONFIG["selected_metrics"],
    }

    if RAGAS_RUN_CONFIG.get("run_ragas"):
        try:
            score_cache_signature = _build_score_cache_signature(
                prepared_dataset=prepared_dataset,
                metric_names=RAGAS_RUN_CONFIG["selected_metrics"],
                include_reference_metrics=RAGAS_RUN_CONFIG["include_reference_metrics"],
                timeout=RAGAS_RUN_CONFIG["ragas_timeout"],
                max_workers=RAGAS_RUN_CONFIG["ragas_max_workers"],
                answer_relevancy_strictness=RAGAS_RUN_CONFIG["answer_relevancy_strictness"],
                repeat_count=RAGAS_RUN_CONFIG["repeat_count"],
                judge_profile=RAGAS_RUN_CONFIG["judge_profile"],
            )
            ragas_result = None
            if RAGAS_RUN_CONFIG.get("reuse_score_cache"):
                ragas_result = _load_score_cache_if_compatible(
                    cache_path=RAGAS_RUN_CONFIG["score_cache_path"],
                    signature=score_cache_signature,
                )
            if ragas_result is None:
                ragas_result = run_repeated_ragas_baseline(
                    prepared_dataset=prepared_dataset,
                    metric_names=RAGAS_RUN_CONFIG["selected_metrics"],
                    include_reference_metrics=RAGAS_RUN_CONFIG["include_reference_metrics"],
                    timeout=RAGAS_RUN_CONFIG["ragas_timeout"],
                    max_workers=RAGAS_RUN_CONFIG["ragas_max_workers"],
                    show_progress=RAGAS_RUN_CONFIG["show_progress"],
                    answer_relevancy_strictness=RAGAS_RUN_CONFIG["answer_relevancy_strictness"],
                    repeat_count=RAGAS_RUN_CONFIG["repeat_count"],
                    judge_profile=RAGAS_RUN_CONFIG["judge_profile"],
                    low_score_threshold=RAGAS_RUN_CONFIG["low_score_threshold"],
                )
                ragas_result["loaded_score_from_cache"] = False
                if RAGAS_RUN_CONFIG.get("reuse_score_cache"):
                    _write_score_cache(
                        cache_path=RAGAS_RUN_CONFIG["score_cache_path"],
                        signature=score_cache_signature,
                        result=ragas_result,
                    )
            result.update(ragas_result)
            result["low_score_cases"] = _build_low_score_cases(
                records=result.get("score_records", []),
                metadata_rows=result.get("metadata", []),
                metric_names=result.get("metrics", []),
                threshold=float(RAGAS_RUN_CONFIG.get("low_score_threshold", 0.5)),
            )
            result["cross_metric_bad_cases"] = build_cross_metric_bad_cases(
                result=result,
                retrieval_eval_path=RAGAS_RUN_CONFIG["retrieval_eval_path"],
                ragas_low_threshold=float(RAGAS_RUN_CONFIG.get("low_score_threshold", 0.5)),
                retrieval_recall_low_threshold=float(
                    RAGAS_RUN_CONFIG.get("retrieval_recall_low_threshold", 0.67)
                ),
                retrieval_mrr_low_threshold=float(
                    RAGAS_RUN_CONFIG.get("retrieval_mrr_low_threshold", 0.5)
                ),
            )
        except Exception as exc:
            result.update(
                {
                    "status": "ragas_failed",
                    "error": repr(exc),
                    "score_summary": {},
                    "score_records": [],
                }
            )

    if RAGAS_RUN_CONFIG.get("save_output"):
        _write_json_file(Path(RAGAS_RUN_CONFIG["output_path"]), result)
        if "low_score_cases" in result:
            _write_json_file(
                Path(RAGAS_RUN_CONFIG["low_score_cases_path"]),
                {
                    "active_profile": result.get("active_profile"),
                    "judge_profile": result.get("judge_profile"),
                    "low_score_threshold": result.get("low_score_threshold"),
                    "case_count": len(result.get("low_score_cases", [])),
                    "cases": result.get("low_score_cases", []),
                },
            )
        if "cross_metric_bad_cases" in result:
            _write_json_file(
                Path(RAGAS_RUN_CONFIG["cross_metric_cases_path"]),
                result.get("cross_metric_bad_cases", {}),
            )
    if RAGAS_RUN_CONFIG.get("save_markdown"):
        write_markdown_file(Path(RAGAS_RUN_CONFIG["report_path"]), build_ragas_markdown_report(result))
    return result


if __name__ == "__main__":
    output = run_ragas_eval_from_code_config()
    if RAGAS_RUN_CONFIG.get("print_full_output"):
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        summary = {
            "status": output.get("status"),
            "active_profile": output.get("active_profile"),
            "judge_profile": output.get("judge_profile"),
            "repeat_count": output.get("repeat_count"),
            "sample_count": output.get("sample_count"),
            "judge_model": output.get("judge_model"),
            "metrics": output.get("metrics"),
            "score_summary": output.get("score_summary", {}),
            "score_stddev": output.get("score_stddev", {}),
            "metric_validity": output.get("metric_validity", {}),
            "low_score_case_count": len(output.get("low_score_cases", [])),
            "cross_metric_bad_case_count": output.get("cross_metric_bad_cases", {})
            .get("summary", {})
            .get("bad_case_count"),
            "build_seconds": output.get("build_seconds"),
            "eval_seconds": output.get("eval_seconds"),
            "loaded_from_cache": output.get("loaded_from_cache", False),
            "loaded_score_from_cache": output.get("loaded_score_from_cache", False),
            "output_path": str(Path(RAGAS_RUN_CONFIG["output_path"]).resolve()),
            "report_path": str(Path(RAGAS_RUN_CONFIG["report_path"]).resolve()),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))

