"""PostgreSQL checkpoint schema 一次性 setup 入口。"""

from __future__ import annotations

import asyncio
import logging

from Agent.causal_agent.postgres_checkpointer import (
    open_checkpoint_pool,
    setup_checkpoint_schema,
    verify_checkpoint_schema,
)


async def _main_async() -> None:
    """等待 PostgreSQL 可用后执行官方幂等 setup。"""
    async with open_checkpoint_pool() as pool:
        await setup_checkpoint_schema(pool)
        await verify_checkpoint_schema(pool)


def main() -> None:
    """命令行入口：python -m Database.checkpoint_setup。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        force=True,
    )
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
