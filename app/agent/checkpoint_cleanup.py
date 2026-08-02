"""MySQL cleanup outbox 与 PostgreSQL LangGraph checkpoint 的桥接服务。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Iterable

from app.db import get_write_connection


MAX_CLEANUP_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (10, 30)


def enqueue_checkpoint_cleanup(
    cursor,
    thread_id: str,
    *,
    operation_id: str | None = None,
) -> bool:
    """登记一个幂等 cleanup 任务，并返回是否仍需后台清理。"""
    cursor.execute(
        """
        INSERT INTO checkpoint_cleanup_outbox (
            thread_id, operation_id, status, attempts, available_at
        ) VALUES (%s, %s, 'pending', 0, UTC_TIMESTAMP(6))
        ON DUPLICATE KEY UPDATE
            operation_id = COALESCE(checkpoint_cleanup_outbox.operation_id, VALUES(operation_id)),
            status = IF(checkpoint_cleanup_outbox.status = 'succeeded',
                        checkpoint_cleanup_outbox.status, 'pending'),
            available_at = IF(checkpoint_cleanup_outbox.status = 'succeeded',
                              checkpoint_cleanup_outbox.available_at, UTC_TIMESTAMP(6)),
            lease_expires_at = NULL,
            last_error = NULL
        """,
        (thread_id, operation_id),
    )
    cursor.execute(
        "SELECT status FROM checkpoint_cleanup_outbox WHERE thread_id = %s",
        (thread_id,),
    )
    row = cursor.fetchone()
    status = row.get("status") if isinstance(row, dict) else (row[0] if row else None)
    return status != "succeeded"


def enqueue_checkpoint_cleanup_many(
    cursor,
    thread_ids: Iterable[str],
    *,
    operation_id: str | None = None,
) -> int:
    """批量登记用户删除涉及的 checkpoint thread，并返回输入数量。"""
    count = 0
    for thread_id in thread_ids:
        if enqueue_checkpoint_cleanup(cursor, str(thread_id), operation_id=operation_id):
            count += 1
    return count


def _json_loads(value: Any) -> dict[str, Any]:
    """读取管理员操作结果 JSON，兼容 MySQL 驱动的字符串和对象返回值。"""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    return json.loads(value)


def _json_dumps(value: Any) -> str:
    """编码不含敏感内容的 cleanup 聚合结果。"""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _update_operation_aggregate(cursor, operation_id: str | None) -> None:
    """根据 outbox 当前状态推进管理员操作的 running/succeeded/failed 状态。"""
    if not operation_id:
        return
    cursor.execute(
        """
        SELECT status, target_count, result_json
        FROM admin_operations
        WHERE operation_id = %s
        FOR UPDATE
        """,
        (operation_id,),
    )
    operation = cursor.fetchone()
    if not operation:
        logging.warning("checkpoint cleanup 找不到管理员操作: %s", operation_id)
        return

    cursor.execute(
        """
        SELECT
            COUNT(*) AS total_count,
            SUM(status = 'succeeded') AS succeeded_count,
            SUM(status = 'failed') AS failed_count,
            SUM(status IN ('pending', 'processing')) AS pending_count
        FROM checkpoint_cleanup_outbox
        WHERE operation_id = %s
        """,
        (operation_id,),
    )
    counts = cursor.fetchone() or {}
    total = int(counts.get("total_count") or 0)
    succeeded = int(counts.get("succeeded_count") or 0)
    failed = int(counts.get("failed_count") or 0)
    pending = int(counts.get("pending_count") or 0)
    if total == 0:
        return

    if failed:
        operation_status = "failed"
        cleanup_status = "failed"
    elif pending:
        operation_status = "running"
        cleanup_status = "pending"
    else:
        operation_status = "succeeded"
        cleanup_status = "succeeded"

    result = _json_loads(operation.get("result_json"))
    cleanup = result.get("checkpoint_cleanup") or {}
    cleanup.update(
        {
            "status": cleanup_status,
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "pending": pending,
        }
    )
    result["checkpoint_cleanup"] = cleanup
    result["status"] = operation_status
    completed_sql = (
        ", completed_at = UTC_TIMESTAMP(6)"
        if operation_status in {"succeeded", "failed"}
        else ", completed_at = NULL"
    )
    cursor.execute(
        f"""
        UPDATE admin_operations
        SET status = %s,
            succeeded_count = %s,
            failed_count = %s,
            result_json = %s
            {completed_sql}
        WHERE operation_id = %s
        """,
        (
            operation_status,
            int(operation.get("target_count") or 0) if operation_status == "succeeded" else 0,
            failed,
            _json_dumps(result),
            operation_id,
        ),
    )


def claim_cleanup_item(
    worker_id: str,
    *,
    lease_seconds: int = 300,
) -> dict[str, Any] | None:
    """使用行锁和 SKIP LOCKED 领取一个到期可执行的 cleanup outbox。"""
    connection = get_write_connection()
    try:
        cursor = connection.cursor(dictionary=True)
        connection.start_transaction()
        cursor.execute(
            """
            SELECT id, operation_id, attempts
            FROM checkpoint_cleanup_outbox
            WHERE status = 'processing'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at < UTC_TIMESTAMP(6)
            FOR UPDATE SKIP LOCKED
            """
        )
        expired_items = cursor.fetchall()
        expired_operations: set[str] = set()
        for expired in expired_items:
            expired_status = (
                "failed"
                if int(expired.get("attempts") or 0) >= MAX_CLEANUP_ATTEMPTS
                else "pending"
            )
            cursor.execute(
                """
                UPDATE checkpoint_cleanup_outbox
                SET status = %s, lease_expires_at = NULL,
                    completed_at = IF(%s = 'failed', UTC_TIMESTAMP(6), NULL)
                WHERE id = %s AND status = 'processing'
                """,
                (expired_status, expired_status, expired["id"]),
            )
            if expired.get("operation_id"):
                expired_operations.add(str(expired["operation_id"]))
        for operation_id in expired_operations:
            _update_operation_aggregate(cursor, operation_id)
        cursor.execute(
            """
            SELECT id, thread_id, operation_id, attempts
            FROM checkpoint_cleanup_outbox
            WHERE status = 'pending'
              AND attempts < %s
              AND available_at <= UTC_TIMESTAMP(6)
            ORDER BY id ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """,
            (MAX_CLEANUP_ATTEMPTS,),
        )
        item = cursor.fetchone()
        if not item:
            connection.commit()
            return None
        cursor.execute(
            """
            UPDATE checkpoint_cleanup_outbox
            SET status = 'processing',
                attempts = attempts + 1,
                lease_expires_at = %s,
                last_error = NULL
            WHERE id = %s AND status = 'pending'
            """,
            (
                datetime.now(timezone.utc).replace(tzinfo=None)
                + timedelta(seconds=lease_seconds),
                item["id"],
            ),
        )
        connection.commit()
        item["attempts"] = int(item.get("attempts") or 0) + 1
        return item
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def mark_cleanup_succeeded(item_id: int) -> None:
    """将 cleanup 标记为成功，并在同一事务内刷新管理员操作聚合状态。"""
    with get_write_connection() as connection:
        cursor = connection.cursor(dictionary=True)
        connection.start_transaction()
        cursor.execute(
            """
            SELECT operation_id
            FROM checkpoint_cleanup_outbox
            WHERE id = %s
            FOR UPDATE
            """,
            (item_id,),
        )
        item = cursor.fetchone()
        if not item:
            connection.rollback()
            return
        cursor.execute(
            """
            UPDATE checkpoint_cleanup_outbox
            SET status = 'succeeded',
                lease_expires_at = NULL,
                last_error = NULL,
                completed_at = UTC_TIMESTAMP(6)
            WHERE id = %s AND status = 'processing'
            """,
            (item_id,),
        )
        _update_operation_aggregate(cursor, item.get("operation_id"))
        connection.commit()


def mark_cleanup_failed(item_id: int, message: str) -> None:
    """记录一次 PostgreSQL 清理失败，并按 10/30 秒策略安排有限重试。"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_write_connection() as connection:
        cursor = connection.cursor(dictionary=True)
        connection.start_transaction()
        cursor.execute(
            """
            SELECT operation_id, attempts
            FROM checkpoint_cleanup_outbox
            WHERE id = %s
            FOR UPDATE
            """,
            (item_id,),
        )
        item = cursor.fetchone()
        if not item:
            connection.rollback()
            return
        attempts = int(item.get("attempts") or 0)
        terminal = attempts >= MAX_CLEANUP_ATTEMPTS
        retry_delay = RETRY_DELAYS_SECONDS[min(attempts - 1, len(RETRY_DELAYS_SECONDS) - 1)]
        available_at = now + timedelta(seconds=retry_delay)
        cursor.execute(
            """
            UPDATE checkpoint_cleanup_outbox
            SET status = %s,
                available_at = %s,
                lease_expires_at = NULL,
                last_error = %s,
                completed_at = %s
            WHERE id = %s AND status = 'processing'
            """,
            (
                "failed" if terminal else "pending",
                available_at,
                message[:4000],
                now if terminal else None,
                item_id,
            ),
        )
        _update_operation_aggregate(cursor, item.get("operation_id"))
        connection.commit()
