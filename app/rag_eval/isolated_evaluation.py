"""对指定暂存索引（staged index）执行完整评测的执行器。

这个模块只接收显式的 Runtime、题集、评测配置和输出目录；它不读取 active pointer，
也不依赖旧的 latest machine/report 输出。检索指标和 Ragas 结果会写入当前运行
目录，并通过统一的运行生命周期接口供 Web 和 worker 读取。
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from Agent.knowledge_base.query_rag import (
    _normalize_question_payload,
    RagRetrievalConfig,
    build_retrieval_config,
    compress_evidence_payloads,
)
from Agent.knowledge_base.rag.rag_config import RAGAS_BASE_CONFIG, RAGAS_RUN_PROFILES, RETRIEVAL_PROFILES
from Agent.knowledge_base.rag.rag_eval.contracts import evaluation_identity, load_eval_dataset, validate_eval_dataset
from Agent.knowledge_base.rag.rag_eval.rag_eval import evaluate_retrieval, sweep_retrieval_configs
from Agent.knowledge_base.rag.rag_eval.ragas_eval import (
    _build_generic_eval_answer_prompt,
    _build_low_score_cases,
    _find_invalid_ragas_answers,
    build_cross_metric_bad_cases,
    run_repeated_ragas_baseline,
)
from Agent.knowledge_base.rag.rag_eval.trace_export import export_trace_bundle
from Agent.knowledge_base.rag.tools.report_utils import (
    build_pipeline_summary_markdown_report,
    build_rag_retrieval_single_markdown_report,
    build_rag_retrieval_sweep_markdown_report,
    build_ragas_markdown_report,
    write_markdown_file,
)


EvaluationEvent = Callable[[str, str, Dict[str, Any]], None]
EvaluationCancel = Callable[[], bool]

DEFAULT_STEPS = [
    "validate_datasets",
    "retrieval_eval",
    "ragas_eval",
    "trace_export",
    "summary",
]
ALLOWED_STEPS = set(DEFAULT_STEPS) | {"retrieval_sweep"}
MAX_SWEEP_CONFIGS = 16


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    """原子写入评测产物，避免中断时留下半个 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    temporary.replace(path)


def _json_default(value: Any) -> Any:
    """把 trace 中的集合转换为稳定 JSON。"""
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def normalize_dataset_payload(payload: Dict[str, Any]) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """校验并规范化内联 rag_eval_v1 题集。"""
    if not isinstance(payload, dict) or payload.get("schema_version") != "rag_eval_v1":
        raise ValueError("eval_dataset.schema_version must be rag_eval_v1")
    samples = payload.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("rag_eval_v1 dataset requires a non-empty samples list")
    canonical = {
        "schema_version": "rag_eval_v1",
        "dataset_id": str(payload.get("dataset_id") or "inline"),
        "dataset_kind": str(payload.get("dataset_kind") or "untyped"),
        "dataset_revision": str(payload.get("dataset_revision") or ""),
        "samples": samples,
    }
    source_snapshot = payload.get("source_snapshot")
    if isinstance(source_snapshot, dict):
        canonical["source_snapshot"] = dict(source_snapshot)
    return canonical, _normalize_dataset_from_payload(canonical)


def _normalize_dataset_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """通过现有通用契约校验内联题集字段。"""
    with tempfile.TemporaryDirectory(prefix="r5_dataset_") as temporary_dir:
        temporary = Path(temporary_dir) / "dataset.json"
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        validation = validate_eval_dataset(temporary)
        if validation.get("errors"):
            raise ValueError("; ".join(validation["errors"]))
        return load_eval_dataset(temporary)


def _config_identity(payload: Dict[str, Any]) -> str:
    """生成评测配置指纹，供结果追溯和缓存隔离使用。"""
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=_json_default)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_retrieval_options(options: Optional[Dict[str, Any]]) -> tuple[Any, Dict[str, Any]]:
    """从显式 profile 和 overrides 构造检索配置。"""
    options = dict(options or {})
    profile = str(options.get("profile") or "active_current")
    if profile not in RETRIEVAL_PROFILES:
        raise ValueError(f"unknown retrieval profile: {profile}")
    overrides = options.get("overrides") or {}
    if not isinstance(overrides, dict):
        raise ValueError("retrieval.overrides must be an object")
    base = dict(RETRIEVAL_PROFILES[profile])
    # 保留 profile 自己声明的 source-adapter 字段（例如
    # official_only_when_available），同时允许正式 retrieval dataclass 新增的
    # answer context 字段；build_retrieval_config 会忽略 adapter-only 字段。
    allowed_override_keys = set(base) | set(RagRetrievalConfig.__dataclass_fields__)
    unknown = sorted(set(overrides) - allowed_override_keys)
    if unknown:
        raise ValueError(f"unsupported retrieval override: {unknown[0]}")
    raw = {**base, **overrides}
    return build_retrieval_config(raw), {
        "profile": profile,
        "overrides": overrides,
        "config": raw,
    }


