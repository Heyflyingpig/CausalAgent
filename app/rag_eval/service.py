"""
RAG评测服务层 —— 封装配置读写、pipeline触发、SSE进度推送和结果查询。

该模块不重复实现评测逻辑，只桥接 Agent/knowledge_base/rag 中已有的评测模块。
"""
import json
import copy
import os
import queue
import re
import shutil
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from Agent.knowledge_base.rag.rag_config import (
    MACHINE_OUTPUT_DIR,
    RAG_EVAL_DATASET_NAME,
    RAG_EVAL_DATASET_PATH,
    REPORT_OUTPUT_DIR,
    RUNS_DIR,
    RETRIEVAL_PROFILES,
    VISIBLE_RETRIEVAL_PROFILES,
    VISIBLE_RETRIEVAL_PROFILE_LIMITS,
    RETRIEVAL_EVAL_CONFIG,
    RAGAS_RUN_CONFIG,
    RAGAS_RUN_PROFILES,
    RAGAS_ACTIVE_PROFILE,
    VISIBLE_RAGAS_PROFILES,
    RAGAS_BASE_CONFIG,
    RUN_PIPELINE_CONFIG,
)
from Agent.knowledge_base.rag.rag_eval.contracts import evaluation_identity, load_eval_dataset
from Agent.knowledge_base.embedding_runtime import resolve_embedding_runtime_config
from Agent.knowledge_base.rag.rag_eval.run_rag_eval import run_pipeline_from_code_config
from Agent.knowledge_base.query_rag import (
    PRODUCTION_RAG_CONFIG_PATH,
    RagRetrievalConfig,
    get_production_rag_config_status,
)
from app.rag_eval.profile_store import list_strategy_profiles
from config.settings import settings

CLAIM_BAD_CASE_SOURCES = {"claim_eval_bad_case"}


# 评测工作台只允许修改这组公开参数；allowed 是硬边界，recommended 只用于提示复核。
RAG_EVAL_PARAMETER_META: Dict[str, Dict[str, Any]] = {
    "dense_fetch_k": {"label": "稠密检索候选数", "meaning": "稠密向量检索阶段先召回的候选 chunk 数。", "allowed": [1, 200], "recommended": [10, 80], "integer": True},
    "dense_mmr_k": {"label": "稠密 MMR 保留数", "meaning": "稠密候选经过 MMR 去重后保留的数量。", "allowed": [1, 100], "recommended": [5, 30], "integer": True},
    "sparse_fetch_k": {"label": "稀疏检索候选数", "meaning": "关键词/稀疏检索阶段先召回的候选 chunk 数。", "allowed": [0, 200], "recommended": [5, 50], "integer": True},
    "final_top_k": {"label": "最终证据数", "meaning": "最终送入回答或评测的证据数量。", "allowed": [1, 20], "recommended": [3, 8], "integer": True},
    "dense_score_threshold": {"label": "稠密分数阈值", "meaning": "稠密检索候选的最低分数阈值。", "allowed": [0, 1], "recommended": [0.3, 0.7]},
    "final_rerank_threshold": {"label": "最终重排阈值", "meaning": "融合重排后进入最终证据的最低分数阈值。", "allowed": [0, 1], "recommended": [0, 0.4]},
    "mmr_lambda": {"label": "MMR 相关性权重", "meaning": "MMR 中相关性相对多样性的权重。", "allowed": [0, 1], "recommended": [0.5, 0.85]},
    "limit": {"label": "样本数上限", "meaning": "本次评测最多处理的样本数；null 表示不截断。", "allowed": [1, 1000], "recommended": [30, 100], "integer": True, "allow_null": True},
    "max_contexts": {"label": "最大上下文数", "meaning": "构造 Ragas 样本时最多送入的上下文段数。", "allowed": [1, 12], "recommended": [4, 8], "integer": True},
    "max_context_chars": {"label": "单段上下文最大字符数", "meaning": "单段上下文送入 Ragas 的最大字符数。", "allowed": [300, 4000], "recommended": [1200, 2000], "integer": True},
    "max_response_chars": {"label": "回答最大字符数", "meaning": "送入 Ragas 的回答最大字符数。", "allowed": [200, 3000], "recommended": [800, 1500], "integer": True},
    "ragas_timeout": {"label": "Ragas 超时时间", "meaning": "单个 Ragas 任务允许等待的最长时间，单位秒。", "allowed": [60, 3600], "recommended": [300, 900], "integer": True},
    "ragas_max_workers": {"label": "Ragas 最大并发数", "meaning": "Ragas judge 并发 worker 数。", "allowed": [1, 16], "recommended": [1, 8], "integer": True},
    "ragas_max_retries": {"label": "Ragas 最大重试次数", "meaning": "Ragas 单任务失败后的最大重试次数。", "allowed": [0, 10], "recommended": [2, 5], "integer": True},
    "ragas_max_wait": {"label": "Ragas 最长重试等待", "meaning": "Ragas 重试退避的最长等待时间，单位秒。", "allowed": [1, 300], "recommended": [10, 60], "integer": True},
    "repeat_count": {"label": "重复评测次数", "meaning": "同一配置重复评测次数。", "allowed": [1, 10], "recommended": [1, 3], "integer": True},
    "low_score_threshold": {"label": "低分坏例阈值", "meaning": "Ragas 分数低于该值时标记为低分坏例。", "allowed": [0, 1], "recommended": [0.4, 0.7]},
    "retrieval_recall_low_threshold": {"label": "检索召回低分阈值", "meaning": "跨指标坏例中判断检索召回偏低的阈值。", "allowed": [0, 1], "recommended": [0.5, 0.8]},
    "retrieval_mrr_low_threshold": {"label": "检索 MRR 低分阈值", "meaning": "跨指标坏例中判断检索排序偏低的阈值。", "allowed": [0, 1], "recommended": [0.3, 0.7]},
}


class ConfigValidationError(ValueError):
    """评测配置不满足工作台硬边界时抛出的可识别错误。"""


def _validate_config_value(path: str, value: Any, key: str) -> None:
    """校验一个公开数值参数，拒绝类型错误和超出硬边界的值。"""
    meta = RAG_EVAL_PARAMETER_META.get(key)
    if not meta:
        return
    if value is None and meta.get("allow_null"):
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigValidationError(f"{path} 必须是数字" + ("或 null" if meta.get("allow_null") else ""))
    if meta.get("integer") and not isinstance(value, int):
        raise ConfigValidationError(f"{path} 必须是整数")
    lower, upper = meta["allowed"]
    if value < lower or value > upper:
        raise ConfigValidationError(f"{path} 超出允许范围 [{lower}, {upper}]")


def get_rag_eval_status() -> Dict[str, Any]:
    """返回通用题集、Runtime 向量库和最新评测结果的汇总状态。"""
    latest_summary = _load_latest_summary()
    vector_db_info = _get_vector_db_info()
    model_info = _get_model_runtime_info()
    benchmark_info = {
        "name": RAG_EVAL_DATASET_NAME,
        "dataset_path": str(RAG_EVAL_DATASET_PATH.resolve()) if RAG_EVAL_DATASET_PATH else "",
        "dataset_exists": bool(RAG_EVAL_DATASET_PATH and RAG_EVAL_DATASET_PATH.is_file()),
        "sample_count": _get_benchmark_sample_count(),
    }
    benchmark_info.update(_get_evaluation_identity_status())
    return {
        "benchmark": benchmark_info,
        "vector_db": vector_db_info,
        "models": model_info,
        "latest_run": latest_summary,
        "last_updated": datetime.now().isoformat(timespec="seconds"),
    }


