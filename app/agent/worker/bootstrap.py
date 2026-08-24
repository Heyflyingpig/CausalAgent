"""编排 worker 启动检查、runtime 创建和 slot 生命周期。"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import logging
import socket
import sys
from typing import Any

from observability.logging_runtime import (
    configure_logging,
    current_environment,
    log_context,
    log_event,
)

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


LOGGER = logging.getLogger(__name__)


async def run_slot(
    slot_index: int,
    checkpoint_pool: Any,
    process_runtime: ProcessRuntime,
) -> None:
    """启动一个 slot，并让其独占 MCP session、tools 和 graph。"""
    worker_id = f"{socket.gethostname()}:{slot_index}"
    with log_context(worker_slot=slot_index):
        stack = AsyncExitStack()
        phase = "runtime_initialization"
        try:
            try:
                slot_runtime = await create_slot_runtime(
                    process_runtime,
                    stack,
                    checkpoint_pool,
                )
                log_event(
                    LOGGER,
                    "worker.slot.ready",
                    details={"tool_count": len(slot_runtime.mcp_tools)},
                )
                phase = "job_polling"
                while True:
                    job = await asyncio.to_thread(job_service.claim_next_job, worker_id)
                    if not job:
                        await asyncio.sleep(settings.JOB_POLL_INTERVAL_SECONDS)
                        continue
                    await run_job(
                        job,
                        slot_runtime,
                        worker_id,
                        worker_slot=slot_index,
                    )
            finally:
                await stack.aclose()
        except asyncio.CancelledError:
            raise
        except BaseException:
            log_event(
                LOGGER,
                "worker.slot.failed",
                details={
                    "phase": phase,
                    "reason_code": (
                        "initialization_failed"
                        if phase == "runtime_initialization"
                        else "runtime_failed"
                    ),
                },
                exc_info=True,
            )
            raise


async def main_async() -> None:
    """执行数据库、checkpoint、LLM/RAG 检查并启动固定数量的 slots。"""
    phase = "database_readiness"
    dependency = "mysql"
    try:
        check_database_readiness()
        phase = "checkpoint_pool"
        dependency = "postgresql"
        async with open_checkpoint_pool() as checkpoint_pool:
            phase = "checkpoint_schema"
            await verify_checkpoint_schema(checkpoint_pool)
            phase = "process_runtime"
            dependency = "worker_runtime"
            process_runtime = create_process_runtime()
            if not process_runtime.rag_available:
                log_event(
                    LOGGER,
                    "rag.startup.unavailable",
                    details={"reason_code": "knowledge_base_missing"},
                )

            slot_count = max(1, settings.JOB_WORKERS)
            log_event(
                LOGGER,
                "worker.startup.ready",
            )
            await asyncio.gather(
                *[
                    run_slot(index + 1, checkpoint_pool, process_runtime)
                    for index in range(slot_count)
                ]
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        if phase != "process_runtime" or "slot_count" not in locals():
            log_event(
                LOGGER,
                "worker.startup.failed",
                details={
                    "phase": phase,
                    "dependency": dependency,
                    "reason_code": "initialization_failed",
                },
                exc_info=True,
            )
        raise


def main() -> None:
    """命令行入口：``python -m app.agent.worker``。"""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    configure_logging("worker", current_environment(), logging.INFO)
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        return
    except Exception:
        raise SystemExit(1) from None
