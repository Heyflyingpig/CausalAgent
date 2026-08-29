"""数据库监控在线配置的解析、校验、缓存与事务写入。"""

from __future__ import annotations

from copy import deepcopy
import logging
import os
import threading
import time
from typing import Any

from app.admin.audit_service import (
    insert_admin_audit_event,
    record_admin_audit_event,
)
from app.db import get_read_connection, get_write_connection
from config.settings import settings
from observability.logging_runtime import log_event
from observability.noise_control import FailureTransitionTracker


LOGGER = logging.getLogger(__name__)
CACHE_TTL_SECONDS = 5.0
SETTINGS_ROW_ID = 1
MAX_SIGNED_INT = 2_147_483_647

FIELD_SPECS: dict[str, dict[str, Any]] = {
    "auto_refresh_enabled": {
        "env": "DB_MONITOR_AUTO_REFRESH_ENABLED",
        "attr": "DB_MONITOR_AUTO_REFRESH_ENABLED",
        "default": True,
        "type": "boolean",
    },
    "realtime_interval_seconds": {
        "env": "DB_MONITOR_REALTIME_INTERVAL_SECONDS",
        "attr": "DB_MONITOR_REALTIME_INTERVAL_SECONDS",
        "default": 10,
        "type": "integer",
        "minimum": 5,
        "maximum": 10,
    },
    "sql_interval_seconds": {
        "env": "DB_MONITOR_SQL_INTERVAL_SECONDS",
        "attr": "DB_MONITOR_SQL_INTERVAL_SECONDS",
        "default": 60,
        "type": "integer",
        "minimum": 30,
        "maximum": 60,
    },
    "table_capacity_interval_seconds": {
        "env": "DB_MONITOR_TABLE_CAPACITY_INTERVAL_SECONDS",
        "attr": "DB_MONITOR_TABLE_CAPACITY_INTERVAL_SECONDS",
        "default": 900,
        "type": "integer",
        "minimum": 300,
        "maximum": 900,
    },
    "slow_query_warning_delta": {
        "env": "DB_MONITOR_SLOW_QUERY_WARNING_DELTA",
        "attr": "DB_MONITOR_SLOW_QUERY_WARNING_DELTA",
        "default": 1,
        "type": "integer",
        "minimum": 1,
        "maximum": MAX_SIGNED_INT,
    },
    "integrity_enabled": {
        "env": "DB_MONITOR_INTEGRITY_ENABLED",
        "attr": "DB_MONITOR_INTEGRITY_ENABLED",
        "default": False,
        "type": "boolean",
    },
    "integrity_interval_seconds": {
        "env": "DB_MONITOR_INTEGRITY_INTERVAL_SECONDS",
        "attr": "DB_MONITOR_INTEGRITY_INTERVAL_SECONDS",
        "default": 86400,
        "type": "integer",
        "minimum": 3600,
        "maximum": MAX_SIGNED_INT,
    },
}
FIELD_NAMES = tuple(FIELD_SPECS)

_cache_lock = threading.Lock()
_cached_payload: dict[str, Any] | None = None
_cache_expires_at = 0.0
_last_good_payload: dict[str, Any] | None = None
_CONFIG_FAILURES = FailureTransitionTracker()


class MonitorSettingsValidationError(ValueError):
    """表示在线监控配置存在一个或多个字段错误。"""

    def __init__(self, errors: dict[str, str]):
        """保存逐字段错误，供 Flask API 返回稳定校验结构。"""
        super().__init__("数据库监控配置校验失败")
        self.errors = errors


class MonitorSettingsVersionConflict(RuntimeError):
    """表示提交版本已经落后于数据库当前版本。"""

    def __init__(self, current: dict[str, Any]):
        """保存当前配置，供冲突响应和前端重新加载。"""
        super().__init__("数据库监控配置版本冲突")
        self.current = current


def _base_values() -> tuple[dict[str, Any], dict[str, str]]:
    """返回环境变量/代码默认形成的基础值与逐字段来源。"""
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for name, spec in FIELD_SPECS.items():
        values[name] = getattr(settings, spec["attr"])
        sources[name] = (
            "environment"
            if os.environ.get(spec["env"]) not in (None, "")
            else "default"
        )
    return values, sources