def get_rag_eval_config() -> Dict[str, Any]:
    """返回所有可调参数，按类别分组。"""
    retrieval_fields = set(RagRetrievalConfig.__dataclass_fields__)
    visible_retrieval_profiles = [
        name for name in VISIBLE_RETRIEVAL_PROFILES
        if name in RETRIEVAL_PROFILES
    ] or list(RETRIEVAL_PROFILES.keys())
    visible_ragas_profiles = [
        name for name in VISIBLE_RAGAS_PROFILES
        if name in RAGAS_RUN_PROFILES
    ] or list(RAGAS_RUN_PROFILES.keys())
    return {
        "strategy_profiles": list_strategy_profiles(),
        "retrieval_profiles": {
            name: {key: value for key, value in cfg.items() if key in retrieval_fields}
            for name, cfg in RETRIEVAL_PROFILES.items()
            if name in visible_retrieval_profiles
        },
        "retrieval_profile_limits": {
            name: VISIBLE_RETRIEVAL_PROFILE_LIMITS.get(name)
            for name in visible_retrieval_profiles
        },
        "active_retrieval_profile": RETRIEVAL_EVAL_CONFIG.get("retrieval_profile", "active_current"),
        "retrieval_current": {
            key: value
            for key, value in RETRIEVAL_PROFILES.get(
                RETRIEVAL_EVAL_CONFIG.get("retrieval_profile", "active_current"),
                {},
            ).items()
            if key in retrieval_fields
        },
        "retrieval_eval": {
            "mode": RETRIEVAL_EVAL_CONFIG.get("mode", "single"),
            "limit": RETRIEVAL_EVAL_CONFIG.get("limit"),
            "save_output": RETRIEVAL_EVAL_CONFIG.get("save_output", True),
            "save_markdown": RETRIEVAL_EVAL_CONFIG.get("save_markdown", True),
        },
        "ragas": {
            "active_profile": RAGAS_RUN_CONFIG.get("active_profile", RAGAS_ACTIVE_PROFILE),
            "available_profiles": visible_ragas_profiles,
            "profiles": {
                name: dict(RAGAS_RUN_PROFILES[name])
                for name in visible_ragas_profiles
            },
            "limit": RAGAS_RUN_CONFIG.get("limit"),
            "selected_metrics": RAGAS_RUN_CONFIG.get("selected_metrics", []),
            "max_contexts": RAGAS_RUN_CONFIG.get("max_contexts", 5),
            "max_context_chars": RAGAS_RUN_CONFIG.get("max_context_chars", 1200),
            "max_response_chars": RAGAS_RUN_CONFIG.get("max_response_chars", 900),
            "ragas_timeout": RAGAS_RUN_CONFIG.get("ragas_timeout", 600),
            "ragas_max_workers": RAGAS_RUN_CONFIG.get("ragas_max_workers", 1),
            "ragas_max_retries": RAGAS_RUN_CONFIG.get("ragas_max_retries", 3),
            "ragas_max_wait": RAGAS_RUN_CONFIG.get("ragas_max_wait", 20),
            "answer_relevancy_strictness": RAGAS_RUN_CONFIG.get("answer_relevancy_strictness", 1),
            "repeat_count": RAGAS_RUN_CONFIG.get("repeat_count", 1),
            "low_score_threshold": RAGAS_RUN_CONFIG.get("low_score_threshold", 0.5),
            "retrieval_recall_low_threshold": RAGAS_RUN_CONFIG.get("retrieval_recall_low_threshold", 0.67),
            "retrieval_mrr_low_threshold": RAGAS_RUN_CONFIG.get("retrieval_mrr_low_threshold", 0.5),
            "run_ragas": RAGAS_RUN_CONFIG.get("run_ragas", True),
            "include_reference_metrics": RAGAS_RUN_CONFIG.get("include_reference_metrics", True),
        },
        "parameter_meta": copy.deepcopy(RAG_EVAL_PARAMETER_META),
        "pipeline": {
            "steps": RUN_PIPELINE_CONFIG.get("steps", []),
            "run_name": RUN_PIPELINE_CONFIG.get("run_name", "active_benchmark_full_pipeline"),
            "thresholds": RUN_PIPELINE_CONFIG.get("thresholds", {}),
            "copy_latest_outputs_to_run_dir": RUN_PIPELINE_CONFIG.get("copy_latest_outputs_to_run_dir", True),
        },
        "evaluation": _get_evaluation_identity_status(),
    }


def get_production_rag_config() -> Dict[str, Any]:
    """返回正式 RAG 调用当前使用的检索配置。"""
    status = get_production_rag_config_status()
    path = Path(status.get("path") or PRODUCTION_RAG_CONFIG_PATH)
    payload = _load_json_safe(path)
    return {
        **status,
        "metadata": payload.get("metadata", {}),
        "exists": path.exists(),
    }


