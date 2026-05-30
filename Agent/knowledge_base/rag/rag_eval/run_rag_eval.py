import hashlib
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[4]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from Agent.knowledge_base.rag.rag_eval.claim_eval import CLAIM_EVAL_CONFIG, run_claim_eval_from_code_config
from Agent.knowledge_base.rag.rag_eval.rag_eval import EVAL_RUN_CONFIG, run_from_code_config as run_retrieval_eval
from Agent.knowledge_base.rag.rag_eval.ragas_eval import RAGAS_RUN_CONFIG, run_ragas_eval_from_code_config
from Agent.knowledge_base.rag.rag_config import (
    MACHINE_OUTPUT_DIR,
    REPORT_OUTPUT_DIR,
    RUNS_DIR,
    RUN_PIPELINE_CONFIG,
)
from Agent.knowledge_base.rag.operation_datasets.dataset_utils import (
    DATASET_FILES,
    validate_all_datasets,
    write_dataset_validation_outputs,
)
from Agent.knowledge_base.rag.tools.report_utils import build_pipeline_summary_markdown_report, write_markdown_file
from Agent.knowledge_base.rag.rag_eval.trace_export import run_trace_export_from_code_config


# 本地手动运行时优先改 rag_config.py 里的 RUN_PIPELINE_CONFIG。


def _now_compact() -> str:
    """生成 run id 使用的时间戳。"""
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


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
    return {dataset_name: _file_fingerprint(path) for dataset_name, path in DATASET_FILES.items()}


def _copy_tree_contents(source_dir: Path, target_dir: Path) -> None:
    """把 latest 输出复制到当前 run 目录。"""
    if not source_dir.exists():
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    for source_path in source_dir.iterdir():
        target_path = target_dir / source_path.name
        if source_path.is_file():
            shutil.copy2(source_path, target_path)


def _snapshot_latest_outputs(run_dir: Path) -> None:
    """保存本次运行后的 latest machine / reports 输出。"""
    _copy_tree_contents(MACHINE_OUTPUT_DIR, run_dir / "machine")
    _copy_tree_contents(REPORT_OUTPUT_DIR, run_dir / "reports")


