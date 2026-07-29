"""阶段一数据生命周期孤立记录修复 CLI。

默认只生成有限修复清单；只有同时提供 ``--apply`` 和精确数据库名确认时，
才会在单个主库事务中删除本批已再次验证仍然孤立的记录。migration 不调用
此脚本，也不会静默清理历史数据。
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from app.db import get_read_connection, get_write_connection
from config.settings import settings


DEFAULT_BATCH_LIMIT = 100
MAX_BATCH_LIMIT = 1000


def _parse_args() -> argparse.Namespace:
    """解析 dry-run、有限批次和显式数据库确认参数。"""
    parser = argparse.ArgumentParser(
        description="列出或修复 archived session/checkpoint 生命周期孤立记录",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_BATCH_LIMIT)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="执行本批物理删除；默认仅 dry-run",
    )
    parser.add_argument(
        "--confirm-database",
        default="",
        help="--apply 时必须精确填写 MYSQL_DATABASE",
    )
    args = parser.parse_args()
    if not 1 <= args.limit <= MAX_BATCH_LIMIT:
        parser.error(f"--limit 必须在 1 到 {MAX_BATCH_LIMIT} 之间")
    if args.apply and args.confirm_database != settings.MYSQL_DATABASE:
        parser.error("--apply 需要 --confirm-database 精确匹配当前 MYSQL_DATABASE")
    return args


def _scan(cursor, *, limit: int, for_update: bool) -> dict[str, list[Any]]:
    """扫描当前缺少外键保护的三类孤立关系，并只返回主键。"""
    lock_clause = " FOR UPDATE" if for_update else ""
    cursor.execute(
        f"""
        SELECT a.id
        FROM archived_sessions AS a
        LEFT JOIN users AS u ON u.id = a.user_id
        WHERE u.id IS NULL
        ORDER BY a.id
        LIMIT %s{lock_clause}
        """,
        (limit,),
    )
    archived_sessions = [row["id"] for row in cursor.fetchall()]
    cursor.execute(
        f"""
        SELECT c.thread_id, c.checkpoint_ns, c.checkpoint_id
        FROM checkpoints AS c
        LEFT JOIN sessions AS s ON s.id = c.thread_id
        WHERE s.id IS NULL
        ORDER BY c.thread_id, c.checkpoint_ns, c.checkpoint_id
        LIMIT %s{lock_clause}
        """,
        (limit,),
    )
    checkpoints = [
        {
            "thread_id": row["thread_id"],
            "checkpoint_ns": row["checkpoint_ns"],
            "checkpoint_id": row["checkpoint_id"],
        }
        for row in cursor.fetchall()
    ]
    cursor.execute(
        f"""
        SELECT w.id
        FROM checkpoint_writes AS w
        LEFT JOIN checkpoints AS c
          ON c.thread_id = w.thread_id
         AND c.checkpoint_ns = w.checkpoint_ns
         AND c.checkpoint_id = w.checkpoint_id
        WHERE c.thread_id IS NULL
        ORDER BY w.id
        LIMIT %s{lock_clause}
        """,
        (limit,),
    )
    checkpoint_writes = [int(row["id"]) for row in cursor.fetchall()]
    return {
        "archived_sessions": archived_sessions,
        "checkpoints": checkpoints,
        "checkpoint_writes": checkpoint_writes,
    }


def build_repair_plan(limit: int) -> dict[str, Any]:
    """通过主库强一致读生成不含正文的有限 dry-run 修复清单。"""
    with get_read_connection(consistency="strong") as connection:
        cursor = connection.cursor(dictionary=True)
        candidates = _scan(cursor, limit=limit, for_update=False)
    return {
        "mode": "dry-run",
        "limit_per_category": limit,
        "candidate_counts": {
            key: len(values)
            for key, values in candidates.items()
        },
        "candidates": candidates,
    }


def apply_repair_plan(limit: int) -> dict[str, Any]:
    """在主库事务中再次锁定并删除本批仍然孤立的记录。"""
    connection = get_write_connection()
    try:
        cursor = connection.cursor(dictionary=True)
        connection.start_transaction(isolation_level="READ COMMITTED")
        candidates = _scan(cursor, limit=limit, for_update=True)

        deleted_writes = 0
        for write_id in candidates["checkpoint_writes"]:
            cursor.execute(
                """
                DELETE w
                FROM checkpoint_writes AS w
                LEFT JOIN checkpoints AS c
                  ON c.thread_id = w.thread_id
                 AND c.checkpoint_ns = w.checkpoint_ns
                 AND c.checkpoint_id = w.checkpoint_id
                WHERE w.id = %s AND c.thread_id IS NULL
                """,
                (write_id,),
            )
            deleted_writes += cursor.rowcount

        deleted_checkpoints = 0
        for checkpoint in candidates["checkpoints"]:
            cursor.execute(
                """
                DELETE c
                FROM checkpoints AS c
                LEFT JOIN sessions AS s ON s.id = c.thread_id
                WHERE c.thread_id = %s
                  AND c.checkpoint_ns = %s
                  AND c.checkpoint_id = %s
                  AND s.id IS NULL
                """,
                (
                    checkpoint["thread_id"],
                    checkpoint["checkpoint_ns"],
                    checkpoint["checkpoint_id"],
                ),
            )
            deleted_checkpoints += cursor.rowcount

        deleted_archives = 0
        for archived_id in candidates["archived_sessions"]:
            cursor.execute(
                """
                DELETE a
                FROM archived_sessions AS a
                LEFT JOIN users AS u ON u.id = a.user_id
                WHERE a.id = %s AND u.id IS NULL
                """,
                (archived_id,),
            )
            deleted_archives += cursor.rowcount

        connection.commit()
        return {
            "mode": "apply",
            "limit_per_category": limit,
            "deleted": {
                "archived_sessions": deleted_archives,
                "checkpoints": deleted_checkpoints,
                "checkpoint_writes": deleted_writes,
            },
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> int:
    """输出 JSON 修复清单或已确认批次的删除计数。"""
    args = _parse_args()
    result = (
        apply_repair_plan(args.limit)
        if args.apply
        else build_repair_plan(args.limit)
    )
    print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
