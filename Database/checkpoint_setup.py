"""PostgreSQL checkpoint schema 一次性 setup 入口。"""

from __future__ import annotations

import asyncio
import logging

from observability.logging_runtime import configure_logging, current_environment

if __name__ == "__main__":
    configure_logging("maintenance", current_environment(), logging.INFO)

from Agent.causal_agent.postgres_checkpointer import (
    open_checkpoint_pool,
    setup_checkpoint_schema,
    verify_checkpoint_schema,
)


async def _main_async() -> None:
    """等待 PostgreSQL 可用后执行官方幂等 setup。"""
    await setup_checkpoint_schema_once()
    logging.info(
        "PostgreSQL checkpoint schema 已就绪",
        extra={
            "event_code": "maintenance.startup.ready",
            "category": "lifecycle",
            "details": {"component": "checkpoint-setup"},
        },
    )


async def setup_checkpoint_schema_once() -> None:
    """执行一次 LangGraph PostgreSQL checkpoint schema 初始化并校验版本。"""
    async with open_checkpoint_pool() as pool:
        await setup_checkpoint_schema(pool)
        await verify_checkpoint_schema(pool)


def main() -> None:
    """命令行入口：python -m Database.checkpoint_setup。"""
    configure_logging("maintenance", current_environment(), logging.INFO)
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
