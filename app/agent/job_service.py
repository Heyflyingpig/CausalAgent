"""
长任务队列服务。

Web 进程只调用创建 job、读取事件；worker 进程调用领取、心跳、
写事件和终态更新。实时路径全部走写库，避免副本延迟影响 SSE。
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import uuid
from typing import Any

import mysql.connector
from mysql.connector import errorcode

from app.chat.session_title import build_session_title
from app.db import get_read_connection, get_read_connection_with_source, get_write_connection
from config.settings import settings


ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("succeeded", "failed", "canceled")
TERMINAL_EVENTS = {"final_result", "interrupt", "error"}


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: Any) -> Any:
    """将原本的 JSON 字符串反序列化为 Python 的字典或列表"""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    return json.loads(value)


def _row_to_job(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """数据清洗"""
    if not row:
        return None
    if "result_json" in row:
        row["result_json"] = _json_loads(row["result_json"])
    return row


def get_active_job(user_id: int, session_id: str) -> dict[str, Any] | None:
    """读取同一用户同一会话下尚未结束的 job。"""
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT *
            FROM analysis_jobs
            WHERE user_id = %s
              AND session_id = %s
              AND status IN ('queued', 'running')
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (user_id, session_id),
        )
        return _row_to_job(cursor.fetchone())


def get_job_for_user(job_id: str, user_id: int) -> dict[str, Any] | None:
    """按 job_id 和用户校验读取 job，返回该用户job的所有值。"""
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM analysis_jobs WHERE job_id = %s AND user_id = %s",
            (job_id, user_id),
        )
        return _row_to_job(cursor.fetchone())


def create_job(user_id: int, session_id: str, message: str) -> tuple[dict[str, Any], bool]:
    """
    创建 job；若同一用户同一会话已有 active job，返回已有 job。
    两个请求同时给同一 user_id + session_id 创建 active job 时，第二个会撞唯一约束，不能插入成功。
    """
    job_id = str(uuid.uuid4())
    now = datetime.now()
    conn = get_write_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()
        # 如果主键重复，直接忽略，确保数据库里绝对有这一行数据，同时避免主键sessionid，延迟创建而重复插入崩溃。
        cursor.execute(
            """
            INSERT INTO sessions (id, user_id, title, created_at, last_activity_at, message_count)
            VALUES (%s, %s, %s, %s, %s, 0)
            ON DUPLICATE KEY UPDATE id = id
            """,
            (session_id, user_id, build_session_title(message), now, now),
        )
        # 增加悲观锁，查看当前session属于当前用户
        cursor.execute(
            "SELECT id FROM sessions WHERE id = %s AND user_id = %s FOR UPDATE",
            (session_id, user_id),
        )
        if not cursor.fetchone():
            conn.rollback()
            raise PermissionError("会话不存在或不属于当前用户")
        # f"{user_id}:{session_id}" 对应UNIQUE KEY uq_analysis_jobs_active_session (active_session_key)唯一键
        cursor.execute(
            """
            INSERT INTO analysis_jobs (
                job_id, user_id, session_id, message, status, max_attempts, created_at, active_session_key
            ) VALUES (%s, %s, %s, %s, 'queued', %s, %s, %s)
            """,
            (
                job_id,
                user_id,
                session_id,
                message,
                settings.JOB_MAX_ATTEMPTS,
                now,
                f"{user_id}:{session_id}",
            ),
        )
        conn.commit()
        job = get_job_for_user(job_id, user_id)
        if job is None:
            raise RuntimeError("job 创建后无法读取")
        # 创建成功后，返回新 job。第二个返回值 False 表示：这不是已有任务，是新创建的任务。
        return job, False
    except mysql.connector.Error as exc:
        conn.rollback()
        if exc.errno == errorcode.ER_DUP_ENTRY:
            existing = get_active_job(user_id, session_id)
            if existing:
                return existing, True
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def claim_next_job(worker_id: str, stale_after_seconds: int | None = None) -> dict[str, Any] | None:
    """
    领取一个可执行 job。

    领取范围包括 queued job，以及 heartbeat 超时且未超过最大尝试次数的
    running job。SQL 使用 FOR UPDATE SKIP LOCKED，避免多个 worker slot
    抢到同一个任务。
    """
    stale_after = int(stale_after_seconds or settings.JOB_STALE_AFTER_SECONDS)
    conn = get_write_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()
        ## 执行抢任务，并锁住
        cursor.execute(
            f"""
            SELECT *
            FROM analysis_jobs
            WHERE (
                    status = 'queued'
                    OR (
                        status = 'running'
                        AND heartbeat_at < (UTC_TIMESTAMP(6) - INTERVAL {stale_after} SECOND)
                    )
                  )
              AND attempt_count < max_attempts
            ORDER BY CASE WHEN status = 'queued' THEN 0 ELSE 1 END, created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        )
        job = cursor.fetchone()
        if not job:
            conn.commit()
            return None
        # 抢完任务之后，执行running
        cursor.execute(
            """
            UPDATE analysis_jobs
            SET status = 'running',
                worker_id = %s,
                locked_at = UTC_TIMESTAMP(6),
                heartbeat_at = UTC_TIMESTAMP(6),
                started_at = COALESCE(started_at, UTC_TIMESTAMP(6)),
                attempt_count = attempt_count + 1
            WHERE id = %s
            """,
            (worker_id, job["id"]),
        )
        conn.commit()
        return _row_to_job(get_job_by_id(job["job_id"]))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_job_by_id(job_id: str) -> dict[str, Any] | None:
    """按 job_id 强一致读取 job，不做用户权限判断。"""
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM analysis_jobs WHERE job_id = %s", (job_id,))
        return _row_to_job(cursor.fetchone())


