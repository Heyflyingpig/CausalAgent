"""PostgreSQL LangGraph checkpoint cleanup outbox worker。"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
from datetime import datetime, timezone
import time

from observability.logging_runtime import configure_logging, current_environment

if __name__ == "__main__":
    configure_logging("maintenance", current_environment(), logging.INFO)

from Agent.causal_agent.postgres_checkpointer import (
    build_checkpointer,
    open_checkpoint_pool,
    verify_checkpoint_schema,
)
from app.agent.checkpoint_cleanup import (
    claim_cleanup_item,
    mark_cleanup_failed,
    mark_cleanup_succeeded,
    write_cleanup_runtime_snapshot,
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
    heartbeat_interval = _float_env(
        "CHECKPOINT_CLEANUP_HEARTBEAT_INTERVAL_SECONDS", 10.0
    )
    lease_seconds = int(
        _float_env("CHECKPOINT_CLEANUP_LEASE_SECONDS", 300.0)
    )
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    state: dict[str, object] = {
        "worker_alias": "checkpoint-cleanup",
        "worker_status": "idle",
        "started_at": started_at,
        "heartbeat_at": started_at,
        "current_outbox_id": None,
        "run_success_count": 0,
        "run_failure_count": 0,
        "startup_success_count": 0,
        "startup_failure_count": 0,
        "heartbeat_interval_seconds": heartbeat_interval,
        "processing_started_at": None,
        "processing_duration_seconds": None,
        "current_processing_started_at": None,
        "current_processing_duration_seconds": None,
        "_processing_monotonic": None,
        "last_failure_at": None,
        "last_error_present": False,
    }

    def publish_runtime(*, force: bool = False) -> None:
        """按心跳周期发布安全运行状态，写入失败不终止清理进程。"""
        now = time.monotonic()
        last = state.get("_last_publish_monotonic")
        if not force and isinstance(last, float) and now - last < heartbeat_interval:
            return
        heartbeat_at = datetime.now(timezone.utc)
        state["heartbeat_at"] = heartbeat_at.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        processing_started = state.get("_processing_monotonic")
        if isinstance(processing_started, float):
            state["processing_duration_seconds"] = round(max(0.0, now - processing_started), 3)
            state["current_processing_duration_seconds"] = state["processing_duration_seconds"]
        else:
            state["processing_duration_seconds"] = None
            state["current_processing_duration_seconds"] = None
        try:
            write_cleanup_runtime_snapshot(state)
            state["_last_publish_monotonic"] = now
        except Exception:
            logging.warning("[checkpoint-cleanup] 发布运行快照失败", exc_info=True)

    async def heartbeat_loop() -> None:
        """独立发布心跳，确保长时间 PostgreSQL 删除期间不会被判定为失联。"""
        while True:
            await asyncio.to_thread(publish_runtime)
            await asyncio.sleep(min(heartbeat_interval, max(0.5, poll_interval)))

    async with open_checkpoint_pool() as checkpoint_pool:
        await verify_checkpoint_schema(checkpoint_pool)
        saver = build_checkpointer(checkpoint_pool)
        logging.info(
            "checkpoint cleanup 启动检查完成",
            extra={
                "event_code": "maintenance.startup.ready",
                "category": "lifecycle",
                "details": {"component": "checkpoint-cleanup"},
            },
        )
        logging.info("[checkpoint-cleanup] worker ready id=%s", worker_id)
        await asyncio.to_thread(publish_runtime, force=True)
        heartbeat_task = asyncio.create_task(heartbeat_loop())
        try:
            while True:
                item = await asyncio.to_thread(
                    claim_cleanup_item,
                    worker_id,
                    lease_seconds=lease_seconds,
                )
                if not item:
                    await asyncio.sleep(poll_interval)
                    continue
                state["worker_status"] = "processing"
                state["current_outbox_id"] = int(item["id"])
                state["_processing_monotonic"] = time.monotonic()
                processing_started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                state["processing_started_at"] = processing_started_at
                state["current_processing_started_at"] = processing_started_at
                await asyncio.to_thread(publish_runtime, force=True)
                try:
                    logging.info(
                        "[checkpoint-cleanup] deleting job=%s attempt=%s",
                        item["job_id"],
                        item["attempts"],
                    )
                    await saver.adelete_thread(item["job_id"])
                except Exception as exc:
                    logging.error(
                        "[checkpoint-cleanup] failed job=%s: %s",
                        item["job_id"],
                        exc,
                        exc_info=True,
                    )
                    await asyncio.to_thread(mark_cleanup_failed, item["id"], str(exc))
                    state["run_failure_count"] = int(state["run_failure_count"]) + 1
                    state["startup_failure_count"] = int(state["startup_failure_count"]) + 1
                    state["last_failure_at"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                    state["last_error_present"] = True
                else:
                    await asyncio.to_thread(mark_cleanup_succeeded, item["id"])
                    state["run_success_count"] = int(state["run_success_count"]) + 1
                    state["startup_success_count"] = int(state["startup_success_count"]) + 1
                    state["last_error_present"] = False
                finally:
                    state["worker_status"] = "idle"
                    state["current_outbox_id"] = None
                    state["processing_started_at"] = None
                    state["processing_duration_seconds"] = None
                    state["current_processing_started_at"] = None
                    state["current_processing_duration_seconds"] = None
                    state["_processing_monotonic"] = None
                    await asyncio.to_thread(publish_runtime, force=True)
        finally:
            state["worker_status"] = "stopped"
            await asyncio.to_thread(publish_runtime, force=True)
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)


def main() -> None:
    """命令行入口：python -m Database.checkpoint_cleanup_worker。"""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    configure_logging("maintenance", current_environment(), logging.INFO)
    asyncio.run(_run_async())


if __name__ == "__main__":
    main()
