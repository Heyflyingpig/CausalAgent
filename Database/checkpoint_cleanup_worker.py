"""PostgreSQL LangGraph checkpoint cleanup outbox worker。"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys

from Agent.causal_agent.postgres_checkpointer import (
    build_checkpointer,
    open_checkpoint_pool,
    verify_checkpoint_schema,
)
from app.agent.checkpoint_cleanup import (
    claim_cleanup_item,
    mark_cleanup_failed,
    mark_cleanup_succeeded,
)
from app.db import check_database_readiness


def _float_env(name: str, default: float) -> float:
    """读取 worker 的非敏感浮点配置。"""
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    value = float(raw)
    if value <= 0:
        raise ValueError(f"配置错误: {name} 必须大于 0。")
    return value


async def _run_async() -> None:
    """连接两侧数据库并持续消费 cleanup outbox。"""
    check_database_readiness()
    poll_interval = _float_env("CHECKPOINT_CLEANUP_POLL_INTERVAL_SECONDS", 1.0)
    lease_seconds = int(
        _float_env("CHECKPOINT_CLEANUP_LEASE_SECONDS", 300.0)
    )
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    async with open_checkpoint_pool() as checkpoint_pool:
        await verify_checkpoint_schema(checkpoint_pool)
        saver = build_checkpointer(checkpoint_pool)
        logging.info("[checkpoint-cleanup] worker ready id=%s", worker_id)
        while True:
            item = await asyncio.to_thread(
                claim_cleanup_item,
                worker_id,
                lease_seconds=lease_seconds,
            )
            if not item:
                await asyncio.sleep(poll_interval)
                continue
            try:
                logging.info(
                    "[checkpoint-cleanup] deleting thread=%s attempt=%s",
                    item["thread_id"],
                    item["attempts"],
                )
                await saver.adelete_thread(item["thread_id"])
            except Exception as exc:
                logging.error(
                    "[checkpoint-cleanup] failed thread=%s: %s",
                    item["thread_id"],
                    exc,
                    exc_info=True,
                )
                await asyncio.to_thread(mark_cleanup_failed, item["id"], str(exc))
            else:
                await asyncio.to_thread(mark_cleanup_succeeded, item["id"])


def main() -> None:
    """命令行入口：python -m Database.checkpoint_cleanup_worker。"""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        force=True,
    )
    asyncio.run(_run_async())


if __name__ == "__main__":
    main()
