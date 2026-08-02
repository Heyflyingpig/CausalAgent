"""PostgreSQL checkpoint 连接池、schema 检查和 Saver 工厂。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from config.checkpoint_settings import CheckpointPostgresConfig


def _connection_kwargs() -> dict[str, Any]:
    """构造 PostgreSQL 连接参数，不生成或记录完整 DSN。"""
    config = CheckpointPostgresConfig.from_env()
    config.validate(require_credentials=True)
    return {
        "host": config.host,
        "port": config.port,
        "dbname": config.database,
        "user": config.user,
        "password": config.password,
        "connect_timeout": config.connect_timeout_seconds,
        "autocommit": True,
        "prepare_threshold": 0,
        "row_factory": dict_row,
    }


@asynccontextmanager
async def open_checkpoint_pool() -> AsyncIterator[AsyncConnectionPool]:
    """打开一个进程级共享连接池，并在退出时释放全部 PostgreSQL 连接。"""
    config = CheckpointPostgresConfig.from_env()
    config.validate(require_credentials=True)
    pool = AsyncConnectionPool(
        conninfo=None,
        kwargs=_connection_kwargs(),
        min_size=config.pool_min_size,
        max_size=config.pool_max_size,
        timeout=config.connect_timeout_seconds,
        open=False,
    )
    try:
        await pool.open(wait=True)
        yield pool
    finally:
        await pool.close()


def build_checkpointer(pool: AsyncConnectionPool) -> AsyncPostgresSaver:
    """为一个 graph slot 创建轻量 Saver，共享传入的连接池。"""
    return AsyncPostgresSaver(
        conn=pool,
        serde=JsonPlusSerializer(pickle_fallback=True),
    )


async def setup_checkpoint_schema(pool: AsyncConnectionPool) -> None:
    """调用官方 setup 幂等创建 PostgreSQL checkpoint schema。"""
    saver = build_checkpointer(pool)
    await saver.setup()


async def verify_checkpoint_schema(pool: AsyncConnectionPool) -> None:
    """确认 setup 服务已完成官方最新 checkpoint schema。"""
    expected_version = len(AsyncPostgresSaver.MIGRATIONS) - 1
    async with pool.connection() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT v FROM checkpoint_migrations ORDER BY v DESC LIMIT 1"
            )
            row = await cursor.fetchone()
    if row is None or int(row["v"]) < expected_version:
        actual_version = None if row is None else row["v"]
        raise RuntimeError(
            "PostgreSQL checkpoint schema 未完成 setup: "
            f"expected>={expected_version}, actual={actual_version}"
        )
