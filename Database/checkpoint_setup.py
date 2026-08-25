"""PostgreSQL checkpoint schema 一次性 setup 入口。"""

from __future__ import annotations

import asyncio
import logging

from observability.logging_runtime import configure_logging, current_environment, log_event

if __name__ == "__main__":
    configure_logging("maintenance", current_environment(), logging.INFO)

LOGGER = logging.getLogger(__name__)

try:
    from Agent.causal_agent.postgres_checkpointer import (
        open_checkpoint_pool,
        setup_checkpoint_schema,
        verify_checkpoint_schema,
    )
except Exception as exc:
    if __name__ == "__main__":
        log_event(
            LOGGER,
            "maintenance.startup.failed",
            details={
                "phase": "module_initialization",
                "dependency": "checkpoint_runtime",
                "reason_code": "initialization_failed",
            },
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        raise SystemExit(1) from None
    raise


async def _main_async() -> None:
    """等待 PostgreSQL 可用后执行官方幂等 setup。"""
    await setup_checkpoint_schema_once()
    log_event(
        LOGGER,
        "maintenance.startup.ready",
    )


async def setup_checkpoint_schema_once() -> None:
    """执行一次 LangGraph PostgreSQL checkpoint schema 初始化并校验版本。"""
    async with open_checkpoint_pool() as pool:
        await setup_checkpoint_schema(pool)
        await verify_checkpoint_schema(pool)


def main() -> None:
    """命令行入口：python -m Database.checkpoint_setup。"""
    configure_logging("maintenance", current_environment(), logging.INFO)
    try:
        asyncio.run(_main_async())
    except Exception as exc:
        log_event(
            LOGGER,
            "maintenance.startup.failed",
            details={
                "phase": "checkpoint_schema",
                "dependency": "postgresql",
                "reason_code": "initialization_failed",
            },
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
