"""管理员审计事件的写入和有界读取服务。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json
import logging
from typing import Any

from app.db import get_read_connection, get_write_connection
from observability.logging_runtime import log_event


LOGGER = logging.getLogger(__name__)


def _json_default(value: Any) -> Any:
    """将审计值中的常见数据库类型转换为 JSON。"""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"无法序列化审计值类型: {type(value).__name__}")


def _json_value(value: Any) -> str | None:
    """把可选结构化值编码成 MySQL JSON 可接受的字符串。"""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def insert_admin_audit_event(
    cursor,
    *,
    actor: dict[str, Any],
    action: str,
    target_type: str,
    target_id: str | None,
    old_values: Any,
    new_values: Any,
    result: str,
    request_id: str,
    error_code: str | None = None,
) -> None:
    """使用调用方事务写入一条不包含秘密的管理员审计事件。"""
    cursor.execute(
        """
        INSERT INTO admin_audit_events (
            actor_user_id, actor_username, action, target_type, target_id,
            old_values_json, new_values_json, result, error_code, request_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            actor.get("id"),
            actor.get("username") or "unknown",
            action,
            target_type,
            target_id,
            _json_value(old_values),
            _json_value(new_values),
            result,
            error_code,
            request_id,
        ),
    )


def record_admin_audit_event(**event: Any) -> bool:
    """在独立事务中尽力记录拒绝或失败事件。"""
    try:
        with get_write_connection() as conn:
            cursor = conn.cursor()
            insert_admin_audit_event(cursor, **event)
            conn.commit()
        return True
    except Exception:
        log_event(
            LOGGER,
            "admin.audit.write_failed",
            details={
                "action": str(event.get("action") or "unknown"),
                "reason_code": "audit_write_failed",
            },
            exc_info=True,
        )
        return False


def _decode_json(value: Any) -> Any:
    """兼容连接器返回 JSON 字符串、字节或对象。"""
    if value is None or isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    return json.loads(value)


def list_monitor_setting_events(
    *,
    limit: int,
    before_id: int | None = None,
) -> dict[str, Any]:
    """按 ID 倒序读取监控配置审计事件并返回下一页游标。"""
    clauses = ["target_type = 'database_monitor_settings'"]
    params: list[Any] = []
    if before_id is not None:
        clauses.append("id < %s")
        params.append(before_id)
    params.append(limit + 1)
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            f"""
            SELECT id, actor_user_id, actor_username, action, target_id,
                   old_values_json, new_values_json, result, error_code,
                   request_id, created_at
            FROM admin_audit_events
            WHERE {' AND '.join(clauses)}
            ORDER BY id DESC
            LIMIT %s
            """,
            tuple(params),
        )
        rows = cursor.fetchall()
    has_more = len(rows) > limit
    items = rows[:limit]
    for item in items:
        item["old_values"] = _decode_json(item.pop("old_values_json"))
        item["new_values"] = _decode_json(item.pop("new_values_json"))
        if isinstance(item.get("created_at"), datetime):
            item["created_at"] = item["created_at"].isoformat(timespec="milliseconds")
    return {
        "items": items,
        "next_before_id": items[-1]["id"] if has_more and items else None,
    }
