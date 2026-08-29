"""Ragas 回答质量评测、缓存和跨指标分析执行器。

模块复用检索评测产物构造 judge 输入，支持 prepare-only、重复运行和坏例
分析；它不改变知识库索引，也不把评测结果自动提升为正式发布结论。
"""

import json
import math
import os
import importlib.util
from contextlib import contextmanager
from importlib import metadata as importlib_metadata
import hashlib
import sys
import time
import types
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Callable, Dict, List, Optional

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[4]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Windows 上 numpy 与 torch 各自带 libiomp，同时导入会触发 OpenMP 重复初始化。
# 在加载任何可能链接 OpenMP 的库之前设置；setdefault 不覆盖用户显式设置。
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from config.settings import settings
from Agent.knowledge_base.query_rag import (
    RagRetrievalConfig,
    build_retrieval_config,
    _answer_question,
    _get_embedding_function,
    _normalize_question_payload,
    build_retrieval_trace,
    get_vector_db_metadata_summary,
)
from Agent.knowledge_base.rag.rag_eval.contracts import (
    candidate_evidence,
    evaluation_identity,
)
from Agent.knowledge_base.rag.rag_config import (
    MACHINE_OUTPUT_DIR,
    RAG_EVAL_DATASET_PATH,
    RAGAS_RUN_CONFIG,
    REPORT_OUTPUT_DIR,
    RETRIEVAL_PROFILES,
)
from Agent.knowledge_base.rag.rag_eval.rag_eval import evaluate_retrieval, load_eval_dataset
from Agent.knowledge_base.rag.tools.report_utils import (
    build_rag_retrieval_single_markdown_report,
    build_ragas_markdown_report,
    write_markdown_file,
)

DEFAULT_DATASET_PATH = str(RAG_EVAL_DATASET_PATH) if RAG_EVAL_DATASET_PATH else ""
DEFAULT_RAGAS_DATASET_PATH = MACHINE_OUTPUT_DIR / "ragas_eval_dataset.json"
DEFAULT_OUTPUT_PATH = MACHINE_OUTPUT_DIR / "ragas_eval_result.json"
DEFAULT_REPORT_PATH = REPORT_OUTPUT_DIR / "ragas_eval_report.md"
DEFAULT_SCORE_CACHE_PATH = MACHINE_OUTPUT_DIR / "ragas_eval_score_cache.json"
DEFAULT_RETRIEVAL_EVAL_PATH = MACHINE_OUTPUT_DIR / "rag_eval_result.json"
DEFAULT_LOW_SCORE_CASES_PATH = MACHINE_OUTPUT_DIR / "ragas_low_score_cases.json"
DEFAULT_CROSS_METRIC_CASES_PATH = MACHINE_OUTPUT_DIR / "ragas_cross_metric_bad_cases.json"
ANSWER_BUILD_VERSION = "answer_fallback_v7_generic_rag_prompt"
RagasEventCallback = Callable[[str, str, Dict[str, Any]], None]
RagasCancelChecker = Callable[[], bool]


class RagasEvalCancelled(RuntimeError):
    """调用方在 Ragas 评测过程中请求协作式取消时抛出的异常。"""


@contextmanager
def _langsmith_tracing_disabled():
    """在 Ragas judge 期间关闭外部 tracing，结束后恢复调用方环境。"""
    names = (
        "LANGCHAIN_TRACING_V2",
        "LANGSMITH_TRACING",
        "LANGSMITH_TRACING_V2",
    )
    original = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ[name] = "false"
        yield
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _cancel_requested(cancel_checker: Optional[RagasCancelChecker]) -> bool:
    """返回调用方是否请求协作式取消当前 Ragas 阶段。"""
    return bool(cancel_checker and cancel_checker())


def _raise_if_cancelled(cancel_checker: Optional[RagasCancelChecker], message: str) -> None:
    """如果收到协作式取消请求，则停止当前 Ragas 阶段。"""
    if _cancel_requested(cancel_checker):
        raise RagasEvalCancelled(message)


def _emit_step_progress(
    event_callback: Optional[RagasEventCallback],
    step_name: str,
    phase: str,
    current: int,
    total: int,
    sample: Optional[Dict[str, Any]] = None,
) -> None:
    """向进度回调发送 Ragas 准备和刷新循环的样本级进度。"""
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

