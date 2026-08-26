"""隔离评测常驻 worker。

启动方式：
    python -m app.rag_eval.worker

该进程不依赖 Flask 请求线程。每个 slot 从 MySQL 队列领取一个任务，
执行期间刷新数据库 heartbeat；进程异常退出后，下一次 worker 启动会把
超时的 running job 和对应 run.json 收敛为 failed，而不会静默重跑。
"""

from __future__ import annotations

import logging
import multiprocessing
import socket
import sys
import threading
import time
from typing import Any

from app.db import check_database_readiness
from app.rag_eval import job_service
from app.rag_eval.isolated_runs import IsolatedRunManager
from config.settings import settings
from observability.logging_runtime import configure_logging, current_environment, log_event

LOGGER = logging.getLogger(__name__)


def _log_lease_failure(
    consecutive_failures: int,
    *,
    suppressed_count: int = 0,
    exc_info=None,
) -> None:
    """记录隔离评测租约异常时所需的完整事件详情。"""
    log_event(
        LOGGER,
        "worker.lease.refresh_failed",
        details={
            "consecutive_failures": max(1, int(consecutive_failures)),
            "suppressed_count": max(0, int(suppressed_count)),
        },
        exc_info=exc_info,
    )


def _log_job_failure(
    job: dict[str, Any] | None,
    *,
    failure_phase: str,
    reason_code: str,
    duration_ms: int = 0,
    exc_info=None,
) -> None:
    """记录隔离评测任务失败时所需的完整事件详情。"""
    attempt = 1
    if isinstance(job, dict):
        try:
            attempt = max(1, int(job.get("attempt_count") or 1))
        except (TypeError, ValueError):
            attempt = 1
    log_event(
        LOGGER,
        "worker.job.failed",
        details={
            "failure_phase": failure_phase,
            "reason_code": reason_code,
            "attempt": attempt,
            "duration_ms": max(0, int(duration_ms)),
        },
        exc_info=exc_info,
    )


def _run_candidate_child(run_id: str) -> None:
    """在独立进程中执行不可抢占的 Ragas 候选生成调用。"""
    IsolatedRunManager().run_queued_sync(run_id)


def _terminate_process(process: multiprocessing.process.BaseProcess) -> None:
    """有界终止子进程，避免取消后的外部模型调用继续占用 worker slot。"""
    process.terminate()
    process.join(timeout=5)
    if process.is_alive():
        process.kill()
        process.join(timeout=2)


def _run_cancellable_candidate(manager: IsolatedRunManager, run_id: str) -> None:
    """隔离 Ragas 生成，使已取消任务能立即释放常驻 worker 的 slot。"""
    if sys.platform == "win32":
        # 生产 worker 运行在 Linux Docker；本地 Windows 保留兼容同步路径。
        manager.run_queued_sync(run_id)
        return

    process = multiprocessing.get_context("fork").Process(
        target=_run_candidate_child,
        args=(run_id,),
        daemon=False,
        name=f"rag_eval_candidate_{run_id}",
    )
    process.start()
    while process.is_alive():
        process.join(timeout=0.25)
        state = manager._load(run_id)
        job = job_service.get_job(run_id)
        if state.get("cancel_requested") or (job and job.get("status") == "cancelled"):
            _terminate_process(process)
            manager.mark_worker_cancelled(run_id, "cancelled by user")
            return
    process.join()
    if process.exitcode not in (0, None):
        state = manager._load(run_id)
        if state.get("status") not in {"cancelled", "failed"}:
            raise RuntimeError(f"candidate child exited with code {process.exitcode}")


def _heartbeat_loop(
    manager: IsolatedRunManager,
    run_id: str,
    worker_id: str,
    stop: threading.Event,
    lease_lost: threading.Event,
) -> None:
    """周期性刷新 SQL 租约和独立心跳文件；失联时触发 fencing。"""
    interval = max(int(settings.RAG_EVAL_EVALUATION_HEARTBEAT_INTERVAL_SECONDS), 1)
    consecutive_failures = 0
    failure_started_at = None
    while not stop.wait(interval):
        try:
            if not job_service.heartbeat_job(run_id, worker_id):
                consecutive_failures += 1
                _log_lease_failure(consecutive_failures)
                lease_lost.set()
                manager.request_lease_abort(run_id, worker_id)
                return
            manager.touch_worker_heartbeat(run_id, worker_id)
            if consecutive_failures:
                log_event(
                    LOGGER,
                    "worker.lease.recovered",
                    details={
                        "failure_count": consecutive_failures,
                        "downtime_ms": max(
                            0,
                            int((time.monotonic() - failure_started_at) * 1000),
                        ) if failure_started_at is not None else 0,
                    },
                )
                consecutive_failures = 0
                failure_started_at = None
        except Exception:
            # 心跳瞬时失败不代表租约失效，不能据此终止长任务；只记录并继续。
            consecutive_failures += 1
            if failure_started_at is None:
                failure_started_at = time.monotonic()
            _log_lease_failure(consecutive_failures, exc_info=True)


def _reconcile_stale_runs(manager: IsolatedRunManager) -> None:
    """把上一进程遗留的 heartbeat 超时任务收敛成失败。"""
    for job in job_service.reconcile_stale_jobs():
        run_id = str(job.get("run_id") or "")
        message = str(job.get("error_message") or "评测 worker heartbeat 超时，任务未完成")
        try:
            manager.mark_worker_timeout(run_id, message)
        except KeyError:
            _log_job_failure(job, failure_phase="state_reconciliation", reason_code="cleanup_failed")
        except Exception:
            _log_job_failure(
                job,
                failure_phase="state_reconciliation",
                reason_code="cleanup_failed",
                exc_info=True,
            )