def publish_current_config_to_production(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把当前评测链路验证过的检索参数发布给正式 RAG 调用。"""
    payload = payload or {}
    config_overrides = payload.get("config_overrides") if isinstance(payload.get("config_overrides"), dict) else {}
    retrieval_config = (
        _retrieval_config_from_overrides(config_overrides)
        if config_overrides
        else _current_eval_retrieval_config()
    )
    source_run_id = str(payload.get("source_run_id") or "").strip()
    note = str(payload.get("note") or "").strip()
    published_payload = {
        "version": 1,
        "retrieval_config": retrieval_config.to_dict(),
        "metadata": {
            "published_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "source": "rag_eval_workbench",
            "source_run_id": source_run_id,
            "note": note,
            "active_retrieval_profile": config_overrides.get("active_retrieval_profile") or RETRIEVAL_EVAL_CONFIG.get("retrieval_profile"),
            "active_ragas_profile": config_overrides.get("active_ragas_profile") or RAGAS_RUN_CONFIG.get("active_profile", RAGAS_ACTIVE_PROFILE),
        },
    }
    path = Path(PRODUCTION_RAG_CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_file(path, published_payload)
    return get_production_rag_config()


def update_rag_eval_config(overrides: Dict[str, Any]) -> Dict[str, Any]:
    """按前端传入的覆盖值更新运行时可调参数。

    注意：这里只修改 Python module 级别的配置对象（内存中），不会持久化到 rag_config.py。
    restart 后恢复默认。
    """
    if not isinstance(overrides, dict):
        raise ConfigValidationError("配置必须是 JSON 对象")

    # 所有输入先写入副本并完整校验，避免某个字段失败后留下半更新状态。
    candidate_profiles = copy.deepcopy(RETRIEVAL_PROFILES)
    candidate_retrieval_eval = copy.deepcopy(RETRIEVAL_EVAL_CONFIG)
    candidate_ragas = copy.deepcopy(RAGAS_RUN_CONFIG)
    candidate_pipeline = copy.deepcopy(RUN_PIPELINE_CONFIG)
    warnings: List[str] = []

    profile_overrides = overrides.get("retrieval_profiles", {})
    if profile_overrides is not None and not isinstance(profile_overrides, dict):
        raise ConfigValidationError("retrieval_profiles 必须是对象")
    for profile_name, profile_cfg in (profile_overrides or {}).items():
        if profile_name not in candidate_profiles:
            warnings.append(f"unknown retrieval profile: {profile_name}")
            continue
        if not isinstance(profile_cfg, dict):
            raise ConfigValidationError(f"retrieval_profiles.{profile_name} 必须是对象")
        for key, value in profile_cfg.items():
            _validate_config_value(f"retrieval_profiles.{profile_name}.{key}", value, key)
        candidate_profiles[profile_name].update(profile_cfg)

    active_retrieval = overrides.get("active_retrieval_profile", candidate_retrieval_eval.get("retrieval_profile", "active_current"))
    if active_retrieval not in candidate_profiles:
        raise ConfigValidationError(f"未知 retrieval profile: {active_retrieval}")
    candidate_retrieval_eval["retrieval_profile"] = active_retrieval

    retrieval_eval = overrides.get("retrieval_eval", {})
    if retrieval_eval is not None and not isinstance(retrieval_eval, dict):
        raise ConfigValidationError("retrieval_eval 必须是对象")
    for key, value in (retrieval_eval or {}).items():
        if key in candidate_retrieval_eval:
            _validate_config_value(f"retrieval_eval.{key}", value, key)
            candidate_retrieval_eval[key] = value

    active_ragas = str(overrides.get("active_ragas_profile", candidate_ragas.get("active_profile", RAGAS_ACTIVE_PROFILE)))
    if active_ragas not in RAGAS_RUN_PROFILES:
        raise ConfigValidationError(f"未知 ragas profile: {active_ragas}")
    if "active_ragas_profile" in overrides:
        candidate_ragas = {
            **RAGAS_BASE_CONFIG,
            **RAGAS_RUN_PROFILES[active_ragas],
            "active_profile": active_ragas,
        }
    ragas_overrides = overrides.get("ragas", {})
    if ragas_overrides is not None and not isinstance(ragas_overrides, dict):
        raise ConfigValidationError("ragas 必须是对象")
    for key, value in (ragas_overrides or {}).items():
        if key not in candidate_ragas:
            warnings.append(f"unknown ragas field: {key}")
            continue
        _validate_config_value(f"ragas.{key}", value, key)
        if key == "selected_metrics":
            allowed_metrics = {"faithfulness", "answer_relevancy", "context_utilization", "context_recall"}
            if not isinstance(value, list) or any(item not in allowed_metrics for item in value):
                raise ConfigValidationError("ragas.selected_metrics 包含不支持的指标")
        candidate_ragas[key] = value

    pipeline_overrides = overrides.get("pipeline", {})
    if pipeline_overrides is not None and not isinstance(pipeline_overrides, dict):
        raise ConfigValidationError("pipeline 必须是对象")
    for key, value in (pipeline_overrides or {}).items():
        if key not in candidate_pipeline:
            continue
        if key == "steps":
            if not isinstance(value, list):
                raise ConfigValidationError("pipeline.steps 必须是数组")
            filtered_steps = [str(step) for step in value if str(step) != "claim_eval"]
            if len(filtered_steps) != len(value):
                warnings.append("claim_eval is temporarily disabled and was removed from pipeline.steps.")
            candidate_pipeline[key] = filtered_steps
        else:
            candidate_pipeline[key] = value

    thresholds = candidate_pipeline.get("thresholds")
    if isinstance(thresholds, dict):
        for key, value in thresholds.items():
            _validate_config_value(f"pipeline.thresholds.{key}", value, key)

    updated: Dict[str, List[str]] = {"updated_fields": [], "warnings": warnings}
    if candidate_profiles != RETRIEVAL_PROFILES:
        RETRIEVAL_PROFILES.clear()
        RETRIEVAL_PROFILES.update(candidate_profiles)
        updated["updated_fields"].append("retrieval_profiles")
    if candidate_retrieval_eval != RETRIEVAL_EVAL_CONFIG:
        RETRIEVAL_EVAL_CONFIG.clear()
        RETRIEVAL_EVAL_CONFIG.update(candidate_retrieval_eval)
        updated["updated_fields"].append("retrieval_eval")
    if candidate_ragas != RAGAS_RUN_CONFIG:
        RAGAS_RUN_CONFIG.clear()
        RAGAS_RUN_CONFIG.update(candidate_ragas)
        updated["updated_fields"].append("ragas")
    if candidate_pipeline != RUN_PIPELINE_CONFIG:
        RUN_PIPELINE_CONFIG.clear()
        RUN_PIPELINE_CONFIG.update(candidate_pipeline)
        updated["updated_fields"].append("pipeline")

    _sync_ragas_retrieval_config(updated)
    return updated


def _apply_ragas_profile(profile_name: str) -> None:
    """切换当前进程内的 Ragas profile，并重置为该 profile 的默认参数。"""
    RAGAS_RUN_CONFIG.clear()
    RAGAS_RUN_CONFIG.update({
        **RAGAS_BASE_CONFIG,
        **RAGAS_RUN_PROFILES[profile_name],
        "active_profile": profile_name,
    })


def _sync_ragas_retrieval_config(updated: Optional[Dict[str, List[str]]] = None) -> None:
    """把当前 active retrieval profile 同步到 Ragas dataset 构建配置。"""
    profile_name = str(RETRIEVAL_EVAL_CONFIG.get("retrieval_profile") or "")
    profile_config = RETRIEVAL_PROFILES.get(profile_name)
    if not isinstance(profile_config, dict):
        return
    previous_profile = RAGAS_RUN_CONFIG.get("retrieval_profile")
    previous_config = RAGAS_RUN_CONFIG.get("retrieval_config")
    merged_config = dict(profile_config)
    if isinstance(previous_config, dict) and "max_evidence_chars" in previous_config:
        merged_config.setdefault("max_evidence_chars", previous_config["max_evidence_chars"])
    RAGAS_RUN_CONFIG["retrieval_profile"] = profile_name
    RAGAS_RUN_CONFIG["retrieval_config"] = merged_config
    if updated is not None:
        if previous_profile != profile_name:
            updated["updated_fields"].append("ragas.retrieval_profile")
        if previous_config != merged_config:
            updated["updated_fields"].append("ragas.retrieval_config")


_pipeline_progress_queues: Dict[str, queue.Queue] = {}
_pipeline_runs: Dict[str, Dict[str, Any]] = {}
_pipeline_lock = threading.Lock()
_MAX_PIPELINE_EVENTS = 400
_RUN_NAME_PATTERN = re.compile(r"[^0-9A-Za-z._-]+")


def _safe_run_name(value: Any) -> str:
    """Normalize a user supplied run name suffix for filesystem-safe run ids."""
    text = str(value or RUN_PIPELINE_CONFIG.get("run_name", "active_benchmark_full_pipeline")).strip()
    text = _RUN_NAME_PATTERN.sub("_", text).strip("._-")
    return text or "active_benchmark_full_pipeline"


def _build_run_id(run_name: str) -> str:
    """生成包含易读时间和安全后缀的run id。"""
    return f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{_safe_run_name(run_name)}"


def current_event_timestamp() -> str:
    """生成带本地时区偏移的事件时间戳，供浏览器稳定显示。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _emit_progress(run_id: str, event_type: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
    """记录pipeline进度事件，并向当前SSE订阅者推送。"""
    payload = {
        "type": event_type,
        "message": message,
        "timestamp": current_event_timestamp(),
    }
    if data:
        payload["data"] = data
    with _pipeline_lock:
        run_state = _pipeline_runs.setdefault(run_id, {
            "run_id": run_id,
            "status": "created",
            "created_at": payload["timestamp"],
            "started_at": "",
            "finished_at": "",
            "current_step": "",
            "steps": [],
            "events": [],
            "cancel_requested": False,
        })
        _update_pipeline_run_state(run_state, payload)
        run_state["events"].append(payload)
        if len(run_state["events"]) > _MAX_PIPELINE_EVENTS:
            run_state["events"] = run_state["events"][-_MAX_PIPELINE_EVENTS:]
        q = _pipeline_progress_queues.get(run_id)
    if q is None:
        return
    try:
        q.put(payload, timeout=1)
    except queue.Full:
        pass


def _update_pipeline_run_state(run_state: Dict[str, Any], event: Dict[str, Any]) -> None:
    """根据事件更新run的轻量状态，供页面刷新后恢复。"""
    event_type = event.get("type")
    data = event.get("data", {})
    timestamp = event.get("timestamp", "")
    if event_type == "pipeline_start":
        run_state["status"] = "running"
        run_state["started_at"] = timestamp
        run_state["steps"] = data.get("steps", [])
    elif event_type == "step_start":
        run_state["status"] = "running"
        run_state["current_step"] = data.get("step") or event.get("message", "")
    elif event_type == "step_done":
        run_state["current_step"] = ""
    elif event_type == "pipeline_done":
        run_state["status"] = data.get("status", "pass")
        run_state["finished_at"] = timestamp
        run_state["current_step"] = ""
        run_state["summary"] = data
    elif event_type == "pipeline_cancel_requested":
        run_state["status"] = "cancelling"
        run_state["cancel_requested"] = True
    elif event_type == "step_cancelled":
        run_state["status"] = "cancelled"
        run_state["finished_at"] = timestamp
        run_state["current_step"] = ""
    elif event_type == "pipeline_error":
        run_state["status"] = "fail"
        run_state["finished_at"] = timestamp
        run_state["current_step"] = ""
        run_state["error"] = data
    elif event_type == "pipeline_closed":
        run_state["closed_at"] = timestamp


def subscribe_progress(run_id: str) -> queue.Queue:
    """订阅某个run的SSE进度队列，并回放已记录的内存事件。"""
    with _pipeline_lock:
        q: queue.Queue = queue.Queue(maxsize=512)
        _pipeline_progress_queues[run_id] = q
        for event in _pipeline_runs.get(run_id, {}).get("events", []):
            try:
                q.put_nowait(event)
            except queue.Full:
                break
        return q


def unsubscribe_progress(run_id: str) -> None:
    """取消订阅。"""
    with _pipeline_lock:
        _pipeline_progress_queues.pop(run_id, None)


def get_pipeline_runtime_state(run_id: Optional[str] = None) -> Dict[str, Any]:
    """返回当前进程内pipeline运行状态，主要用于前端刷新后恢复页面。"""
    with _pipeline_lock:
        if run_id:
            run_state = _pipeline_runs.get(run_id)
            if not run_state:
                return {"available": False, "run_id": run_id}
            return {"available": True, "latest_run": _copy_pipeline_run_state(run_state)}
        if not _pipeline_runs:
            return {"available": False, "latest_run": None}
        latest = sorted(
            _pipeline_runs.values(),
            key=lambda item: item.get("created_at", ""),
            reverse=True,
        )[0]
        return {"available": True, "latest_run": _copy_pipeline_run_state(latest)}


def _copy_pipeline_run_state(run_state: Dict[str, Any]) -> Dict[str, Any]:
    """复制run状态，避免调用方修改内部缓存。"""
    copied = dict(run_state)
    copied["events"] = list(run_state.get("events", []))
    return copied


def _is_cancel_requested(run_id: str) -> bool:
    """Return whether the user has requested cancellation for a run."""
    with _pipeline_lock:
        return bool(_pipeline_runs.get(run_id, {}).get("cancel_requested"))


def request_pipeline_cancel(run_id: str) -> Dict[str, Any]:
    """Request cooperative cancellation for a running pipeline."""
    with _pipeline_lock:
        run_state = _pipeline_runs.get(run_id)
        if not run_state:
            return {"status": "not_found", "run_id": run_id}
        if run_state.get("status") not in {"created", "running", "cancelling"}:
            return {"status": run_state.get("status", "unknown"), "run_id": run_id}
    _emit_progress(run_id, "pipeline_cancel_requested", "已请求停止 Pipeline", {"run_id": run_id})
    return {"status": "cancelling", "run_id": run_id}


def _pipeline_event_callback(run_id: str) -> Callable[[str, str, Dict[str, Any]], None]:
    """Build a callback that forwards low-level pipeline events to SSE state."""
    def callback(event_type: str, message: str, data: Dict[str, Any]) -> None:
        _emit_progress(run_id, event_type, message, data)

    return callback


def run_pipeline_async(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """异步触发完整pipeline，返回run_id供前端订阅SSE。"""
    config_result = update_rag_eval_config(overrides or {})
    run_name = _safe_run_name((overrides or {}).get("run_name") or RUN_PIPELINE_CONFIG.get("run_name"))
    RUN_PIPELINE_CONFIG["run_name"] = run_name
    run_id = _build_run_id(run_name)
    _emit_progress(run_id, "run_created", f"创建run: {run_id}", {"run_id": run_id})

    def _run():
        try:
            _emit_progress(run_id, "pipeline_start", "Pipeline开始执行...", {
                "steps": RUN_PIPELINE_CONFIG.get("steps", []),
                "config_snapshot": {
                    "retrieval_profile": RETRIEVAL_EVAL_CONFIG.get("retrieval_profile"),
                    "ragas_active_profile": RAGAS_RUN_CONFIG.get("active_profile", RAGAS_ACTIVE_PROFILE),
                    "ragas_limit": RAGAS_RUN_CONFIG.get("limit"),
                    "ragas_metrics": RAGAS_RUN_CONFIG.get("selected_metrics"),
                    "applied_overrides": config_result,
                },
            })

            summary = run_pipeline_from_code_config(
                run_id=run_id,
                event_callback=_pipeline_event_callback(run_id),
                cancel_checker=lambda: _is_cancel_requested(run_id),
            )

            status = summary.get("status", "unknown")
            key_metrics = summary.get("key_metrics", {})
            threshold_checks = summary.get("threshold_checks", [])
            steps = summary.get("steps", [])

            _emit_progress(run_id, "pipeline_done", f"Pipeline完成: status={status}", {
                "status": status,
                "status_reason": summary.get("status_reason", ""),
                "key_metrics": key_metrics,
                "threshold_checks": threshold_checks,
                "steps": steps,
                "run_dir": summary.get("run_dir"),
            })
        except Exception as exc:
            _emit_progress(run_id, "pipeline_error", f"Pipeline异常: {exc!r}", {
                "error": repr(exc),
                "traceback": traceback.format_exc(),
            })
        finally:
            _emit_progress(run_id, "pipeline_closed", "Pipeline连接关闭")

    thread = threading.Thread(target=_run, daemon=True, name=f"rag_eval_{run_id}")
    thread.start()
    return {"run_id": run_id, "status": "started"}


def get_latest_results() -> Dict[str, Any]:
    """读取最新的评测结果。"""
    summary_full = _load_json_safe(MACHINE_OUTPUT_DIR / "summary.json")
    metric_sources = summary_full.get("metric_sources", {})
    retrieval = _load_latest_source_json(metric_sources, "retrieval", MACHINE_OUTPUT_DIR / "rag_eval_result.json")
    ragas = _load_latest_source_json(metric_sources, "ragas", MACHINE_OUTPUT_DIR / "ragas_eval_result.json")
    trace = _load_latest_source_json(metric_sources, "trace", MACHINE_OUTPUT_DIR / "trace_index.json")
    summary = _load_latest_summary()
    trace_bad_count = trace.get("bad_case_trace_count")
    ragas_bad_count = ragas.get("cross_metric_bad_cases", {}).get("summary", {}).get("bad_case_count", 0)

    return {
        "summary": summary,
        "retrieval": {
            "recall_at_k": retrieval.get("recall_at_k"),
            "mrr": retrieval.get("mrr"),
            "hit_rate": retrieval.get("hit_rate"),
            "sample_count": retrieval.get("sample_count"),
            "loss_reason_counts": retrieval.get("loss_reason_counts", {}),
            "stage_metrics": retrieval.get("stage_metrics", {}),
            "avg_timings_ms": retrieval.get("avg_timings_ms", {}),
        },
        "ragas": {
            "score_summary": ragas.get("score_summary", {}),
            "score_stddev": ragas.get("score_stddev", {}),
            "sample_count": ragas.get("sample_count"),
            "low_score_case_count": len(ragas.get("low_score_cases", [])),
            "cross_metric_bad_case_count": ragas.get("cross_metric_bad_cases", {})
            .get("summary", {})
            .get("bad_case_count", 0),
            "metric_validity": ragas.get("metric_validity", {}),
        },
        "trace": {
            "trace_count": trace.get("trace_count"),
            "bad_case_trace_count": trace_bad_count if trace_bad_count is not None else ragas_bad_count,
        },
    }


def list_runs() -> List[Dict[str, Any]]:
    """列出历史run目录。"""
    if not RUNS_DIR.exists():
        return []
    runs = []
    for run_dir in sorted(RUNS_DIR.iterdir(), key=lambda p: p.name, reverse=True):
        if not run_dir.is_dir():
            continue
        summary_path = run_dir / "summary.json"
        summary = _load_json_safe(summary_path)
        display = _run_display_info(run_dir.name, summary)
        runs.append({
            "run_id": run_dir.name,
            **display,
            "status": summary.get("status", "unknown"),
            "status_reason": summary.get("status_reason", ""),
            "started_at": summary.get("started_at", ""),
            "finished_at": summary.get("finished_at", ""),
            "key_metrics": summary.get("key_metrics", {}),
            "steps": summary.get("steps", []),
        })
    return runs


def list_runs_page(page: int = 1, page_size: int = 10) -> Dict[str, Any]:
    """按页返回历史run记录，避免前端一次渲染过多pipeline。"""
    safe_page = max(int(page or 1), 1)
    safe_page_size = min(max(int(page_size or 10), 1), 100)
    runs = list_runs()
    total = len(runs)
    total_pages = max((total + safe_page_size - 1) // safe_page_size, 1)
    safe_page = min(safe_page, total_pages)
    start = (safe_page - 1) * safe_page_size
    return {
        "items": runs[start:start + safe_page_size],
        "page": safe_page,
        "page_size": safe_page_size,
        "total": total,
        "total_pages": total_pages,
    }


def delete_run(run_id: str) -> Dict[str, Any]:
    """删除单个历史run目录，只允许删除RUNS_DIR直属子目录。"""
    target = _resolve_run_dir(run_id)
    if target is None:
        return {"status": "invalid", "run_id": run_id, "message": "invalid run_id"}
    if not target.exists():
        return {"status": "not_found", "run_id": run_id}
    if not target.is_dir():
        return {"status": "invalid", "run_id": run_id, "message": "run path is not a directory"}
    with _pipeline_lock:
        run_state = _pipeline_runs.get(run_id)
        if run_state and run_state.get("status") in {"created", "running", "cancelling"}:
            return {"status": "running", "run_id": run_id, "message": "run is still running"}
    shutil.rmtree(target)
    with _pipeline_lock:
        _pipeline_runs.pop(run_id, None)
        _pipeline_progress_queues.pop(run_id, None)
    return {"status": "deleted", "run_id": run_id, "deleted": True, "deleted_path": str(target)}


def get_run_detail(run_id: str) -> Dict[str, Any]:
    """获取某个run的详细信息。"""
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        return {"error": "run not found", "run_id": run_id}

    summary = _load_json_safe(run_dir / "summary.json")
    config_snapshot = _load_json_safe(run_dir / "config_snapshot.json")
    analysis = _build_analysis_payload(run_id)
    display = _run_display_info(run_id, summary)

    return {
        "run_id": run_id,
        **display,
        "summary": summary,
        "config_snapshot": config_snapshot,
        "analysis": analysis if "error" not in analysis else {},
    }


def get_latest_analysis() -> Dict[str, Any]:
    """聚合最新评测的报告、trace和坏例明细，供前端分析页读取。"""
    return _build_analysis_payload()


def get_run_analysis(run_id: str) -> Dict[str, Any]:
    """聚合指定run的报告、trace和坏例明细。"""
    return _build_analysis_payload(run_id)


def get_run_diff(base_run_id: Optional[str] = None, candidate_run_id: Optional[str] = None) -> Dict[str, Any]:
    """对比两个run的关键指标、坏例变化和核心配置差异。"""
    base_id, candidate_id = _resolve_diff_run_ids(base_run_id, candidate_run_id)
    if not base_id or not candidate_id:
        return {"available": False, "message": "至少需要两个历史run才能对比。"}

    base_dir = RUNS_DIR / base_id
    candidate_dir = RUNS_DIR / candidate_id
    if not base_dir.exists() or not candidate_dir.exists():
        return {"available": False, "message": "run not found", "base_run_id": base_id, "candidate_run_id": candidate_id}

    base_summary = _load_json_safe(base_dir / "summary.json")
    candidate_summary = _load_json_safe(candidate_dir / "summary.json")
    base_cases = _bad_case_question_ids(base_id)
    candidate_cases = _bad_case_question_ids(candidate_id)

    return {
        "available": True,
        "base_run_id": base_id,
        "candidate_run_id": candidate_id,
        "metric_deltas": _build_metric_deltas(
            base_summary.get("key_metrics", {}),
            candidate_summary.get("key_metrics", {}),
        ),
        "bad_case_delta": {
            "base_count": len(base_cases),
            "candidate_count": len(candidate_cases),
            "delta": len(candidate_cases) - len(base_cases),
            "resolved_question_indexes": sorted(base_cases - candidate_cases),
            "new_question_indexes": sorted(candidate_cases - base_cases),
            "persistent_question_indexes": sorted(base_cases & candidate_cases),
        },
        "step_seconds_delta": _build_step_seconds_delta(base_summary, candidate_summary),
        "config_deltas": _build_config_deltas(
            _load_json_safe(base_dir / "config_snapshot.json"),
            _load_json_safe(candidate_dir / "config_snapshot.json"),
        ),
    }


# ---- 内部辅助函数 ----

def _load_json_safe(path: Path) -> Dict[str, Any]:
    """安全读取JSON文件，不存在时返回空dict。"""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _resolve_run_dir(run_id: str) -> Optional[Path]:
    """把run_id解析为RUNS_DIR下的直属目录，阻止路径穿越。"""
    clean_run_id = str(run_id or "").strip()
    if not clean_run_id or clean_run_id in {".", ".."}:
        return None
    if "/" in clean_run_id or "\\" in clean_run_id or ".." in clean_run_id:
        return None
    root = RUNS_DIR.resolve()
    target = (root / clean_run_id).resolve()
    if target.parent != root:
        return None
    return target


def _run_display_info(run_id: str, summary: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """从机器run_id中拆出面向用户展示的pipeline名和时间。"""
    summary = summary or {}
    display_name = _parse_run_name_from_id(run_id)
    started_at = str(summary.get("started_at") or "")
    return {
        "display_name": display_name,
        "display_time": _format_display_time(started_at),
        "display_subtitle": f"ID: {run_id}" if run_id else "",
    }


def _parse_run_name_from_id(run_id: str) -> str:
    """去掉run_id前缀时间，只保留用户输入的pipeline名称。"""
    text = str(run_id or "").strip()
    match = re.match(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_(.+)$", text)
    if match:
        return match.group(1) or RUN_PIPELINE_CONFIG.get("run_name", "active_benchmark_full_pipeline")
    return text or RUN_PIPELINE_CONFIG.get("run_name", "active_benchmark_full_pipeline")


def _format_display_time(value: str) -> str:
    """把ISO时间压缩成用户可读的日期时间文本；空值返回--。"""
    if not value:
        return "--"
    return value.replace("T", " ")[:19]


def _write_json_file(path: Path, data: Dict[str, Any]) -> None:
    """写入格式化 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _current_eval_retrieval_config() -> RagRetrievalConfig:
    """提取当前评测配置中可发布给正式 RAG 的检索参数。"""
    raw_config = RAGAS_RUN_CONFIG.get("retrieval_config")
    if not isinstance(raw_config, dict):
        profile_name = RAGAS_RUN_CONFIG.get("retrieval_profile") or RETRIEVAL_EVAL_CONFIG.get("retrieval_profile")
        raw_config = RETRIEVAL_PROFILES.get(str(profile_name), {})
    allowed_fields = set(RagRetrievalConfig.__dataclass_fields__.keys())
    filtered = {key: value for key, value in dict(raw_config).items() if key in allowed_fields}
    if "final_top_k" not in filtered and RETRIEVAL_EVAL_CONFIG.get("top_k") is not None:
        filtered["final_top_k"] = RETRIEVAL_EVAL_CONFIG["top_k"]
    return RagRetrievalConfig(**filtered)


def _retrieval_config_from_overrides(overrides: Dict[str, Any]) -> RagRetrievalConfig:
    """从前端当前表单覆盖值中提取可发布给正式 RAG 的检索参数。"""
    profile_name = str(
        overrides.get("active_retrieval_profile")
        or RETRIEVAL_EVAL_CONFIG.get("retrieval_profile")
        or ""
    )
    raw_config: Dict[str, Any] = {}
    profile_overrides = overrides.get("retrieval_profiles")
    if isinstance(profile_overrides, dict) and isinstance(profile_overrides.get(profile_name), dict):
        raw_config.update(profile_overrides[profile_name])
    else:
        raw_config.update(RETRIEVAL_PROFILES.get(profile_name, {}))

    current_ragas_retrieval = RAGAS_RUN_CONFIG.get("retrieval_config")
    if isinstance(current_ragas_retrieval, dict):
        for key in ("max_evidence_chars",):
            if key not in raw_config and key in current_ragas_retrieval:
                raw_config[key] = current_ragas_retrieval[key]

    retrieval_eval = overrides.get("retrieval_eval")
    if isinstance(retrieval_eval, dict) and retrieval_eval.get("top_k") is not None:
        raw_config["final_top_k"] = retrieval_eval["top_k"]

    allowed_fields = set(RagRetrievalConfig.__dataclass_fields__.keys())
    filtered = {key: value for key, value in raw_config.items() if key in allowed_fields}
    return RagRetrievalConfig(**filtered)


def _load_latest_source_json(
    metric_sources: Dict[str, Any],
    source_name: str,
    fallback_path: Path,
) -> Dict[str, Any]:
    """只读取当前summary确认使用的latest来源，避免旧产物混入新run。"""
    if metric_sources:
        source = metric_sources.get(source_name, {})
        if not source.get("used"):
            return {}
        return _load_json_safe(Path(source.get("path") or fallback_path))
    return _load_json_safe(fallback_path)


def _load_jsonl_safe(path: Path) -> List[Dict[str, Any]]:
    """安全读取JSONL文件，不存在或解析失败的行会被跳过。"""
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
    except OSError:
        return []
    return rows


def _read_text_safe(path: Path, max_chars: int = 24000) -> str:
    """安全读取文本报告，限制长度以避免前端一次加载过大内容。"""
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n...（报告内容已截断）"


def _analysis_dirs(run_id: Optional[str] = None) -> Tuple[Path, Path, str]:
    """返回分析产物所在的machine目录、reports目录和来源标识。"""
    if run_id:
        run_dir = RUNS_DIR / run_id
        return run_dir / "machine", run_dir / "reports", run_id
    latest = _load_latest_summary()
    return MACHINE_OUTPUT_DIR, REPORT_OUTPUT_DIR, latest.get("run_id", "latest")


def _analysis_summary(run_id: Optional[str] = None) -> Dict[str, Any]:
    """读取报告页对应run的summary，供前端展示结构化指标。"""
    if run_id:
        return _load_json_safe(RUNS_DIR / run_id / "summary.json")
    return _load_json_safe(MACHINE_OUTPUT_DIR / "summary.json")


def _compact_evidence(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """压缩单条证据，保留前端分析需要的字段。"""
    content = evidence.get("content") or ""
    return {
        "metadata": dict(evidence.get("metadata") or {}),
        "scores": {
            key: evidence.get(key)
            for key in ("dense_score", "sparse_score", "rerank_score")
            if evidence.get(key) is not None
        },
        "retrieval_source": evidence.get("retrieval_source"),
        "content_preview": content[:700] + ("..." if len(content) > 700 else ""),
    }


def _is_claim_bad_case(case: Dict[str, Any]) -> bool:
    """判断坏例来源是否属于暂时屏蔽的 claim_eval。"""
    source = str(case.get("source") or "").lower()
    metric = str(case.get("metric") or "").lower()
    reason = str(case.get("reason") or "").lower()
    return source in CLAIM_BAD_CASE_SOURCES or "claim" in source or "claim" in metric or "claim" in reason


def _filter_visible_bad_cases(cases: Any) -> List[Dict[str, Any]]:
    """过滤前端调参视角不展示的坏例类型。"""
    if not isinstance(cases, list):
        return []
    return [
        case for case in cases
        if isinstance(case, dict) and not _is_claim_bad_case(case)
    ]


def _compact_trace(trace: Dict[str, Any]) -> Dict[str, Any]:
    """压缩trace详情，避免把完整长文本全部塞给列表页。"""
    retrieval = trace.get("retrieval_eval", {})
    generation = trace.get("generation", {})
    bad_case = trace.get("bad_case", {})
    visible_bad_cases = _filter_visible_bad_cases(bad_case.get("cases", []))
    return {
        "trace_id": trace.get("trace_id"),
        "question_index": trace.get("question_index"),
        "question": trace.get("question"),
        "sample_id": trace.get("sample_id"),
        "source": trace.get("source", {}),
        "reference_answer": trace.get("reference_answer"),
        "answer": generation.get("answer"),
        "answer_preview": generation.get("answer_preview"),
        "is_bad_case": bool(visible_bad_cases),
        "bad_case_count": len(visible_bad_cases),
        "bad_case_cases": visible_bad_cases,
        "retrieval": {
            "recall": retrieval.get("recall"),
            "reciprocal_rank": retrieval.get("reciprocal_rank"),
            "loss_reasons": retrieval.get("loss_reasons", []),
            "gold_evidence": retrieval.get("gold_evidence", []),
            "retrieved_evidence": retrieval.get("retrieved_evidence", []),
            "matched_evidence": retrieval.get("matched_evidence", []),
        },
        "ragas_scores": trace.get("ragas_scores", {}),
        "evidence": [
            _compact_evidence(item)
            for item in generation.get("final_evidence_payload", [])
            if isinstance(item, dict)
        ],
    }


def _build_report_cards(report_dir: Path) -> List[Dict[str, Any]]:
    """读取当前run的Markdown报告卡片。"""
    report_specs = [
        ("summary", "总报告", "summary.md"),
        ("dataset_validation", "数据集校验", "dataset_validation_report.md"),
        ("retrieval", "检索报告", "rag_eval_report.md"),
        ("ragas", "Ragas报告", "ragas_eval_report.md"),
    ]
    if (report_dir / "trace_report.md").exists():
        report_specs.append(("trace", "坏例链路报告", "trace_report.md"))
    reports = []
    for key, title, filename in report_specs:
        path = report_dir / filename
        reports.append({
            "key": key,
            "title": title,
            "filename": filename,
            "available": path.exists(),
            "path": str(path.resolve()),
            "content": _read_text_safe(path),
        })
    return reports


def _build_analysis_payload(run_id: Optional[str] = None) -> Dict[str, Any]:
    """构建前端分析页需要的只读聚合数据。"""
    machine_dir, report_dir, source_run_id = _analysis_dirs(run_id)
    if run_id and not machine_dir.parent.exists():
        return {"error": "run not found", "run_id": run_id}

    summary = _analysis_summary(run_id)
    trace_index = _load_json_safe(machine_dir / "trace_index.json")
    traces = _load_jsonl_safe(machine_dir / "trace.jsonl")
    low_score = _load_json_safe(machine_dir / "ragas_low_score_cases.json")
    cross_metric = _load_json_safe(machine_dir / "ragas_cross_metric_bad_cases.json")

    compact_traces = [_compact_trace(trace) for trace in traces]
    bad_traces = [trace for trace in compact_traces if trace.get("is_bad_case")]
    cross_metric_cases = cross_metric.get("cases", [])
    bad_case_count = len(bad_traces) if bad_traces else len(cross_metric_cases)
    diagnosis = _build_developer_diagnosis(summary, trace_index, cross_metric, compact_traces)
    display = _run_display_info(source_run_id, summary)

    return {
        "run_id": source_run_id,
        **display,
        "machine_dir": str(machine_dir.resolve()),
        "report_dir": str(report_dir.resolve()),
        "summary": summary,
        "trace_index": {
            "trace_count": trace_index.get("trace_count", len(compact_traces)),
            "bad_case_trace_count": bad_case_count,
            "retrieval_eval_trace_count": trace_index.get("retrieval_eval_trace_count"),
            "ragas_eval_trace_count": trace_index.get("ragas_eval_trace_count"),
            "traces": trace_index.get("traces", []),
        },
        "bad_cases": {
            "count": bad_case_count,
            "traces": bad_traces,
            "low_score_cases": low_score.get("cases", []),
            "cross_metric_cases": cross_metric_cases,
            "cross_metric_summary": cross_metric.get("summary", {}),
        },
        "developer_diagnosis": diagnosis,
        "reports": _build_report_cards(report_dir),
    }


def _build_developer_diagnosis(
    summary: Dict[str, Any],
    trace_index: Dict[str, Any],
    cross_metric: Dict[str, Any],
    compact_traces: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """根据现有指标和坏例类型生成面向开发者的调参诊断。"""
    metrics = summary.get("key_metrics", {})
    cases = cross_metric.get("cases", [])
    case_count = len(cases)
    category_counts: Dict[str, int] = {}
    low_metric_counts: Dict[str, int] = {}
    for case in cases:
        for category in case.get("categories", []):
            category_counts[category] = category_counts.get(category, 0) + 1
        for metric in case.get("low_ragas_metrics", []):
            low_metric_counts[metric] = low_metric_counts.get(metric, 0) + 1

    trace_count = trace_index.get("trace_count") or len(compact_traces)
    retrieval_recall = _as_float(metrics.get("retrieval_recall_at_k"))
    retrieval_mrr = _as_float(metrics.get("retrieval_mrr"))
    context_recall = _as_float(metrics.get("ragas_context_recall"))
    faithfulness = _as_float(metrics.get("ragas_faithfulness"))

    bottleneck = "暂无足够数据"
    severity = "info"
    evidence: List[str] = []
    suggestions: List[Dict[str, Any]] = []

    retrieval_ok_ragas_bad = category_counts.get("retrieval_ok_ragas_bad", 0)
    retrieval_and_generation_bad = category_counts.get("retrieval_and_generation_bad", 0)
    context_recall_low = low_metric_counts.get("context_recall", 0)

    if case_count == 0 and trace_count:
        bottleneck = "当前样本未发现明显坏例"
        evidence.append("bad_case_count=0，可扩大样本或提高阈值做回归检查。")
        suggestions.append(_suggestion(
            "扩大样本验证稳定性",
            "把 limit 从当前 smoke 扩到 100 或全量，确认指标不是小样本偶然波动。",
            {"limit": 100, "reuse_score_cache": False},
        ))
    elif retrieval_recall is not None and retrieval_recall < 0.9:
        bottleneck = "检索召回不足"
        severity = "warning"
        evidence.append(f"retrieval_recall_at_k={retrieval_recall:.4f}，优先排查 dense/sparse 候选池。")
        suggestions.extend([
            _suggestion("放大候选池", "提高 dense_fetch_k、sparse_fetch_k 和 dense_mmr_k，先看 gold 是否进入候选。", {"dense_fetch_k": 40, "sparse_fetch_k": 40, "dense_mmr_k": 20}),
            _suggestion("运行 retrieval sweep", "只跑 retrieval_eval，对比 final_top_k 和 threshold 对召回的影响。", {"steps": ["validate_datasets", "retrieval_eval", "summary"]}),
        ])
    elif retrieval_ok_ragas_bad >= max(1, int(case_count * 0.6)) and context_recall_low:
        bottleneck = "上下文覆盖不足"
        severity = "warning" if context_recall is not None and context_recall < 0.7 else "info"
        evidence.append(f"{retrieval_ok_ragas_bad}/{case_count} 个坏例属于 retrieval_ok_ragas_bad。")
        evidence.append(f"context_recall 低分样本数={context_recall_low}。")
        if retrieval_recall is not None:
            evidence.append(f"retrieval_recall_at_k={retrieval_recall:.4f}，说明问题主要不在基础召回。")
        suggestions.extend([
            _suggestion("扩大上下文预算", "优先试 max_contexts=6/8、max_evidence_chars=2200，观察 context_recall 是否提升。", {"max_contexts": [6, 8], "max_evidence_chars": 2200}),
            _suggestion("扩大 final evidence", "试 final_top_k=6 或 8，确认更多 gold 邻近 chunk 是否能覆盖 reference 要点。", {"retrieval_final_top_k": [6, 8]}),
            _suggestion("检查 chunk 粒度", "抽查低 context_recall 样本，判断是否需要相邻 chunk 合并或 doc-level context。", {"manual_review": "inspect low context_recall traces"}),
        ])
    elif retrieval_and_generation_bad:
        bottleneck = "检索排序与生成同时有风险"
        severity = "warning"
        evidence.append(f"{retrieval_and_generation_bad}/{case_count} 个坏例同时触发 retrieval/generation 低分。")
        if retrieval_mrr is not None:
            evidence.append(f"retrieval_mrr={retrieval_mrr:.4f}，关注 gold rank 靠后的样本。")
        suggestions.extend([
            _suggestion("提高 gold 排名", "先调 rerank/final_top_k，减少 gold doc 排名靠后导致的 answer 误判。", {"retrieval_final_top_k": [6, 8], "final_rerank_threshold": 0.0}),
            _suggestion("复核回答提示词", "对 answer_relevancy 和 faithfulness 同时低的样本检查 prompt 是否过度拒答。", {"manual_review": "answer prompt and insufficient_evidence cases"}),
        ])
    elif faithfulness is not None and faithfulness < 0.75:
        bottleneck = "回答忠实性不足"
        severity = "warning"
        evidence.append(f"ragas_faithfulness={faithfulness:.4f}。")
        suggestions.append(_suggestion("收紧回答约束", "要求 answer 只使用证据、必须引用 evidence id，并减少未支撑推断。", {"target": "answer_prompt"}))
    else:
        bottleneck = "生成质量或评测口径需人工复核"
        evidence.append("检索指标较高，但仍存在 Ragas 低分样本。")
        suggestions.extend([
            _suggestion("抽查持续坏例", "优先看 persistent bad cases，区分真实错误和 reference/judge 口径问题。", {"manual_review": "persistent bad cases"}),
            _suggestion("做 run diff", "把本次 run 与上一条成功 run 对比，确认调参收益和退化样本。", {"compare": "latest successful run"}),
        ])

    return {
        "primary_bottleneck": bottleneck,
        "severity": severity,
        "evidence": evidence,
        "category_counts": category_counts,
        "low_metric_counts": low_metric_counts,
        "suggested_experiments": suggestions,
    }


def _suggestion(title: str, rationale: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """构造统一的调参建议结构。"""
    return {"title": title, "rationale": rationale, "params": params}


def _as_float(value: Any) -> Optional[float]:
    """把指标值转换为float，失败时返回None。"""
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_diff_run_ids(base_run_id: Optional[str], candidate_run_id: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """解析对比run id；未指定时默认取最近两个有summary的run。"""
    if base_run_id and candidate_run_id:
        return base_run_id, candidate_run_id
    runs = [run for run in list_runs() if run.get("status") != "unknown"]
    if candidate_run_id:
        older = [run["run_id"] for run in runs if run.get("run_id") != candidate_run_id]
        return (base_run_id or (older[0] if older else None)), candidate_run_id
    if len(runs) < 2:
        return None, None
    return runs[1]["run_id"], runs[0]["run_id"]


def _build_metric_deltas(base_metrics: Dict[str, Any], candidate_metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    """生成关键指标delta列表。"""
    metric_names = [
        "retrieval_recall_at_k",
        "retrieval_mrr",
        "retrieval_hit_rate",
        "ragas_faithfulness",
        "ragas_answer_relevancy",
        "ragas_context_utilization",
        "ragas_context_recall",
        "bad_case_trace_count",
    ]
    rows = []
    for name in metric_names:
        base_value = _as_float(base_metrics.get(name))
        candidate_value = _as_float(candidate_metrics.get(name))
        delta = None if base_value is None or candidate_value is None else candidate_value - base_value
        rows.append({
            "metric": name,
            "base": base_metrics.get(name),
            "candidate": candidate_metrics.get(name),
            "delta": delta,
            "direction": _metric_direction(name, delta),
        })
    return rows


def _metric_direction(name: str, delta: Optional[float]) -> str:
    """判断指标变化方向是否有利。"""
    if delta is None or abs(delta) < 1e-12:
        return "flat"
    lower_is_better = {"bad_case_trace_count"}
    if name in lower_is_better:
        return "better" if delta < 0 else "worse"
    return "better" if delta > 0 else "worse"


def _bad_case_question_ids(run_id: str) -> set:
    """读取某个run的坏例题号集合。"""
    machine_dir = RUNS_DIR / run_id / "machine"
    trace_index = _load_json_safe(machine_dir / "trace_index.json")
    ids = {
        int(item["question_index"])
        for item in trace_index.get("traces", [])
        if item.get("is_bad_case") and item.get("question_index") is not None
    }
    if ids:
        return ids
    cross_metric = _load_json_safe(machine_dir / "ragas_cross_metric_bad_cases.json")
    return {
        int(item["question_index"])
        for item in cross_metric.get("cases", [])
        if item.get("question_index") is not None
    }


def _build_step_seconds_delta(base_summary: Dict[str, Any], candidate_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """对比步骤耗时变化。"""
    base_steps = {step.get("name"): step for step in base_summary.get("steps", [])}
    candidate_steps = {step.get("name"): step for step in candidate_summary.get("steps", [])}
    names = sorted(set(base_steps) | set(candidate_steps))
    rows = []
    for name in names:
        base_seconds = _as_float(base_steps.get(name, {}).get("seconds"))
        candidate_seconds = _as_float(candidate_steps.get(name, {}).get("seconds"))
        rows.append({
            "step": name,
            "base_seconds": base_seconds,
            "candidate_seconds": candidate_seconds,
            "delta_seconds": None if base_seconds is None or candidate_seconds is None else candidate_seconds - base_seconds,
        })
    return rows


def _build_config_deltas(base_config: Dict[str, Any], candidate_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """抽取开发者调参最关心的配置变化。"""
    paths = [
        ("retrieval_eval.retrieval_profile", "检索 profile"),
        ("retrieval_eval.limit", "检索样本数"),
        ("ragas_eval.active_profile", "Ragas profile"),
        ("ragas_eval.limit", "Ragas 样本数"),
        ("ragas_eval.max_contexts", "Context 数"),
        ("ragas_eval.max_context_chars", "单 context 字符"),
        ("ragas_eval.max_response_chars", "回答字符"),
        ("ragas_eval.ragas_max_workers", "Ragas 并发"),
        ("ragas_eval.judge_profile", "Judge profile"),
    ]
    rows = []
    for path, label in paths:
        base_value = _get_path(base_config, path)
        candidate_value = _get_path(candidate_config, path)
        if base_value != candidate_value:
            rows.append({"field": path, "label": label, "base": base_value, "candidate": candidate_value})
    return rows


def _get_path(data: Dict[str, Any], path: str) -> Any:
    """按点分路径读取dict。"""
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _load_latest_summary() -> Dict[str, Any]:
    """从latest机器输出读取summary。"""
    summary_path = MACHINE_OUTPUT_DIR / "summary.json"
    if not summary_path.exists():
        # 尝试从report目录读取
        report_summary = REPORT_OUTPUT_DIR / "summary.md"
        return {
            "available": False,
            "message": "暂无评测结果。点击「运行Pipeline」开始评测。",
        }

    data = _load_json_safe(summary_path)
    display = _run_display_info(data.get("run_id", ""), data)
    return {
        "available": True,
        "status": data.get("status", "unknown"),
        "status_reason": data.get("status_reason", ""),
        "run_id": data.get("run_id", ""),
        **display,
        "started_at": data.get("started_at", ""),
        "finished_at": data.get("finished_at", ""),
        "key_metrics": data.get("key_metrics", {}),
        "threshold_checks": data.get("threshold_checks", []),
        "steps": data.get("steps", []),
    }


def _get_vector_db_info() -> Dict[str, Any]:
    """读取 Runtime 暴露的向量库身份，不解析题集或 active pointer。"""
    try:
        from Agent.knowledge_base.query_rag import get_vector_db_metadata_summary

        info = dict(get_vector_db_metadata_summary())
        path = Path(str(info.get("persist_directory", ""))) if info.get("persist_directory") else None
        info.update(
            {
                "path": str(path.resolve()) if path else "",
                "exists": bool(path and path.is_dir()),
                "status": "ready",
                "doc_count": info.get("doc_count", info.get("vector_count", 0)),
            }
        )
        if path and path.is_dir():
            info["size_mb"] = round(
                sum(file.stat().st_size for file in path.rglob("*") if file.is_file()) / (1024 * 1024),
                2,
            )
        return info
    except Exception as exc:
        return {
            "status": "unavailable",
            "exists": False,
            "path": "",
            "error": str(exc),
        }


def _get_model_runtime_info() -> Dict[str, Any]:
    """返回首页展示用的模型运行时配置状态，不触发真实模型调用。"""
    return {
        "embedding": _get_embedding_runtime_info(),
        "answer": _get_llm_runtime_info("answer", "正式 RAG 回答生成"),
        "judge": _get_llm_runtime_info("judge", "Ragas / 评测 judge", RAGAS_RUN_CONFIG.get("judge_profile", "")),
    }


def _get_embedding_runtime_info() -> Dict[str, Any]:
    """返回当前查询侧 embedding 配置状态，避免用户误把配置缺失当成调参问题。"""
    try:
        embedding_config = resolve_embedding_runtime_config()
    except ValueError as exc:
        return {
            "status": "missing",
            "mode": os.environ.get("RAG_EMBEDDING_PROVIDER", "auto"),
            "provider": "invalid",
            "model": "--",
            "message": str(exc),
        }
    info = dict(embedding_config)
    if info.get("base_url"):
        info["endpoint"] = _safe_base_url_label(str(info.get("base_url") or ""))
        info.pop("base_url", None)
    return info


def _get_llm_runtime_info(role: str, purpose: str, judge_profile: str = "") -> Dict[str, Any]:
    """返回回答模型或评测judge模型配置状态，不暴露密钥内容。"""
    api_key_configured = bool(getattr(settings, "API_KEY", ""))
    base_url = str(getattr(settings, "BASE_URL", "") or "")
    model = str(getattr(settings, "MODEL", "") or "")
    base_url_configured = bool(base_url)
    model_configured = bool(model)
    status = "ready" if api_key_configured and base_url_configured and model_configured else "missing"
    missing = []
    if not api_key_configured:
        missing.append("API_KEY")
    if not base_url_configured:
        missing.append("BASE_URL")
    if not model_configured:
        missing.append("MODEL")
    return {
        "status": status,
        "role": role,
        "purpose": purpose,
        "provider": "openai_compatible",
        "model": model or "--",
        "api_key_configured": api_key_configured,
        "base_url_configured": base_url_configured,
        "endpoint": _safe_base_url_label(base_url),
        "judge_profile": judge_profile,
        "message": "配置完整" if status == "ready" else "缺少 " + ", ".join(missing),
    }


def _safe_base_url_label(base_url: str) -> str:
    """展示不含密钥和 query 的 base_url 摘要。"""
    if not base_url:
        return "--"
    parsed = urlparse(base_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return base_url.split("?", 1)[0]


def _get_benchmark_sample_count() -> int:
    """获取显式通用题集的样本数。"""
    if not RAG_EVAL_DATASET_PATH or not RAG_EVAL_DATASET_PATH.exists():
        return 0
    try:
        return len(load_eval_dataset(RAG_EVAL_DATASET_PATH))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return 0


def _get_evaluation_identity_status() -> Dict[str, Any]:
    """返回通用题集的只读身份摘要。"""
    path = RAG_EVAL_DATASET_PATH
    result: Dict[str, Any] = {
        "dataset_name": RAG_EVAL_DATASET_NAME,
        "dataset_path": str(path.resolve()) if path else "",
        "dataset_exists": bool(path and path.is_file()),
    }
    if not path or not path.is_file():
        result["status"] = "not_configured"
        return result
    try:
        identity = evaluation_identity(path)
        result.update(
            {
                "status": "ready",
                "dataset_sha256": identity.get("dataset_sha256", ""),
                "dataset_schema": identity.get("schema_version", ""),
                "sample_count": identity.get("sample_count", 0),
            }
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        result.update({"status": "blocked", "error": str(exc)})
    return result


def get_step_descriptions() -> Dict[str, str]:
    """返回每个pipeline步骤的中文描述。"""
    return {
        "validate_datasets": "数据集校验：检查benchmark数据完整性、gold标注一致性",
        "retrieval_eval": "检索评测(Phase2)：评测dense/sparse/rerank链路的recall、hit_rate、MRR和各阶段丢失原因",
        "ragas_eval": "Ragas生成质量评测(Phase3)：评测faithfulness、answer_relevancy、context_utilization、context_recall",
        "trace_export": "坏例链路导出：整合retrieval/ragas结果生成Bad Case Traces供人工复查",
        "summary": "生成汇总报告：合并各阶段核心指标，执行回归阈值检查",
    }