# 本地手动运行时优先改这里。
# Phase3 只读取 RAG_EVAL_DATASET_PATH 指定的通用题集。
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
# - reviewed_all_core_metrics：通用题集全量核心指标。
# - reviewed_all_prepare_only：只构造 Ragas dataset，不调用 Ragas judge。
# - strict_repeat3：通用题集四指标重复 3 次。
def run_ragas_eval_from_code_config(
    event_callback: Optional[RagasEventCallback] = None,
    cancel_checker: Optional[RagasCancelChecker] = None,
) -> Dict[str, Any]:
    """根据 RAGAS_RUN_CONFIG 准备数据、运行 Ragas，并写入输出文件。"""
    dataset_path = str(RAGAS_RUN_CONFIG.get("dataset_path") or "").strip()
    if not dataset_path:
        raise ValueError("RAG_EVAL_DATASET_PATH is not configured.")
    retrieval_config = _build_retrieval_config(RAGAS_RUN_CONFIG.get("retrieval_config"))
    sample_filter = RAGAS_RUN_CONFIG.get("sample_filter")
    prepared_dataset = None
    _raise_if_cancelled(cancel_checker, "cancelled before Ragas dataset preparation")
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
    _raise_if_cancelled(cancel_checker, "cancelled after loading prepared Ragas dataset")
    if prepared_dataset is None:
        prepared_dataset = build_ragas_dataset(
            dataset_path=RAGAS_RUN_CONFIG["dataset_path"],
            limit=RAGAS_RUN_CONFIG["limit"],
            retrieval_config=retrieval_config,
            max_contexts=RAGAS_RUN_CONFIG["max_contexts"],
            max_context_chars=RAGAS_RUN_CONFIG["max_context_chars"],
            max_response_chars=RAGAS_RUN_CONFIG["max_response_chars"],
            sample_filter=sample_filter,
            event_callback=event_callback,
            cancel_checker=cancel_checker,
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
        "evaluation_identity": prepared_dataset.get("evaluation_identity", {}),
        "ragas_rows": prepared_dataset["ragas_rows"],
        "metadata": prepared_dataset["metadata"],
        "metrics": RAGAS_RUN_CONFIG["selected_metrics"],
        "kmp_duplicate_lib_ok": os.environ.get("KMP_DUPLICATE_LIB_OK", ""),
    }
    if prepared_dataset.get("status") == "cancelled":
        result["status"] = "cancelled"
        result["cancelled_after_samples"] = prepared_dataset.get("cancelled_after_samples", 0)
        return result
    invalid_answers = _find_invalid_ragas_answers(prepared_dataset.get("ragas_rows", []))
    if invalid_answers:
        result.update(
            {
                "status": "fail",
                "status_reason": "answer_generation_failed",
                "error": "Ragas dataset contains generated-answer failures; skip judge to avoid misleading scores.",
                "invalid_answer_count": len(invalid_answers),
                "invalid_answer_examples": invalid_answers[:5],
                "score_summary": {},
                "score_records": [],
            }
        )
        if RAGAS_RUN_CONFIG.get("save_output"):
            _write_json_file(Path(RAGAS_RUN_CONFIG["output_path"]), result)
        if RAGAS_RUN_CONFIG.get("save_markdown"):
            write_markdown_file(Path(RAGAS_RUN_CONFIG["report_path"]), build_ragas_markdown_report(result))
        return result

    if RAGAS_RUN_CONFIG.get("run_ragas"):
        _raise_if_cancelled(cancel_checker, "cancelled before Ragas judge")
        if RAGAS_RUN_CONFIG.get("refresh_retrieval_eval_before_ragas", True):
            try:
                result["retrieval_eval_freshness"] = ensure_retrieval_eval_for_ragas(
                    prepared_dataset=prepared_dataset,
                    retrieval_config=retrieval_config,
                    sample_filter=sample_filter,
                    event_callback=event_callback,
                    cancel_checker=cancel_checker,
                )
                if result["retrieval_eval_freshness"].get("status") == "cancelled":
                    result["status"] = "cancelled"
                    return result
            except Exception as exc:
                if isinstance(exc, RagasEvalCancelled):
                    result.update(
                        {
                            "status": "cancelled",
                            "error": str(exc),
                            "score_summary": {},
                            "score_records": [],
                        }
                    )
                    return result
                result.update(
                    {
                        "status": "retrieval_refresh_failed",
                        "error": repr(exc),
                        "score_summary": {},
                        "score_records": [],
                    }
                )
                if RAGAS_RUN_CONFIG.get("save_output"):
                    _write_json_file(Path(RAGAS_RUN_CONFIG["output_path"]), result)
                if RAGAS_RUN_CONFIG.get("save_markdown"):
                    write_markdown_file(Path(RAGAS_RUN_CONFIG["report_path"]), build_ragas_markdown_report(result))
                return result
        try:
            score_cache_signature = _build_score_cache_signature(
                prepared_dataset=prepared_dataset,
                metric_names=RAGAS_RUN_CONFIG["selected_metrics"],
                include_reference_metrics=RAGAS_RUN_CONFIG["include_reference_metrics"],
                timeout=RAGAS_RUN_CONFIG["ragas_timeout"],
                max_workers=RAGAS_RUN_CONFIG["ragas_max_workers"],
                max_retries=RAGAS_RUN_CONFIG.get("ragas_max_retries", 3),
                max_wait=RAGAS_RUN_CONFIG.get("ragas_max_wait", 20),
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
                    max_retries=RAGAS_RUN_CONFIG.get("ragas_max_retries", 3),
                    max_wait=RAGAS_RUN_CONFIG.get("ragas_max_wait", 20),
                    show_progress=RAGAS_RUN_CONFIG["show_progress"],
                    answer_relevancy_strictness=RAGAS_RUN_CONFIG["answer_relevancy_strictness"],
                    repeat_count=RAGAS_RUN_CONFIG["repeat_count"],
                    judge_profile=RAGAS_RUN_CONFIG["judge_profile"],
                    low_score_threshold=RAGAS_RUN_CONFIG["low_score_threshold"],
                    event_callback=event_callback,
                    cancel_checker=cancel_checker,
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
            if isinstance(exc, RagasEvalCancelled):
                result.update(
                    {
                        "status": "cancelled",
                        "error": str(exc),
                        "score_summary": {},
                        "score_records": [],
                    }
                )
            else:
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


def run_repeated_ragas_baseline(
    prepared_dataset: Dict[str, Any],
    metric_names: List[str],
    include_reference_metrics: bool = True,
    timeout: int = 180,
    max_workers: int = 2,
    max_retries: int = 3,
    max_wait: int = 20,
    show_progress: bool = True,
    answer_relevancy_strictness: int = 1,
    repeat_count: int = 1,
    judge_profile: str = "standard_single",
    low_score_threshold: float = 0.5,
    event_callback: Optional[RagasEventCallback] = None,
    cancel_checker: Optional[RagasCancelChecker] = None,
    embedding_function: Any = None,
) -> Dict[str, Any]:
    """运行一次或多次 Ragas，并聚合 judge 稳定性统计。"""
    effective_repeat_count = max(int(repeat_count), 1)
    run_results: List[Dict[str, Any]] = []
    started_at = time.perf_counter()

    for run_index in range(effective_repeat_count):
        _raise_if_cancelled(cancel_checker, f"cancelled before Ragas judge repeat {run_index + 1}")
        if event_callback is not None:
            event_callback(
                "step_progress",
                f"ragas_eval judge: {run_index + 1}/{effective_repeat_count}",
                {
                    "step": "ragas_eval",
                    "phase": "judge",
                    "current": run_index + 1,
                    "total": effective_repeat_count,
                },
            )
        run_result = run_ragas_baseline(
            prepared_dataset=prepared_dataset,
            metric_names=metric_names,
            include_reference_metrics=include_reference_metrics,
            timeout=timeout,
            max_workers=max_workers,
            max_retries=max_retries,
            max_wait=max_wait,
            show_progress=show_progress,
            answer_relevancy_strictness=answer_relevancy_strictness,
            embedding_function=embedding_function,
        )
        run_result["run_index"] = run_index + 1
        run_results.append(run_result)
        _raise_if_cancelled(cancel_checker, f"cancelled after Ragas judge repeat {run_index + 1}")

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
        "ragas_max_retries": max_retries,
        "ragas_max_wait": max_wait,
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


def run_ragas_baseline(
    prepared_dataset: Dict[str, Any],
    metric_names: List[str],
    include_reference_metrics: bool = True,
    timeout: int = 180,
    max_workers: int = 2,
    max_retries: int = 3,
    max_wait: int = 20,
    show_progress: bool = True,
    answer_relevancy_strictness: int = 1,
    embedding_function: Any = None,
) -> Dict[str, Any]:
    """运行 Ragas baseline，并返回结构化结果。"""
    components = _load_legacy_ragas_components(
        metric_names=metric_names,
        include_reference_metrics=include_reference_metrics,
        answer_relevancy_strictness=answer_relevancy_strictness,
    )
    metric_objects = components["metrics"]
    effective_metric_names = [metric.name for metric in metric_objects]

    evaluation_dataset = components["EvaluationDataset"].from_list(prepared_dataset["ragas_rows"])
    judge_llm = components["LangchainLLMWrapper"](_build_legacy_ragas_judge_llm())
    embeddings = None
    if "answer_relevancy" in effective_metric_names:
        source_embedding = embedding_function if embedding_function is not None else _get_embedding_function()
        embeddings = components["LangchainEmbeddingsWrapper"](source_embedding)
    run_config = components["RunConfig"](
        timeout=timeout,
        max_workers=max_workers,
        max_retries=max_retries,
        max_wait=max_wait,
    )

    started_at = time.perf_counter()
    with _langsmith_tracing_disabled():
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
        "ragas_max_retries": max_retries,
        "ragas_max_wait": max_wait,
        "answer_relevancy_strictness": answer_relevancy_strictness,
        "score_summary": summary,
        "score_stddev": {metric_name: 0.0 for metric_name in summary},
        "metric_validity": metric_validity,
        "score_records": records,
        "warning": ""
        if summary
        else "Ragas finished but produced no numeric metric scores. Check LLM/API connectivity and score_records.",
    }


