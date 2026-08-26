"""RAG 评测策略 profile 的默认定义、SQL 持久化和正式发布适配器。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
from typing import Any, Dict, Optional

from Agent.knowledge_base.query_rag import PRODUCTION_RAG_CONFIG_PATH
from Agent.knowledge_base.rag.rag_config import (
    RAGAS_BASE_CONFIG,
    RAGAS_RUN_PROFILES,
    RETRIEVAL_PROFILES,
)
from app.db import db_cursor


PROFILE_RAGAS_KEYS = {
    "limit",
    "selected_metrics",
    "include_reference_metrics",
    "run_ragas",
    "reuse_prepared_dataset",
    "reuse_score_cache",
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
}

BUILTIN_STRATEGIES = {
    "active_current": {
        "name": "active_current",
        "retrieval_profile": "active_current",
        "ragas_profile": "generic_pipeline",
    },
    "quick_cached": {
        "name": "quick_cached",
        "retrieval_profile": "active_current",
        "ragas_profile": "quick_cached",
    },
    "reviewed_5_core_metrics": {
        "name": "reviewed_5_core_metrics",
        "retrieval_profile": "active_current",
        "ragas_profile": "reviewed_5_core_metrics",
    },
}


def _profile_owner_clause(owner_user_id: Optional[int]) -> tuple[str, tuple[Any, ...]]:
    """返回允许访问全局 profile 或当前用户 profile 的 SQL 条件。"""
    if owner_user_id is None:
        return "owner_user_id IS NULL", ()
    return "(owner_user_id IS NULL OR owner_user_id = %s)", (owner_user_id,)


def _json_object(value: Any) -> Dict[str, Any]:
    """把 MySQL JSON 字段安全转换为对象。"""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, (str, bytes, bytearray)):
        parsed = json.loads(value)
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _builtin_profile(profile_id: str) -> Dict[str, Any]:
    """解析一个只读内置 unified strategy profile。"""
    definition = BUILTIN_STRATEGIES[profile_id]
    retrieval_profile = definition["retrieval_profile"]
    ragas_profile = definition["ragas_profile"]
    ragas_config = {
        key: value
        for key, value in {
            **RAGAS_BASE_CONFIG,
            **RAGAS_RUN_PROFILES[ragas_profile],
        }.items()
        if key in PROFILE_RAGAS_KEYS
    }
    return {
        "profile_id": profile_id,
        "name": definition["name"],
        "kind": "builtin",
        "editable": False,
        "retrieval_profile": retrieval_profile,
        "ragas_profile": ragas_profile,
        "retrieval": dict(RETRIEVAL_PROFILES[retrieval_profile]),
        "ragas": ragas_config,
    }


def _row_to_profile(row: Dict[str, Any]) -> Dict[str, Any]:
    """把 SQL profile 行转换为前端和评测运行共用的对象。"""
    return {
        "profile_id": row["profile_id"],
        "name": row["name"],
        "kind": "custom",
        "editable": True,
        "owner_user_id": row.get("owner_user_id"),
        "retrieval_profile": row["retrieval_base_profile"],
        "ragas_profile": row["ragas_base_profile"],
        "retrieval": _json_object(row.get("retrieval_config")),
        "ragas": _json_object(row.get("ragas_config")),
        "version": int(row.get("version") or 1),
        "created_at": row.get("created_at").isoformat() if row.get("created_at") else "",
        "updated_at": row.get("updated_at").isoformat() if row.get("updated_at") else "",
    }


def get_custom_profile(profile_id: str, owner_user_id: Optional[int] = None) -> Dict[str, Any]:
    """读取当前用户可访问的自定义 profile。"""
    clause, owner_params = _profile_owner_clause(owner_user_id)
    with db_cursor(write=False, consistency="strong", dictionary=True) as (_, cursor):
        cursor.execute(
            f"SELECT * FROM rag_eval_profiles WHERE profile_id = %s AND {clause}",
            (profile_id, *owner_params),
        )
        row = cursor.fetchone()
    if not row:
        raise KeyError(f"custom profile not found: {profile_id}")
    return _row_to_profile(row)


def get_strategy_profile(profile_id: str, owner_user_id: Optional[int] = None) -> Dict[str, Any]:
    """读取内置或自定义 unified strategy profile。"""
    if profile_id in BUILTIN_STRATEGIES:
        return _builtin_profile(profile_id)
    return get_custom_profile(profile_id, owner_user_id)


def _published_profile_id() -> str:
    """读取正式配置快照中的 profile 指针。"""
    path = Path(PRODUCTION_RAG_CONFIG_PATH)
    if not path.is_file():
        return "active_current"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        metadata = payload.get("metadata") if isinstance(payload, dict) else {}
        profile_id = metadata.get("profile_id") if isinstance(metadata, dict) else None
        return str(profile_id or "active_current")
    except (OSError, ValueError, TypeError):
        return "active_current"


def list_strategy_profiles(owner_user_id: Optional[int] = None) -> Dict[str, Any]:
    """返回内置只读 profile、自定义 profile 和正式 profile 指针。"""
    profiles = [_builtin_profile(profile_id) for profile_id in BUILTIN_STRATEGIES]
    clause, owner_params = _profile_owner_clause(owner_user_id)
    with db_cursor(write=False, consistency="strong", dictionary=True) as (_, cursor):
        cursor.execute(
            f"SELECT * FROM rag_eval_profiles WHERE {clause} ORDER BY updated_at DESC, id DESC",
            owner_params,
        )
        profiles.extend(_row_to_profile(row) for row in cursor.fetchall())
    published_id = _published_profile_id()
    if not any(profile["profile_id"] == published_id for profile in profiles):
        published_id = "active_current"
    return {
        "default_profile_id": published_id,
        "published_profile_id": published_id,
        "profiles": profiles,
    }


def _validate_profile_payload(payload: Dict[str, Any]) -> tuple[str, Dict[str, Any], Dict[str, Any], str, str]:
    """校验并裁剪自定义 profile 的持久化字段。"""
    name = str(payload.get("name") or "").strip()
    if not 1 <= len(name) <= 120:
        raise ValueError("profile name must contain 1 to 120 characters")
    retrieval = payload.get("retrieval")
    ragas = payload.get("ragas")
    if not isinstance(retrieval, dict) or not isinstance(ragas, dict):
        raise ValueError("retrieval and ragas must be objects")
    base_retrieval = str(payload.get("retrieval_profile") or "active_current")
    base_ragas = str(payload.get("ragas_profile") or "generic_pipeline")
    if base_retrieval not in RETRIEVAL_PROFILES:
        raise ValueError(f"unknown retrieval base profile: {base_retrieval}")
    if base_ragas not in RAGAS_RUN_PROFILES:
        raise ValueError(f"unknown ragas base profile: {base_ragas}")
    return name, dict(retrieval), {key: value for key, value in ragas.items() if key in PROFILE_RAGAS_KEYS}, base_retrieval, base_ragas


def create_custom_profile(payload: Dict[str, Any], owner_user_id: Optional[int] = None) -> Dict[str, Any]:
    """创建一个只读内置 profile 之外的自定义 profile。"""
    name, retrieval, ragas, base_retrieval, base_ragas = _validate_profile_payload(payload)
    profile_id = f"custom_{uuid.uuid4().hex[:20]}"
    with db_cursor(write=True, dictionary=True) as (conn, cursor):
        cursor.execute(
            """
            INSERT INTO rag_eval_profiles
                (profile_id, owner_user_id, name, retrieval_base_profile, ragas_base_profile,
                 retrieval_config, ragas_config)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                profile_id,
                owner_user_id,
                name,
                base_retrieval,
                base_ragas,
                json.dumps(retrieval, ensure_ascii=False),
                json.dumps(ragas, ensure_ascii=False),
            ),
        )
        conn.commit()
    return get_custom_profile(profile_id, owner_user_id)


