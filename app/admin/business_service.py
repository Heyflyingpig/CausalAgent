"""管理员 3.1 只读业务数据查询、正文分块与文件访问服务。"""

from __future__ import annotations

import csv
from datetime import datetime
from io import BytesIO, StringIO
import json
import os
from typing import Any

from app.admin.audit_service import insert_admin_audit_event
from app.admin.contracts import (
    AdminApiError,
    decode_cursor,
    page_result,
)
from app.db import get_read_connection, get_write_connection
from app.request_context import get_request_id


CSV_PREVIEW_BYTES = 256 * 1024
CSV_PREVIEW_ROWS = 100
CSV_PREVIEW_COLUMNS = 50
CSV_PREVIEW_CELL_CHARS = 1000

USER_ROLES = {"user", "admin"}
JOB_STATUSES = {"queued", "running", "succeeded", "failed", "canceled"}
MESSAGE_TYPES = {"user", "ai"}
CONTENT_KINDS = {"input", "result", "error"}


def _decode_json(value: Any) -> Any:
    """兼容 MySQL JSON 返回的字典、字符串和字节形式。"""
    if value is None or isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    return json.loads(value)


def _prefix_like(value: str) -> str:
    """把用户名或标题搜索词转换为转义后的前缀匹配。"""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%"


def _validated_search(value: str | None) -> str | None:
    """规范化最长 100 字符的列表搜索词。"""
    normalized = (value or "").strip()
    if not normalized:
        return None
    if len(normalized) > 100:
        raise AdminApiError(
            code="invalid_query",
            message="搜索词不能超过 100 个字符",
            fields={"q": "不能超过 100 个字符"},
        )
    return normalized


def _validated_positive_id(value: str | int | None, *, field: str) -> int | None:
    """把可选 ID 解析为正整数。"""
    if value in (None, ""):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise AdminApiError(
            code="invalid_query",
            message=f"{field} 必须是正整数",
            fields={field: "必须是正整数"},
        ) from exc
    if result <= 0:
        raise AdminApiError(
            code="invalid_query",
            message=f"{field} 必须是正整数",
            fields={field: "必须是正整数"},
        )
    return result


def _validated_enum(
    value: str | None,
    *,
    field: str,
    allowed: set[str],
) -> str | None:
    """验证可选枚举查询参数。"""
    if value in (None, ""):
        return None
    if value not in allowed:
        raise AdminApiError(
            code="invalid_query",
            message=f"{field} 取值无效",
            fields={field: f"仅支持 {', '.join(sorted(allowed))}"},
        )
    return value


def _validated_bool(value: str | None, *, field: str) -> bool | None:
    """解析查询字符串中的严格 true/false。"""
    if value in (None, ""):
        return None
    normalized = value.lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise AdminApiError(
        code="invalid_query",
        message=f"{field} 仅支持 true/false",
        fields={field: "仅支持 true/false"},
    )


def _timestamp_cursor(value: Any) -> datetime:
    """把游标中的 ISO 时间恢复为无时区数据库时间。"""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise AdminApiError(
            code="invalid_cursor",
            message="分页游标时间无效",
            fields={"cursor": "时间无法解析"},
        ) from exc
    return parsed.replace(tzinfo=None)


def _decode_text_chunk(content: bytes, *, limit: int) -> tuple[str, int]:
    """在 64 KiB 源字节边界内回退到完整 UTF-8 字符，避免分块破坏正文。"""
    candidate = content[:limit]
    while candidate:
        try:
            return candidate.decode("utf-8"), len(candidate)
        except UnicodeDecodeError as exc:
            if exc.reason == "unexpected end of data" and exc.end == len(candidate):
                candidate = candidate[:exc.start]
                continue
            return candidate.decode("utf-8", errors="replace"), len(candidate)
    return content[:1].decode("utf-8", errors="replace"), min(1, len(content))