def _load_legacy_ragas_components(
    metric_names: List[str],
    include_reference_metrics: bool,
    answer_relevancy_strictness: int = 1,
) -> Dict[str, Any]:
    """按当前已验证的 Ragas 0.4.x API 加载评测组件。"""
    _install_ragas_vertexai_import_shim()
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


def preflight_ragas_dependencies(
    metric_names: Optional[List[str]] = None,
    include_reference_metrics: Optional[bool] = None,
    answer_relevancy_strictness: Optional[int] = None,
) -> Dict[str, Any]:
    """轻量检查 Ragas / LangChain 导入链，不触发真实 judge 调用。"""
    effective_metric_names = metric_names or list(RAGAS_RUN_CONFIG.get("selected_metrics", []))
    effective_include_reference = (
        RAGAS_RUN_CONFIG.get("include_reference_metrics", True)
        if include_reference_metrics is None
        else include_reference_metrics
    )
    effective_strictness = (
        RAGAS_RUN_CONFIG.get("answer_relevancy_strictness", 1)
        if answer_relevancy_strictness is None
        else answer_relevancy_strictness
    )
    components = _load_legacy_ragas_components(
        metric_names=effective_metric_names,
        include_reference_metrics=effective_include_reference,
        answer_relevancy_strictness=effective_strictness,
    )
    return {
        "status": "pass",
        "ragas_version": getattr(components["ragas"], "__version__", "unknown"),
        "metrics": effective_metric_names,
        "versions": {
            "ragas": _package_version("ragas"),
            "langchain": _package_version("langchain"),
            "langchain-community": _package_version("langchain-community"),
            "langchain-core": _package_version("langchain-core"),
            "langchain-openai": _package_version("langchain-openai"),
        },
    }


