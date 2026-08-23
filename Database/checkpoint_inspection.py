"""PostgreSQL checkpoint 的共享只读查询与审计服务。

该模块只读取 LangGraph 官方 schema 中的安全元数据，不返回 checkpoint
状态正文、blob 或 pending write 内容，也不会记录连接串或凭据。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import math
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from config.checkpoint_settings import CheckpointPostgresConfig


LOGGER = logging.getLogger(__name__)
CHECKPOINT_SOURCE_ALIAS = "checkpoint-postgres"
EXPECTED_TABLE_COLUMNS = {
    "checkpoint_migrations": {"v"},
    "checkpoints": {
        "thread_id",
        "checkpoint_ns",
        "checkpoint_id",
        "parent_checkpoint_id",
        "type",
        "checkpoint",
        "metadata",
    },
    "checkpoint_blobs": {
        "thread_id",
        "checkpoint_ns",
        "channel",
        "version",
        "type",
        "blob",
    },
    "checkpoint_writes": {
        "thread_id",
        "checkpoint_ns",
        "checkpoint_id",
        "task_id",
        "idx",
        "channel",
        "type",
        "blob",
        "task_path",
    },
}
EXPECTED_PRIMARY_KEYS = {
    "checkpoint_migrations": ["v"],
    "checkpoints": ["thread_id", "checkpoint_ns", "checkpoint_id"],
    "checkpoint_blobs": ["thread_id", "checkpoint_ns", "channel", "version"],
    "checkpoint_writes": [
        "thread_id",
        "checkpoint_ns",
        "checkpoint_id",
        "task_id",
        "idx",
    ],
}
EXPECTED_INDEX_COLUMNS = {
    "checkpoints_thread_id_idx": ["thread_id"],
    "checkpoint_blobs_thread_id_idx": ["thread_id"],
    "checkpoint_writes_thread_id_idx": ["thread_id"],
}
CHECKPOINT_DATA_TABLES = ("checkpoints", "checkpoint_writes", "checkpoint_blobs")


class CheckpointPostgresUnavailable(RuntimeError):
    """表示 PostgreSQL checkpoint 只读链路当前不可用。"""


def _expected_migration_version() -> int:
    """从锁定的 LangGraph Saver 实现读取当前期望 migration 版本。"""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    return len(AsyncPostgresSaver.MIGRATIONS) - 1


@contextmanager
def checkpoint_read_connection(*, timeout_ms: int) -> Iterator[psycopg.Connection]:
    """打开带只读事务默认值和语句超时的 PostgreSQL 连接。"""
    config = CheckpointPostgresConfig.from_env()
    config.validate(require_credentials=True)
    connection = psycopg.connect(
        host=config.host,
        port=config.port,
        dbname=config.database,
        user=config.user,
        password=config.password,
        connect_timeout=max(1, math.ceil(config.connect_timeout_seconds)),
        options=(
            f"-c default_transaction_read_only=on "
            f"-c statement_timeout={max(1, int(timeout_ms))}"
        ),
        autocommit=True,
        row_factory=dict_row,
    )
    try:
        yield connection
    finally:
        connection.close()


def _quick_check(
    key: str,
    label: str,
    status: str,
    value: int | None,
    warning: str | None = None,
    *,
    description: str | None = None,
) -> dict[str, Any]:
    """构造兼容现有 quick integrity 契约的 PostgreSQL 检查项。"""
    return {
        "key": key,
        "label": label,
        "description": description or label,
        "severity": "blocking",
        "applicable": True,
        "status": status,
        "value": value,
        "observed_at": datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z"),
        "source_role": "checkpoint",
        "source_alias": CHECKPOINT_SOURCE_ALIAS,
        "is_estimate": False,
        "warning": warning,
    }


def _unknown_quick_checks() -> list[dict[str, Any]]:
    """在连接不可用时返回三个稳定且不泄露连接信息的检查项。"""
    warning = "PostgreSQL checkpoint 只读检查不可用"
    return [
        _quick_check(
            "checkpoint_postgres_connection",
            "PostgreSQL checkpoint 连接",
            "unknown",
            None,
            warning,
            description="确认管理员审计可以通过独立只读连接访问 PostgreSQL checkpoint。",
        ),
        _quick_check(
            "checkpoint_postgres_schema",
            "PostgreSQL checkpoint 官方表集合",
            "unknown",
            None,
            warning,
            description=(
                "确认当前 schema 存在 LangGraph checkpoint 官方四张表："
                "checkpoint_migrations、checkpoints、checkpoint_blobs、checkpoint_writes。"
            ),
        ),
        _quick_check(
            "checkpoint_postgres_migration",
            "PostgreSQL checkpoint migration 版本",
            "unknown",
            None,
            warning,
            description=(
                "确认 checkpoint_migrations 的最新版本不低于当前锁定的 "
                "LangGraph Saver setup 版本。"
            ),
        ),
    ]


def inspect_checkpoint_quick(*, timeout_ms: int) -> list[dict[str, Any]]:
    """检查 PostgreSQL 连通性、官方表集合和 migration 版本。"""
    try:
        with checkpoint_read_connection(timeout_ms=timeout_ms) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 AS connected")
                cursor.fetchone()
                connection_check = _quick_check(
                    "checkpoint_postgres_connection",
                    "PostgreSQL checkpoint 连接",
                    "healthy",
                    1,
                    description=(
                        "确认管理员审计可以通过独立只读连接访问 "
                        "PostgreSQL checkpoint。"
                    ),
                )

                cursor.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = current_schema()
                      AND table_name = ANY(%s)
                    """,
                    (list(EXPECTED_TABLE_COLUMNS),),
                )
                actual_tables = {row["table_name"] for row in cursor.fetchall()}
                missing_tables = set(EXPECTED_TABLE_COLUMNS) - actual_tables
                schema_check = _quick_check(
                    "checkpoint_postgres_schema",
                    "PostgreSQL checkpoint 官方表集合",
                    "healthy" if not missing_tables else "error",
                    len(missing_tables),
                    None if not missing_tables else "PostgreSQL checkpoint schema 不完整",
                    description=(
                        "确认当前 schema 存在 LangGraph checkpoint 官方四张表："
                        "checkpoint_migrations、checkpoints、checkpoint_blobs、"
                        "checkpoint_writes。"
                    ),
                )

                actual_version: int | None = None
                if "checkpoint_migrations" in actual_tables:
                    cursor.execute(
                        "SELECT v FROM checkpoint_migrations ORDER BY v DESC LIMIT 1"
                    )
                    row = cursor.fetchone()
                    actual_version = int(row["v"]) if row else None
                expected_version = _expected_migration_version()
                migration_ok = (
                    actual_version is not None and actual_version >= expected_version
                )
                migration_check = _quick_check(
                    "checkpoint_postgres_migration",
                    "PostgreSQL checkpoint migration 版本",
                    "healthy" if migration_ok else "error",
                    0 if migration_ok else 1,
                    None if migration_ok else "PostgreSQL checkpoint setup 尚未达到锁定版本",
                    description=(
                        "确认 checkpoint_migrations 的最新版本不低于当前锁定的 "
                        "LangGraph Saver setup 版本。"
                    ),
                )
        return [connection_check, schema_check, migration_check]
    except Exception as exc:
        LOGGER.warning(
            "PostgreSQL checkpoint quick 检查失败: %s",
            type(exc).__name__,
        )
        return _unknown_quick_checks()