def get_business_overview() -> dict[str, Any]:
    """返回表级估算数量和最近共享快照摘要，不执行无界 COUNT。"""
    table_labels = {
        "users": "用户",
        "sessions": "会话",
        "chat_messages": "消息",
        "chat_attachments": "附件",
        "uploaded_files": "文件",
        "analysis_jobs": "分析任务",
        "analysis_job_events": "任务事件",
    }
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        placeholders = ", ".join(["%s"] * len(table_labels))
        cursor.execute(
            f"""
            SELECT TABLE_NAME AS table_name, TABLE_ROWS AS table_rows
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME IN ({placeholders})
            """,
            tuple(table_labels),
        )
        estimates = {
            row["table_name"]: int(row.get("table_rows") or 0)
            for row in cursor.fetchall()
        }
        cursor.execute("""
            SELECT snapshot_key, observed_at, refresh_requested_at, payload_json
            FROM database_monitor_snapshots
            WHERE snapshot_key IN (
                'realtime', 'sql_performance', 'capacity', 'integrity', 'deep_audit'
            )
            ORDER BY snapshot_key
        """)
        snapshot_rows = cursor.fetchall()
        cursor.execute("SELECT UTC_TIMESTAMP(6) AS observed_at")
        observed_at = (cursor.fetchone() or {}).get("observed_at")

    metrics = [
        {
            "key": table_name,
            "label": label,
            "value": estimates.get(table_name, 0),
            "is_estimate": True,
            "source_alias": "primary-schema-estimate",
        }
        for table_name, label in table_labels.items()
    ]
    snapshots = []
    for row in snapshot_rows:
        payload = _decode_json(row.pop("payload_json")) or {}
        snapshots.append({
            **row,
            "status": payload.get("status", "unknown"),
            "warning": payload.get("warning"),
            "source_alias": payload.get("source_alias", "shared-snapshot"),
        })
    return {
        "metrics": metrics,
        "snapshots": snapshots,
        "observed_at": observed_at,
        "source_alias": "primary+shared-snapshot",
        "is_estimate": True,
    }


def list_users(
    *,
    limit: int,
    cursor: str | None,
    q: str | None,
    role: str | None,
    is_active: str | None,
) -> dict[str, Any]:
    """按主键倒序分页读取脱敏用户列表。"""
    search = _validated_search(q)
    normalized_role = _validated_enum(role, field="role", allowed=USER_ROLES)
    active = _validated_bool(is_active, field="is_active")
    cursor_values = decode_cursor(cursor, size=1)
    clauses = ["1 = 1"]
    params: list[Any] = []
    if search:
        clauses.append("username LIKE %s")
        params.append(_prefix_like(search))
    if normalized_role:
        clauses.append("role = %s")
        params.append(normalized_role)
    if active is not None:
        clauses.append("is_active = %s")
        params.append(active)
    if cursor_values:
        clauses.append("id < %s")
        params.append(_validated_positive_id(cursor_values[0], field="cursor"))
    params.append(limit + 1)
    with get_read_connection(consistency="strong") as conn:
        db_cursor = conn.cursor(dictionary=True)
        db_cursor.execute(
            f"""
            SELECT id, username, role, is_active, created_at, last_login_at
            FROM users
            WHERE {' AND '.join(clauses)}
            ORDER BY id DESC
            LIMIT %s
            """,
            tuple(params),
        )
        rows = db_cursor.fetchall()
    for row in rows:
        row["is_active"] = bool(row.get("is_active"))
    return page_result(rows, limit=limit, cursor_fields=("id",))


def get_user_detail(user_id: int) -> dict[str, Any]:
    """读取单个用户的允许展示字段。"""
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, username, role, is_active, created_at, last_login_at
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        )
        row = cursor.fetchone()
    if not row:
        raise AdminApiError("not_found", "用户不存在", 404)
    row["is_active"] = bool(row.get("is_active"))
    return row


