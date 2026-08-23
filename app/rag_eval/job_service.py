"""隔离评测长任务的持久队列与容量读取。

本文件只负责 MySQL 任务入队、领取、状态收敛和并发限制，不执行具体摄取或
评测逻辑；实际任务由常驻 worker 按 job_kind 分发。
"""

from __future__ import annotations

import json
from typing import Any

from app.db import get_read_connection, get_write_connection
from config.settings import settings

_JOB_KINDS = {"ingestion", "candidate_generation", "rag_query", "evaluation", "dataset_governance", "tuning_dataset_governance"}
_JOB_PRIORITIES = {
    "rag_query": 60,
    "evaluation": 50,
    "dataset_governance": 40,
    "tuning_dataset_governance": 30,
    "candidate_generation": 20,
    "ingestion": 10,
}
_JOB_LIMIT_SETTINGS = {
    "ingestion": "RAG_EVAL_INGESTION_CONCURRENCY_LIMIT",
    "candidate_generation": "RAG_EVAL_CANDIDATE_GENERATION_CONCURRENCY_LIMIT",
    "tuning_dataset_governance": "RAG_EVAL_TUNING_DATASET_GOVERNANCE_CONCURRENCY_LIMIT",
    "dataset_governance": "RAG_EVAL_DATASET_GOVERNANCE_CONCURRENCY_LIMIT",
    "evaluation": "RAG_EVAL_EVALUATION_CONCURRENCY_LIMIT",
    "rag_query": "RAG_EVAL_RAG_QUERY_CONCURRENCY_LIMIT",
}


def job_priority(job_kind: str) -> int:
    """返回由服务端固定定义的任务优先级。"""
    try:
        return _JOB_PRIORITIES[job_kind]
    except KeyError as exc:
        raise ValueError(f"不支持的隔离评测任务类型: {job_kind}") from exc


def job_limits() -> dict[str, int]:
    """读取各隔离评测任务类型的并发上限。"""
    return {kind: int(getattr(settings, setting_name)) for kind, setting_name in _JOB_LIMIT_SETTINGS.items()}


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    return json.loads(value)


