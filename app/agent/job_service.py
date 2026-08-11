"""长任务队列、冻结输入和生命周期幂等服务。"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import math
from typing import Any
from uuid import UUID, uuid4

import mysql.connector
from mysql.connector import errorcode

from app.chat.services import (
    save_assistant_for_job_in_transaction,
    save_user_input_for_job_in_transaction,
)
from app.db import get_read_connection, get_read_connection_with_source, get_write_connection
from config.settings import settings


ACTIVE_STATUSES = ("queued", "running", "waiting_input")
TERMINAL_STATUSES = ("succeeded", "failed", "canceled")
TERMINAL_EVENTS = {"final_result", "error", "canceled"}
MAX_ATTEMPTS_ERROR = "任务达到最大 stale recovery 次数，且最后一次 worker 心跳已过期"
MAX_INPUT_TEXT_LENGTH = 20000
MAX_STRUCTURED_INPUT_BYTES = 8192
MAX_STRUCTURED_INPUT_DEPTH = 4
MAX_STRUCTURED_INPUT_ITEMS = 64
CHECKPOINT_RECOVERY_TIMEOUT_MS = 3000


class InvalidIdempotencyKeyError(ValueError):
    """表示请求没有提供标准 UUID v4 幂等键。"""


class IdempotencyConflictError(ValueError):
    """表示同一个幂等键被用于不同的请求参数。"""


class ActiveJobConflictError(ValueError):
    """表示同一 session 已经存在活动 Job。"""

    def __init__(self, job: dict[str, Any]):
        super().__init__("当前会话已有 queued/running/waiting_input 任务")
        self.job = job


class JobStateConflictError(ValueError):
    """表示 Job 当前状态不允许执行请求。"""

    def __init__(self, message: str, job: dict[str, Any] | None = None):
        super().__init__(message)
        self.job = job


class _CheckpointRecoveryBlocked(RuntimeError):
    """PostgreSQL checkpoint 不可读时阻止本轮 stale recovery。"""


def normalize_idempotency_key(value: str | None) -> str:
    """校验标准 UUID v4 并规范化为小写 canonical 文本。"""
    normalized = value.strip() if isinstance(value, str) else ""
    if len(normalized) != 36 or normalized.count("-") != 4:
        raise InvalidIdempotencyKeyError("Idempotency-Key 必须是标准 UUID v4")
    try:
        parsed = UUID(normalized)
    except (TypeError, ValueError) as exc:
        raise InvalidIdempotencyKeyError("Idempotency-Key 必须是标准 UUID v4") from exc
    if parsed.version != 4 or str(parsed) != normalized.lower():
        raise InvalidIdempotencyKeyError("Idempotency-Key 必须是标准 UUID v4")
    return str(parsed)


def _validate_input_text(value: Any) -> str:
    """校验普通文本输入的类型、非空约束和长度。"""
    if not isinstance(value, str):
        raise ValueError("消息必须是文本")
    text = value.strip()
    if not text:
        raise ValueError("消息不能为空")
    if len(text) > MAX_INPUT_TEXT_LENGTH:
        raise ValueError("输入内容超过长度限制")
    return text


def _validate_structured_value(value: Any, *, depth: int = 0) -> None:
    """递归校验恢复回答中的有限 JSON 类型、深度、项数和字符串大小。"""
    if depth > MAX_STRUCTURED_INPUT_DEPTH:
        raise ValueError("结构化回答嵌套层级过深")
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str):
            if len(value) > MAX_INPUT_TEXT_LENGTH:
                raise ValueError("结构化回答中的文本超过长度限制")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("结构化回答包含无效数字")
        return
    if isinstance(value, dict):
        if len(value) > MAX_STRUCTURED_INPUT_ITEMS:
            raise ValueError("结构化回答字段过多")
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 128:
                raise ValueError("结构化回答字段名无效")
            _validate_structured_value(item, depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > MAX_STRUCTURED_INPUT_ITEMS:
            raise ValueError("结构化回答数组项过多")
        for item in value:
            _validate_structured_value(item, depth=depth + 1)
        return
    raise ValueError("回答必须是文本或受限 JSON 对象/数组")


def _normalize_input_value(value: Any) -> tuple[str, Any]:
    """规范化文本或结构化恢复回答，返回存储文本和 worker 运行时值。"""
    if isinstance(value, str):
        text = _validate_input_text(value)
        return text, text
    if not isinstance(value, (dict, list)):
        raise ValueError("回答必须是文本或受限 JSON 对象/数组")
    _validate_structured_value(value)
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("结构化回答不是有效 JSON") from exc
    if len(encoded.encode("utf-8")) > MAX_STRUCTURED_INPUT_BYTES:
        raise ValueError("结构化回答超过大小限制")
    return encoded, value


def _request_fingerprint(
    session_id: str,
    message: str,
    input_user_file_id: int | None = None,
) -> str:
    """使用服务端密钥为创建请求生成包含冻结文件选择的指纹。"""
    canonical = json.dumps(
        {
            "message": message,
            "session_id": session_id,
            "input_user_file_id": input_user_file_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    secret = str(settings.SECRET_KEY).encode("utf-8")
    return hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def _action_fingerprint(
    *,
    job_id: str,
    action: str,
    text: str = "",
    question_id: str = "",
) -> str:
    """为恢复/取消操作生成不包含敏感正文的服务端指纹。"""
    canonical = json.dumps(
        {
            "action": action,
            "job_id": job_id,
            "question_id": question_id,
            "text": text,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hmac.new(
        str(settings.SECRET_KEY).encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _ensure_same_request(job: dict[str, Any], fingerprint: str) -> dict[str, Any]:
    """确认已有幂等记录与本次创建请求参数一致。"""
    if job.get("request_fingerprint") != fingerprint:
        raise IdempotencyConflictError("Idempotency-Key 已用于不同的分析请求")
    return job


def _json_dumps(value: Any) -> str:
    """把内部结构化值编码成 JSON。"""
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: Any) -> Any:
    """把 MySQL JSON 值转换为 Python 值。"""
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    return json.loads(value)


def _row_to_job(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """清洗 Job 行中的 JSON 结果。"""
    if not row:
        return None
    if "result_json" in row:
        row["result_json"] = _json_loads(row["result_json"])
    return row


def get_active_job(user_id: int, session_id: str) -> dict[str, Any] | None:
    """读取同一用户同一会话下尚未结束的 Job。"""
    with get_read_connection(consistency="strong") as connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT *
            FROM analysis_jobs
            WHERE user_id = %s AND session_id = %s
              AND status IN ('queued', 'running', 'waiting_input')
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (user_id, session_id),
        )
        return _row_to_job(cursor.fetchone())


def get_active_jobs(user_id: int, session_id: str | None = None) -> list[dict[str, Any]]:
    """读取当前用户全部或指定会话的活动 Job，供页面刷新恢复执行状态。"""
    clauses = ["user_id = %s", "status IN ('queued', 'running', 'waiting_input')"]
    params: list[Any] = [user_id]
    if session_id:
        clauses.append("session_id = %s")
        params.append(session_id)
    with get_read_connection(consistency="strong") as connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            f"""
            SELECT job_id, user_id, session_id, status, worker_id, lease_epoch,
                   attempt_count, recovery_count, resume_count, max_attempts,
                   current_question_id, current_waiting_prompt, input_user_file_id,
                   input_filename, created_at
            FROM analysis_jobs
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at ASC
            """,
            tuple(params),
        )
        return cursor.fetchall()


def get_latest_event_id(job_id: str) -> int:
    """读取 Job 当前公开事件的最大 ID，避免刷新后重放整条时间线。"""
    with get_read_connection(consistency="strong") as connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT COALESCE(MAX(id), 0) AS event_id FROM analysis_job_events WHERE job_id = %s",
            (job_id,),
        )
        row = cursor.fetchone() or {}
    return int(row.get("event_id") or 0)


def get_job_by_idempotency_key(user_id: int, idempotency_key: str) -> dict[str, Any] | None:
    """按用户和创建幂等键读取历史 Job。"""
    with get_read_connection(consistency="strong") as connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT *
            FROM analysis_jobs
            WHERE user_id = %s AND idempotency_key = %s
            """,
            (user_id, idempotency_key),
        )
        return _row_to_job(cursor.fetchone())


