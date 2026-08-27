import hashlib
import json
import shutil
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[4]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from Agent.knowledge_base.rag.rag_eval.rag_eval import EVAL_RUN_CONFIG, run_from_code_config as run_retrieval_eval
from Agent.knowledge_base.rag.rag_eval.ragas_eval import (
    RAGAS_RUN_CONFIG,
    preflight_ragas_dependencies,
    run_ragas_eval_from_code_config,
)
from Agent.knowledge_base.rag.rag_config import (
    MACHINE_OUTPUT_DIR,
    RAG_EVAL_DATASET_NAME,
    RAG_EVAL_DATASET_PATH,
    REPORT_OUTPUT_DIR,
    RUNS_DIR,
    RUN_PIPELINE_CONFIG,
)
from Agent.knowledge_base.rag.operation_datasets.dataset_utils import (
    validate_all_datasets,
    write_dataset_validation_outputs,
)
from Agent.knowledge_base.rag.tools.report_utils import build_pipeline_summary_markdown_report, write_markdown_file
from Agent.knowledge_base.rag.rag_eval.trace_export import run_trace_export_from_code_config
from Agent.knowledge_base.rag.rag_eval.contracts import evaluation_identity


# 本地手动运行时优先改 rag_config.py 里的 RUN_PIPELINE_CONFIG。

STEP_OUTPUTS: Dict[str, List[Tuple[str, Path]]] = {
    "validate_datasets": [
        ("dataset_validation", MACHINE_OUTPUT_DIR / "dataset_validation_result.json"),
    ],
    "retrieval_eval": [
        ("retrieval", MACHINE_OUTPUT_DIR / "rag_eval_result.json"),
    ],
    "ragas_eval": [
        ("ragas", MACHINE_OUTPUT_DIR / "ragas_eval_result.json"),
    ],
    "trace_export": [
        ("trace", MACHINE_OUTPUT_DIR / "trace_index.json"),
    ],
}

STEP_DEPENDENCIES: Dict[str, List[str]] = {
    "retrieval_eval": ["validate_datasets"],
    "ragas_eval": ["validate_datasets", "retrieval_eval"],
    "trace_export": ["retrieval_eval", "ragas_eval"],
}

PipelineEventCallback = Callable[[str, str, Dict[str, Any]], None]
PipelineCancelChecker = Callable[[], bool]


class PipelineCancelled(RuntimeError):
    """Raised when a caller requests a cooperative pipeline cancellation."""