def _row_to_job(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    result = dict(row)
    result["payload_json"] = _json_loads(result.get("payload_json")) or {}
    return result


def enqueue_job(run_id: str, job_kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """把已落盘的隔离评测长任务加入同一张持久队列。"""
    if job_kind not in _JOB_KINDS:
        raise ValueError(f"不支持的隔离评测任务类型: {job_kind}")
    conn = get_write_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO rag_eval_jobs (
                run_id, job_kind, priority, status, payload_json, max_attempts, created_at
            ) VALUES (%s, %s, %s, 'queued', %s, %s, UTC_TIMESTAMP(6))
            """,
            (run_id, job_kind, job_priority(job_kind), _json_dumps(payload), 1),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    job = get_job(run_id)
    if job is None:
        raise RuntimeError(f"隔离评测任务入队后无法读取: {run_id}")
    return job


def enqueue_evaluation(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """兼容旧入口。"""
    return enqueue_job(run_id, "evaluation", payload)


def get_job(run_id: str) -> dict[str, Any] | None:
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM rag_eval_jobs WHERE run_id = %s", (run_id,))
        return _row_to_job(cursor.fetchone())


def get_evaluation_job(run_id: str) -> dict[str, Any] | None:
    """兼容旧入口。"""
    return get_job(run_id)


def claim_next_job(worker_id: str) -> dict[str, Any] | None:
    """在命名锁保护下领取未超过类型并发上限的最高优先级任务。"""
    conn = get_write_connection()
    lock_acquired = False
    transaction_started = False
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT GET_LOCK('rag_eval_job_claim', 2)")
        lock_result = cursor.fetchone()
        lock_acquired = bool(lock_result and (lock_result[0] if not isinstance(lock_result, dict) else next(iter(lock_result.values()))))
        if not lock_acquired:
            return None
        conn.start_transaction()
        transaction_started = True
        cursor.execute(
            """
            SELECT job_kind, COUNT(*) AS running_count
            FROM rag_eval_jobs
            WHERE status = 'running'
            GROUP BY job_kind
            """
        )
        running_counts = {row["job_kind"]: int(row["running_count"]) for row in cursor.fetchall()}
        blocked_kinds = [kind for kind, limit in job_limits().items() if running_counts.get(kind, 0) >= limit]
        blocked_clause = ""
        blocked_params: tuple[str, ...] = ()
        if blocked_kinds:
            placeholders = ", ".join(["%s"] * len(blocked_kinds))
            blocked_clause = f" AND job_kind NOT IN ({placeholders})"
            blocked_params = tuple(blocked_kinds)
        cursor.execute(
            f"""
            SELECT * FROM rag_eval_jobs
            WHERE status = 'queued'{blocked_clause}
            ORDER BY priority DESC, created_at ASC, id ASC
            LIMIT 1 FOR UPDATE SKIP LOCKED
            """,
            blocked_params,
        )
        job = cursor.fetchone()
        if not job:
            conn.commit()
            transaction_started = False
            return None
        cursor.execute(
            """
            UPDATE rag_eval_jobs
            SET status = 'running', worker_id = %s, locked_at = UTC_TIMESTAMP(6),
                heartbeat_at = UTC_TIMESTAMP(6), started_at = COALESCE(started_at, UTC_TIMESTAMP(6)),
                attempt_count = attempt_count + 1
            WHERE id = %s AND status = 'queued'
            """,
            (worker_id, job["id"]),
        )
        conn.commit()
        transaction_started = False
        job.update({"status": "running", "worker_id": worker_id, "attempt_count": int(job.get("attempt_count") or 0) + 1})
        return _row_to_job(job)
    except Exception:
        if transaction_started:
            conn.rollback()
        raise
    finally:
        if lock_acquired:
            try:
                cursor.execute("SELECT RELEASE_LOCK('rag_eval_job_claim')")
                cursor.fetchone()
            except Exception:
                pass
        conn.close()


def get_capacity_snapshot() -> dict[str, Any]:
    """只读汇总隔离评测队列容量，不协调或修改任何任务状态。"""
    limits = job_limits()
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT status, job_kind, COUNT(*) AS count
            FROM rag_eval_jobs
            WHERE status IN ('queued', 'running')
            GROUP BY status, job_kind
            """
        )
        counts = cursor.fetchall()
        cursor.execute(
            """
            SELECT TIMESTAMPDIFF(SECOND, MIN(created_at), UTC_TIMESTAMP(6)) AS oldest_queued_age_seconds
            FROM rag_eval_jobs WHERE status = 'queued'
            """
        )
        oldest = cursor.fetchone() or {}
        stale_after = max(int(getattr(settings, "RAG_EVAL_EVALUATION_JOB_STALE_AFTER_SECONDS", 120)), 30)
        cursor.execute(
            f"""
            SELECT COUNT(*) AS stale_running_count,
                   TIMESTAMPDIFF(SECOND, MIN(heartbeat_at), UTC_TIMESTAMP(6)) AS oldest_heartbeat_age_seconds
            FROM rag_eval_jobs
            WHERE status = 'running'
              AND heartbeat_at < (UTC_TIMESTAMP(6) - INTERVAL {stale_after} SECOND)
            """
        )
        stale = cursor.fetchone() or {}

    kinds = {kind: {"queued": 0, "running": 0, "limit": limit} for kind, limit in limits.items()}
    for row in counts:
        kind = row["job_kind"]
        status = row["status"]
        if kind in kinds and status in ("queued", "running"):
            kinds[kind][status] = int(row["count"])
    queued_total = sum(item["queued"] for item in kinds.values())
    running_total = sum(item["running"] for item in kinds.values())
    configured_slots = int(settings.RAG_EVAL_EVALUATION_WORKERS)
    return {
        "configured_slots": configured_slots,
        "queued_total": queued_total,
        "running_total": running_total,
        "available_slots": max(configured_slots - running_total, 0),
        "kinds": kinds,
        "oldest_queued_age_seconds": oldest.get("oldest_queued_age_seconds"),
        "stale_running": {
            "count": int(stale.get("stale_running_count") or 0),
            "oldest_heartbeat_age_seconds": stale.get("oldest_heartbeat_age_seconds"),
        },
    }


def claim_next_evaluation(worker_id: str) -> dict[str, Any] | None:
    """兼容旧入口。"""
    return claim_next_job(worker_id)


def heartbeat_job(run_id: str, worker_id: str) -> bool:
    with get_write_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE rag_eval_jobs SET heartbeat_at = UTC_TIMESTAMP(6)
               WHERE run_id = %s AND worker_id = %s AND status = 'running'""",
            (run_id, worker_id),
        )
        conn.commit()
        return cursor.rowcount == 1


def heartbeat_evaluation(run_id: str, worker_id: str) -> bool:
    return heartbeat_job(run_id, worker_id)


def complete_job(run_id: str) -> bool:
    """把 running 任务收敛为 succeeded；返回是否真正发生了状态迁移。"""
    with get_write_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE rag_eval_jobs SET status = 'succeeded', heartbeat_at = UTC_TIMESTAMP(6),
               finished_at = UTC_TIMESTAMP(6) WHERE run_id = %s AND status = 'running'""",
            (run_id,),
        )
        conn.commit()
        return cursor.rowcount == 1