def update_custom_profile(profile_id: str, payload: Dict[str, Any], owner_user_id: Optional[int] = None) -> Dict[str, Any]:
    """更新自定义 profile，不允许更新内置 profile。"""
    if profile_id in BUILTIN_STRATEGIES:
        raise ValueError("builtin profiles are read-only; use save as custom profile")
    name, retrieval, ragas, base_retrieval, base_ragas = _validate_profile_payload(payload)
    clause, owner_params = _profile_owner_clause(owner_user_id)
    with db_cursor(write=True, dictionary=True) as (conn, cursor):
        cursor.execute(
            f"""
            UPDATE rag_eval_profiles
            SET name = %s,
                retrieval_base_profile = %s,
                ragas_base_profile = %s,
                retrieval_config = %s,
                ragas_config = %s,
                version = version + 1
            WHERE profile_id = %s AND {clause}
            """,
            (
                name,
                base_retrieval,
                base_ragas,
                json.dumps(retrieval, ensure_ascii=False),
                json.dumps(ragas, ensure_ascii=False),
                profile_id,
                *owner_params,
            ),
        )
        if cursor.rowcount == 0:
            conn.rollback()
            raise KeyError(f"custom profile not found: {profile_id}")
        conn.commit()
    return get_custom_profile(profile_id, owner_user_id)


def delete_custom_profile(profile_id: str, owner_user_id: Optional[int] = None) -> None:
    """删除自定义 profile；内置 profile 永远不能删除。"""
    if profile_id in BUILTIN_STRATEGIES:
        raise ValueError("builtin profiles cannot be deleted")
    if _published_profile_id() == profile_id:
        raise ValueError("published profile cannot be deleted before another profile is published")
    clause, owner_params = _profile_owner_clause(owner_user_id)
    with db_cursor(write=True, dictionary=True) as (conn, cursor):
        cursor.execute(
            f"DELETE FROM rag_eval_profiles WHERE profile_id = %s AND {clause}",
            (profile_id, *owner_params),
        )
        if cursor.rowcount == 0:
            conn.rollback()
            raise KeyError(f"custom profile not found: {profile_id}")
        conn.commit()


def publish_custom_profile(profile_id: str, owner_user_id: Optional[int] = None, note: str = "") -> Dict[str, Any]:
    """把自定义 profile 的 retrieval 快照发布给正式 RAG，并切换默认 profile 指针。"""
    profile = get_custom_profile(profile_id, owner_user_id)
    path = Path(PRODUCTION_RAG_CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 2,
        "profile_id": profile["profile_id"],
        "profile_name": profile["name"],
        "retrieval_config": profile["retrieval"],
        "metadata": {
            "published_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "source": "rag_eval_profile",
            "profile_id": profile["profile_id"],
            "profile_name": profile["name"],
            "note": note,
        },
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return profile
