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
    lease_epoch: int,
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
            lease_epoch,
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
    lease_epoch = int(job.get("lease_epoch") or 0)
    stop_heartbeat = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        heartbeat_until_stopped(
            job_id,
            worker_id,
            attempt_count,
            lease_epoch,
            stop_heartbeat,
        )
    )

    try:
        writer = OrderedEventWriter(job, worker_id)
        latest_input = await asyncio.to_thread(job_service.get_latest_input_value, job_id)
        if latest_input is None:
            raise RuntimeError("任务输入账本为空")
        initial_input = latest_input
        if (
            job.get("claim_kind") == "stale_recovery"
            and latest_input.get("input_type") != "initial"
        ):
            initial_input = await asyncio.to_thread(
                job_service.get_initial_input_value,
                job_id,
            )
            if initial_input is None:
                raise RuntimeError("任务初始输入账本为空")
        logging.info(
            "[worker] start job=%s worker=%s session=%s tools=%s",
            job_id,
            worker_id,
            job["session_id"],
            len(slot_runtime.mcp_tools),
        )
        async for payload in ai_call_stream(
            latest_input,
            job["user_id"],
            f"user-{job['user_id']}",
            job["session_id"],
            job_id=job_id,
            job_attempt=attempt_count,
            input_user_file_id=job.get("input_user_file_id"),
            input_object_id=job.get("input_object_id"),
            input_file_hash=job.get("input_file_hash"),
            input_filename=job.get("input_filename"),
            graph=slot_runtime.graph,
            claim_kind=job.get("claim_kind", "initial"),
            initial_input_record=initial_input,
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
                lease_epoch,
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
            lease_epoch=lease_epoch,
        )
    finally:
        stop_heartbeat.set()
        await heartbeat_task