def _read_settings_row() -> dict[str, Any]:
    """从主库强一致读取配置单例及最后修改人。"""
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT s.id, s.auto_refresh_enabled, s.realtime_interval_seconds,
                   s.sql_interval_seconds, s.table_capacity_interval_seconds,
                   s.slow_query_warning_delta, s.integrity_enabled,
                   s.integrity_interval_seconds, s.version,
                   s.updated_by_user_id, s.updated_at,
                   u.username AS updated_by_username
            FROM database_monitor_settings AS s
            LEFT JOIN users AS u ON u.id = s.updated_by_user_id
            WHERE s.id = 1
            """
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("database_monitor_settings 单例行不存在")
    return row


def _normalize_bool(value: Any) -> bool | None:
    """把 MySQL BOOLEAN 返回值规范为 Python bool。"""
    if value is None:
        return None
    return bool(value)


def _build_payload(row: dict[str, Any]) -> dict[str, Any]:
    """把数据库覆盖行合并为前后端共用的有效配置 DTO。"""
    base, sources = _base_values()
    overrides: dict[str, Any] = {}
    effective = dict(base)
    for name, spec in FIELD_SPECS.items():
        override = row.get(name)
        if spec["type"] == "boolean":
            override = _normalize_bool(override)
        overrides[name] = override
        if override is not None:
            effective[name] = override
            sources[name] = "database"
    updated_at = row.get("updated_at")
    if hasattr(updated_at, "isoformat"):
        updated_at = updated_at.isoformat(timespec="milliseconds")
    limits = {
        name: {
            key: spec[key]
            for key in ("type", "minimum", "maximum")
            if key in spec
        }
        for name, spec in FIELD_SPECS.items()
    }
    return {
        "version": int(row["version"]),
        "overrides": overrides,
        "effective": effective,
        "sources": sources,
        "limits": limits,
        "updated_by": (
            {
                "id": row.get("updated_by_user_id"),
                "username": row.get("updated_by_username"),
            }
            if row.get("updated_by_user_id") is not None
            else None
        ),
        "updated_at": updated_at,
        "state": "current",
        "warning": None,
    }


def _fallback_payload(exc: Exception, *, now: float | None = None) -> dict[str, Any]:
    """构造读取失败时的最后有效值或环境默认降级结果。"""
    if _last_good_payload is not None:
        payload = deepcopy(_last_good_payload)
    else:
        base, sources = _base_values()
        payload = {
            "version": None,
            "overrides": {name: None for name in FIELD_NAMES},
            "effective": base,
            "sources": sources,
            "limits": {
                name: {
                    key: spec[key]
                    for key in ("type", "minimum", "maximum")
                    if key in spec
                }
                for name, spec in FIELD_SPECS.items()
            },
            "updated_by": None,
            "updated_at": None,
        }
    payload["state"] = "degraded"
    payload["warning"] = "在线配置读取失败，当前继续使用最后有效值或环境默认值"
    decision = _CONFIG_FAILURES.record_failure(
        "online_settings",
        type(exc).__name__,
        now=now,
    )
    if decision.emit:
        log_event(
            LOGGER,
            "monitor.config.degraded",
            details={
                "reason_code": "config_read_failed",
                "suppressed_count": decision.suppressed_count,
            },
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    return payload


def get_monitor_settings(*, force_refresh: bool = False) -> dict[str, Any]:
    """读取最多缓存五秒的有效配置，失败时安全降级。"""
    global _cached_payload, _cache_expires_at, _last_good_payload
    now = time.monotonic()
    with _cache_lock:
        if (
            not force_refresh
            and _cached_payload is not None
            and now < _cache_expires_at
        ):
            return deepcopy(_cached_payload)
        try:
            payload = _build_payload(_read_settings_row())
            _last_good_payload = deepcopy(payload)
            recovery = _CONFIG_FAILURES.record_success("online_settings", now=now)
            if recovery is not None:
                log_event(
                    LOGGER,
                    "monitor.config.recovered",
                    details={
                        "downtime_ms": recovery.downtime_ms,
                        "failure_count": recovery.failure_count,
                    },
                )
        except Exception as exc:
            payload = _fallback_payload(exc, now=now)
        _cached_payload = deepcopy(payload)
        _cache_expires_at = now + CACHE_TTL_SECONDS
        return deepcopy(payload)


def get_effective_monitor_values(*, force_refresh: bool = False) -> dict[str, Any]:
    """返回调度器和采集器消费的七项有效值。"""
    return get_monitor_settings(force_refresh=force_refresh)["effective"]


def invalidate_monitor_settings_cache() -> None:
    """使当前进程下一次访问立即重新读取配置。"""
    global _cached_payload, _cache_expires_at
    with _cache_lock:
        _cached_payload = None
        _cache_expires_at = 0.0


def validate_monitor_overrides(overrides: Any) -> dict[str, Any]:
    """校验完整的七项可空覆盖快照并返回规范化结果。"""
    if not isinstance(overrides, dict):
        raise MonitorSettingsValidationError({"overrides": "overrides 必须是对象"})
    errors: dict[str, str] = {}
    missing = [name for name in FIELD_NAMES if name not in overrides]
    extra = [name for name in overrides if name not in FIELD_SPECS]
    if missing:
        errors["overrides"] = f"缺少字段: {', '.join(missing)}"
    if extra:
        errors["unknown_fields"] = f"不支持字段: {', '.join(extra)}"
    normalized: dict[str, Any] = {}
    for name, spec in FIELD_SPECS.items():
        value = overrides.get(name)
        if value is None:
            normalized[name] = None
            continue
        if spec["type"] == "boolean":
            if type(value) is not bool:
                errors[name] = "必须是 true、false 或 null"
            else:
                normalized[name] = value
            continue
        if type(value) is not int:
            errors[name] = "必须是整数或 null"
            continue
        minimum = spec["minimum"]
        maximum = spec["maximum"]
        if not minimum <= value <= maximum:
            errors[name] = f"必须在 {minimum} 到 {maximum} 之间"
        else:
            normalized[name] = value
    if errors:
        raise MonitorSettingsValidationError(errors)
    return normalized


def _row_overrides(row: dict[str, Any]) -> dict[str, Any]:
    """从锁定行提取规范化的七项数据库覆盖值。"""
    result = {}
    for name, spec in FIELD_SPECS.items():
        value = row.get(name)
        result[name] = _normalize_bool(value) if spec["type"] == "boolean" else value
    return result


def _record_rejected_event(
    *,
    actor: dict[str, Any],
    action: str,
    old_values: Any,
    new_values: Any,
    request_id: str,
    error_code: str,
) -> None:
    """在主事务以外尽力持久化被拒绝的配置写尝试。"""
    record_admin_audit_event(
        actor=actor,
        action=action,
        target_type="database_monitor_settings",
        target_id=str(SETTINGS_ROW_ID),
        old_values=old_values,
        new_values=new_values,
        result="rejected",
        error_code=error_code,
        request_id=request_id,
    )


def save_monitor_settings(
    *,
    version: Any,
    overrides: Any,
    actor: dict[str, Any],
    request_id: str,
    action: str = "db_monitor_settings.update",
) -> dict[str, Any]:
    """按乐观版本在一个主库事务中保存配置并写入成功审计。"""
    try:
        normalized = validate_monitor_overrides(overrides)
    except MonitorSettingsValidationError:
        _record_rejected_event(
            actor=actor,
            action=action,
            old_values=None,
            new_values=overrides,
            request_id=request_id,
            error_code="validation_error",
        )
        raise
    if type(version) is not int or version < 1:
        error = MonitorSettingsValidationError({"version": "version 必须是正整数"})
        _record_rejected_event(
            actor=actor,
            action=action,
            old_values=None,
            new_values=normalized,
            request_id=request_id,
            error_code="validation_error",
        )
        raise error

    with get_write_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT auto_refresh_enabled, realtime_interval_seconds,
                   sql_interval_seconds, table_capacity_interval_seconds,
                   slow_query_warning_delta, integrity_enabled,
                   integrity_interval_seconds, version
            FROM database_monitor_settings
            WHERE id = 1
            FOR UPDATE
            """
        )
        current = cursor.fetchone()
        if current is None:
            conn.rollback()
            raise RuntimeError("database_monitor_settings 单例行不存在")
        old_values = _row_overrides(current)
        if int(current["version"]) != version:
            conn.rollback()
            invalidate_monitor_settings_cache()
            current_payload = get_monitor_settings(force_refresh=True)
            _record_rejected_event(
                actor=actor,
                action=action,
                old_values=old_values,
                new_values=normalized,
                request_id=request_id,
                error_code="version_conflict",
            )
            raise MonitorSettingsVersionConflict(current_payload)
        cursor.execute(
            """
            UPDATE database_monitor_settings
            SET auto_refresh_enabled = %s,
                realtime_interval_seconds = %s,
                sql_interval_seconds = %s,
                table_capacity_interval_seconds = %s,
                slow_query_warning_delta = %s,
                integrity_enabled = %s,
                integrity_interval_seconds = %s,
                version = version + 1,
                updated_by_user_id = %s
            WHERE id = 1 AND version = %s
            """,
            (
                normalized["auto_refresh_enabled"],
                normalized["realtime_interval_seconds"],
                normalized["sql_interval_seconds"],
                normalized["table_capacity_interval_seconds"],
                normalized["slow_query_warning_delta"],
                normalized["integrity_enabled"],
                normalized["integrity_interval_seconds"],
                actor["id"],
                version,
            ),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            invalidate_monitor_settings_cache()
            current_payload = get_monitor_settings(force_refresh=True)
            raise MonitorSettingsVersionConflict(current_payload)
        audit_cursor = conn.cursor()
        insert_admin_audit_event(
            audit_cursor,
            actor=actor,
            action=action,
            target_type="database_monitor_settings",
            target_id=str(SETTINGS_ROW_ID),
            old_values=old_values,
            new_values=normalized,
            result="success",
            error_code=None,
            request_id=request_id,
        )
        conn.commit()
    invalidate_monitor_settings_cache()
    return get_monitor_settings(force_refresh=True)


def reset_monitor_settings(
    *,
    version: Any,
    actor: dict[str, Any],
    request_id: str,
) -> dict[str, Any]:
    """把七项覆盖全部重置为空并复用同一乐观锁与审计事务。"""
    return save_monitor_settings(
        version=version,
        overrides={name: None for name in FIELD_NAMES},
        actor=actor,
        request_id=request_id,
        action="db_monitor_settings.reset",
    )