def list_sessions(
    *,
    limit: int,
    cursor: str | None,
    q: str | None,
    user_id: str | None,
    is_archived: str | None,
) -> dict[str, Any]:
    """按最后活动时间稳定分页读取会话摘要。"""
    search = _validated_search(q)
    owner_id = _validated_positive_id(user_id, field="user_id")
    archived = _validated_bool(is_archived, field="is_archived")
    cursor_values = decode_cursor(cursor, size=2)
    clauses = ["1 = 1"]
    params: list[Any] = []
    if search:
        clauses.append("(s.id = %s OR s.title LIKE %s)")
        params.extend((search, _prefix_like(search)))
    if owner_id:
        clauses.append("s.user_id = %s")
        params.append(owner_id)
    if archived is not None:
        clauses.append("s.is_archived = %s")
        params.append(archived)
    if cursor_values:
        activity = _timestamp_cursor(cursor_values[0])
        session_id = str(cursor_values[1])
        clauses.append(
            "(s.last_activity_at < %s "
            "OR (s.last_activity_at = %s AND s.id < %s))"
        )
        params.extend((activity, activity, session_id))
    params.append(limit + 1)
    with get_read_connection(consistency="strong") as conn:
        db_cursor = conn.cursor(dictionary=True)
        db_cursor.execute(
            f"""
            SELECT s.id, s.user_id, u.username, s.title, s.created_at,
                   s.last_activity_at, s.message_count, s.is_archived, s.archived_at
            FROM sessions AS s
            JOIN users AS u ON u.id = s.user_id
            WHERE {' AND '.join(clauses)}
            ORDER BY s.last_activity_at DESC, s.id DESC
            LIMIT %s
            """,
            tuple(params),
        )
        rows = db_cursor.fetchall()
    for row in rows:
        row["is_archived"] = bool(row.get("is_archived"))
    return page_result(
        rows,
        limit=limit,
        cursor_fields=("last_activity_at", "id"),
    )


def get_session_detail(session_id: str) -> dict[str, Any]:
    """读取会话元数据，不在详情响应中夹带消息正文。"""
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT s.id, s.user_id, u.username, s.title, s.created_at,
                   s.last_activity_at, s.message_count, s.is_archived, s.archived_at
            FROM sessions AS s
            JOIN users AS u ON u.id = s.user_id
            WHERE s.id = %s
            """,
            (session_id,),
        )
        row = cursor.fetchone()
    if not row:
        raise AdminApiError("not_found", "会话不存在", 404)
    row["is_archived"] = bool(row.get("is_archived"))
    return row


def list_session_messages(
    *,
    session_id: str,
    limit: int,
    cursor: str | None,
    message_type: str | None,
) -> dict[str, Any]:
    """读取消息摘要并通过独立接口延迟读取正文。"""
    normalized_type = _validated_enum(
        message_type,
        field="message_type",
        allowed=MESSAGE_TYPES,
    )
    cursor_values = decode_cursor(cursor, size=1)
    clauses = ["m.session_id = %s"]
    params: list[Any] = [session_id]
    if normalized_type:
        clauses.append("m.message_type = %s")
        params.append(normalized_type)
    if cursor_values:
        clauses.append("m.id < %s")
        params.append(_validated_positive_id(cursor_values[0], field="cursor"))
    params.append(limit + 1)
    with get_read_connection(consistency="strong") as conn:
        db_cursor = conn.cursor(dictionary=True)
        db_cursor.execute(
            "SELECT 1 AS present FROM sessions WHERE id = %s",
            (session_id,),
        )
        if not db_cursor.fetchone():
            raise AdminApiError("not_found", "会话不存在", 404)
        db_cursor.execute(
            f"""
            SELECT m.id, m.session_id, m.user_id, u.username, m.message_type,
                   CONCAT('正文 ', CHAR_LENGTH(m.content), ' 字符') AS content_preview,
                   CHAR_LENGTH(m.content) AS content_length,
                   m.has_attachment, m.created_at,
                   (
                       SELECT COUNT(*)
                       FROM chat_attachments AS a
                       WHERE a.message_id = m.id
                   ) AS attachment_count
            FROM chat_messages AS m
            JOIN users AS u ON u.id = m.user_id
            WHERE {' AND '.join(clauses)}
            ORDER BY m.id DESC
            LIMIT %s
            """,
            tuple(params),
        )
        rows = db_cursor.fetchall()
    for row in rows:
        row["has_attachment"] = bool(row.get("has_attachment"))
    return page_result(rows, limit=limit, cursor_fields=("id",))


def list_message_attachments(message_id: int) -> list[dict[str, Any]]:
    """读取消息附件的类型、大小和时间，不返回附件正文。"""
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, message_id, attachment_type, content_size, created_at
            FROM chat_attachments
            WHERE message_id = %s
            ORDER BY id
            LIMIT 50
            """,
            (message_id,),
        )
        rows = cursor.fetchall()
        if not rows:
            cursor.execute(
                "SELECT 1 AS present FROM chat_messages WHERE id = %s LIMIT 1",
                (message_id,),
            )
            if not cursor.fetchone():
                raise AdminApiError("not_found", "消息不存在", 404)
    return rows