def _package_version(package_name: str) -> str:
    """读取已安装包版本；缺失时返回 unavailable，避免 preflight 自身失败。"""
    try:
        return importlib_metadata.version(package_name)
    except importlib_metadata.PackageNotFoundError:
        return "unavailable"


def _install_ragas_vertexai_import_shim() -> None:
    """为 Ragas 0.4.x 兼容新版 langchain-community 移除的 VertexAI chat import。"""
    module_name = "langchain_community.chat_models.vertexai"
    if module_name in sys.modules:
        return
    if importlib.util.find_spec(module_name) is not None:
        return
    from langchain_community.llms.vertexai import VertexAI

    shim = types.ModuleType(module_name)
    shim.__package__ = "langchain_community.chat_models"
    shim.ChatVertexAI = VertexAI
    sys.modules[module_name] = shim


def _build_legacy_ragas_judge_llm() -> Any:
    """构造旧版 Ragas wrapper 使用的 judge LLM。"""
    return ChatOpenAI(
        api_key=settings.API_KEY,
        base_url=settings.BASE_URL,
        model_name=settings.MODEL,
        temperature=0,
    )


def build_ragas_dataset(
    dataset_path: str,
    limit: Optional[int] = None,
    retrieval_config: Optional[RagRetrievalConfig] = None,
    max_contexts: Optional[int] = None,
    max_context_chars: Optional[int] = None,
    max_response_chars: Optional[int] = None,
    sample_filter: Optional[Dict[str, Any]] = None,
    event_callback: Optional[RagasEventCallback] = None,
    cancel_checker: Optional[RagasCancelChecker] = None,
    step_name: str = "ragas_eval",
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
    eval_identity = (
        evaluation_identity(dataset_path)
        if Path(dataset_path).is_file()
        else {"schema_version": "rag_eval_v1", "dataset_path": str(Path(dataset_path))}
    )
    rows: List[Dict[str, Any]] = []
    metadata_rows: List[Dict[str, Any]] = []
    started_at = time.perf_counter()
    total_count = len(dataset)
    cancelled = False

    for sample_index, sample in enumerate(dataset, start=1):
        if _cancel_requested(cancel_checker):
            cancelled = True
            _emit_step_progress(event_callback, step_name, "cancelled", sample_index - 1, total_count, sample)
            break
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
        _emit_step_progress(event_callback, step_name, "build_dataset", sample_index, total_count, sample)
        if _cancel_requested(cancel_checker):
            cancelled = True
            _emit_step_progress(event_callback, step_name, "cancelled", sample_index, total_count, sample)
            break

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
        "vector_db_summary": get_vector_db_metadata_summary(),
        "evaluation_identity": eval_identity,
    }
    result = {
        "status": "cancelled" if cancelled else "pass",
        "dataset_path": str(Path(dataset_path).resolve()),
        "sample_count": len(rows),
        "source_sample_count": len(load_eval_dataset(dataset_path)),
        "config": config.to_dict(),
        "dataset_build_config": dataset_build_config,
        "evaluation_identity": eval_identity,
        "build_seconds": round(time.perf_counter() - started_at, 3),
        "ragas_rows": rows,
        "metadata": metadata_rows,
    }
    if cancelled:
        result["cancelled_after_samples"] = len(rows)
    return result