def _emit_pipeline_event(
    callback: Optional[PipelineEventCallback],
    event_type: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit a pipeline event if an observer callback is available."""
    if callback is not None:
        callback(event_type, message, data or {})


def _cancel_requested(cancel_checker: Optional[PipelineCancelChecker]) -> bool:
    """Return whether the current pipeline run should stop cooperatively."""
    return bool(cancel_checker and cancel_checker())


def _now_compact() -> str:
    """生成 run id 使用的时间戳。"""
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _now_iso() -> str:
    """生成 summary 使用的 ISO 时间。"""
    return datetime.now().isoformat(timespec="seconds")


def _read_json(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """读取 JSON object；文件不存在时返回 default。"""
    if not path.exists():
        return default or {}
    with path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object.")
    return data


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    """写入 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _file_fingerprint(path: Path) -> Dict[str, Any]:
    """计算文件大小和 sha256，用于记录数据集版本。"""
    if not path.exists():
        return {"exists": False}
    content = path.read_bytes()
    return {
        "exists": True,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _dataset_fingerprints() -> Dict[str, Dict[str, Any]]:
    """记录当前评测数据集的文件指纹。"""
    if not RAG_EVAL_DATASET_PATH:
        return {RAG_EVAL_DATASET_NAME: {"exists": False}}
    return {RAG_EVAL_DATASET_NAME: _file_fingerprint(RAG_EVAL_DATASET_PATH)}


def _is_current_output(path: Path, run_started_epoch: float) -> bool:
    """判断输出文件是否由本次 pipeline 刷新。"""
    return path.exists() and path.stat().st_mtime >= run_started_epoch - 1.0


def _collect_step_output_status(name: str, run_started_epoch: float) -> List[Dict[str, Any]]:
    """汇总单个 step 的预期输出文件状态。"""
    output_status = []
    for source_name, output_path in STEP_OUTPUTS.get(name, []):
        exists = output_path.exists()
        mtime = output_path.stat().st_mtime if exists else None
        output_status.append(
            {
                "source": source_name,
                "path": str(output_path),
                "exists": exists,
                "current": bool(exists and mtime is not None and mtime >= run_started_epoch),
                "mtime": mtime,
            }
        )
    return output_status


def _copy_current_tree_contents(source_dir: Path, target_dir: Path, run_started_epoch: float) -> None:
    """只把本次运行刷新过的 latest 输出复制到当前 run 目录。"""
    if not source_dir.exists():
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    for source_path in source_dir.iterdir():
        target_path = target_dir / source_path.name
        if source_path.is_file() and _is_current_output(source_path, run_started_epoch):
            shutil.copy2(source_path, target_path)


def _snapshot_current_outputs(run_dir: Path, run_started_epoch: float) -> None:
    """保存本次运行实际刷新的 machine / reports 输出，避免复制旧产物。"""
    _copy_current_tree_contents(MACHINE_OUTPUT_DIR, run_dir / "machine", run_started_epoch)
    _copy_current_tree_contents(REPORT_OUTPUT_DIR, run_dir / "reports", run_started_epoch)


def _run_step(name: str, func: Callable[[], Dict[str, Any]], run_started_epoch: float) -> Dict[str, Any]:
    """执行单个 pipeline step，并校验其预期输出是否由本次运行刷新。"""
    started_at = time.perf_counter()
    try:
        result = func()
        status = result.get("status", "pass")
        output_status = _collect_step_output_status(name, run_started_epoch)
        stale_outputs = [item for item in output_status if not item["current"]]
        message = "ok"
        if status not in {"pass", "cancelled"}:
            message = str(result.get("error") or result.get("status_reason") or status)
        if status == "pass" and stale_outputs:
            status = "fail"
            stale_names = ", ".join(item["source"] for item in stale_outputs)
            message = f"missing or stale outputs: {stale_names}"
        return {
            "name": name,
            "status": status,
            "seconds": round(time.perf_counter() - started_at, 3),
            "message": message,
            "output_status": output_status,
            "result": result,
        }
    except Exception as exc:
        return {
            "name": name,
            "status": "fail",
            "seconds": round(time.perf_counter() - started_at, 3),
            "message": repr(exc),
            "output_status": _collect_step_output_status(name, run_started_epoch),
            "result": {},
        }


def _run_step_with_events(
    name: str,
    func: Callable[[], Dict[str, Any]],
    run_started_epoch: float,
    event_callback: Optional[PipelineEventCallback] = None,
    cancel_checker: Optional[PipelineCancelChecker] = None,
) -> Dict[str, Any]:
    """Run one pipeline step with progress, waiting, and cooperative cancel events."""
    if _cancel_requested(cancel_checker):
        _emit_pipeline_event(event_callback, "step_cancelled", f"已取消: {name}", {"step": name})
        return {
            "name": name,
            "status": "cancelled",
            "seconds": 0.0,
            "message": "cancelled before step start",
            "output_status": _collect_step_output_status(name, run_started_epoch),
            "result": {},
        }

    started_at = time.perf_counter()
    stop_waiting = threading.Event()

    def _waiting_loop() -> None:
        waited_seconds = 0
        while not stop_waiting.wait(30):
            waited_seconds += 30
            _emit_pipeline_event(
                event_callback,
                "api_call_waiting",
                f"{name} 已等待 {waited_seconds}s，仍在运行",
                {"step": name, "waited_seconds": waited_seconds},
            )

    _emit_pipeline_event(event_callback, "step_start", f"开始执行: {name}", {"step": name})
    if name in {"retrieval_eval", "ragas_eval"}:
        _emit_pipeline_event(event_callback, "api_call_start", f"正在等待长时间 API 阶段: {name}", {"step": name})
    threading.Thread(target=_waiting_loop, daemon=True, name=f"rag_eval_waiting_{name}").start()

    try:
        result = func()
        status = result.get("status", "pass")
        if status == "cancelled" or _cancel_requested(cancel_checker):
            raise PipelineCancelled(f"cancelled after {name}")
        output_status = _collect_step_output_status(name, run_started_epoch)
        stale_outputs = [item for item in output_status if not item["current"]]
        message = "ok"
        if status == "pass" and stale_outputs:
            status = "fail"
            stale_names = ", ".join(item["source"] for item in stale_outputs)
            message = f"missing or stale outputs: {stale_names}"
        step_result = {
            "name": name,
            "status": status,
            "seconds": round(time.perf_counter() - started_at, 3),
            "message": message,
            "output_status": output_status,
            "result": result,
        }
        if name in {"retrieval_eval", "ragas_eval"}:
            _emit_pipeline_event(
                event_callback,
                "api_call_done",
                f"长时间 API 阶段完成: {name}",
                {"step": name, "seconds": step_result["seconds"], "status": status},
            )
        _emit_pipeline_event(
            event_callback,
            "step_done",
            f"完成: {name} (耗时 {step_result['seconds']}s, 状态={status})",
            {"step": name, "status": status, "seconds": step_result["seconds"]},
        )
        return step_result
    except PipelineCancelled as exc:
        step_result = {
            "name": name,
            "status": "cancelled",
            "seconds": round(time.perf_counter() - started_at, 3),
            "message": str(exc),
            "output_status": _collect_step_output_status(name, run_started_epoch),
            "result": {},
        }
        _emit_pipeline_event(
            event_callback,
            "step_cancelled",
            f"已取消: {name} (耗时 {step_result['seconds']}s)",
            {"step": name, "seconds": step_result["seconds"]},
        )
        return step_result
    except Exception as exc:
        step_result = {
            "name": name,
            "status": "fail",
            "seconds": round(time.perf_counter() - started_at, 3),
            "message": repr(exc),
            "output_status": _collect_step_output_status(name, run_started_epoch),
            "result": {},
        }
        _emit_pipeline_event(
            event_callback,
            "step_error",
            f"失败: {name} - {exc!r}",
            {"step": name, "error": repr(exc), "seconds": step_result["seconds"]},
        )
        return step_result
    finally:
        stop_waiting.set()


def _skip_step(name: str, blocked_dependencies: List[str]) -> Dict[str, Any]:
    """生成依赖失败时的跳过 step 结果。"""
    return {
        "name": name,
        "status": "skipped",
        "seconds": 0.0,
        "message": f"skipped because dependency failed: {', '.join(blocked_dependencies)}",
        "output_status": [],
        "result": {},
    }


def _run_ragas_dependency_preflight(
    event_callback: Optional[PipelineEventCallback],
    run_started_epoch: float,
) -> Optional[Dict[str, Any]]:
    """在 Ragas judge 前检查导入依赖，失败时返回 step 失败结果。"""
    started_at = time.perf_counter()
    _emit_pipeline_event(
        event_callback,
        "dependency_check_start",
        "正在检查 Ragas / LangChain 依赖",
        {"step": "ragas_eval"},
    )
    try:
        result = preflight_ragas_dependencies()
        _emit_pipeline_event(
            event_callback,
            "dependency_check_done",
            f"Ragas 依赖检查通过: ragas={result.get('ragas_version', 'unknown')}",
            {"step": "ragas_eval", **result},
        )
        return None
    except Exception as exc:
        elapsed = round(time.perf_counter() - started_at, 3)
        message = repr(exc)
        event_type = "dependency_check_failed"
        if "langchain_community.chat_models.vertexai" in message:
            event_type = "dependency_compat_failed"
        _emit_pipeline_event(
            event_callback,
            event_type,
            f"Ragas 依赖检查失败: {message}",
            {
                "step": "ragas_eval",
                "error": message,
                "seconds": elapsed,
                "traceback": traceback.format_exc(),
            },
        )
        return {
            "name": "ragas_eval",
            "status": "fail",
            "seconds": elapsed,
            "message": message,
            "output_status": _collect_step_output_status("ragas_eval", run_started_epoch),
            "result": {},
        }


def _validate_datasets_step() -> Dict[str, Any]:
    """运行数据集校验并写入最新输出。"""
    result = validate_all_datasets()
    write_dataset_validation_outputs(result)
    return result


def _load_current_metric_sources(
    step_results: List[Dict[str, Any]],
    run_started_epoch: float,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """只读取本次 pipeline 刷新且对应 step 通过的核心评测结果。"""
    steps_by_name = {step.get("name", ""): step for step in step_results}
    sources: Dict[str, Dict[str, Any]] = {
        "retrieval": {},
        "ragas": {},
        "trace": {},
        "dataset_validation": {},
    }
    source_status: Dict[str, Dict[str, Any]] = {}
    for step_name, output_items in STEP_OUTPUTS.items():
        step = steps_by_name.get(step_name, {})
        step_passed = step.get("status") == "pass"
        for source_name, output_path in output_items:
            current = _is_current_output(output_path, run_started_epoch)
            used = bool(step_passed and current)
            source_status[source_name] = {
                "step": step_name,
                "path": str(output_path),
                "step_status": step.get("status", "missing"),
                "current": current,
                "used": used,
            }
            if used:
                sources[source_name] = _read_json(output_path)
    return sources, source_status


def _extract_key_metrics(sources: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """从各 eval 输出中抽取 summary 需要展示的核心指标。"""
    retrieval = sources.get("retrieval", {})
    ragas = sources.get("ragas", {})
    trace = sources.get("trace", {})
    ragas_scores = ragas.get("score_summary", {})
    metrics = {
        "retrieval_recall_at_k": retrieval.get("recall_at_k"),
        "retrieval_mrr": retrieval.get("mrr"),
        "retrieval_hit_rate": retrieval.get("hit_rate"),
        "ragas_faithfulness": ragas_scores.get("faithfulness"),
        "ragas_answer_relevancy": ragas_scores.get("answer_relevancy"),
        "ragas_context_utilization": ragas_scores.get("context_utilization"),
        "ragas_context_recall": ragas_scores.get("context_recall"),
    }
    if trace:
        metrics["bad_case_trace_count"] = trace.get("bad_case_trace_count")
    return metrics


def _check_min(name: str, actual: Any, threshold: float) -> Dict[str, Any]:
    """执行 min 类型阈值检查。"""
    if actual is None:
        return {"name": name, "status": "missing", "actual": None, "threshold": threshold}
    return {"name": name, "status": "pass" if actual >= threshold else "fail", "actual": actual, "threshold": threshold}


def _check_max(name: str, actual: Any, threshold: float) -> Dict[str, Any]:
    """执行 max 类型阈值检查。"""
    if actual is None:
        return {"name": name, "status": "missing", "actual": None, "threshold": threshold}
    return {"name": name, "status": "pass" if actual <= threshold else "fail", "actual": actual, "threshold": threshold}


def _build_threshold_checks(metrics: Dict[str, Any], thresholds: Dict[str, float]) -> List[Dict[str, Any]]:
    """根据当前配置生成回归阈值检查结果。"""
    check_specs = {
        "retrieval_hit_rate_min": ("min", "retrieval_hit_rate"),
        "retrieval_recall_at_k_min": ("min", "retrieval_recall_at_k"),
        "ragas_faithfulness_min": ("min", "ragas_faithfulness"),
    }
    checks = []
    for threshold_name, threshold in thresholds.items():
        spec = check_specs.get(threshold_name)
        if spec is None:
            continue
        check_type, metric_name = spec
        if check_type == "max":
            checks.append(_check_max(threshold_name, metrics.get(metric_name), threshold))
        else:
            checks.append(_check_min(threshold_name, metrics.get(metric_name), threshold))
    return checks

def _pipeline_status(step_results: List[Dict[str, Any]], threshold_checks: List[Dict[str, Any]]) -> str:
    """根据步骤状态和阈值检查生成总状态。"""
    if any(step["status"] == "cancelled" for step in step_results):
        return "cancelled"
    if any(step["status"] in {"fail", "skipped"} for step in step_results):
        return "fail"
    if any(check["status"] == "fail" for check in threshold_checks):
        return "fail"
    if any(check["status"] == "missing" for check in threshold_checks):
        return "needs_review"
    return "pass"


def _pipeline_status_reason(step_results: List[Dict[str, Any]], threshold_checks: List[Dict[str, Any]]) -> str:
    """说明总状态的触发原因，避免把阈值未达标误读为执行异常。"""
    if any(step["status"] == "cancelled" for step in step_results):
        return "cancelled"
    if any(step["status"] in {"fail", "skipped"} for step in step_results):
        return "step_failed"
    if any(check["status"] == "fail" for check in threshold_checks):
        return "threshold_failed"
    if any(check["status"] == "missing" for check in threshold_checks):
        return "threshold_missing"
    return "ok"


def _build_config_snapshot() -> Dict[str, Any]:
    """保存本次运行的关键配置快照。"""
    dataset_path = RUN_PIPELINE_CONFIG.get("dataset_path") or EVAL_RUN_CONFIG.get("dataset_path")
    if not dataset_path:
        dataset_path = RAGAS_RUN_CONFIG.get("dataset_path", "")
    return {
        "pipeline": RUN_PIPELINE_CONFIG,
        "retrieval_eval": EVAL_RUN_CONFIG,
        "ragas_eval": RAGAS_RUN_CONFIG,
        "evaluation_identity": evaluation_identity(dataset_path) if dataset_path else {},
    }


def run_pipeline_from_code_config(
    run_id: Optional[str] = None,
    event_callback: Optional[PipelineEventCallback] = None,
    cancel_checker: Optional[PipelineCancelChecker] = None,
) -> Dict[str, Any]:
    """根据 RUN_PIPELINE_CONFIG 运行 RAG 评测流水线并保存 run 目录。"""
    started_at = _now_iso()
    run_started_epoch = time.time()
    run_id = run_id or f"{_now_compact()}_{RUN_PIPELINE_CONFIG['run_name']}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    available_steps: Dict[str, Callable[[], Dict[str, Any]]] = {
        "validate_datasets": _validate_datasets_step,
        "retrieval_eval": lambda: run_retrieval_eval(
            **{
                key: value
                for key, value in {
                    "event_callback": event_callback,
                    "cancel_checker": cancel_checker,
                }.items()
                if value is not None
            }
        ),
        "ragas_eval": lambda: run_ragas_eval_from_code_config(
            **{
                key: value
                for key, value in {
                    "event_callback": event_callback,
                    "cancel_checker": cancel_checker,
                }.items()
                if value is not None
            }
        ),
        "trace_export": run_trace_export_from_code_config,
    }

    step_results = []
    step_results_by_name: Dict[str, Dict[str, Any]] = {}
    for step_name in RUN_PIPELINE_CONFIG["steps"]:
        if step_name == "summary":
            continue
        if _cancel_requested(cancel_checker):
            step_result = {
                "name": step_name,
                "status": "cancelled",
                "seconds": 0.0,
                "message": "cancelled before step start",
                "output_status": [],
                "result": {},
            }
            _emit_pipeline_event(event_callback, "step_cancelled", f"已取消: {step_name}", {"step": step_name})
            step_results.append(step_result)
            step_results_by_name[step_name] = step_result
            break
        step_func = available_steps.get(step_name)
        if step_func is None:
            step_result = {
                "name": step_name,
                "status": "fail",
                "seconds": 0.0,
                "message": f"unknown step: {step_name}",
                "output_status": [],
                "result": {},
            }
        else:
            blocked_dependencies = [
                dependency
                for dependency in STEP_DEPENDENCIES.get(step_name, [])
                if step_results_by_name.get(dependency, {}).get("status") != "pass"
            ]
            if blocked_dependencies:
                step_result = _skip_step(step_name, blocked_dependencies)
                _emit_pipeline_event(
                    event_callback,
                    "step_skipped",
                    f"跳过: {step_name}，依赖失败: {', '.join(blocked_dependencies)}",
                    {"step": step_name, "blocked_dependencies": blocked_dependencies},
                )
            else:
                preflight_failure = (
                    _run_ragas_dependency_preflight(event_callback, run_started_epoch)
                    if step_name == "ragas_eval"
                    else None
                )
                step_result = preflight_failure or _run_step_with_events(
                    step_name,
                    step_func,
                    run_started_epoch,
                    event_callback=event_callback,
                    cancel_checker=cancel_checker,
                )
        step_results.append(step_result)
        step_results_by_name[step_name] = step_result
        if step_result.get("status") == "cancelled":
            break

    sources, metric_source_status = _load_current_metric_sources(step_results, run_started_epoch)
    key_metrics = _extract_key_metrics(sources)
    threshold_checks = _build_threshold_checks(key_metrics, RUN_PIPELINE_CONFIG["thresholds"])
    status = _pipeline_status(step_results, threshold_checks)
    status_reason = _pipeline_status_reason(step_results, threshold_checks)

    summary = {
        "status": status,
        "status_reason": status_reason,
        "run_id": run_id,
        "run_dir": str(run_dir.resolve()),
        "started_at": started_at,
        "finished_at": _now_iso(),
        "steps": [
            {key: value for key, value in step.items() if key != "result"}
            for step in step_results
        ],
        "key_metrics": key_metrics,
        "metric_sources": metric_source_status,
        "threshold_checks": threshold_checks,
        "dataset_fingerprints": _dataset_fingerprints(),
    }

    _write_json(run_dir / "config_snapshot.json", _build_config_snapshot())
    _write_json(run_dir / "summary.json", summary)
    _write_json(MACHINE_OUTPUT_DIR / "summary.json", summary)
    write_markdown_file(run_dir / "summary.md", build_pipeline_summary_markdown_report(summary))
    write_markdown_file(REPORT_OUTPUT_DIR / "summary.md", build_pipeline_summary_markdown_report(summary))

    if RUN_PIPELINE_CONFIG.get("copy_latest_outputs_to_run_dir"):
        _snapshot_current_outputs(run_dir, run_started_epoch)
    return summary
