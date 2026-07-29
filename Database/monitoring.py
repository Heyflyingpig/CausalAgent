"""数据库看板共享快照仓储、分层采集和旧接口兼容层。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import logging
from typing import Any, Iterable

from Database.inspection import (
    get_capacity_report,
    get_quick_integrity_report,
    get_realtime_report,
    inspect_slow_queries,
)
from Database.monitor_settings import get_monitor_settings
from app.db import get_read_connection_with_source, get_write_connection


LOGGER = logging.getLogger(__name__)
SNAPSHOT_KEYS = ("realtime", "sql_performance", "capacity", "integrity")
DEFAULT_REFRESH_GROUPS = ("realtime", "sql_performance", "capacity")
SLOW_QUERY_LIMIT = 20


def _utc_now() -> datetime:
    """返回带时区的当前 UTC 时间。"""
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime | None = None) -> str:
    """把时间统一序列化为毫秒精度 UTC ISO 8601。"""
    current = value or _utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_utc(value: Any) -> datetime | None:
    """解析数据库时间或 ISO 字符串，无法识别时返回 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _json_default(value: Any) -> Any:
    """序列化数据库游标可能返回的时间、Decimal 和二进制值。"""
    if isinstance(value, datetime):
        return _iso_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    raise TypeError(f"无法序列化监控快照类型: {type(value).__name__}")


def _decode_payload(value: Any) -> dict[str, Any] | None:
    """兼容连接器返回 JSON 字符串或字典的两种形式。"""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    decoded = json.loads(value)
    return decoded if isinstance(decoded, dict) else None


def _interval_seconds(
    snapshot_key: str,
    policy: dict[str, Any] | None = None,
) -> int:
    """从统一配置取得某类快照的采集周期。"""
    effective = policy or get_monitor_settings()["effective"]
    intervals = {
        "realtime": effective["realtime_interval_seconds"],
        "sql_performance": effective["sql_interval_seconds"],
        "capacity": effective["table_capacity_interval_seconds"],
        "integrity": effective["integrity_interval_seconds"],
    }
    return int(intervals[snapshot_key])


def _scheduled(
    snapshot_key: str,
    policy: dict[str, Any] | None = None,
) -> bool:
    """判断某类快照是否允许自动定时采集。"""
    effective = policy or get_monitor_settings()["effective"]
    if not effective["auto_refresh_enabled"]:
        return False
    return snapshot_key != "integrity" or effective["integrity_enabled"]


def get_refresh_policy() -> dict[str, Any]:
    """返回供采集器和前端共同使用的有效刷新策略。"""
    resolved = get_monitor_settings()
    effective = resolved["effective"]
    return {
        **effective,
        "configuration_version": resolved["version"],
        "configuration_state": resolved["state"],
        "configuration_warning": resolved["warning"],
    }