def _find_invalid_ragas_answers(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """找出会使 Ragas 分数失真的回答生成失败记录。"""
    failure_markers = (
        "回答生成失败",
        "Insufficient Balance",
        "Error code:",
        "fallback_failed",
        "证据已检索，但回答生成失败",
    )
    invalid_rows: List[Dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        response = str(row.get("response") or "").strip()
        if not response:
            invalid_rows.append(
                {
                    "index": index,
                    "reason": "empty_response",
                    "user_input": row.get("user_input", ""),
                }
            )
            continue
        matched_marker = next((marker for marker in failure_markers if marker in response), "")
        if matched_marker:
            invalid_rows.append(
                {
                    "index": index,
                    "reason": matched_marker,
                    "user_input": row.get("user_input", ""),
                    "response_preview": response[:240],
                }
            )
    return invalid_rows


def ensure_retrieval_eval_for_ragas(
    prepared_dataset: Dict[str, Any],
    retrieval_config: RagRetrievalConfig,
    sample_filter: Optional[Dict[str, Any]] = None,
    event_callback: Optional[RagasEventCallback] = None,
    cancel_checker: Optional[RagasCancelChecker] = None,
) -> Dict[str, Any]:
    """保证 cross-metric 使用的 retrieval latest 与本次 Ragas 样本和检索配置一致。"""
    retrieval_path = Path(RAGAS_RUN_CONFIG["retrieval_eval_path"])
    report_path = Path(
        RAGAS_RUN_CONFIG.get(
            "retrieval_report_path",
            str(REPORT_OUTPUT_DIR / "rag_eval_report.md"),
        )
    )
    existing = _check_retrieval_eval_compatibility(
        retrieval_path=retrieval_path,
        prepared_dataset=prepared_dataset,
        retrieval_config=retrieval_config,
    )
    if existing["compatible"]:
        _raise_if_cancelled(cancel_checker, "cancelled after checking retrieval freshness")
        return {
            "status": "reused",
            "reason": "latest retrieval eval already matches current Ragas run",
            "retrieval_eval_path": str(retrieval_path.resolve()),
            "retrieval_report_path": str(report_path.resolve()),
            "sample_count": prepared_dataset["sample_count"],
        }

    dataset = _load_ragas_source_samples(
        dataset_path=RAGAS_RUN_CONFIG["dataset_path"],
        limit=RAGAS_RUN_CONFIG["limit"],
        sample_filter=sample_filter,
    )
    _raise_if_cancelled(cancel_checker, "cancelled before refreshing retrieval eval for Ragas")
    refreshed = evaluate_retrieval(
        dataset,
        retrieval_config=retrieval_config,
        event_callback=event_callback,
        cancel_checker=cancel_checker,
        step_name="ragas_eval",
    )
    if refreshed.get("status") == "cancelled":
        return {
            "status": "cancelled",
            "reason": "cancelled while refreshing retrieval eval for Ragas",
            "retrieval_eval_path": str(retrieval_path.resolve()),
            "retrieval_report_path": str(report_path.resolve()),
            "sample_count": refreshed.get("sample_count"),
            "cancelled_after_samples": refreshed.get("cancelled_after_samples", refreshed.get("sample_count", 0)),
        }
    refreshed["evaluation_identity"] = prepared_dataset.get("evaluation_identity") or evaluation_identity(
        RAGAS_RUN_CONFIG["dataset_path"]
    )
    _write_json_file(retrieval_path, refreshed)
    write_markdown_file(report_path, build_rag_retrieval_single_markdown_report(refreshed))
    return {
        "status": "refreshed",
        "reason": existing["reason"],
        "retrieval_eval_path": str(retrieval_path.resolve()),
        "retrieval_report_path": str(report_path.resolve()),
        "sample_count": refreshed.get("sample_count"),
        "config": refreshed.get("config", {}),
    }


def _check_retrieval_eval_compatibility(
    retrieval_path: Path,
    prepared_dataset: Dict[str, Any],
    retrieval_config: RagRetrievalConfig,
) -> Dict[str, Any]:
    """检查已落盘 retrieval 结果是否可安全用于当前 Ragas cross-metric 报告。"""
    if not retrieval_path.exists():
        return {"compatible": False, "reason": "retrieval eval file is missing"}
    try:
        retrieval_eval = _load_json_file(retrieval_path)
    except Exception as exc:
        return {"compatible": False, "reason": f"retrieval eval file is unreadable: {exc!r}"}

    expected_questions = [
        metadata.get("question", "").strip()
        for metadata in prepared_dataset.get("metadata", [])
        if metadata.get("question", "").strip()
    ]
    actual_questions = [
        detail.get("question", "").strip()
        for detail in retrieval_eval.get("details", [])
        if detail.get("question", "").strip()
    ]
    if retrieval_eval.get("sample_count") != prepared_dataset.get("sample_count"):
        return {"compatible": False, "reason": "sample_count mismatch"}
    if actual_questions != expected_questions:
        return {"compatible": False, "reason": "question order mismatch"}
    if retrieval_eval.get("config") != retrieval_config.to_dict():
        return {"compatible": False, "reason": "retrieval config mismatch"}

    expected_identity = prepared_dataset.get("evaluation_identity") or prepared_dataset.get(
        "dataset_build_config", {}
    ).get("evaluation_identity")
    if expected_identity and retrieval_eval.get("evaluation_identity") != expected_identity:
        return {"compatible": False, "reason": "evaluation identity mismatch"}

    expected_vector_summary = prepared_dataset.get("dataset_build_config", {}).get("vector_db_summary")
    actual_vector_summary = retrieval_eval.get("vector_db_summary")
    if expected_vector_summary and not _stable_vector_summary_equal(expected_vector_summary, actual_vector_summary):
        return {"compatible": False, "reason": "vector db summary mismatch"}
    return {"compatible": True, "reason": ""}


def _stable_vector_summary_equal(expected: Dict[str, Any], actual: Optional[Dict[str, Any]]) -> bool:
    """只比较向量库身份稳定字段，忽略 retrieval 额外诊断字段。"""
    if not actual:
        return False
    stable_keys = [
        "exists",
        "persist_directory",
        "collection_name",
        "vector_count",
        "release_id",
        "embedding_config",
        "metadata_key_counts",
    ]
    return {key: expected.get(key) for key in stable_keys} == {key: actual.get(key) for key in stable_keys}


def _load_ragas_source_samples(
    dataset_path: str,
    limit: Optional[int],
    sample_filter: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """按 Ragas 当前数据选择规则加载 retrieval 刷新所需的同一批源样本。"""
    dataset = load_eval_dataset(dataset_path)
    dataset = filter_eval_samples(dataset, sample_filter=sample_filter)
    if limit is not None:
        dataset = dataset[:limit]
    return [sample for sample in dataset if sample.get("question", "").strip()]


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
    answer_prompt = _build_generic_eval_answer_prompt()
    answer_result = _answer_question(
        _normalize_question_payload(sample),
        evidence_payloads,
        answer_prompt=answer_prompt,
    )

    retrieved_contexts = [
        _truncate_for_eval(evidence.get("content", ""), max_context_chars)
        for evidence in ragas_evidence_payloads
    ]
    reference = sample.get("reference_answer", "")
    response = _truncate_for_eval(answer_result.get("answer", ""), max_response_chars)

    ragas_row: Dict[str, Any] = {
        "user_input": question,
        "response": response,
        "retrieved_contexts": retrieved_contexts,
    }
    if reference:
        ragas_row["reference"] = reference

    metadata = {
        "sample_id": sample.get("sample_id", ""),
        "question": question,
        "source": sample.get("source", {}),
        "gold_evidence": sample.get("gold_evidence", []),
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
        "retrieved_evidence": [
            candidate_evidence(evidence.get("metadata", {}))
            for evidence in evidence_payloads
        ],
    }

    return {
        "ragas_row": ragas_row,
        "metadata": metadata,
    }


def _build_generic_eval_answer_prompt() -> ChatPromptTemplate:
    """构造不依赖知识源或文件格式的 RAG 评测回答 prompt。"""
    return ChatPromptTemplate.from_template(
        """
        You are a careful answer writer for a general RAG evaluation.
        Use only the retrieved evidence, regardless of how the source was parsed or stored.

        # 问题
        {question}

        # 问题意图
        {intent}

        # 为什么需要这个问题
        {why_needed}

        # 检索到的证据
        {evidence_blocks}

        # 回答规则
        1. Do not add facts that are absent from the retrieved evidence.
        2. If the evidence is insufficient, use `status="insufficient_evidence"`.
        3. Every substantive claim must cite one or more evidence IDs actually used.
        4. `citations` may contain only IDs such as E1 or E2.
        5. Keep the answer concise and return only the structured result.
        """
    )

def filter_eval_samples(
    dataset: List[Dict[str, Any]],
    sample_filter: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """按通用 sample_id 或 source 元数据筛选评测样本。"""
    if not sample_filter:
        return dataset

    sample_ids = set(sample_filter.get("sample_ids") or [])
    filtered = []
    for sample in dataset:
        if sample_ids and sample.get("sample_id") not in sample_ids:
            continue
        filtered.append(sample)
    return filtered


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
    eval_identity = (
        evaluation_identity(dataset_path)
        if Path(dataset_path).is_file()
        else {"schema_version": "rag_eval_v1", "dataset_path": str(Path(dataset_path))}
    )
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
        "vector_db_summary": get_vector_db_metadata_summary(),
        "evaluation_identity": eval_identity,
    }


def _build_score_cache_signature(
    prepared_dataset: Dict[str, Any],
    metric_names: List[str],
    include_reference_metrics: bool,
    timeout: int,
    max_workers: int,
    max_retries: int,
    max_wait: int,
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
        "max_retries": max_retries,
        "max_wait": max_wait,
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
            "ragas_max_retries",
            "ragas_max_wait",
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


def _build_retrieval_config(raw_config: Optional[Dict[str, Any]] = None) -> RagRetrievalConfig:
    """构造 Ragas baseline 使用的检索配置。"""
    if not raw_config:
        profile_name = RAGAS_RUN_CONFIG.get("retrieval_profile", "active_current")
        return build_retrieval_config(RETRIEVAL_PROFILES[profile_name])
    return build_retrieval_config(raw_config)


def _truncate_for_eval(text: str, max_chars: Optional[int]) -> str:
    """限制进入 Ragas judge 的文本长度，降低评测耗时和 token 成本。"""
    if max_chars is None or max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _write_json_file(path: Path, data: Dict[str, Any]) -> None:
    """写入 JSON 文件。"""
    _ensure_parent_dir(path)
    path.write_text(json.dumps(_json_safe(data), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def _json_safe(value: Any) -> Any:
    """把非有限浮点数转为 None，保证输出是标准 JSON。"""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _ensure_parent_dir(path: Path) -> None:
    """确保输出文件所在目录存在。"""
    path.parent.mkdir(parents=True, exist_ok=True)


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
