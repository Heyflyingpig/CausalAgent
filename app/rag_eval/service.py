"""
RAG评测服务层 —— 封装配置读写、pipeline触发、SSE进度推送和结果查询。

该模块不重复实现评测逻辑，只桥接 Agent/knowledge_base/rag 中已有的评测模块。
"""
import json
import copy
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from Agent.knowledge_base.rag.rag_config import (
    MACHINE_OUTPUT_DIR,
    RAG_EVAL_DATASET_NAME,
    RAG_EVAL_DATASET_PATH,
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
from Agent.knowledge_base.query_rag import (
    PRODUCTION_RAG_CONFIG_PATH,
    RagRetrievalConfig,
    get_production_rag_config_status,
)
from app.rag_eval.profile_store import list_strategy_profiles
from config.settings import settings

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


def current_event_timestamp() -> str:
    """生成带本地时区偏移的事件时间戳，供浏览器稳定显示。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")
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


def _load_latest_summary() -> Dict[str, Any]:
    """从latest机器输出读取summary。"""
    summary_path = MACHINE_OUTPUT_DIR / "summary.json"
    if not summary_path.exists():
        return {
            "available": False,
            "message": "暂无评测结果。请从评测中心创建隔离评测。",
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