def _build_ragas_options(options: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """从显式 Ragas profile 构造本次 judge 配置。"""
    options = dict(options or {})
    profile = str(options.get("profile") or "quick_cached")
    if profile not in RAGAS_RUN_PROFILES:
        raise ValueError(f"unknown ragas profile: {profile}")
    allowed = {
        "limit",
        "selected_metrics",
        "include_reference_metrics",
        "max_contexts",
        "max_context_chars",
        "max_response_chars",
        "ragas_timeout",
        "ragas_max_workers",
        "ragas_max_retries",
        "ragas_max_wait",
        "answer_relevancy_strictness",
        "judge_profile",
        "repeat_count",
        "low_score_threshold",
        "retrieval_recall_low_threshold",
        "retrieval_mrr_low_threshold",
        "run",
        "prepare_only",
    }
    config = {
        key: RAGAS_BASE_CONFIG[key]
        for key in allowed
        if key in RAGAS_BASE_CONFIG
    }
    # Profile 还包含缓存、输出和检索构建元数据；这些字段不属于 judge 执行器参数。
    profile_config = RAGAS_RUN_PROFILES[profile]
    config.update({
        key: value
        for key, value in profile_config.items()
        if key in allowed
    })
    overrides = {key: value for key, value in options.items() if key not in {"profile"}}
    unknown = sorted(set(overrides) - allowed)
    if unknown:
        raise ValueError(f"unsupported ragas option: {unknown[0]}")
    config.update(overrides)
    config["profile"] = profile
    # 配置源使用 run_ragas，路由 API 为了兼容使用 run。前者必须在未显式
    # 覆盖时成为默认值，否则所有内置 profile 都会静默退化为只准备数据。
    run_requested = options.get(
        "run",
        profile_config.get("run_ragas", RAGAS_BASE_CONFIG.get("run_ragas", False)),
    )
    config["run"] = bool(run_requested) and not bool(config.get("prepare_only", False))
    return config


def _emit(event: Optional[EvaluationEvent], event_type: str, message: str, data: Dict[str, Any]) -> None:
    """向隔离任务推送统一事件。"""
    if event:
        event(event_type, message, data)


def _check_cancel(cancel: Optional[EvaluationCancel]) -> None:
    """在评测步骤安全点检查取消请求。"""
    if cancel and cancel():
        raise InterruptedError("isolated evaluation was cancelled")


def _artifact_paths(output_dir: Path) -> Dict[str, str]:
    """生成本次评测的固定产物名称，不使用旧的全局输出目录。"""
    machine = output_dir / "machine"
    reports = output_dir / "reports"
    return {
        "dataset": str(output_dir / "dataset_snapshot.json"),
        "retrieval": str(machine / "rag_eval_result.json"),
        "retrieval_report": str(reports / "rag_eval_report.md"),
        "retrieval_sweep": str(machine / "rag_eval_sweep_result.json"),
        "retrieval_sweep_report": str(reports / "rag_eval_sweep_report.md"),
        "ragas_dataset": str(machine / "ragas_eval_dataset.json"),
        "ragas": str(machine / "ragas_eval_result.json"),
        "ragas_report": str(reports / "ragas_eval_report.md"),
        "ragas_low_cases": str(machine / "ragas_low_score_cases.json"),
        "ragas_cross_cases": str(machine / "ragas_cross_metric_bad_cases.json"),
        "trace": str(machine / "trace.jsonl"),
        "trace_index": str(machine / "trace_index.json"),
        "trace_report": str(reports / "trace_report.md"),
        "summary": str(output_dir / "summary.json"),
        "summary_report": str(output_dir / "summary.md"),
    }


def _build_ragas_prepared_dataset(
    dataset: List[Dict[str, Any]],
    retrieval_result: Dict[str, Any],
    service: Any,
    retrieval_config: Any,
    ragas_config: Dict[str, Any],
    dataset_path: Path,
    cancel_checker: Optional[EvaluationCancel],
    event_callback: Optional[EvaluationEvent],
) -> Dict[str, Any]:
    """使用隔离检索结果生成 Ragas prepared dataset，不再次查询默认索引。"""
    source_dataset = dataset
    limit = ragas_config.get("limit")
    if limit is not None:
        limit = int(limit)
        if limit < 1:
            raise ValueError("ragas.limit must be positive")
        dataset = dataset[:limit]

    details = retrieval_result.get("details", [])
    by_sample_id = {str(detail.get("sample_id") or ""): detail for detail in details}
    by_question = {str(detail.get("question") or "").strip(): detail for detail in details}
    max_contexts = ragas_config.get("max_contexts")
    answer_max_contexts = retrieval_config.answer_max_contexts
    effective_contexts = answer_max_contexts if answer_max_contexts is not None else max_contexts
    compression_strategy = retrieval_config.answer_context_compression
    max_context_chars = ragas_config.get("max_context_chars")
    max_response_chars = ragas_config.get("max_response_chars")
    answer_prompt = _build_generic_eval_answer_prompt()
    rows: List[Dict[str, Any]] = []
    metadata: List[Dict[str, Any]] = []

    for index, sample in enumerate(dataset, start=1):
        _check_cancel(cancel_checker)
        detail = by_sample_id.get(sample.get("sample_id", "")) or by_question.get(sample["question"])
        if detail is None:
            continue
        evidence = list(detail.get("final_evidence_payload") or [])
        selected = compress_evidence_payloads(
            evidence,
            max_contexts=effective_contexts,
            strategy=compression_strategy,
        )
        answer = service.answer_question(
            _normalize_question_payload(sample),
            selected,
            answer_prompt=answer_prompt,
        )
        contexts = [
            _truncate_text(item.get("content", ""), max_context_chars)
            for item in selected
        ]
        response = _truncate_text(answer.get("answer", ""), max_response_chars)
        row: Dict[str, Any] = {
            "user_input": sample["question"],
            "response": response,
            "retrieved_contexts": contexts,
        }
        if sample.get("reference_answer"):
            row["reference"] = sample["reference_answer"]
        rows.append(row)
        metadata.append(
            {
                "sample_id": sample.get("sample_id", ""),
                "question": sample["question"],
                "source": sample.get("source", {}),
                "gold_evidence": sample.get("gold_evidence", []),
                "expected_claims": sample.get("expected_claims", []),
                "reference_answer": sample.get("reference_answer", ""),
                "judge_rubric": sample.get("judge_rubric", {}),
                "answer_status": answer.get("status", ""),
                "answer_confidence": answer.get("confidence", ""),
                "citations": answer.get("citations", []),
                "context_count": len(contexts),
                "full_context_count": len(evidence),
                "ragas_context_count": len(selected),
                "ragas_max_context_chars": max_context_chars,
                "ragas_max_response_chars": max_response_chars,
                "answer_context_compression": compression_strategy,
                "answer_evidence_count": len(selected),
                "trace_timings_ms": detail.get("trace_timings_ms", {}),
                "final_evidence_payload": evidence,
                "answer_evidence_payload": selected,
                "retrieved_evidence": detail.get("retrieved_evidence", []),
            }
        )
        invalid_answers = _find_invalid_ragas_answers([row])
        _emit(event_callback, "step_progress", f"ragas_eval prepare: {index}/{len(dataset)}", {
            "step": "ragas_eval",
            "phase": "answer_generation_failed" if invalid_answers else "prepare_dataset",
            "current": index,
            "total": len(dataset),
            "sample_id": sample.get("sample_id", ""),
        })
        if invalid_answers:
            break

    return {
        "status": "pass",
        "dataset_path": str(dataset_path.resolve()),
        "sample_count": len(rows),
        "source_sample_count": len(source_dataset),
        "config": ragas_config,
        "dataset_build_config": {
            "limit": limit,
            "retrieval_config": retrieval_result.get("config", {}),
            "max_contexts": max_contexts,
            "answer_max_contexts": answer_max_contexts,
            "answer_context_compression": compression_strategy,
            "max_context_chars": max_context_chars,
            "max_response_chars": max_response_chars,
            "vector_db_summary": service.get_vector_db_metadata_summary(),
            "evaluation_identity": evaluation_identity(dataset_path),
        },
        "evaluation_identity": evaluation_identity(dataset_path),
        "build_seconds": 0.0,
        "ragas_rows": rows,
        "metadata": metadata,
    }


def _truncate_text(value: Any, limit: Optional[int]) -> str:
    """按 Ragas 配置截断上下文或回答。"""
    text = str(value or "")
    if not limit or len(text) <= limit:
        return text
    return text[: max(0, int(limit) - 3)] + "..."


def _run_ragas(
    prepared: Dict[str, Any],
    ragas_config: Dict[str, Any],
    retrieval_path: Path,
    paths: Dict[str, str],
    embedding_function: Any = None,
    event_callback: Optional[EvaluationEvent] = None,
    cancel_checker: Optional[EvaluationCancel] = None,
) -> Dict[str, Any]:
    """运行已有 Ragas baseline，并把坏例文件和 Markdown 报告落到本次目录。"""
    metric_names = list(ragas_config.get("selected_metrics") or [])
    invalid_answers = _find_invalid_ragas_answers(prepared.get("ragas_rows", []))
    if invalid_answers:
        first = invalid_answers[0]
        preview = str(first.get("response_preview") or first.get("reason") or "answer generation failed")
        result = {
            "status": "failed",
            "status_reason": "answer_generation_failed",
            "error": f"Ragas 回答生成失败，未调用 judge：{preview}",
            "invalid_answer_count": len(invalid_answers),
            "invalid_answer_examples": invalid_answers[:5],
            "active_profile": ragas_config["profile"],
            "judge_profile": ragas_config.get("judge_profile", ""),
            "repeat_count": ragas_config.get("repeat_count", 0),
            "dataset_path": prepared["dataset_path"],
            "sample_count": prepared["sample_count"],
            "source_sample_count": prepared["source_sample_count"],
            "config": prepared["config"],
            "evaluation_identity": prepared["evaluation_identity"],
            "ragas_rows": prepared["ragas_rows"],
            "metadata": prepared["metadata"],
            "metrics": metric_names,
            "score_summary": {},
            "score_records": [],
            "low_score_cases": [],
            "cross_metric_bad_cases": {},
        }
    elif not ragas_config.get("run"):
        result = {
            "status": "dataset_prepared",
            "active_profile": ragas_config["profile"],
            "judge_profile": ragas_config.get("judge_profile", ""),
            "repeat_count": ragas_config.get("repeat_count", 0),
            "dataset_path": prepared["dataset_path"],
            "sample_count": prepared["sample_count"],
            "source_sample_count": prepared["source_sample_count"],
            "config": prepared["config"],
            "evaluation_identity": prepared["evaluation_identity"],
            "ragas_rows": prepared["ragas_rows"],
            "metadata": prepared["metadata"],
            "metrics": metric_names,
            "score_summary": {},
            "score_records": [],
            "low_score_cases": [],
            "cross_metric_bad_cases": {},
        }
    else:
        result = run_repeated_ragas_baseline(
            prepared,
            metric_names=metric_names,
            include_reference_metrics=bool(ragas_config.get("include_reference_metrics", True)),
            timeout=int(ragas_config.get("ragas_timeout", 600)),
            max_workers=int(ragas_config.get("ragas_max_workers", 1)),
            max_retries=int(ragas_config.get("ragas_max_retries", 3)),
            max_wait=int(ragas_config.get("ragas_max_wait", 20)),
            show_progress=False,
            answer_relevancy_strictness=int(ragas_config.get("answer_relevancy_strictness", 1)),
            repeat_count=int(ragas_config.get("repeat_count", 1)),
            judge_profile=str(ragas_config.get("judge_profile") or "standard_single"),
            low_score_threshold=float(ragas_config.get("low_score_threshold", 0.5)),
            embedding_function=embedding_function,
            event_callback=event_callback,
            cancel_checker=cancel_checker,
        )
        result.update(
            {
                "active_profile": ragas_config["profile"],
                "judge_profile": ragas_config.get("judge_profile", ""),
                "repeat_count": ragas_config.get("repeat_count", 1),
                "dataset_path": prepared["dataset_path"],
                "sample_count": prepared["sample_count"],
                "source_sample_count": prepared["source_sample_count"],
                "config": prepared["config"],
                "evaluation_identity": prepared["evaluation_identity"],
                "ragas_rows": prepared["ragas_rows"],
                "metadata": prepared["metadata"],
                "metrics": metric_names,
            }
        )
        if result.get("status") == "ragas_no_valid_scores":
            result.update(
                {
                    "status": "failed",
                    "status_reason": "ragas_judge_no_valid_scores",
                    "error": str(
                        result.get("warning")
                        or "Ragas judge 未产生任何有效数值分数，请检查模型 API、余额和运行结果。"
                    ),
                }
            )

    low_score_cases = _build_low_score_cases(
        result.get("score_records", []),
        prepared["metadata"],
        metric_names,
        float(ragas_config.get("low_score_threshold", 0.5)),
    )
    result["low_score_cases"] = low_score_cases
    result["cross_metric_bad_cases"] = build_cross_metric_bad_cases(
        result,
        str(retrieval_path),
        float(ragas_config.get("low_score_threshold", 0.5)),
        float(ragas_config.get("retrieval_recall_low_threshold", 0.67)),
        float(ragas_config.get("retrieval_mrr_low_threshold", 0.5)),
    )
    _write_json(Path(paths["ragas"]), result)
    _write_json(Path(paths["ragas_low_cases"]), {"cases": low_score_cases})
    _write_json(Path(paths["ragas_cross_cases"]), result["cross_metric_bad_cases"])
    _write_json(Path(paths["ragas_dataset"]), prepared)
    write_markdown_file(Path(paths["ragas_report"]), build_ragas_markdown_report(result))
    return result


def execute_isolated_evaluation(
    *,
    run_id: str,
    ingestion_run_id: str,
    index_version: str,
    dataset_path: Path,
    output_dir: Path,
    service: Any,
    retrieval_options: Optional[Dict[str, Any]],
    ragas_options: Optional[Dict[str, Any]],
    strategy_profile: Optional[Dict[str, Any]] = None,
    steps: Optional[List[str]] = None,
    event_callback: Optional[EvaluationEvent] = None,
    cancel_checker: Optional[EvaluationCancel] = None,
) -> Dict[str, Any]:
    """执行一次与知识源解耦、绑定 staged index 的完整评测流程。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset = load_eval_dataset(dataset_path)
    selected_steps = list(DEFAULT_STEPS if steps is None else steps)
    unknown_steps = sorted(set(selected_steps) - ALLOWED_STEPS)
    if unknown_steps:
        raise ValueError(f"unsupported evaluation step: {unknown_steps[0]}")
    retrieval_config, retrieval_snapshot = _build_retrieval_options(retrieval_options)
    ragas_config = _build_ragas_options(ragas_options)
    paths = _artifact_paths(output_dir)
    sweep_specs = (retrieval_options or {}).get("sweep") if retrieval_options else None
    sweep_max_workers = min(max(int((retrieval_options or {}).get("sweep_max_workers", 1)), 1), 8)
    if sweep_specs is not None:
        if not isinstance(sweep_specs, list) or not sweep_specs or len(sweep_specs) > MAX_SWEEP_CONFIGS:
            raise ValueError(f"retrieval.sweep must contain 1 to {MAX_SWEEP_CONFIGS} configs")
        if "retrieval_sweep" not in selected_steps:
            if "retrieval_eval" in selected_steps:
                selected_steps.insert(selected_steps.index("retrieval_eval") + 1, "retrieval_sweep")
            elif "summary" in selected_steps:
                selected_steps.insert(selected_steps.index("summary"), "retrieval_sweep")
            else:
                selected_steps.append("retrieval_sweep")
        sweep_max_workers = min(sweep_max_workers, len(sweep_specs))
        retrieval_snapshot["sweep"] = sweep_specs
        retrieval_snapshot["sweep_max_workers"] = sweep_max_workers

    config_snapshot = {
        "strategy_profile": dict(strategy_profile or {}),
        "retrieval": retrieval_snapshot,
        "ragas": ragas_config,
        "steps": selected_steps,
    }
    manifest = {
        "schema_version": "r5_evaluation_run_v1",
        "run_id": run_id,
        "ingestion_run_id": ingestion_run_id,
        "index_version": index_version,
        "dataset_identity": evaluation_identity(dataset_path),
        "config_identity": _config_identity(config_snapshot),
        "config": config_snapshot,
        "artifacts": {key: str(Path(value).relative_to(output_dir)) for key, value in paths.items()},
    }
    _write_json(output_dir / "run_manifest.json", manifest)

    step_results: List[Dict[str, Any]] = []
    step_status: Dict[str, str] = {}
    retrieval_result: Dict[str, Any] = {}
    ragas_result: Dict[str, Any] = {}
    started = time.perf_counter()

    def run_step(name: str, action: Callable[[], Dict[str, Any]]) -> None:
        """执行单步骤并记录状态，失败后由依赖关系阻断后续步骤。"""
        _check_cancel(cancel_checker)
        start = time.perf_counter()
        _emit(event_callback, "step_start", f"开始 {name}", {"step": name})
        try:
            result = action()
            result_status = str(result.get("status") or "")
            if result_status == "cancelled":
                status = "cancelled"
            elif result_status in {"failed", "error", "fail"}:
                status = "fail"
            elif result_status in {"partial", "ragas_no_valid_scores", "needs_review"}:
                status = "needs_review"
            else:
                status = "pass"
            step_status[name] = status
            step_results.append({
                "name": name,
                "status": status,
                "seconds": round(time.perf_counter() - start, 3),
                "message": result.get("status", "completed"),
                "result": result,
            })
            if status == "fail":
                _emit(
                    event_callback,
                    "step_error",
                    f"{name} 失败: {result.get('error') or result.get('status_reason') or result_status}",
                    {
                        "step": name,
                        "status": status,
                        "status_reason": result.get("status_reason", ""),
                        "error": result.get("error", ""),
                    },
                )
            else:
                _emit(event_callback, "step_done", f"完成 {name}", {"step": name, "status": status})
        except InterruptedError:
            step_status[name] = "cancelled"
            step_results.append({"name": name, "status": "cancelled", "seconds": round(time.perf_counter() - start, 3), "message": "cancelled", "result": {}})
            raise
        except Exception as exc:
            step_status[name] = "fail"
            step_results.append({"name": name, "status": "fail", "seconds": round(time.perf_counter() - start, 3), "message": str(exc), "result": {}})
            _emit(event_callback, "step_error", f"{name} 失败", {"step": name, "error": str(exc)})

    if "validate_datasets" in selected_steps:
        run_step("validate_datasets", lambda: _validate_dataset_step(dataset_path))

    if "retrieval_eval" in selected_steps and step_status.get("validate_datasets", "pass") == "pass":
        def run_retrieval() -> Dict[str, Any]:
            result = evaluate_retrieval(
                dataset,
                retrieval_config=retrieval_config,
                retrieval_trace_builder=service.build_retrieval_trace,
                vector_summary_provider=service.get_vector_db_metadata_summary,
                event_callback=lambda kind, message, data: _emit(event_callback, kind, message, data),
                cancel_checker=cancel_checker,
            )
            result.update({
                "run_id": run_id,
                "ingestion_run_id": ingestion_run_id,
                "index_version": index_version,
                "evaluation_identity": evaluation_identity(dataset_path),
            })
            _write_json(Path(paths["retrieval"]), result)
            write_markdown_file(Path(paths["retrieval_report"]), build_rag_retrieval_single_markdown_report(result))
            return result

        run_step("retrieval_eval", run_retrieval)
        retrieval_result = step_results[-1].get("result", {})

    if "retrieval_sweep" in selected_steps and step_status.get("validate_datasets", "pass") == "pass":
        def run_sweep() -> Dict[str, Any]:
            result = sweep_retrieval_configs(
                dataset,
                sweep_specs or [],
                retrieval_trace_builder=service.build_retrieval_trace,
                vector_summary_provider=service.get_vector_db_metadata_summary,
                max_workers=sweep_max_workers,
                event_callback=lambda kind, message, data: _emit(event_callback, kind, message, data),
                cancel_checker=cancel_checker,
            )
            result.update({"run_id": run_id, "ingestion_run_id": ingestion_run_id, "index_version": index_version})
            _write_json(Path(paths["retrieval_sweep"]), result)
            write_markdown_file(Path(paths["retrieval_sweep_report"]), build_rag_retrieval_sweep_markdown_report(result))
            return result

        run_step("retrieval_sweep", run_sweep)

    if "ragas_eval" in selected_steps and step_status.get("retrieval_eval") == "pass":
        def run_ragas_step() -> Dict[str, Any]:
            prepared = _build_ragas_prepared_dataset(
                dataset,
                retrieval_result,
                service,
                retrieval_config,
                ragas_config,
                dataset_path,
                cancel_checker,
                event_callback,
            )
            invalid_answers = _find_invalid_ragas_answers(prepared.get("ragas_rows", []))
            return _run_ragas(
                prepared,
                ragas_config,
                Path(paths["retrieval"]),
                paths,
                embedding_function=(
                    service.runtime.embedding
                    if ragas_config.get("run") and not invalid_answers
                    else None
                ),
                event_callback=event_callback,
                cancel_checker=cancel_checker,
            )

        run_step("ragas_eval", run_ragas_step)
        ragas_result = step_results[-1].get("result", {})

    if "trace_export" in selected_steps and step_status.get("retrieval_eval") == "pass" and step_status.get("ragas_eval") == "pass":
        def run_trace() -> Dict[str, Any]:
            return export_trace_bundle({
                "retrieval_result_path": paths["retrieval"],
                "ragas_result_path": paths["ragas"],
                "claim_result_path": str(output_dir / "machine" / "claim_eval_result.json"),
                "ragas_low_cases_path": paths["ragas_low_cases"],
                "ragas_cross_cases_path": paths["ragas_cross_cases"],
                "claim_bad_cases_path": str(output_dir / "machine" / "claim_eval_bad_cases.json"),
                "trace_jsonl_path": paths["trace"],
                "trace_index_path": paths["trace_index"],
                "report_path": paths["trace_report"],
                "context_preview_chars": 240,
                "answer_preview_chars": 360,
                "save_output": True,
                "save_markdown": True,
            })

        run_step("trace_export", run_trace)

    key_metrics = {
        "retrieval_recall_at_k": retrieval_result.get("recall_at_k"),
        "retrieval_mrr": retrieval_result.get("mrr"),
        "retrieval_hit_rate": retrieval_result.get("hit_rate"),
    }
    key_metrics.update({f"ragas_{key}": value for key, value in ragas_result.get("score_summary", {}).items()})
    failed_step = next((item for item in step_results if item["status"] == "fail"), None)
    all_passed = all(item["status"] == "pass" for item in step_results)
    failed_result = failed_step.get("result", {}) if failed_step else {}
    summary = {
        "status": "failed" if failed_step else "pass" if all_passed else "needs_review",
        "status_reason": (
            str(failed_result.get("status_reason") or failed_step.get("message") or "step_failed")
            if failed_step
            else "ok" if all_passed else "step_failed_or_skipped"
        ),
        "error": str(failed_result.get("error") or failed_step.get("message") or "") if failed_step else "",
        "run_id": run_id,
        "run_dir": str(output_dir.resolve()),
        "started_at": "",
        "finished_at": "",
        "seconds": round(time.perf_counter() - started, 3),
        "ingestion_run_id": ingestion_run_id,
        "index_version": index_version,
        "dataset_identity": manifest["dataset_identity"],
        "config_identity": manifest["config_identity"],
        "steps": [{key: value for key, value in step.items() if key != "result"} for step in step_results],
        "key_metrics": key_metrics,
        "threshold_checks": [],
        "artifacts": manifest["artifacts"],
    }
    _write_json(Path(paths["summary"]), summary)
    write_markdown_file(Path(paths["summary_report"]), build_pipeline_summary_markdown_report(summary))
    result = {
        "schema_version": "r5_evaluation_result_v1",
        "run_id": run_id,
        "ingestion_run_id": ingestion_run_id,
        "index_version": index_version,
        "dataset_identity": manifest["dataset_identity"],
        "config_identity": manifest["config_identity"],
        "summary": summary,
        "artifacts": manifest["artifacts"],
    }
    _write_json(output_dir / "result.json", result)
    return result


def _validate_dataset_step(dataset_path: Path) -> Dict[str, Any]:
    """执行通用题集校验步骤。"""
    validation = validate_eval_dataset(dataset_path)
    if validation.get("errors"):
        raise ValueError("; ".join(validation["errors"]))
    validation["dataset_identity"] = evaluation_identity(dataset_path)
    return validation