def _read_snapshot_records() -> dict[str, dict[str, Any]]:
    """通过主库强一致读一次取得全部共享快照行。"""
    connection, _source = get_read_connection_with_source(consistency="strong")
    with connection as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT snapshot_key, payload_json, observed_at, refresh_requested_at, updated_at,
                   UTC_TIMESTAMP(6) AS database_now
            FROM database_monitor_snapshots
            WHERE snapshot_key IN ('realtime', 'sql_performance', 'capacity', 'integrity')
        """)
        rows = cursor.fetchall()
    return {row["snapshot_key"]: row for row in rows}


def _empty_snapshot(snapshot_key: str) -> dict[str, Any]:
    """构造尚未采集时的统一降级快照。"""
    return {
        "status": "unknown",
        "observed_at": None,
        "source_role": "monitor",
        "source_alias": "shared-snapshot",
        "is_estimate": snapshot_key == "capacity",
        "warning": "尚未生成共享监控快照",
    }


def _enrich_snapshot(
    snapshot_key: str,
    row: dict[str, Any] | None,
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """为持久化 payload 补充过期、调度和手动请求状态。"""
    payload = _decode_payload(row.get("payload_json")) if row else None
    result = dict(payload or _empty_snapshot(snapshot_key))
    observed_at = _parse_utc((row or {}).get("observed_at") or result.get("observed_at"))
    requested_at = _parse_utc((row or {}).get("refresh_requested_at"))
    effective = policy or get_monitor_settings()["effective"]
    interval = _interval_seconds(snapshot_key, effective)
    now = _parse_utc((row or {}).get("database_now")) or _utc_now()
    result["observed_at"] = _iso_utc(observed_at) if observed_at else None
    result["refresh_requested_at"] = _iso_utc(requested_at) if requested_at else None
    result["refresh_pending"] = bool(requested_at and (not observed_at or requested_at > observed_at))
    result["scheduled"] = _scheduled(snapshot_key, effective)
    result["interval_seconds"] = interval
    result["is_stale"] = not observed_at or now - observed_at > timedelta(seconds=interval * 2)
    result["next_due_at"] = (
        _iso_utc(observed_at + timedelta(seconds=interval))
        if observed_at and result["scheduled"]
        else None
    )
    return result


def get_dashboard_snapshots() -> dict[str, Any]:
    """返回全部共享快照；该函数绝不触发现场数据库采集。"""
    resolved = get_monitor_settings()
    effective = resolved["effective"]
    try:
        records = _read_snapshot_records()
    except Exception as exc:
        LOGGER.warning("读取数据库监控共享快照失败: %s", exc, exc_info=True)
        records = {}
    return {
        key: _enrich_snapshot(key, records.get(key), policy=effective)
        for key in SNAPSHOT_KEYS
    } | {
        "refresh_policy": {
            **effective,
            "configuration_version": resolved["version"],
            "configuration_state": resolved["state"],
            "configuration_warning": resolved["warning"],
        }
    }


def request_snapshot_refresh(groups: Iterable[str]) -> dict[str, Any]:
    """登记共享刷新请求；真正采集由独立 monitor 进程执行。"""
    normalized = tuple(dict.fromkeys(groups))
    invalid = [group for group in normalized if group not in SNAPSHOT_KEYS]
    if invalid or not normalized:
        raise ValueError(f"不支持的监控快照类型: {invalid or list(normalized)}")
    with get_write_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        for group in normalized:
            cursor.execute("""
                INSERT INTO database_monitor_snapshots (snapshot_key, refresh_requested_at)
                VALUES (%s, UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE refresh_requested_at = CASE
                    WHEN refresh_requested_at IS NULL THEN VALUES(refresh_requested_at)
                    ELSE GREATEST(refresh_requested_at, VALUES(refresh_requested_at))
                END
            """, (group,))
        placeholders = ", ".join(["%s"] * len(normalized))
        cursor.execute(
            f"""SELECT MAX(refresh_requested_at) AS requested_at
                FROM database_monitor_snapshots
                WHERE snapshot_key IN ({placeholders})""",
            normalized,
        )
        row = cursor.fetchone() or {}
        requested_at = _parse_utc(row.get("requested_at"))
        conn.commit()
    if requested_at is None:
        raise RuntimeError("数据库未返回共享刷新请求时间")
    return {"groups": list(normalized), "requested_at": _iso_utc(requested_at)}


def _result_status(results: Iterable[dict[str, Any]]) -> str:
    """按 error、warning/unknown、healthy 优先级汇总状态。"""
    statuses = {result.get("status") for result in results}
    if "error" in statuses:
        return "error"
    if statuses.intersection({"warning", "unknown"}):
        return "warning"
    return "healthy"


def get_slow_query_summary(
    limit: int = SLOW_QUERY_LIMIT,
    previous: dict[str, Any] | None = None,
    warning_threshold: int | None = None,
) -> dict[str, Any]:
    """采集并展平 SQL 性能结果，同时保留旧慢查询字段。"""
    result = inspect_slow_queries(
        limit=limit,
        previous=previous,
        warning_threshold=warning_threshold,
    )
    value = result.get("value") or {}
    statements = value.get("high_load_statements", value.get("top_statements") or [])
    return {
        **value,
        "Slow_queries": value.get("slow_queries_total", value.get("Slow_queries")),
        "slow_queries_total": value.get("slow_queries_total", value.get("Slow_queries")),
        "slow_queries_delta": value.get("slow_queries_delta"),
        "high_load_statements": statements,
        "top_statements": statements,
        "status": result["status"],
        "observed_at": result["observed_at"],
        "source_role": result["source_role"],
        "source_alias": result["source_alias"],
        "is_estimate": result["is_estimate"],
        "warning": result["warning"],
    }


def _collect_payload(
    snapshot_key: str,
    previous: dict[str, Any] | None,
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """调用指定分层采集器，路由和 SQL 均不包含调度策略。"""
    effective = policy or get_monitor_settings()["effective"]
    if snapshot_key == "realtime":
        return get_realtime_report()
    if snapshot_key == "sql_performance":
        return get_slow_query_summary(
            previous=previous,
            warning_threshold=effective["slow_query_warning_delta"],
        )
    if snapshot_key == "capacity":
        return get_capacity_report()
    if snapshot_key == "integrity":
        return get_quick_integrity_report()
    raise ValueError(f"未知监控快照类型: {snapshot_key}")


def _collection_failure_payload(snapshot_key: str, exc: Exception) -> dict[str, Any]:
    """把单层采集器的未处理异常转换为可持久化的降级快照。"""
    LOGGER.error("采集共享监控快照失败 [%s]: %s", snapshot_key, exc, exc_info=True)
    payload: dict[str, Any] = {
        "status": "unknown",
        "observed_at": _iso_utc(),
        "source_role": "monitor",
        "source_alias": "shared-snapshot",
        "is_estimate": snapshot_key == "capacity",
        "warning": f"{snapshot_key} 采集失败，已记录降级快照",
    }
    if snapshot_key == "sql_performance":
        payload.update({
            "Slow_queries": None,
            "slow_queries_total": None,
            "slow_queries_delta": None,
            "high_load_statements": [],
            "top_statements": [],
            "baseline_reset": True,
        })
    if snapshot_key == "integrity":
        payload.update({"blocking_count": 0, "blocking_record_count": 0, "checks": []})
    return payload


def collect_snapshot(snapshot_key: str, *, require_due: bool = False) -> bool:
    """在 MySQL 命名锁保护下复核调度状态并采集一个共享快照。"""
    if snapshot_key not in SNAPSHOT_KEYS:
        raise ValueError(f"未知监控快照类型: {snapshot_key}")
    lock_name = f"causalchat:db-monitor:{snapshot_key}"
    with get_write_connection() as lock_connection:
        cursor = lock_connection.cursor(dictionary=True)
        cursor.execute("SELECT GET_LOCK(%s, 0) AS acquired", (lock_name,))
        acquired = int((cursor.fetchone() or {}).get("acquired") or 0) == 1
        if not acquired:
            return False
        try:
            records = _read_snapshot_records()
            effective = get_monitor_settings()["effective"]
            if require_due and not _record_is_due(
                snapshot_key,
                records.get(snapshot_key),
                policy=effective,
            ):
                return False
            previous = _decode_payload((records.get(snapshot_key) or {}).get("payload_json"))
            try:
                payload = _collect_payload(
                    snapshot_key,
                    previous,
                    policy=effective,
                )
            except Exception as exc:
                payload = _collection_failure_payload(snapshot_key, exc)
            cursor.execute("""
                INSERT INTO database_monitor_snapshots (
                    snapshot_key, payload_json, observed_at
                ) VALUES (%s, %s, UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE
                    payload_json = VALUES(payload_json),
                    observed_at = VALUES(observed_at)
            """, (
                snapshot_key,
                json.dumps(payload, ensure_ascii=False, default=_json_default),
            ))
            lock_connection.commit()
            return True
        finally:
            try:
                cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
                cursor.fetchone()
            except Exception:
                LOGGER.warning("释放监控采集锁失败: %s", snapshot_key, exc_info=True)


def _record_is_due(
    snapshot_key: str,
    row: dict[str, Any] | None,
    *,
    policy: dict[str, Any] | None = None,
) -> bool:
    """判断快照是否因手动请求或自动周期到期而需要采集。"""
    effective = policy or get_monitor_settings()["effective"]
    observed_at = _parse_utc((row or {}).get("observed_at"))
    requested_at = _parse_utc((row or {}).get("refresh_requested_at"))
    if requested_at and (not observed_at or requested_at > observed_at):
        return True
    if not _scheduled(snapshot_key, effective):
        return False
    now = _parse_utc((row or {}).get("database_now")) or _utc_now()
    return not observed_at or now - observed_at >= timedelta(
        seconds=_interval_seconds(snapshot_key, effective)
    )


def get_due_snapshot_keys() -> tuple[str, ...]:
    """读取一次调度状态并返回当前到期或收到手动请求的快照类型。"""
    try:
        records = _read_snapshot_records()
    except Exception as exc:
        LOGGER.warning("读取监控调度状态失败: %s", exc, exc_info=True)
        return ()
    effective = get_monitor_settings()["effective"]
    return tuple(
        snapshot_key
        for snapshot_key in SNAPSHOT_KEYS
        if _record_is_due(
            snapshot_key,
            records.get(snapshot_key),
            policy=effective,
        )
    )


def collect_due_snapshots() -> dict[str, bool]:
    """同步采集所有到期类型；常驻 monitor 使用独立执行单元避免跨层阻塞。"""
    results: dict[str, bool] = {}
    for snapshot_key in get_due_snapshot_keys():
        try:
            results[snapshot_key] = collect_snapshot(snapshot_key, require_due=True)
        except Exception as exc:
            LOGGER.error("采集共享监控快照失败 [%s]: %s", snapshot_key, exc, exc_info=True)
            results[snapshot_key] = False
    return results


def _overview_from_dashboard(dashboard: dict[str, Any]) -> dict[str, Any]:
    """从一次 dashboard 读取结果组装旧 overview 数据结构。"""
    realtime = dashboard["realtime"]
    capacity = dashboard["capacity"]
    primary = realtime.get("primary") or _empty_snapshot("realtime")
    replica = realtime.get("replica") or _empty_snapshot("realtime")
    connections = realtime.get("connections") or _empty_snapshot("realtime")
    revision = capacity.get("revision") or _empty_snapshot("capacity")
    tables = capacity.get("tables") or _empty_snapshot("capacity")
    blocks = [revision, primary, replica, connections, tables]
    return {
        "status": _result_status(blocks),
        "observed_at": max(
            (item.get("observed_at") for item in blocks if item.get("observed_at")),
            default=None,
        ),
        "revision": revision,
        "primary": primary,
        "replica": replica,
        "connections": connections,
        "tables": tables,
        "blocking_issues": [
            *(realtime.get("blocking_issues") or []),
            *(capacity.get("blocking_issues") or []),
        ],
    }


def get_database_overview_snapshot() -> dict[str, Any]:
    """从共享快照组装旧 overview 数据结构。"""
    return _overview_from_dashboard(get_dashboard_snapshots())


def _legacy_replica_value(replica: dict[str, Any]) -> dict[str, Any] | None:
    """把标准从库检查结果映射回旧接口字段。"""
    value = replica.get("value")
    if not value or not value.get("available"):
        return None
    return {
        "Replica_IO_Running": value.get("io_running"),
        "Replica_SQL_Running": value.get("sql_running"),
        "Seconds_Behind_Source": value.get("lag_seconds"),
        "Last_IO_Error": value.get("last_io_error"),
        "Last_SQL_Error": value.get("last_sql_error"),
    }


def get_db_health() -> dict[str, Any]:
    """从共享快照返回兼容旧字段的数据库健康摘要。"""
    dashboard = get_dashboard_snapshots()
    overview = _overview_from_dashboard(dashboard)
    connection_value = overview["connections"].get("value") or {}
    table_value = overview["tables"].get("value") or []
    sql_snapshot = dashboard["sql_performance"]
    return {
        "connections": {
            "Threads_connected": connection_value.get("threads_connected"),
            "Threads_running": connection_value.get("threads_running"),
            "max_connections": connection_value.get("max_connections"),
        },
        "slow_queries": sql_snapshot.get("slow_queries_total", sql_snapshot.get("Slow_queries")),
        "replica": _legacy_replica_value(overview["replica"]),
        "tables": table_value,
        "status": overview["status"],
        "observed_at": overview["observed_at"],
        "sources": {
            key: {
                "source_role": overview[key].get("source_role"),
                "source_alias": overview[key].get("source_alias"),
                "observed_at": overview[key].get("observed_at"),
                "is_estimate": overview[key].get("is_estimate", False),
                "warning": overview[key].get("warning"),
            }
            for key in ("connections", "replica", "tables")
        },
    }


def get_integrity_snapshot() -> dict[str, Any]:
    """读取最近一次运行期完整性审计快照。"""
    return get_dashboard_snapshots()["integrity"]


def get_sql_performance_snapshot(limit: int = SLOW_QUERY_LIMIT) -> dict[str, Any]:
    """读取 SQL 性能快照，并在兼容接口上限制返回行数。"""
    result = dict(get_dashboard_snapshots()["sql_performance"])
    statements = result.get("high_load_statements") or result.get("top_statements") or []
    result["high_load_statements"] = statements[:limit]
    result["top_statements"] = statements[:limit]
    result["Slow_queries"] = result.get("slow_queries_total", result.get("Slow_queries"))
    result["limit"] = limit
    return result


def get_worker_snapshot_from_cache() -> dict[str, Any]:
    """读取实时快照内的 Worker/Job 区块。"""
    realtime = get_dashboard_snapshots()["realtime"]
    return realtime.get("jobs") or {
        "jobs": [],
        "summary": {"queued": None, "running": None, "stale": None, "max_attempts_running": None},
        "status": "unknown",
        "observed_at": realtime.get("observed_at"),
        "source_role": "primary",
        "source_alias": "primary",
        "is_estimate": False,
        "warning": realtime.get("warning") or "尚未采集 Worker/Job 快照",
    }