def _read_text_chunk(
    *,
    table: str,
    id_column: str,
    id_value: Any,
    content_sql: str,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    """从固定白名单表读取有界正文片段及总长度。"""
    allowed_tables = {
        "chat_messages",
        "chat_attachments",
        "analysis_jobs",
    }
    if table not in allowed_tables:
        raise ValueError(f"不支持的正文表: {table}")
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            f"""
            SELECT SUBSTRING(
                       CAST(({content_sql}) AS BINARY),
                       %s,
                       %s
                   ) AS content,
                   OCTET_LENGTH(({content_sql})) AS total_length
            FROM {table}
            WHERE {id_column} = %s
            """,
            (offset + 1, limit + 4, id_value),
        )
        row = cursor.fetchone()
    if not row:
        raise AdminApiError("not_found", "敏感正文不存在", 404)
    content = row.get("content")
    if content is None:
        content = ""
    returned_bytes: int
    if isinstance(content, (dict, list)):
        content = json.dumps(content, ensure_ascii=False, indent=2)
        returned_bytes = len(content.encode("utf-8"))
    elif isinstance(content, (bytes, bytearray)):
        content, returned_bytes = _decode_text_chunk(bytes(content), limit=limit)
    else:
        content = str(content)
        returned_bytes = len(content.encode("utf-8"))
    total_length = int(row.get("total_length") or returned_bytes)
    next_offset = offset + returned_bytes
    return {
        "content": content,
        "offset": offset,
        "limit": limit,
        "total_length": total_length,
        "complete": next_offset >= total_length,
        "next_offset": None if next_offset >= total_length else next_offset,
    }