def get_job_for_user(job_id: str, user_id: int) -> dict[str, Any] | None:
    """按 Job ID 和用户归属强一致读取 Job。"""
    with get_read_connection(consistency="strong") as connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM analysis_jobs WHERE job_id = %s AND user_id = %s",
            (job_id, user_id),
        )
        return _row_to_job(cursor.fetchone())


def _load_file_snapshot(cursor, user_id: int, user_file_id: int | None) -> dict[str, Any] | None:
    """锁定用户文件及其不可变对象，并返回创建 Job 所需快照。"""
    if user_file_id is None:
        return None
    cursor.execute(
        """
        SELECT uf.id AS input_user_file_id,
               fo.id AS input_object_id,
               fo.content_hash AS input_file_hash,
               uf.filename AS input_filename
        FROM user_files AS uf
        JOIN file_objects AS fo ON fo.id = uf.object_id
        WHERE uf.id = %s AND uf.user_id = %s AND fo.owner_user_id = %s
        FOR UPDATE
        """,
        (user_file_id, user_id, user_id),
    )
    snapshot = cursor.fetchone()
    if not snapshot:
        raise PermissionError("文件不存在或不属于当前用户")
    return snapshot


def create_job(
    user_id: int,
    session_id: str,
    message: str,
    idempotency_key: str,
    input_user_file_id: int | None = None,
) -> tuple[dict[str, Any], bool]:
    """在一个 MySQL 事务中创建或重放带冻结文件输入的 Job。"""
    normalized_message = _validate_input_text(message)
    idempotency_key = normalize_idempotency_key(idempotency_key)
    if input_user_file_id is not None:
        try:
            input_user_file_id = int(input_user_file_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("input_user_file_id 无效") from exc
    fingerprint = _request_fingerprint(session_id, normalized_message, input_user_file_id)
    job_id = str(uuid4())
    connection = get_write_connection()
    try:
        cursor = connection.cursor(dictionary=True)
        connection.start_transaction()
        cursor.execute(
            """
            SELECT *
            FROM analysis_jobs
            WHERE user_id = %s AND idempotency_key = %s
            FOR UPDATE
            """,
            (user_id, idempotency_key),
        )
        existing = _row_to_job(cursor.fetchone())
        if existing:
            _ensure_same_request(existing, fingerprint)
            connection.commit()
            return existing, True

        cursor.execute(
            """
            SELECT *
            FROM analysis_jobs
            WHERE user_id = %s AND session_id = %s
              AND status IN ('queued', 'running', 'waiting_input')
            ORDER BY created_at ASC
            LIMIT 1
            FOR UPDATE
            """,
            (user_id, session_id),
        )
        active = _row_to_job(cursor.fetchone())
        if active:
            raise ActiveJobConflictError(active)

        cursor.execute(
            "SELECT id FROM sessions WHERE id = %s AND user_id = %s FOR UPDATE",
            (session_id, user_id),
        )
        if not cursor.fetchone():
            raise PermissionError("会话不存在或不属于当前用户")

        snapshot = _load_file_snapshot(cursor, user_id, input_user_file_id)
        snapshot_values = snapshot or {
            "input_user_file_id": None,
            "input_object_id": None,
            "input_file_hash": None,
            "input_filename": None,
        }
        cursor.execute(
            """
            INSERT INTO analysis_jobs (
                job_id, user_id, session_id, message,
                input_user_file_id, input_object_id, input_file_hash, input_filename,
                status, max_attempts, active_session_key,
                idempotency_key, request_fingerprint
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                'queued', %s, %s, %s, %s
            )
            """,
            (
                job_id,
                user_id,
                session_id,
                normalized_message,
                snapshot_values["input_user_file_id"],
                snapshot_values["input_object_id"],
                snapshot_values["input_file_hash"],
                snapshot_values["input_filename"],
                settings.JOB_MAX_ATTEMPTS,
                f"{user_id}:{session_id}",
                idempotency_key,
                fingerprint,
            ),
        )
        cursor.execute(
            """
            INSERT INTO analysis_job_inputs (
                job_id, sequence, input_type, input_text,
                idempotency_key, request_fingerprint
            ) VALUES (%s, 0, 'initial', %s, %s, %s)
            """,
            (job_id, normalized_message, idempotency_key, fingerprint),
        )
        input_id = int(cursor.lastrowid)
        chat_message_id = save_user_input_for_job_in_transaction(
            cursor,
            job_id=job_id,
            input_id=input_id,
            user_id=user_id,
            session_id=session_id,
            text=normalized_message,
        )
        cursor.execute(
            "UPDATE analysis_job_inputs SET chat_message_id = %s WHERE input_id = %s",
            (chat_message_id, input_id),
        )
        connection.commit()
        job = get_job_for_user(job_id, user_id)
        if job is None:
            raise RuntimeError("Job 创建后无法读取")
        return job, False
    except IdempotencyConflictError:
        connection.rollback()
        raise
    except ActiveJobConflictError:
        connection.rollback()
        raise
    except mysql.connector.Error as exc:
        connection.rollback()
        if exc.errno == errorcode.ER_DUP_ENTRY:
            existing = get_job_by_idempotency_key(user_id, idempotency_key)
            if existing:
                _ensure_same_request(existing, fingerprint)
                return existing, True
            active = get_active_job(user_id, session_id)
            if active:
                raise ActiveJobConflictError(active) from exc
        raise
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _event_key(event_type: str, payload: dict[str, Any], question_id: str | None = None) -> str | None:
    """为生命周期事件生成稳定语义键；普通进度事件保持可重复。"""
    if event_type == "interrupt":
        stable_question_id = question_id or payload.get("question_id")
        return f"interrupt:{stable_question_id}" if stable_question_id else None
    if event_type == "final_result":
        return "terminal:final_result"
    if event_type == "error":
        return "terminal:error"
    if event_type == "canceled":
        return "terminal:canceled"
    return None


def _payload_matches(existing_payload: Any, payload: dict[str, Any]) -> bool:
    """比较生命周期重放的受限 JSON payload。"""
    try:
        return _json_loads(existing_payload) == payload
    except (TypeError, ValueError, json.JSONDecodeError):
        return False


def _existing_event(cursor, job_id: str, event_key: str | None):
    """读取同一生命周期键已有事件。"""
    if not event_key:
        return None
    cursor.execute(
        """
        SELECT id, payload_json
        FROM analysis_job_events
        WHERE job_id = %s AND event_key = %s
        FOR UPDATE
        """,
        (job_id, event_key),
    )
    return cursor.fetchone()


def _lock_owned_running_job(
    cursor,
    job_id: str,
    worker_id: str,
    attempt_count: int,
    lease_epoch: int | None = None,
) -> bool:
    """锁定 Job 并确认 worker、attempt 和 lease epoch 仍然匹配。"""
    cursor.execute(
        """
        SELECT status, worker_id, attempt_count, lease_epoch,
               user_id, session_id
        FROM analysis_jobs
        WHERE job_id = %s
        FOR UPDATE
        """,
        (job_id,),
    )
    job = cursor.fetchone()
    if not job or job["status"] != "running":
        return False
    if job["worker_id"] != worker_id or int(job["attempt_count"]) != int(attempt_count):
        return False
    if lease_epoch is not None and "lease_epoch" in job:
        return int(job["lease_epoch"]) == int(lease_epoch)
    return True


def _insert_event(
    cursor,
    *,
    job_id: str,
    event_type: str,
    payload: dict[str, Any],
    event_key: str | None,
) -> int:
    """插入或幂等重放一条事件，并拒绝同键不同 payload。"""
    existing = _existing_event(cursor, job_id, event_key)
    if existing:
        if not _payload_matches(existing["payload_json"], payload):
            raise IdempotencyConflictError("同一生命周期事件键对应了不同 payload")
        return int(existing["id"])
    cursor.execute(
        """
        INSERT INTO analysis_job_events (job_id, event_type, event_key, payload_json)
        VALUES (%s, %s, %s, %s)
        """,
        (job_id, event_type, event_key, _json_dumps(payload)),
    )
    return int(cursor.lastrowid)


def _latest_input_id(cursor, job_id: str) -> int | None:
    """读取当前 Job 最近一条用户输入账本 ID。"""
    cursor.execute(
        """
        SELECT input_id
        FROM analysis_job_inputs
        WHERE job_id = %s
        ORDER BY sequence DESC
        LIMIT 1
        """,
        (job_id,),
    )
    row = cursor.fetchone()
    return int(row["input_id"] if isinstance(row, dict) else row[0]) if row else None


def _lock_job_then_session(
    cursor,
    *,
    job_id: str,
    user_id: int,
) -> dict[str, Any] | None:
    """按统一的 ``analysis_jobs -> sessions`` 顺序锁定用户 Job。"""
    cursor.execute(
        """
        SELECT *
        FROM analysis_jobs
        WHERE job_id = %s AND user_id = %s
        FOR UPDATE
        """,
        (job_id, user_id),
    )
    job = _row_to_job(cursor.fetchone())
    if not job:
        return None
    cursor.execute(
        "SELECT id FROM sessions WHERE id = %s AND user_id = %s FOR UPDATE",
        (job["session_id"], user_id),
    )
    if not cursor.fetchone():
        raise PermissionError("会话不存在或不属于当前用户")
    return job


def _get_pending_checkpoint_interrupt(job: dict[str, Any]) -> dict[str, str] | None:
    """读取 Job 根 checkpoint 的 pending interrupt；失败时不冒险重放 Agent。"""
    try:
        from app.agent.checkpoint_recovery import (
            CheckpointRecoveryUnavailable,
            get_pending_interrupt,
        )

        return get_pending_interrupt(
            job_id=str(job["job_id"]),
            timeout_ms=CHECKPOINT_RECOVERY_TIMEOUT_MS,
        )
    except CheckpointRecoveryUnavailable as exc:
        raise _CheckpointRecoveryBlocked(
            f"无法确认 Job {job['job_id']} 的 checkpoint 恢复状态"
        ) from exc


def _repair_pending_interrupt(cursor, job: dict[str, Any]) -> bool:
    """把 PostgreSQL 中尚未恢复的 interrupt 幂等修复到 MySQL waiting_input。"""
    pending = _get_pending_checkpoint_interrupt(job)
    if not pending:
        return False

    question_id = pending["question_id"]
    payload = {
        "type": "interrupt",
        "message": pending["message"],
        "question_id": question_id,
    }
    event_id = _insert_event(
        cursor,
        job_id=job["job_id"],
        event_type="interrupt",
        payload=payload,
        event_key=_event_key("interrupt", payload, question_id),
    )
    save_assistant_for_job_in_transaction(
        cursor,
        job_id=job["job_id"],
        user_id=int(job["user_id"]),
        session_id=job["session_id"],
        ai_response={"type": "human_input_required", "summary": pending["message"]},
        source_event_id=event_id,
        analysis_job_input_id=_latest_input_id(cursor, job["job_id"]),
    )
    cursor.execute(
        """
        UPDATE analysis_jobs
        SET status = 'waiting_input', worker_id = NULL,
            locked_at = NULL, heartbeat_at = NULL,
            current_question_id = %s, current_waiting_prompt = %s,
            finished_at = NULL
        WHERE job_id = %s AND status = 'running'
        """,
        (question_id, pending["message"], job["job_id"]),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("修复 pending interrupt 时 Job 状态已发生变化")
    return True


def _complete_job_lifecycle(
    job: dict[str, Any],
    worker_id: str | None,
    event_type: str,
    payload: dict[str, Any],
    *,
    lease_epoch: int | None = None,
    question_id: str | None = None,
    chat_response: dict[str, Any] | str | None = None,
    result: dict[str, Any] | None = None,
    status: str,
) -> bool:
    """在一个事务中完成事件、assistant 消息和 Job 状态更新。"""
    job_id = job["job_id"]
    event_key = _event_key(event_type, payload, question_id)
    with get_write_connection() as connection:
        try:
            connection.start_transaction()
            cursor = connection.cursor(dictionary=True)
            existing = _existing_event(cursor, job_id, event_key)
            if existing:
                if not _payload_matches(existing["payload_json"], payload):
                    raise IdempotencyConflictError("同一生命周期事件键对应了不同 payload")
                connection.commit()
                return True

            if worker_id is not None and not _lock_owned_running_job(
                cursor,
                job_id,
                worker_id,
                int(job["attempt_count"]),
                lease_epoch,
            ):
                connection.rollback()
                return False
            if worker_id is None:
                cursor.execute(
                    "SELECT status FROM analysis_jobs WHERE job_id = %s FOR UPDATE",
                    (job_id,),
                )
                current = cursor.fetchone()
                if not current or current["status"] != "waiting_input":
                    connection.rollback()
                    return False

            event_id = _insert_event(
                cursor,
                job_id=job_id,
                event_type=event_type,
                payload=payload,
                event_key=event_key,
            )
            if chat_response is not None:
                save_assistant_for_job_in_transaction(
                    cursor,
                    job_id=job_id,
                    user_id=int(job["user_id"]),
                    session_id=job["session_id"],
                    ai_response=chat_response,
                    source_event_id=event_id,
                    analysis_job_input_id=_latest_input_id(cursor, job_id),
                )

            if status == "waiting_input":
                cursor.execute(
                    """
                    UPDATE analysis_jobs
                    SET status = 'waiting_input', worker_id = NULL,
                        locked_at = NULL, heartbeat_at = NULL,
                        current_question_id = %s, current_waiting_prompt = %s,
                        finished_at = NULL
                    WHERE job_id = %s AND status = 'running'
                    """,
                    (
                        question_id,
                        payload.get("message"),
                        job_id,
                    ),
                )
            elif status == "succeeded":
                cursor.execute(
                    """
                    UPDATE analysis_jobs
                    SET status = 'succeeded', result_json = %s,
                        active_session_key = NULL, worker_id = NULL,
                        locked_at = NULL, heartbeat_at = UTC_TIMESTAMP(6),
                        chat_saved_at = UTC_TIMESTAMP(6), finished_at = UTC_TIMESTAMP(6),
                        current_question_id = NULL, current_waiting_prompt = NULL
                    WHERE job_id = %s AND status = 'running'
                    """,
                    (_json_dumps(result or {}), job_id),
                )
            elif status == "failed":
                cursor.execute(
                    """
                    UPDATE analysis_jobs
                    SET status = 'failed', error_message = %s, last_error = %s,
                        active_session_key = NULL, worker_id = NULL,
                        locked_at = NULL, heartbeat_at = UTC_TIMESTAMP(6),
                        chat_saved_at = UTC_TIMESTAMP(6), finished_at = UTC_TIMESTAMP(6),
                        current_question_id = NULL, current_waiting_prompt = NULL
                    WHERE job_id = %s AND status = 'running'
                    """,
                    (payload.get("message", "任务执行失败"), payload.get("message", "任务执行失败"), job_id),
                )
            elif status == "canceled":
                cursor.execute(
                    """
                    UPDATE analysis_jobs
                    SET status = 'canceled', active_session_key = NULL,
                        worker_id = NULL, locked_at = NULL, heartbeat_at = NULL,
                        current_question_id = NULL, current_waiting_prompt = NULL,
                        finished_at = UTC_TIMESTAMP(6)
                    WHERE job_id = %s AND status = 'waiting_input'
                    """,
                    (job_id,),
                )
            else:
                raise ValueError(f"不支持的终态: {status}")
            if cursor.rowcount != 1:
                connection.rollback()
                return False
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise


def _finalize_exhausted_job(cursor, stale_after: int) -> bool:
    """锁定并失败一个 stale recovery 已耗尽的 Job。"""
    cursor.execute(
        f"""
        SELECT job_id, user_id, session_id, attempt_count, lease_epoch
        FROM analysis_jobs
        WHERE status = 'running'
          AND recovery_count >= max_attempts
          AND (heartbeat_at IS NULL OR heartbeat_at <
               (UTC_TIMESTAMP(6) - INTERVAL {stale_after} SECOND))
        ORDER BY heartbeat_at ASC, created_at ASC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
        """
    )
    job = cursor.fetchone()
    if not job:
        return False
    if _repair_pending_interrupt(cursor, job):
        return True
    payload = {"type": "error", "message": MAX_ATTEMPTS_ERROR}
    event_id = _insert_event(
        cursor,
        job_id=job["job_id"],
        event_type="error",
        payload=payload,
        event_key="terminal:error",
    )
    save_assistant_for_job_in_transaction(
        cursor,
        job_id=job["job_id"],
        user_id=int(job["user_id"]),
        session_id=job["session_id"],
        ai_response={"type": "text", "summary": MAX_ATTEMPTS_ERROR},
        source_event_id=event_id,
        analysis_job_input_id=_latest_input_id(cursor, job["job_id"]),
    )
    cursor.execute(
        """
        UPDATE analysis_jobs
        SET status = 'failed', error_message = %s, last_error = %s,
            active_session_key = NULL, worker_id = NULL, locked_at = NULL,
            heartbeat_at = UTC_TIMESTAMP(6), chat_saved_at = UTC_TIMESTAMP(6),
            finished_at = UTC_TIMESTAMP(6)
        WHERE job_id = %s AND status = 'running'
        """,
        (MAX_ATTEMPTS_ERROR, MAX_ATTEMPTS_ERROR, job["job_id"]),
    )
    return cursor.rowcount == 1


def claim_next_job(worker_id: str, stale_after_seconds: int | None = None) -> dict[str, Any] | None:
    """领取 queued Job 或 stale running Job，并递增 lease epoch。"""
    stale_after = int(stale_after_seconds or settings.JOB_STALE_AFTER_SECONDS)
    connection = get_write_connection()
    try:
        cursor = connection.cursor(dictionary=True)
        connection.start_transaction()
        _finalize_exhausted_job(cursor, stale_after)
        cursor.execute(
            f"""
            SELECT *
            FROM analysis_jobs
            WHERE (
                status = 'queued'
                OR (
                    status = 'running'
                    AND (heartbeat_at IS NULL OR heartbeat_at <
                         (UTC_TIMESTAMP(6) - INTERVAL {stale_after} SECOND))
                    AND recovery_count < max_attempts
                )
            )
            ORDER BY CASE WHEN status = 'queued' THEN 0 ELSE 1 END, created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        )
        job = cursor.fetchone()
        if not job:
            connection.commit()
            return None
        stale = job["status"] == "running"
        if stale and _repair_pending_interrupt(cursor, job):
            connection.commit()
            return None
        cursor.execute(
            """
            UPDATE analysis_jobs
            SET status = 'running', worker_id = %s,
                lease_epoch = lease_epoch + 1,
                locked_at = UTC_TIMESTAMP(6), heartbeat_at = UTC_TIMESTAMP(6),
                started_at = COALESCE(started_at, UTC_TIMESTAMP(6)),
                attempt_count = attempt_count + 1,
                recovery_count = recovery_count + %s
            WHERE id = %s AND status IN ('queued', 'running')
            """,
            (worker_id, 1 if stale else 0, job["id"]),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return None
        connection.commit()
        claimed = _row_to_job(get_job_by_id(job["job_id"]))
        if claimed is not None:
            claimed["claim_kind"] = (
                "stale_recovery"
                if stale
                else "user_resume"
                if int(job.get("resume_count") or 0) > 0
                else "initial"
            )
        return claimed
    except _CheckpointRecoveryBlocked:
        # 不确认 checkpoint 就不能安全地把 stale Job 重新执行；回滚本轮锁定，
        # 让下一次领取继续重试，而不是把任务误判为可重放或失败。
        connection.rollback()
        return None
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_job_by_id(job_id: str) -> dict[str, Any] | None:
    """按 Job ID 强一致读取，不做用户权限判断。"""
    with get_read_connection(consistency="strong") as connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM analysis_jobs WHERE job_id = %s", (job_id,))
        return _row_to_job(cursor.fetchone())


def _decode_input_record(row: dict[str, Any]) -> dict[str, Any]:
    """按 input_type 解码输入账本，初始 JSON 文本永远保持字符串。"""
    stored = row.get("input_text")
    if isinstance(stored, (bytes, bytearray)):
        stored = bytes(stored).decode("utf-8")
    if not isinstance(stored, str):
        stored = "" if stored is None else str(stored)
    input_type = str(row.get("input_type") or "")
    runtime_value: Any = stored
    if input_type == "resume" and stored[:1] in {"{", "["}:
        try:
            parsed = json.loads(stored)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            runtime_value = parsed
    return {
        "input_type": input_type,
        "runtime_value": runtime_value,
        "stored_text": stored,
        "chat_message_id": (
            int(row["chat_message_id"])
            if row.get("chat_message_id") is not None
            else None
        ),
    }


def _get_input_record(job_id: str, *, sequence: int | None = None) -> dict[str, Any] | None:
    """读取 Job 输入账本的指定序号或最后一条输入。"""
    with get_read_connection(consistency="strong") as connection:
        cursor = connection.cursor(dictionary=True)
        if sequence is None:
            cursor.execute(
                """
                SELECT input_type, input_text, chat_message_id
                FROM analysis_job_inputs
                WHERE job_id = %s
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (job_id,),
            )
        else:
            cursor.execute(
                """
                SELECT input_type, input_text, chat_message_id
                FROM analysis_job_inputs
                WHERE job_id = %s AND sequence = %s
                LIMIT 1
                """,
                (job_id, sequence),
            )
        row = cursor.fetchone()
    if not row:
        return None
    return _decode_input_record(row)


def get_latest_input_value(job_id: str) -> dict[str, Any] | None:
    """读取 Job 输入账本最后一条，并只为 resume 恢复结构化运行时值。"""
    return _get_input_record(job_id)


def get_initial_input_value(job_id: str) -> dict[str, Any] | None:
    """读取 Job 序号为 0 的冻结初始输入，用于无 checkpoint 的 stale 重启。"""
    return _get_input_record(job_id, sequence=0)


def update_heartbeat(
    job_id: str,
    worker_id: str,
    attempt_count: int,
    lease_epoch: int | None = None,
) -> bool:
    """仅为当前 worker attempt 和 lease epoch 刷新 heartbeat。"""
    with get_write_connection() as connection:
        cursor = connection.cursor()
        if lease_epoch is None:
            cursor.execute(
                """
                UPDATE analysis_jobs SET heartbeat_at = UTC_TIMESTAMP(6)
                WHERE job_id = %s AND worker_id = %s AND attempt_count = %s
                  AND status = 'running'
                """,
                (job_id, worker_id, attempt_count),
            )
        else:
            cursor.execute(
                """
                UPDATE analysis_jobs SET heartbeat_at = UTC_TIMESTAMP(6)
                WHERE job_id = %s AND worker_id = %s AND attempt_count = %s
                  AND lease_epoch = %s AND status = 'running'
                """,
                (job_id, worker_id, attempt_count, lease_epoch),
            )
        connection.commit()
        return cursor.rowcount == 1


def write_event(
    job_id: str,
    worker_id: str,
    attempt_count: int,
    event_type: str,
    payload: dict[str, Any],
    *,
    lease_epoch: int | None = None,
    event_key: str | None = None,
) -> int | None:
    """仅为当前租约写入普通事件，生命周期键支持安全重放。"""
    with get_write_connection() as connection:
        try:
            connection.start_transaction()
            cursor = connection.cursor(dictionary=True)
            if not _lock_owned_running_job(
                cursor,
                job_id,
                worker_id,
                attempt_count,
                lease_epoch,
            ):
                connection.rollback()
                return None
            event_id = _insert_event(
                cursor,
                job_id=job_id,
                event_type=event_type,
                payload=payload,
                event_key=event_key or _event_key(event_type, payload),
            )
            connection.commit()
            return event_id
        except Exception:
            connection.rollback()
            raise


def read_events_after(job_id: str, after_id: int = 0, limit: int = 100) -> list[dict[str, Any]]:
    """读取指定事件 ID 之后的强一致公开事件。"""
    with get_read_connection(consistency="strong") as connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, job_id, event_type, event_key, payload_json, created_at
            FROM analysis_job_events
            WHERE job_id = %s AND id > %s
            ORDER BY id ASC
            LIMIT %s
            """,
            (job_id, after_id, limit),
        )
        rows = cursor.fetchall()
    for row in rows:
        row["payload_json"] = _json_loads(row["payload_json"])
    return rows


def complete_job(
    job_id: str,
    worker_id: str,
    attempt_count: int,
    result: dict[str, Any] | None,
    lease_epoch: int | None = None,
) -> bool:
    """为没有显式终态事件的旧执行路径补写成功终态。"""
    job = get_job_by_id(job_id)
    if not job:
        return False
    return _complete_job_lifecycle(
        job,
        worker_id,
        "final_result",
        {"type": "final_result", "data": result or {}},
        lease_epoch=lease_epoch,
        result=result or {},
        status="succeeded",
    )


def complete_job_with_chat(
    job: dict[str, Any],
    worker_id: str,
    event_type: str,
    payload: dict[str, Any],
    chat_response: dict[str, Any] | str,
    result: dict[str, Any] | None,
    *,
    lease_epoch: int | None = None,
    question_id: str | None = None,
) -> bool:
    """在一个事务内完成 final、error 或 interrupt 生命周期。"""
    if event_type == "interrupt":
        return _complete_job_lifecycle(
            job,
            worker_id,
            event_type,
            payload,
            lease_epoch=lease_epoch,
            question_id=question_id,
            chat_response=chat_response,
            status="waiting_input",
        )
    if event_type == "error":
        return _complete_job_lifecycle(
            job,
            worker_id,
            event_type,
            payload,
            lease_epoch=lease_epoch,
            chat_response=chat_response,
            status="failed",
        )
    return _complete_job_lifecycle(
        job,
        worker_id,
        "final_result",
        payload,
        lease_epoch=lease_epoch,
        chat_response=chat_response,
        result=result,
        status="succeeded",
    )


def fail_job(
    job_id: str,
    worker_id: str,
    attempt_count: int,
    message: str,
    *,
    lease_epoch: int | None = None,
    write_error_event: bool = True,
) -> bool:
    """以当前 lease 将 Job 失败，并原子写入 error 事件和 assistant 消息。"""
    logging.error("analysis job %s failed", job_id)
    job = get_job_by_id(job_id)
    if not job or int(job.get("attempt_count") or 0) != int(attempt_count):
        return False
    if not write_error_event:
        with get_write_connection() as connection:
            cursor = connection.cursor()
            if lease_epoch is None:
                cursor.execute(
                    """
                    UPDATE analysis_jobs
                    SET status = 'failed', error_message = %s, last_error = %s,
                        active_session_key = NULL, finished_at = UTC_TIMESTAMP(6)
                    WHERE job_id = %s AND worker_id = %s AND attempt_count = %s
                      AND status = 'running'
                    """,
                    (message, message, job_id, worker_id, attempt_count),
                )
            else:
                cursor.execute(
                    """
                    UPDATE analysis_jobs
                    SET status = 'failed', error_message = %s, last_error = %s,
                        active_session_key = NULL, finished_at = UTC_TIMESTAMP(6)
                    WHERE job_id = %s AND worker_id = %s AND attempt_count = %s
                      AND lease_epoch = %s AND status = 'running'
                    """,
                    (message, message, job_id, worker_id, attempt_count, lease_epoch),
                )
            connection.commit()
            return cursor.rowcount == 1
    return _complete_job_lifecycle(
        job,
        worker_id,
        "error",
        {"type": "error", "message": message},
        lease_epoch=lease_epoch,
        chat_response={"type": "text", "summary": message},
        status="failed",
    )


def resume_job(
    user_id: int,
    job_id: str,
    question_id: str,
    answer: Any,
    idempotency_key: str,
) -> tuple[dict[str, Any], bool]:
    """在 waiting_input Job 上追加恢复输入并重新排队。"""
    normalized_answer, _runtime_answer = _normalize_input_value(answer)
    question_id = question_id.strip() if isinstance(question_id, str) else ""
    if not question_id or len(question_id) > 255:
        raise ValueError("question_id 无效")
    idempotency_key = normalize_idempotency_key(idempotency_key)
    fingerprint = _action_fingerprint(
        job_id=job_id,
        action="resume",
        text=normalized_answer,
        question_id=question_id,
    )
    with get_write_connection() as connection:
        try:
            cursor = connection.cursor(dictionary=True)
            connection.start_transaction()
            job = _lock_job_then_session(
                cursor,
                job_id=job_id,
                user_id=user_id,
            )
            if not job:
                raise PermissionError("任务不存在或无权访问")
            cursor.execute(
                """
                SELECT * FROM analysis_job_inputs
                WHERE job_id = %s AND idempotency_key = %s
                FOR UPDATE
                """,
                (job_id, idempotency_key),
            )
            existing_input = cursor.fetchone()
            if existing_input:
                if existing_input["request_fingerprint"] != fingerprint:
                    raise IdempotencyConflictError("Idempotency-Key 已用于不同的恢复输入")
                connection.commit()
                return job, True
            if job["status"] != "waiting_input":
                raise JobStateConflictError("任务当前不在 waiting_input 状态", job)
            if job.get("current_question_id") != question_id:
                raise JobStateConflictError("question_id 与当前等待问题不匹配", job)

            cursor.execute(
                "SELECT COALESCE(MAX(sequence), -1) + 1 AS next_sequence FROM analysis_job_inputs WHERE job_id = %s",
                (job_id,),
            )
            sequence_row = cursor.fetchone() or {}
            sequence = int(sequence_row.get("next_sequence") or 0)
            cursor.execute(
                """
                INSERT INTO analysis_job_inputs (
                    job_id, sequence, input_type, input_text, question_id,
                    idempotency_key, request_fingerprint
                ) VALUES (%s, %s, 'resume', %s, %s, %s, %s)
                """,
                (job_id, sequence, normalized_answer, question_id, idempotency_key, fingerprint),
            )
            input_id = int(cursor.lastrowid)
            chat_message_id = save_user_input_for_job_in_transaction(
                cursor,
                job_id=job_id,
                input_id=input_id,
                user_id=user_id,
                session_id=job["session_id"],
                text=normalized_answer,
            )
            cursor.execute(
                "UPDATE analysis_job_inputs SET chat_message_id = %s WHERE input_id = %s",
                (chat_message_id, input_id),
            )
            cursor.execute(
                """
                UPDATE analysis_jobs
                SET status = 'queued', resume_count = resume_count + 1,
                    current_question_id = NULL, current_waiting_prompt = NULL,
                    finished_at = NULL
                WHERE job_id = %s AND status = 'waiting_input'
                """,
                (job_id,),
            )
            if cursor.rowcount != 1:
                raise JobStateConflictError("任务状态已被其他请求改变")
            connection.commit()
            refreshed = get_job_for_user(job_id, user_id)
            if not refreshed:
                raise RuntimeError("恢复后无法读取 Job")
            return refreshed, False
        except Exception:
            connection.rollback()
            raise


def cancel_job(
    user_id: int,
    job_id: str,
    idempotency_key: str,
) -> tuple[dict[str, Any], bool]:
    """取消 waiting_input Job，并幂等写入 canceled 生命周期事件。"""
    idempotency_key = normalize_idempotency_key(idempotency_key)
    fingerprint = _action_fingerprint(job_id=job_id, action="cancel")
    payload = {"type": "canceled", "message": "任务已取消"}
    event_key = "terminal:canceled"
    with get_write_connection() as connection:
        try:
            cursor = connection.cursor(dictionary=True)
            connection.start_transaction()
            job = _lock_job_then_session(
                cursor,
                job_id=job_id,
                user_id=user_id,
            )
            if not job:
                raise PermissionError("任务不存在或无权访问")
            stored_key = job.get("cancel_idempotency_key")
            if stored_key and stored_key == idempotency_key:
                if job.get("cancel_request_fingerprint") != fingerprint:
                    raise IdempotencyConflictError("Idempotency-Key 已用于不同的取消请求")
                connection.commit()
                return job, True
            existing = _existing_event(cursor, job_id, event_key)
            if existing:
                if not _payload_matches(existing["payload_json"], payload):
                    raise IdempotencyConflictError("取消事件 payload 不一致")
                connection.commit()
                return job, True
            if job["status"] == "canceled":
                raise JobStateConflictError("任务已经取消", job)
            if job["status"] != "waiting_input":
                raise JobStateConflictError("只有 waiting_input 任务可以取消", job)
            event_id = _insert_event(
                cursor,
                job_id=job_id,
                event_type="canceled",
                payload=payload,
                event_key=event_key,
            )
            save_assistant_for_job_in_transaction(
                cursor,
                job_id=job_id,
                user_id=user_id,
                session_id=job["session_id"],
                ai_response={"type": "text", "summary": payload["message"]},
                source_event_id=event_id,
                analysis_job_input_id=_latest_input_id(cursor, job_id),
            )
            cursor.execute(
                """
                UPDATE analysis_jobs
                SET status = 'canceled', active_session_key = NULL,
                    current_question_id = NULL, current_waiting_prompt = NULL,
                    cancel_idempotency_key = %s,
                    cancel_request_fingerprint = %s,
                    finished_at = UTC_TIMESTAMP(6)
                WHERE job_id = %s AND status = 'waiting_input'
                """,
                (idempotency_key, fingerprint, job_id),
            )
            if cursor.rowcount != 1:
                raise JobStateConflictError("任务状态已被其他请求改变")
            connection.commit()
            refreshed = get_job_for_user(job_id, user_id)
            if not refreshed:
                raise RuntimeError("取消后无法读取 Job")
            return refreshed, False
        except Exception:
            connection.rollback()
            raise


def get_worker_snapshot() -> list[dict[str, Any]]:
    """返回活动 Job 快照。"""
    return get_worker_snapshot_report()["jobs"]


def get_worker_snapshot_report() -> dict[str, Any]:
    """返回 queued/running/waiting_input 汇总和 worker 活动摘要。"""
    observed_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
    try:
        connection, source = get_read_connection_with_source(consistency="strong")
        stale_after = int(settings.JOB_STALE_AFTER_SECONDS)
        timeout_ms = int(settings.DB_INSPECTION_QUERY_TIMEOUT_MS)
        with connection as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                f"""
                SELECT /*+ MAX_EXECUTION_TIME({timeout_ms}) */
                    SUM(status = 'queued') AS queued,
                    SUM(status = 'running') AS running,
                    SUM(status = 'waiting_input') AS waiting_input,
                    SUM(status = 'running' AND (heartbeat_at IS NULL OR
                        heartbeat_at < (UTC_TIMESTAMP(6) - INTERVAL {stale_after} SECOND))) AS stale,
                    SUM(status = 'running' AND recovery_count >= max_attempts) AS max_attempts_running
                FROM analysis_jobs
                WHERE status IN ('queued', 'running', 'waiting_input')
                """
            )
            summary_row = cursor.fetchone() or {}
            cursor.execute(
                f"""
                SELECT /*+ MAX_EXECUTION_TIME({timeout_ms}) */
                    job_id, status, worker_id, lease_epoch, heartbeat_at,
                    attempt_count, recovery_count, resume_count, max_attempts, created_at
                FROM analysis_jobs
                WHERE status IN ('queued', 'running', 'waiting_input')
                ORDER BY created_at ASC
                LIMIT 100
                """
            )
            jobs = cursor.fetchall()
        summary = {
            key: int(summary_row.get(key) or 0)
            for key in ("queued", "running", "waiting_input", "stale", "max_attempts_running")
        }
        warning = None
        status = "healthy"
        if summary["stale"] or summary["max_attempts_running"]:
            status = "warning"
            warning = "存在心跳过期或 stale recovery 达到上限的任务"
        return {
            "jobs": jobs,
            "summary": summary,
            "status": status,
            "observed_at": observed_at,
            **source,
            "is_estimate": False,
            "warning": warning,
        }
    except Exception:
        logging.warning("读取 worker/job 看板快照失败", exc_info=True)
        return {
            "jobs": [],
            "summary": {
                "queued": None,
                "running": None,
                "waiting_input": None,
                "stale": None,
                "max_attempts_running": None,
            },
            "status": "unknown",
            "observed_at": observed_at,
            "source_role": "primary",
            "source_alias": "primary",
            "is_estimate": False,
            "warning": "读取 worker/job 快照失败",
        }