def complete_evaluation(run_id: str) -> bool:
    return complete_job(run_id)


def fail_job(run_id: str, message: str) -> None:
    with get_write_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE rag_eval_jobs SET status = 'failed', error_message = %s, last_error = %s,
               heartbeat_at = UTC_TIMESTAMP(6), finished_at = UTC_TIMESTAMP(6)
               WHERE run_id = %s AND status IN ('queued', 'running')""",
            (message, message, run_id),
        )
        conn.commit()


def fail_evaluation(run_id: str, message: str) -> None:
    fail_job(run_id, message)


def cancel_job(run_id: str) -> dict[str, Any] | None:
    with get_write_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE rag_eval_jobs SET status = 'cancelled', finished_at = UTC_TIMESTAMP(6),
               error_message = 'cancelled by user'
               WHERE run_id = %s AND status IN ('queued', 'running')""",
            (run_id,),
        )
        conn.commit()
    return get_job(run_id)


def cancel_evaluation(run_id: str) -> dict[str, Any] | None:
    return cancel_job(run_id)


def reconcile_stale_jobs(limit: int = 100) -> list[dict[str, Any]]:
    """将 heartbeat 超时任务失败关闭；绝不自动重跑。"""
    stale_after = max(int(getattr(settings, "RAG_EVAL_EVALUATION_JOB_STALE_AFTER_SECONDS", 120)), 30)
    safe_limit = min(max(int(limit or 100), 1), 500)
    message = f"RAG 任务 worker heartbeat 超时（{stale_after} 秒），任务未完成"
    conn = get_write_connection()
    stale_jobs: list[dict[str, Any]] = []
    try:
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()
        cursor.execute(
            f"""SELECT * FROM rag_eval_jobs WHERE status = 'running'
                AND heartbeat_at < (UTC_TIMESTAMP(6) - INTERVAL {stale_after} SECOND)
                ORDER BY heartbeat_at ASC LIMIT {safe_limit} FOR UPDATE SKIP LOCKED"""
        )
        stale_jobs = cursor.fetchall()
        if stale_jobs:
            placeholders = ",".join(["%s"] * len(stale_jobs))
            cursor.execute(
                f"""UPDATE rag_eval_jobs SET status = 'failed', error_message = %s, last_error = %s,
                    finished_at = UTC_TIMESTAMP(6) WHERE id IN ({placeholders}) AND status = 'running'""",
                (message, message, *(job["id"] for job in stale_jobs)),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    for job in stale_jobs:
        job.update({"error_message": message, "last_error": message, "status": "failed"})
    return stale_jobs


def reconcile_stale_evaluations(limit: int = 100) -> list[dict[str, Any]]:
    return reconcile_stale_jobs(limit)
