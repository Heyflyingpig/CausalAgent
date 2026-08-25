"""编排 worker 启动检查、runtime 创建和 slot 生命周期。"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import logging
import signal
import socket
import sys
from typing import Any

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
    stop_event: asyncio.Event | None = None,
) -> None:
    """启动一个 slot，并让其独占 MCP session、tools 和 graph。"""
    stop_event = stop_event or asyncio.Event()
    worker_id = f"{socket.gethostname()}:{slot_index}"
    stack = AsyncExitStack()
    try:
        slot_runtime = await create_slot_runtime(
            process_runtime,
            stack,
            checkpoint_pool,
        )
        logging.info(
            "[worker] slot ready worker=%s tools=%s rag_status=%s rag_release=%s rag_error_code=%s",
            worker_id,
            [tool.name for tool in slot_runtime.mcp_tools],
            process_runtime.rag_status,
            process_runtime.rag_release_id,
            process_runtime.rag_error_code,
        )
        while not stop_event.is_set():
            job = await asyncio.to_thread(job_service.claim_next_job, worker_id)
            if not job:
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=settings.JOB_POLL_INTERVAL_SECONDS,
                    )
                except asyncio.TimeoutError:
                    pass
                continue
            if stop_event.is_set():
                logging.info(
                    "[worker] shutdown raced with job claim worker=%s; leaving lease for recovery",
                    worker_id,
                )
                break
            await run_job(job, slot_runtime, worker_id)
        logging.info(
            "[worker] slot stopped claiming jobs worker=%s; running jobs are left for recovery if needed",
            worker_id,
        )
    finally:
        await stack.aclose()


def _install_shutdown_handlers(stop_event: asyncio.Event) -> dict[int, Any]:
    """把终止信号转换为可测试的异步 drain 事件。"""
    loop = asyncio.get_running_loop()
    previous: dict[int, Any] = {}

    def request_shutdown(signum: int, _frame: Any) -> None:
        """把收到的终止信号转发给当前事件循环。"""
        logging.info("[worker] shutdown requested signal=%s; starting graceful drain", signum)
        loop.call_soon_threadsafe(stop_event.set)

    for name in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        try:
            previous[signum] = signal.signal(signum, request_shutdown)
        except (OSError, ValueError):
            logging.debug("[worker] signal handler unavailable signal=%s", name)
    return previous


def _restore_shutdown_handlers(previous: dict[int, Any]) -> None:
    """恢复 worker 启动前的信号处理器。"""
    for signum, handler in previous.items():
        try:
            signal.signal(signum, handler)
        except (OSError, ValueError):
            logging.debug("[worker] failed to restore signal handler signal=%s", signum)


async def _run_slots_until_shutdown(
    slot_tasks: list[asyncio.Task[Any]],
    stop_event: asyncio.Event,
) -> None:
    """等待 slots，收到停止信号后按超时执行 drain 并取消残留任务。"""
    shutdown_waiter = asyncio.create_task(stop_event.wait())
    try:
        done, _ = await asyncio.wait(
            [*slot_tasks, shutdown_waiter],
            return_when=asyncio.FIRST_COMPLETED,
        )
        if shutdown_waiter not in done:
            await asyncio.gather(*slot_tasks)
            return

        logging.info(
            "[worker] draining running jobs timeout=%ss",
            settings.JOB_DRAIN_TIMEOUT_SECONDS,
        )
        _, pending = await asyncio.wait(
            slot_tasks,
            timeout=settings.JOB_DRAIN_TIMEOUT_SECONDS,
        )
        if pending:
            logging.warning(
                "[worker] drain timeout reached; stopping %s slot(s) without finalizing their running jobs",
                len(pending),
            )
            for task in pending:
                task.cancel()
        await asyncio.gather(*slot_tasks, return_exceptions=True)
    finally:
        if not shutdown_waiter.done():
            shutdown_waiter.cancel()
        await asyncio.gather(shutdown_waiter, return_exceptions=True)
        pending_slots = [task for task in slot_tasks if not task.done()]
        for task in pending_slots:
            task.cancel()
        if pending_slots:
            await asyncio.gather(*pending_slots, return_exceptions=True)


async def main_async() -> None:
    """执行数据库、checkpoint、LLM/RAG 检查并启动固定数量的 slots。"""
    stop_event = asyncio.Event()
    previous_handlers = _install_shutdown_handlers(stop_event)
    try:
        check_database_readiness()
        async with open_checkpoint_pool() as checkpoint_pool:
            await verify_checkpoint_schema(checkpoint_pool)
            process_runtime = create_process_runtime()
            if not process_runtime.rag_available:
                logging.warning(
                    "[worker] RAG status=%s code=%s; continuing in degraded no-RAG mode",
                    process_runtime.rag_status,
                    process_runtime.rag_error_code,
                )

            slot_count = max(1, settings.JOB_WORKERS)
            logging.info("[worker] starting slot_count=%s", slot_count)
            slot_tasks = [
                asyncio.create_task(
                    run_slot(index + 1, checkpoint_pool, process_runtime, stop_event)
                )
                for index in range(slot_count)
            ]
            await _run_slots_until_shutdown(slot_tasks, stop_event)
    finally:
        _restore_shutdown_handlers(previous_handlers)


def main() -> None:
    """命令行入口：``python -m app.agent.worker``。"""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        force=True,
    )
    asyncio.run(main_async())
