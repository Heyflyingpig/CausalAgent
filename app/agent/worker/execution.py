"""执行单个 analysis job 并维护其 heartbeat。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.agent import job_service
from app.agent.worker.event_adapter import sanitize_public_error
from app.agent.worker.event_writer import OrderedEventWriter
from app.agent.worker.graph_runner import ai_call_stream
from app.agent.worker.runtime import SlotRuntime
from config.settings import settings


async def heartbeat_until_stopped(
    job_id: str,
    worker_id: str,
    attempt_count: int,
    stop: asyncio.Event,
) -> None:
    """在 job 执行期间定期刷新 heartbeat，直到收到停止信号。"""
    while not stop.is_set():
        await asyncio.sleep(settings.JOB_HEARTBEAT_INTERVAL_SECONDS)
        if stop.is_set():
            break
        await asyncio.to_thread(
            job_service.update_heartbeat,
            job_id,
            worker_id,
            attempt_count,
        )
        logging.info("[worker] heartbeat job=%s worker=%s", job_id, worker_id)


async def run_job(
    job: dict[str, Any],
    slot_runtime: SlotRuntime,
    worker_id: str,
) -> None:
    """使用显式 slot runtime 执行 job、写事件并处理终态。"""
    job_id = job["job_id"]
    attempt_count = int(job["attempt_count"])
    stop_heartbeat = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        heartbeat_until_stopped(
            job_id,
            worker_id,
            attempt_count,
            stop_heartbeat,
        )
    )
    writer = OrderedEventWriter(job, worker_id)

    try:
        logging.info(
            "[worker] start job=%s worker=%s session=%s tools=%s",
            job_id,
            worker_id,
            job["session_id"],
            len(slot_runtime.mcp_tools),
        )
        async for payload in ai_call_stream(
            job["message"],
            job["user_id"],
            f"user-{job['user_id']}",
            job["session_id"],
            job_id=job_id,
            job_attempt=attempt_count,
            graph=slot_runtime.graph,
        ):
            await writer.submit(payload)
        await writer.close()

        if not writer.terminal_seen:
            await asyncio.to_thread(
                job_service.complete_job,
                job_id,
                worker_id,
                attempt_count,
                {},
            )
        logging.info("[worker] finish job=%s worker=%s", job_id, worker_id)
    except Exception as exc:
        logging.error(
            "[worker] job failed job=%s worker=%s error=%s",
            job_id,
            worker_id,
            exc,
            exc_info=True,
        )
        await asyncio.to_thread(
            job_service.fail_job,
            job_id,
            worker_id,
            attempt_count,
            sanitize_public_error(exc),
        )
    finally:
        stop_heartbeat.set()
        await heartbeat_task