def get_message_content(
    message_id: int,
    *,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    """读取一段聊天消息正文。"""
    return _read_text_chunk(
        table="chat_messages",
        id_column="id",
        id_value=message_id,
        content_sql="content",
        offset=offset,
        limit=limit,
    )


def get_attachment_content(
    attachment_id: int,
    *,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    """读取一段聊天附件正文。"""
    return _read_text_chunk(
        table="chat_attachments",
        id_column="id",
        id_value=attachment_id,
        content_sql="content",
        offset=offset,
        limit=limit,
    )


def list_jobs(
    *,
    limit: int,
    cursor: str | None,
    q: str | None,
    status: str | None,
    user_id: str | None,
    session_id: str | None,
) -> dict[str, Any]:
    """按创建时间与内部主键倒序分页读取任务摘要。"""
    search = _validated_search(q)
    normalized_status = _validated_enum(
        status,
        field="status",
        allowed=JOB_STATUSES,
    )
    owner_id = _validated_positive_id(user_id, field="user_id")
    normalized_session_id = (session_id or "").strip() or None
    if normalized_session_id and len(normalized_session_id) > 36:
        raise AdminApiError(
            "invalid_query",
            "session_id 不能超过 36 个字符",
            fields={"session_id": "不能超过 36 个字符"},
        )
    cursor_values = decode_cursor(cursor, size=2)
    clauses = ["1 = 1"]
    params: list[Any] = []
    if search:
        clauses.append("j.job_id LIKE %s")
        params.append(_prefix_like(search))
    if normalized_status:
        clauses.append("j.status = %s")
        params.append(normalized_status)
    if owner_id:
        clauses.append("j.user_id = %s")
        params.append(owner_id)
    if normalized_session_id:
        clauses.append("j.session_id = %s")
        params.append(normalized_session_id)
    if cursor_values:
        created_at = _timestamp_cursor(cursor_values[0])
        row_id = _validated_positive_id(cursor_values[1], field="cursor")
        clauses.append(
            "(j.created_at < %s OR (j.created_at = %s AND j.id < %s))"
        )
        params.extend((created_at, created_at, row_id))
    params.append(limit + 1)
    with get_read_connection(consistency="strong") as conn:
        db_cursor = conn.cursor(dictionary=True)
        db_cursor.execute(
            f"""
            SELECT j.id AS row_id, j.job_id, j.user_id, u.username, j.session_id,
                   j.status, j.worker_id, j.attempt_count, j.max_attempts,
                   (j.result_json IS NOT NULL) AS has_result,
                   j.locked_at, j.heartbeat_at, j.created_at, j.started_at,
                   j.finished_at, j.chat_saved_at
            FROM analysis_jobs AS j
            JOIN users AS u ON u.id = j.user_id
            WHERE {' AND '.join(clauses)}
            ORDER BY j.created_at DESC, j.id DESC
            LIMIT %s
            """,
            tuple(params),
        )
        rows = db_cursor.fetchall()
    for row in rows:
        row["has_result"] = bool(row.get("has_result"))
    return page_result(
        rows,
        limit=limit,
        cursor_fields=("created_at", "row_id"),
    )


def get_job_detail(job_id: str) -> dict[str, Any]:
    """读取任务元数据，不返回输入、结果或完整错误正文。"""
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT j.job_id, j.user_id, u.username, j.session_id, j.status,
                   j.worker_id, j.locked_at, j.heartbeat_at, j.attempt_count,
                   j.max_attempts, j.created_at, j.started_at, j.finished_at,
                   j.chat_saved_at, (j.message IS NOT NULL) AS has_input,
                   (j.result_json IS NOT NULL) AS has_result,
                   (
                       j.error_message IS NOT NULL OR j.last_error IS NOT NULL
                   ) AS has_error
            FROM analysis_jobs AS j
            JOIN users AS u ON u.id = j.user_id
            WHERE j.job_id = %s
            """,
            (job_id,),
        )
        row = cursor.fetchone()
    if not row:
        raise AdminApiError("not_found", "分析任务不存在", 404)
    for field in ("has_input", "has_result", "has_error"):
        row[field] = bool(row.get(field))
    return row


def list_job_events(
    *,
    job_id: str,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    """按事件 ID 倒序读取任务时间线，不返回 payload 正文。"""
    cursor_values = decode_cursor(cursor, size=1)
    clauses = ["job_id = %s"]
    params: list[Any] = [job_id]
    if cursor_values:
        clauses.append("id < %s")
        params.append(_validated_positive_id(cursor_values[0], field="cursor"))
    params.append(limit + 1)
    with get_read_connection(consistency="strong") as conn:
        db_cursor = conn.cursor(dictionary=True)
        db_cursor.execute(
            "SELECT 1 AS present FROM analysis_jobs WHERE job_id = %s",
            (job_id,),
        )
        if not db_cursor.fetchone():
            raise AdminApiError("not_found", "分析任务不存在", 404)
        db_cursor.execute(
            f"""
            SELECT id, job_id, event_type, created_at,
                   (payload_json IS NOT NULL) AS has_payload
            FROM analysis_job_events
            WHERE {' AND '.join(clauses)}
            ORDER BY id DESC
            LIMIT %s
            """,
            tuple(params),
        )
        rows = db_cursor.fetchall()
    for row in rows:
        row["has_payload"] = bool(row.get("has_payload"))
    return page_result(rows, limit=limit, cursor_fields=("id",))


def get_job_content(
    job_id: str,
    *,
    kind: str | None,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    """按固定类别读取任务输入、结果或错误正文片段。"""
    normalized_kind = _validated_enum(
        kind,
        field="kind",
        allowed=CONTENT_KINDS,
    )
    if normalized_kind is None:
        raise AdminApiError(
            "invalid_query",
            "kind 不能为空",
            fields={"kind": "必须指定 input、result 或 error"},
        )
    content_sql = {
        "input": "message",
        "result": "CAST(result_json AS CHAR CHARACTER SET utf8mb4)",
        "error": "CONCAT_WS('\\n', error_message, last_error)",
    }[normalized_kind]
    result = _read_text_chunk(
        table="analysis_jobs",
        id_column="job_id",
        id_value=job_id,
        content_sql=content_sql,
        offset=offset,
        limit=limit,
    )
    result["kind"] = normalized_kind
    return result


def list_files(
    *,
    limit: int,
    cursor: str | None,
    q: str | None,
    user_id: str | None,
    mime_type: str | None,
) -> dict[str, Any]:
    """按上传时间与主键倒序分页读取文件元数据。"""
    search = _validated_search(q)
    owner_id = _validated_positive_id(user_id, field="user_id")
    normalized_mime = (mime_type or "").strip() or None
    if normalized_mime and len(normalized_mime) > 100:
        raise AdminApiError(
            "invalid_query",
            "mime_type 不能超过 100 个字符",
            fields={"mime_type": "不能超过 100 个字符"},
        )
    cursor_values = decode_cursor(cursor, size=2)
    clauses = ["1 = 1"]
    params: list[Any] = []
    if search:
        clauses.append("f.original_filename LIKE %s")
        params.append(_prefix_like(search))
    if owner_id:
        clauses.append("f.user_id = %s")
        params.append(owner_id)
    if normalized_mime:
        clauses.append("f.mime_type = %s")
        params.append(normalized_mime)
    if cursor_values:
        uploaded_at = _timestamp_cursor(cursor_values[0])
        file_id = _validated_positive_id(cursor_values[1], field="cursor")
        clauses.append(
            "(f.upload_timestamp < %s "
            "OR (f.upload_timestamp = %s AND f.id < %s))"
        )
        params.extend((uploaded_at, uploaded_at, file_id))
    params.append(limit + 1)
    with get_read_connection(consistency="strong") as conn:
        db_cursor = conn.cursor(dictionary=True)
        db_cursor.execute(
            f"""
            SELECT f.id, f.user_id, u.username, f.filename, f.original_filename,
                   f.mime_type, f.file_size, f.upload_timestamp,
                   f.last_accessed_at, f.access_count
            FROM uploaded_files AS f
            JOIN users AS u ON u.id = f.user_id
            WHERE {' AND '.join(clauses)}
            ORDER BY f.upload_timestamp DESC, f.id DESC
            LIMIT %s
            """,
            tuple(params),
        )
        rows = db_cursor.fetchall()
    return page_result(
        rows,
        limit=limit,
        cursor_fields=("upload_timestamp", "id"),
    )


def get_file_detail(file_id: int) -> dict[str, Any]:
    """读取单个文件的允许展示元数据。"""
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT f.id, f.user_id, u.username, f.filename, f.original_filename,
                   f.mime_type, f.file_size, f.upload_timestamp,
                   f.last_accessed_at, f.access_count
            FROM uploaded_files AS f
            JOIN users AS u ON u.id = f.user_id
            WHERE f.id = %s
            """,
            (file_id,),
        )
        row = cursor.fetchone()
    if not row:
        raise AdminApiError("not_found", "文件不存在", 404)
    return row


def _decode_csv_bytes(content: bytes) -> tuple[str, str]:
    """优先按 UTF-8 解码 CSV，失败时兼容 GB18030。"""
    for trim in range(0, min(4, len(content)) + 1):
        candidate = content[:-trim] if trim else content
        try:
            return candidate.decode("utf-8-sig"), "utf-8-sig"
        except UnicodeDecodeError:
            continue
    for trim in range(0, min(4, len(content)) + 1):
        candidate = content[:-trim] if trim else content
        try:
            return candidate.decode("gb18030"), "gb18030"
        except UnicodeDecodeError:
            continue
    raise AdminApiError(
        code="preview_decode_failed",
        message="CSV 不是受支持的 UTF-8 或 GB18030 编码",
        status=422,
    )


def _record_file_access(
    *,
    file_id: int,
    actor: dict[str, Any],
    action: str,
) -> None:
    """在同一事务中更新访问计数并写入不含正文的审计事件。"""
    try:
        with get_write_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                UPDATE uploaded_files
                SET last_accessed_at = UTC_TIMESTAMP(6),
                    access_count = access_count + 1
                WHERE id = %s
                """,
                (file_id,),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                raise AdminApiError("not_found", "文件不存在", 404)
            insert_admin_audit_event(
                cursor,
                actor=actor,
                action=action,
                target_type="uploaded_file",
                target_id=str(file_id),
                old_values=None,
                new_values={"access_count_increment": 1},
                result="success",
                request_id=get_request_id(),
                error_code=None,
            )
            conn.commit()
    except AdminApiError:
        raise
    except Exception as exc:
        raise AdminApiError(
            code="audit_unavailable",
            message="文件访问审计暂时不可用",
            status=503,
        ) from exc


def preview_file_csv(
    file_id: int,
    *,
    actor: dict[str, Any],
) -> dict[str, Any]:
    """安全解析受限 CSV 预览，并在成功后原子记录访问。"""
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, original_filename, mime_type, file_size,
                   SUBSTRING(file_content, 1, %s) AS preview_content
            FROM uploaded_files
            WHERE id = %s
            """,
            (CSV_PREVIEW_BYTES + 4, file_id),
        )
        row = cursor.fetchone()
    if not row:
        raise AdminApiError("not_found", "文件不存在", 404)
    filename = str(row.get("original_filename") or "")
    mime_type = str(row.get("mime_type") or "")
    if os.path.splitext(filename)[1].lower() != ".csv" or mime_type not in {
        "text/csv",
        "application/vnd.ms-excel",
    }:
        raise AdminApiError(
            code="preview_not_supported",
            message="仅支持 CSV 文件安全预览",
            status=415,
        )
    content = bytes(row.get("preview_content") or b"")[:CSV_PREVIEW_BYTES]
    decoded, encoding = _decode_csv_bytes(content)
    reader = csv.reader(StringIO(decoded, newline=""))
    parsed_rows: list[list[str]] = []
    columns_truncated = False
    cells_truncated = False
    rows_truncated = False
    try:
        for index, csv_row in enumerate(reader):
            if index >= CSV_PREVIEW_ROWS + 1:
                rows_truncated = True
                break
            if len(csv_row) > CSV_PREVIEW_COLUMNS:
                columns_truncated = True
            normalized_row = []
            for cell in csv_row[:CSV_PREVIEW_COLUMNS]:
                if len(cell) > CSV_PREVIEW_CELL_CHARS:
                    cells_truncated = True
                normalized_row.append(cell[:CSV_PREVIEW_CELL_CHARS])
            parsed_rows.append(normalized_row)
    except csv.Error as exc:
        raise AdminApiError(
            code="preview_parse_failed",
            message="CSV 内容解析失败",
            status=422,
        ) from exc
    columns = parsed_rows[0] if parsed_rows else []
    data_rows = parsed_rows[1:] if len(parsed_rows) > 1 else []
    byte_truncated = int(row.get("file_size") or 0) > CSV_PREVIEW_BYTES
    _record_file_access(
        file_id=file_id,
        actor=actor,
        action="business.file.preview",
    )
    return {
        "file_id": file_id,
        "filename": filename,
        "mime_type": mime_type,
        "encoding": encoding,
        "columns": columns,
        "rows": data_rows,
        "truncated": bool(
            byte_truncated or rows_truncated or columns_truncated or cells_truncated
        ),
        "limits": {
            "bytes": CSV_PREVIEW_BYTES,
            "rows": CSV_PREVIEW_ROWS,
            "columns": CSV_PREVIEW_COLUMNS,
            "cell_chars": CSV_PREVIEW_CELL_CHARS,
        },
    }


def download_file(
    file_id: int,
    *,
    actor: dict[str, Any],
) -> tuple[BytesIO, dict[str, Any]]:
    """读取完整文件并在返回前原子记录访问计数与审计。"""
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, original_filename, mime_type, file_size, file_content
            FROM uploaded_files
            WHERE id = %s
            """,
            (file_id,),
        )
        row = cursor.fetchone()
    if not row:
        raise AdminApiError("not_found", "文件不存在", 404)
    content = bytes(row.pop("file_content") or b"")
    _record_file_access(
        file_id=file_id,
        actor=actor,
        action="business.file.download",
    )
    return BytesIO(content), row