def update_heartbeat(job_id: str, worker_id: str) -> None:
    """刷新 running job 的 worker 心跳，用于崩溃恢复判断。检测进程或者协是否正常"""
    with get_write_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE analysis_jobs
            SET heartbeat_at = UTC_TIMESTAMP(6)
            WHERE job_id = %s AND worker_id = %s AND status = 'running'
            """,
            (job_id, worker_id),
        )
        conn.commit()


def write_event(job_id: str, event_type: str, payload: dict[str, Any]) -> int:
    """把 worker 产生的节点进度或终态事件写入事件表。"""
    with get_write_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO analysis_job_events (job_id, event_type, payload_json)
            VALUES (%s, %s, %s)
            """,
            (job_id, event_type, _json_dumps(payload)),
        )
        event_id = cursor.lastrowid
        conn.commit()
        return int(event_id)


def read_events_after(job_id: str, after_id: int = 0, limit: int = 100) -> list[dict[str, Any]]:
    """读取某个 job 在指定事件 id 之后的新事件，可以供 SSE 断线续传使用。"""
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, job_id, event_type, payload_json, created_at
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


def complete_job(job_id: str, result: dict[str, Any] | None) -> None:
    """把 job 标记为成功并保存最终结构化结果。"""
    with get_write_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE analysis_jobs
            SET status = 'succeeded',
                result_json = %s,
                active_session_key = NULL,
                heartbeat_at = UTC_TIMESTAMP(6),
                finished_at = UTC_TIMESTAMP(6)
            WHERE job_id = %s
            """,
            (_json_dumps(result or {}), job_id),
        )
        conn.commit()


def fail_job(job_id: str, message: str, *, write_error_event: bool = True) -> None:
    """把 job 标记为失败；必要时同时写入 error SSE 事件。"""
    logging.error("analysis job %s failed: %s", job_id, message)
    if write_error_event:
        write_event(job_id, "error", {"type": "error", "message": message})
    with get_write_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE analysis_jobs
            SET status = 'failed',
                error_message = %s,
                last_error = %s,
                active_session_key = NULL,
                heartbeat_at = UTC_TIMESTAMP(6),
                finished_at = UTC_TIMESTAMP(6)
            WHERE job_id = %s
            """,
            (message, message, job_id),
        )
        conn.commit()


def mark_chat_saved(job_id: str) -> bool:
    """幂等标记聊天历史已保存；返回本次调用是否真正写入标记。"""
    with get_write_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE analysis_jobs
            SET chat_saved_at = UTC_TIMESTAMP(6)
            WHERE job_id = %s AND chat_saved_at IS NULL
            """,
            (job_id,),
        )
        changed = cursor.rowcount > 0
        conn.commit()
        return changed


def get_worker_snapshot() -> list[dict[str, Any]]:
    """返回 queued/running job 快照，供轻量管理接口观察 worker 活性。"""
    return get_worker_snapshot_report()["jobs"]


def get_worker_snapshot_report() -> dict[str, Any]:
    """返回任务总量、异常计数和最多 100 条活动任务，并标明主库来源。"""
    observed_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
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
                    SUM(
                        status = 'running'
                        AND (
                            heartbeat_at IS NULL
                            OR heartbeat_at < (UTC_TIMESTAMP(6) - INTERVAL {stale_after} SECOND)
                        )
                    ) AS stale,
                    SUM(status = 'running' AND attempt_count >= max_attempts) AS max_attempts_running
                FROM analysis_jobs
                WHERE status IN ('queued', 'running')
                """
            )
            summary_row = cursor.fetchone() or {}
            cursor.execute(
                f"""
                SELECT /*+ MAX_EXECUTION_TIME({timeout_ms}) */
                    job_id, status, worker_id, heartbeat_at,
                    attempt_count, max_attempts, created_at
                FROM analysis_jobs
                WHERE status IN ('queued', 'running')
                ORDER BY created_at ASC
                LIMIT 100
                """
            )
            jobs = cursor.fetchall()

        summary = {
            key: int(summary_row.get(key) or 0)
            for key in ("queued", "running", "stale", "max_attempts_running")
        }
        warning = None
        status = "healthy"
        if summary["stale"] or summary["max_attempts_running"]:
            status = "warning"
            warning = "存在心跳过期或达到最大尝试次数但仍运行的任务"
        return {
            "jobs": jobs,
            "summary": summary,
            "status": status,
            "observed_at": observed_at,
            **source,
            "is_estimate": False,
            "warning": warning,
        }
    except Exception as exc:
        logging.warning("读取 worker/job 看板快照失败: %s", exc, exc_info=True)
        return {
            "jobs": [],
            "summary": {
                "queued": None,
                "running": None,
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