def _reconcile_terminal_state(manager: IsolatedRunManager, run_id: str) -> None:
    """根据 SQL 实际终态收敛 run.json，避免成功/失败/取消状态分裂。

    complete_job 返回 false 或租约失效时，SQL 可能已被取消、被 reconcile 标记
    为 failed，或已经 succeeded。这里读取 SQL 真实终态并让 run.json 与之对齐，
    而不是一律把 run.json 标记为 failed（否则会得到 SQL=cancelled 而
    run.json=failed 的分裂）。
    """
    sql_status = ""
    try:
        job = job_service.get_job(run_id)
        sql_status = str(job.get("status") or "") if job else ""
    except Exception:
        _log_job_failure(
            None,
            failure_phase="state_reconciliation",
            reason_code="database_unavailable",
            exc_info=True,
        )
    if sql_status == "cancelled":
        manager.mark_worker_cancelled(run_id, "cancelled by user")
    elif sql_status == "failed":
        manager.mark_worker_fenced(run_id, "RAG 任务已在 SQL 侧失败，结果被丢弃")
    elif sql_status == "succeeded":
        # SQL 已成功，run.json 保持成功终态即可（幂等）。
        return
    else:
        # SQL 终态未知或读取失败，按失败收敛（fail-closed）。
        manager.mark_worker_fenced(run_id, "RAG 任务租约失效，结果被丢弃")


def _run_one(manager: IsolatedRunManager, job: dict[str, Any], worker_id: str) -> None:
    """执行单个已领取任务，并把 run.json 与 SQL 状态同步到终态。"""
    run_id = str(job["run_id"])
    state = manager._load(run_id)
    if state.get("status") == "cancelled" or state.get("cancel_requested"):
        job_service.cancel_job(run_id)
        return
    manager.mark_worker_started(run_id, worker_id)
    started_at = time.monotonic()
    stop = threading.Event()
    lease_lost = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_loop,
        args=(manager, run_id, worker_id, stop, lease_lost),
        daemon=True,
        name=f"rag_eval_eval_heartbeat_{run_id}",
    )
    heartbeat.start()
    try:
        if state.get("kind") == "candidate_generation":
            _run_cancellable_candidate(manager, run_id)
        else:
            manager.run_queued_sync(run_id)
        state = manager._load(run_id)
        status = state.get("status")
        kind = state.get("kind")
        if lease_lost.is_set():
            _reconcile_terminal_state(manager, run_id)
        elif status == "cancelled":
            # 取消请求已经由 Web 或执行器写入 run.json；SQL 只需保留终态。
            job_service.cancel_job(run_id)
        elif kind == "ingestion" and status == "staged":
            # 摄取成功终态是 staged，SQL 仍同步为 succeeded。
            if not job_service.complete_job(run_id):
                _reconcile_terminal_state(manager, run_id)
        elif status == "succeeded":
            if not job_service.complete_job(run_id):
                _reconcile_terminal_state(manager, run_id)
        elif status == "failed":
            job_service.fail_job(run_id, str(state.get("error") or "RAG 任务执行失败"))
        else:
            message = f"评测执行结束但未产生终态: {status}"
            manager.mark_worker_timeout(run_id, message)
            job_service.fail_job(run_id, message)
    except Exception as exc:
        _log_job_failure(
            job,
            failure_phase="evaluation",
            reason_code="runtime_failed",
            duration_ms=max(0, int((time.monotonic() - started_at) * 1000)),
            exc_info=True,
        )
        if lease_lost.is_set():
            _reconcile_terminal_state(manager, run_id)
        else:
            try:
                manager.mark_worker_timeout(run_id, str(exc))
            finally:
                job_service.fail_job(run_id, str(exc))
    finally:
        stop.set()
        heartbeat.join(timeout=max(int(settings.RAG_EVAL_EVALUATION_HEARTBEAT_INTERVAL_SECONDS), 1) + 1)


def _run_slot(slot_index: int) -> None:
    """运行一个常驻评测 slot。"""
    manager = IsolatedRunManager()
    worker_id = f"{socket.gethostname()}:rag-eval:{slot_index}"
    poll_interval = max(float(settings.RAG_EVAL_EVALUATION_POLL_INTERVAL_SECONDS), 0.1)
    while True:
        _reconcile_stale_runs(manager)
        job = job_service.claim_next_job(worker_id)
        if job:
            _run_one(manager, job, worker_id)
        else:
            time.sleep(poll_interval)


def main() -> None:
    """命令行入口：校验数据库后启动常驻评测 slots。"""
    # 隔离 worker 不带 Compose 观测标签，但受管事件仍使用与 develop
    # 一致的 JSON stderr 运行时，避免回退到普通文本日志。
    configure_logging("worker", current_environment(), logging.INFO)
    check_database_readiness()
    slot_count = max(int(settings.RAG_EVAL_EVALUATION_WORKERS), 1)
    slots = [
        threading.Thread(target=_run_slot, args=(index,), daemon=False, name=f"rag_eval_eval_slot_{index}")
        for index in range(1, slot_count + 1)
    ]
    for slot in slots:
        slot.start()
    for slot in slots:
        slot.join()


if __name__ == "__main__":
    main()