def list_job_checkpoint_summaries(
    *,
    thread_id: str,
    job_id: str,
    limit: int,
    before_checkpoint_id: str | None,
    timeout_ms: int,
) -> dict[str, Any]:
    """按 job metadata 分页读取安全 checkpoint 摘要。"""
    clauses = ["thread_id = %s", "metadata ->> 'job_id' = %s"]
    params: list[Any] = [thread_id, job_id]
    if before_checkpoint_id:
        clauses.append("checkpoint_id < %s")
        params.append(before_checkpoint_id)
    params.append(limit + 1)

    try:
        with checkpoint_read_connection(timeout_ms=timeout_ms) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT checkpoint_id, parent_checkpoint_id, checkpoint_ns,
                           checkpoint ->> 'ts' AS created_at,
                           metadata ->> 'step' AS step,
                           metadata ->> 'source' AS source,
                           CASE
                               WHEN jsonb_typeof(checkpoint -> 'updated_channels') = 'array'
                               THEN checkpoint -> 'updated_channels'
                               ELSE '[]'::jsonb
                           END AS updated_channels
                    FROM checkpoints
                    WHERE {' AND '.join(clauses)}
                    ORDER BY checkpoint_id DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                rows = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM checkpoints
                        WHERE thread_id = %s
                          AND metadata ->> 'job_id' IS NULL
                    ) AS legacy_unattributed
                    """,
                    (thread_id,),
                )
                legacy_row = cursor.fetchone() or {}
    except Exception as exc:
        LOGGER.warning(
            "PostgreSQL checkpoint 任务摘要读取失败: %s",
            type(exc).__name__,
        )
        raise CheckpointPostgresUnavailable(
            "PostgreSQL checkpoint 只读服务不可用"
        ) from exc

    has_more = len(rows) > limit
    items = rows[:limit]
    for item in items:
        raw_step = item.get("step")
        try:
            item["step"] = int(raw_step) if raw_step is not None else None
        except (TypeError, ValueError):
            item["step"] = None
        source = item.get("source")
        item["source"] = source[:128] if isinstance(source, str) else None
        channels = item.get("updated_channels")
        item["updated_channels"] = (
            [
                value[:128]
                for value in channels
                if isinstance(value, str)
            ][:100]
            if isinstance(channels, list)
            else []
        )

    return {
        "items": items,
        "has_more": has_more,
        "next_checkpoint_id": (
            items[-1]["checkpoint_id"] if has_more and items else None
        ),
        "legacy_unattributed": bool(legacy_row.get("legacy_unattributed")),
    }


def collect_checkpoint_deep_facts(
    *,
    timeout_ms: int,
    sample_limit: int,
) -> dict[str, Any]:
    """读取 PostgreSQL schema、估算统计和有界 thread 样本。"""
    with checkpoint_read_connection(timeout_ms=timeout_ms) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = ANY(%s)
                """,
                (list(EXPECTED_TABLE_COLUMNS),),
            )
            actual_columns: dict[str, set[str]] = {}
            for row in cursor.fetchall():
                actual_columns.setdefault(row["table_name"], set()).add(
                    row["column_name"]
                )

            cursor.execute(
                """
                SELECT tc.table_name, kcu.column_name, kcu.ordinal_position
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON kcu.constraint_schema = tc.constraint_schema
                 AND kcu.constraint_name = tc.constraint_name
                 AND kcu.table_name = tc.table_name
                WHERE tc.table_schema = current_schema()
                  AND tc.constraint_type = 'PRIMARY KEY'
                  AND tc.table_name = ANY(%s)
                ORDER BY tc.table_name, kcu.ordinal_position
                """,
                (list(EXPECTED_PRIMARY_KEYS),),
            )
            actual_primary_keys: dict[str, list[str]] = {}
            for row in cursor.fetchall():
                actual_primary_keys.setdefault(row["table_name"], []).append(
                    row["column_name"]
                )

            cursor.execute(
                """
                SELECT index_table.relname AS index_name,
                       array_agg(attribute.attname ORDER BY key_part.ordinality)
                           AS columns
                FROM pg_catalog.pg_class AS data_table
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = data_table.relnamespace
                JOIN pg_catalog.pg_index AS index_meta
                  ON index_meta.indrelid = data_table.oid
                JOIN pg_catalog.pg_class AS index_table
                  ON index_table.oid = index_meta.indexrelid
                JOIN LATERAL unnest(index_meta.indkey)
                     WITH ORDINALITY AS key_part(attnum, ordinality) ON TRUE
                JOIN pg_catalog.pg_attribute AS attribute
                  ON attribute.attrelid = data_table.oid
                 AND attribute.attnum = key_part.attnum
                WHERE namespace.nspname = current_schema()
                  AND index_table.relname = ANY(%s)
                GROUP BY index_table.relname
                """,
                (list(EXPECTED_INDEX_COLUMNS),),
            )
            actual_indexes = {
                row["index_name"]: list(row["columns"])
                for row in cursor.fetchall()
            }

            actual_version: int | None = None
            if "checkpoint_migrations" in actual_columns:
                cursor.execute(
                    "SELECT v FROM checkpoint_migrations ORDER BY v DESC LIMIT 1"
                )
                row = cursor.fetchone()
                actual_version = int(row["v"]) if row else None

            cursor.execute(
                """
                SELECT relname AS table_name,
                       COALESCE(n_live_tup, 0)::bigint AS estimated_rows,
                       last_analyze, last_autoanalyze
                FROM pg_stat_user_tables
                WHERE schemaname = current_schema()
                  AND relname = ANY(%s)
                ORDER BY relname
                """,
                (list(CHECKPOINT_DATA_TABLES),),
            )
            stats = cursor.fetchall()

            cursor.execute(
                """
                SELECT DISTINCT thread_id
                FROM checkpoints
                ORDER BY thread_id DESC
                LIMIT %s
                """,
                (sample_limit,),
            )
            thread_ids = [str(row["thread_id"]) for row in cursor.fetchall()]

    missing_columns = {
        table: sorted(expected - actual_columns.get(table, set()))
        for table, expected in EXPECTED_TABLE_COLUMNS.items()
        if expected - actual_columns.get(table, set())
    }
    invalid_primary_keys = {
        table: {
            "expected": expected,
            "actual": actual_primary_keys.get(table, []),
        }
        for table, expected in EXPECTED_PRIMARY_KEYS.items()
        if actual_primary_keys.get(table, []) != expected
    }
    invalid_indexes = {
        index_name: {
            "expected": expected,
            "actual": actual_indexes.get(index_name, []),
        }
        for index_name, expected in EXPECTED_INDEX_COLUMNS.items()
        if actual_indexes.get(index_name, []) != expected
    }
    expected_version = _expected_migration_version()
    return {
        "schema": {
            "missing_columns": missing_columns,
            "invalid_primary_keys": invalid_primary_keys,
            "invalid_indexes": invalid_indexes,
            "expected_migration_version": expected_version,
            "actual_migration_version": actual_version,
            "migration_current": (
                actual_version is not None and actual_version >= expected_version
            ),
        },
        "stats": stats,
        "thread_ids": thread_ids,
    }
