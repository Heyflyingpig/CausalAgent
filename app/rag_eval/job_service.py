"""R5 隔离评测的持久任务队列。

Web 进程只负责创建、读取和取消评测任务；真正的评测由 resident worker
领取并执行。运行产物仍保存在每次评测自己的目录中，数据库只保存队列、
租约和错误状态，避免把大型报告写入 SQL。
"""

from __future__ import annotations

import json
from typing import Any

from app.db import get_read_connection, get_write_connection
from config.settings import settings


def _json_dumps(value: Any) -> str:
    """将 worker 任务参数编码为 MySQL JSON 字符串。"""
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: Any) -> Any:
    """将数据库中的 JSON 字段解码为 Python 对象。"""
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    return json.loads(value)


def _row_to_job(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """把数据库行转换为接口和 worker 可直接使用的 job 字典。"""
    if not row:
        return None
    row = dict(row)
    row["payload_json"] = _json_loads(row.get("payload_json")) or {}
    return row


def enqueue_evaluation(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """将一个隔离评测加入持久队列，并使用 run_id 保证幂等。"""
    conn = get_write_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO rag_eval_jobs (
                run_id, status, payload_json, max_attempts, created_at
            ) VALUES (%s, 'queued', %s, %s, UTC_TIMESTAMP(6))
            """,
            (run_id, _json_dumps(payload), 1),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    job = get_evaluation_job(run_id)
    if job is None:
        raise RuntimeError(f"评测任务入队后无法读取: {run_id}")
    return job


def get_evaluation_job(run_id: str) -> dict[str, Any] | None:
    """按 run_id 强一致读取评测队列状态。"""
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM rag_eval_jobs WHERE run_id = %s", (run_id,))
        return _row_to_job(cursor.fetchone())


def claim_next_evaluation(worker_id: str) -> dict[str, Any] | None:
    """原子领取最早的 queued 评测，避免多个 worker 重复执行。"""
    conn = get_write_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()
        cursor.execute(
            """
            SELECT *
            FROM rag_eval_jobs
            WHERE status = 'queued'
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        )
        job = cursor.fetchone()
        if not job:
            conn.commit()
            return None
        cursor.execute(
            """
            UPDATE rag_eval_jobs
            SET status = 'running',
                worker_id = %s,
                locked_at = UTC_TIMESTAMP(6),
                heartbeat_at = UTC_TIMESTAMP(6),
                started_at = COALESCE(started_at, UTC_TIMESTAMP(6)),
                attempt_count = attempt_count + 1
            WHERE id = %s AND status = 'queued'
            """,
            (worker_id, job["id"]),
        )
        conn.commit()
        job.update(
            {
                "status": "running",
                "worker_id": worker_id,
                "attempt_count": int(job.get("attempt_count") or 0) + 1,
            }
        )
        return _row_to_job(job)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def heartbeat_evaluation(run_id: str, worker_id: str) -> bool:
    """刷新评测 worker 租约；返回该租约是否仍归当前 worker。"""
    with get_write_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE rag_eval_jobs
            SET heartbeat_at = UTC_TIMESTAMP(6)
            WHERE run_id = %s AND worker_id = %s AND status = 'running'
            """,
            (run_id, worker_id),
        )
        conn.commit()
        return cursor.rowcount == 1


def complete_evaluation(run_id: str) -> None:
    """把当前 worker 正常完成的评测标记为 succeeded。"""
    with get_write_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE rag_eval_jobs
            SET status = 'succeeded',
                heartbeat_at = UTC_TIMESTAMP(6),
                finished_at = UTC_TIMESTAMP(6)
            WHERE run_id = %s AND status = 'running'
            """,
            (run_id,),
        )
        conn.commit()


def fail_evaluation(run_id: str, message: str) -> None:
    """记录评测失败，供 worker 异常和超时收敛使用。"""
    with get_write_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE rag_eval_jobs
            SET status = 'failed',
                error_message = %s,
                last_error = %s,
                heartbeat_at = UTC_TIMESTAMP(6),
                finished_at = UTC_TIMESTAMP(6)
            WHERE run_id = %s AND status IN ('queued', 'running')
            """,
            (message, message, run_id),
        )
        conn.commit()


def cancel_evaluation(run_id: str) -> dict[str, Any] | None:
    """取消 queued 或 running 评测；运行中的任务再由 run.json 协作停止。"""
    with get_write_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE rag_eval_jobs
            SET status = 'cancelled',
                finished_at = UTC_TIMESTAMP(6),
                error_message = 'cancelled by user'
            WHERE run_id = %s AND status IN ('queued', 'running')
            """,
            (run_id,),
        )
        conn.commit()
    return get_evaluation_job(run_id)


def reconcile_stale_evaluations(limit: int = 100) -> list[dict[str, Any]]:
    """将 heartbeat 超时的 running 评测一次性收敛为 failed。

    评测默认不自动重试：Ragas 可能已经产生外部模型调用，自动重跑会让
    报告出现重复请求且难以解释。用户可以在失败后显式重新发起一次。
    """
    stale_after = max(int(getattr(settings, "R5_EVALUATION_JOB_STALE_AFTER_SECONDS", 120)), 30)
    safe_limit = min(max(int(limit or 100), 1), 500)
    conn = get_write_connection()
    stale_jobs: list[dict[str, Any]] = []
    try:
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()
        cursor.execute(
            f"""
            SELECT *
            FROM rag_eval_jobs
            WHERE status = 'running'
              AND heartbeat_at < (UTC_TIMESTAMP(6) - INTERVAL {stale_after} SECOND)
            ORDER BY heartbeat_at ASC
            LIMIT {safe_limit}
            FOR UPDATE SKIP LOCKED
            """
        )
        stale_jobs = cursor.fetchall()
        if stale_jobs:
            ids = [job["id"] for job in stale_jobs]
            placeholders = ",".join(["%s"] * len(ids))
            message = f"评测 worker heartbeat 超时（>{stale_after} 秒），任务未完成"
            cursor.execute(
                f"""
                UPDATE rag_eval_jobs
                SET status = 'failed',
                    error_message = %s,
                    last_error = %s,
                    finished_at = UTC_TIMESTAMP(6)
                WHERE id IN ({placeholders}) AND status = 'running'
                """,
                (message, message, *ids),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    for job in stale_jobs:
        job = dict(job)
        job["error_message"] = f"评测 worker heartbeat 超时（>{stale_after} 秒），任务未完成"
        job["last_error"] = job["error_message"]
        job["status"] = "failed"
    return stale_jobs