def _run_step(name: str, func: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    """执行单个 pipeline step，并把异常转成结构化结果。"""
    started_at = time.perf_counter()
    try:
        result = func()
        status = result.get("status", "pass")
        return {
            "name": name,
            "status": status,
            "seconds": round(time.perf_counter() - started_at, 3),
            "message": "ok",
            "result": result,
        }
    except Exception as exc:
        return {
            "name": name,
            "status": "fail",
            "seconds": round(time.perf_counter() - started_at, 3),
            "message": repr(exc),
            "result": {},
        }


def _validate_datasets_step() -> Dict[str, Any]:
    """运行数据集校验并写入最新输出。"""
    result = validate_all_datasets()
    write_dataset_validation_outputs(result)
    return result


def _load_latest_metric_sources() -> Dict[str, Dict[str, Any]]:
    """读取 latest 输出中的核心评测结果。"""
    return {
        "retrieval": _read_json(MACHINE_OUTPUT_DIR / "rag_eval_result.json"),
        "ragas": _read_json(MACHINE_OUTPUT_DIR / "ragas_eval_result.json"),
        "claim": _read_json(MACHINE_OUTPUT_DIR / "claim_eval_result.json"),
        "trace": _read_json(MACHINE_OUTPUT_DIR / "trace_index.json"),
        "dataset_validation": _read_json(MACHINE_OUTPUT_DIR / "dataset_validation_result.json"),
    }


def _extract_key_metrics(sources: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """从各 eval 输出中抽取 summary 需要展示的核心指标。"""
    retrieval = sources.get("retrieval", {})
    ragas = sources.get("ragas", {})
    claim = sources.get("claim", {})
    trace = sources.get("trace", {})
    claim_scores = claim.get("score_summary", {})
    ragas_scores = ragas.get("score_summary", {})
    return {
        "retrieval_recall_at_k": retrieval.get("recall_at_k"),
        "retrieval_mrr": retrieval.get("mrr"),
        "retrieval_hit_rate": retrieval.get("hit_rate"),
        "ragas_faithfulness": ragas_scores.get("faithfulness"),
        "ragas_answer_relevancy": ragas_scores.get("answer_relevancy"),
        "ragas_context_utilization": ragas_scores.get("context_utilization"),
        "ragas_context_recall": ragas_scores.get("context_recall"),
        "claim_coverage": claim_scores.get("claim_coverage"),
        "evidence_support_rate": claim_scores.get("evidence_support_rate"),
        "unsupported_answer_claim_count": claim_scores.get("unsupported_answer_claim_count"),
        "judge_failed_count": claim.get("judge_failed_count"),
        "bad_case_trace_count": trace.get("bad_case_trace_count"),
    }


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
    return [
        _check_min("retrieval_hit_rate_min", metrics.get("retrieval_hit_rate"), thresholds["retrieval_hit_rate_min"]),
        _check_min(
            "retrieval_recall_at_k_min",
            metrics.get("retrieval_recall_at_k"),
            thresholds["retrieval_recall_at_k_min"],
        ),
        _check_min("ragas_faithfulness_min", metrics.get("ragas_faithfulness"), thresholds["ragas_faithfulness_min"]),
        _check_min("claim_coverage_min", metrics.get("claim_coverage"), thresholds["claim_coverage_min"]),
        _check_min(
            "evidence_support_rate_min",
            metrics.get("evidence_support_rate"),
            thresholds["evidence_support_rate_min"],
        ),
        _check_max("judge_failed_count_max", metrics.get("judge_failed_count"), thresholds["judge_failed_count_max"]),
    ]


def _pipeline_status(step_results: List[Dict[str, Any]], threshold_checks: List[Dict[str, Any]]) -> str:
    """根据步骤状态和阈值检查生成总状态。"""
    if any(step["status"] == "fail" for step in step_results):
        return "fail"
    if any(check["status"] == "fail" for check in threshold_checks):
        return "fail"
    if any(check["status"] == "missing" for check in threshold_checks):
        return "needs_review"
    return "pass"


def _build_config_snapshot() -> Dict[str, Any]:
    """保存本次运行的关键配置快照。"""
    return {
        "pipeline": RUN_PIPELINE_CONFIG,
        "retrieval_eval": EVAL_RUN_CONFIG,
        "ragas_eval": {
            key: value
            for key, value in RAGAS_RUN_CONFIG.items()
            if key not in {"print_full_output"}
        },
        "claim_eval": CLAIM_EVAL_CONFIG,
    }


def run_pipeline_from_code_config() -> Dict[str, Any]:
    """根据 RUN_PIPELINE_CONFIG 运行 RAG 评测流水线并保存 run 目录。"""
    started_at = _now_iso()
    run_id = f"{_now_compact()}_{RUN_PIPELINE_CONFIG['run_name']}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    available_steps: Dict[str, Callable[[], Dict[str, Any]]] = {
        "validate_datasets": _validate_datasets_step,
        "retrieval_eval": run_retrieval_eval,
        "ragas_eval": run_ragas_eval_from_code_config,
        "claim_eval": run_claim_eval_from_code_config,
        "trace_export": run_trace_export_from_code_config,
    }

    step_results = []
    for step_name in RUN_PIPELINE_CONFIG["steps"]:
        if step_name == "summary":
            continue
        step_func = available_steps.get(step_name)
        if step_func is None:
            step_results.append(
                {
                    "name": step_name,
                    "status": "fail",
                    "seconds": 0.0,
                    "message": f"unknown step: {step_name}",
                    "result": {},
                }
            )
            continue
        step_results.append(_run_step(step_name, step_func))

    sources = _load_latest_metric_sources()
    key_metrics = _extract_key_metrics(sources)
    threshold_checks = _build_threshold_checks(key_metrics, RUN_PIPELINE_CONFIG["thresholds"])
    status = _pipeline_status(step_results, threshold_checks)

    summary = {
        "status": status,
        "run_id": run_id,
        "run_dir": str(run_dir.resolve()),
        "started_at": started_at,
        "finished_at": _now_iso(),
        "steps": [
            {key: value for key, value in step.items() if key != "result"}
            for step in step_results
        ],
        "key_metrics": key_metrics,
        "threshold_checks": threshold_checks,
        "dataset_fingerprints": _dataset_fingerprints(),
    }

    _write_json(run_dir / "config_snapshot.json", _build_config_snapshot())
    _write_json(run_dir / "summary.json", summary)
    write_markdown_file(run_dir / "summary.md", build_pipeline_summary_markdown_report(summary))
    write_markdown_file(REPORT_OUTPUT_DIR / "summary.md", build_pipeline_summary_markdown_report(summary))

    if RUN_PIPELINE_CONFIG.get("copy_latest_outputs_to_run_dir"):
        _snapshot_latest_outputs(run_dir)
    return summary


if __name__ == "__main__":
    pipeline_summary = run_pipeline_from_code_config()
    if RUN_PIPELINE_CONFIG.get("print_full_output"):
        print(json.dumps(pipeline_summary, ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "status": pipeline_summary.get("status"),
                    "run_id": pipeline_summary.get("run_id"),
                    "run_dir": pipeline_summary.get("run_dir"),
                    "key_metrics": pipeline_summary.get("key_metrics"),
                    "threshold_checks": pipeline_summary.get("threshold_checks"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

