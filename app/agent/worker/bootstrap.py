"""编排 worker 启动检查、runtime 创建和 slot 生命周期。"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import logging
import socket
import sys
from typing import Any

from observability.logging_runtime import configure_logging, current_environment

if __name__ == "__main__":
    configure_logging("worker", current_environment(), logging.INFO)

from Agent.causal_agent.postgres_checkpointer import (
    open_checkpoint_pool,
    verify_checkpoint_schema,
)
from app.agent import job_service
from app.agent.worker.execution import run_job
from app.agent.worker.runtime import (
    ProcessRuntime,
    create_process_runtime,
    create_slot_runtime,
)
from app.db import check_database_readiness
from config.settings import settings


async def run_slot(
    slot_index: int,
    checkpoint_pool: Any,
    process_runtime: ProcessRuntime,
) -> None:
    """启动一个 slot，并让其独占 MCP session、tools 和 graph。"""
    worker_id = f"{socket.gethostname()}:{slot_index}"
    stack = AsyncExitStack()
    try:
        slot_runtime = await create_slot_runtime(
            process_runtime,
            stack,
            checkpoint_pool,
        )
        logging.info(
            "[worker] slot ready worker=%s tools=%s",
            worker_id,
            [tool.name for tool in slot_runtime.mcp_tools],
        )
        while True:
            job = await asyncio.to_thread(job_service.claim_next_job, worker_id)
            if not job:
                await asyncio.sleep(settings.JOB_POLL_INTERVAL_SECONDS)
                continue
            await run_job(job, slot_runtime, worker_id)
    finally:
        await stack.aclose()


async def main_async() -> None:
    """执行数据库、checkpoint、LLM/RAG 检查并启动固定数量的 slots。"""
    check_database_readiness()
    async with open_checkpoint_pool() as checkpoint_pool:
        await verify_checkpoint_schema(checkpoint_pool)
        process_runtime = create_process_runtime()
        if not process_runtime.rag_available:
            logging.warning("RAG 系统不可用，worker 将以无知识库模式运行。")

        slot_count = max(1, settings.JOB_WORKERS)
        logging.info(
            "worker 启动检查完成",
            extra={
                "event_code": "worker.startup.ready",
                "category": "lifecycle",
                "details": {"slot_count": slot_count},
            },
        )
        logging.info("[worker] starting slot_count=%s", slot_count)
        await asyncio.gather(
            *[
                run_slot(index + 1, checkpoint_pool, process_runtime)
                for index in range(slot_count)
            ]
        )


def main() -> None:
    """命令行入口：``python -m app.agent.worker``。"""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    configure_logging("worker", current_environment(), logging.INFO)
    asyncio.run(main_async())
