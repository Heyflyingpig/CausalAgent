"""R5 隔离评测 resident worker。

启动方式：
    python -m app.rag_eval.worker

该进程不依赖 Flask 请求线程。每个 slot 从 MySQL 队列领取一个评测，
执行期间刷新数据库 heartbeat；进程异常退出后，下一次 worker 启动会把
超时的 running job 和对应 run.json 收敛为 failed，而不会静默重跑。
"""

from __future__ import annotations

import logging
import socket
import sys
import threading
import time
from typing import Any

from app.db import check_database_readiness
from app.rag_eval import job_service
from app.rag_eval.isolated_runs import IsolatedRunManager
from config.settings import settings


def _heartbeat_loop(
    manager: IsolatedRunManager,
    run_id: str,
    worker_id: str,
    stop: threading.Event,
) -> None:
    """周期性刷新 SQL 租约和独立心跳文件。"""
    interval = max(int(settings.R5_EVALUATION_HEARTBEAT_INTERVAL_SECONDS), 1)
    while not stop.wait(interval):
        try:
            if not job_service.heartbeat_evaluation(run_id, worker_id):
                logging.warning("[rag-eval-worker] lease lost run=%s worker=%s", run_id, worker_id)
                return
            manager.touch_worker_heartbeat(run_id, worker_id)
        except Exception:
            logging.exception("[rag-eval-worker] heartbeat failed run=%s worker=%s", run_id, worker_id)


def _reconcile_stale_runs(manager: IsolatedRunManager) -> None:
    """把上一进程遗留的 heartbeat 超时任务收敛成失败。"""
    for job in job_service.reconcile_stale_evaluations():
        run_id = str(job.get("run_id") or "")
        message = str(job.get("error_message") or "评测 worker heartbeat 超时，任务未完成")
        try:
            manager.mark_worker_timeout(run_id, message)
        except KeyError:
            logging.warning("[rag-eval-worker] stale run directory missing run=%s", run_id)
        except Exception:
            logging.exception("[rag-eval-worker] failed to reconcile run=%s", run_id)


def _run_one(manager: IsolatedRunManager, job: dict[str, Any], worker_id: str) -> None:
    """执行单个已领取任务，并把 run.json 与 SQL 状态同步到终态。"""
    run_id = str(job["run_id"])
    manager.mark_worker_started(run_id, worker_id)
    stop = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_loop,
        args=(manager, run_id, worker_id, stop),
        daemon=True,
        name=f"r5_eval_heartbeat_{run_id}",
    )
    heartbeat.start()
    try:
        manager.run_evaluation_sync(run_id)
        state = manager._load(run_id)
        status = state.get("status")
        if status == "cancelled":
            job_service.cancel_evaluation(run_id)
        if status == "succeeded":
            job_service.complete_evaluation(run_id)
        elif status == "cancelled":
            # 取消请求已经由 Web 或执行器写入 run.json；SQL 只需保留终态。
            job_service.cancel_evaluation(run_id)
        elif status == "failed":
            job_service.fail_evaluation(run_id, str(state.get("error") or "评测执行失败"))
        else:
            message = f"评测执行结束但未产生终态: {status}"
            manager.mark_worker_timeout(run_id, message)
            job_service.fail_evaluation(run_id, message)
    except Exception as exc:
        logging.exception("[rag-eval-worker] evaluation failed run=%s", run_id)
        try:
            manager.mark_worker_timeout(run_id, str(exc))
        finally:
            job_service.fail_evaluation(run_id, str(exc))
    finally:
        stop.set()
        heartbeat.join(timeout=max(int(settings.R5_EVALUATION_HEARTBEAT_INTERVAL_SECONDS), 1) + 1)


def _run_slot(slot_index: int) -> None:
    """运行一个常驻评测 slot。"""
    manager = IsolatedRunManager()
    worker_id = f"{socket.gethostname()}:rag-eval:{slot_index}"
    poll_interval = max(float(settings.R5_EVALUATION_POLL_INTERVAL_SECONDS), 0.1)
    while True:
        _reconcile_stale_runs(manager)
        job = job_service.claim_next_evaluation(worker_id)
        if job:
            _run_one(manager, job, worker_id)
        else:
            time.sleep(poll_interval)


def main() -> None:
    """命令行入口：校验数据库后启动常驻评测 slots。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        force=True,
    )
    check_database_readiness()
    slot_count = max(int(settings.R5_EVALUATION_WORKERS), 1)
    logging.info("[rag-eval-worker] starting slot_count=%s", slot_count)
    slots = [
        threading.Thread(target=_run_slot, args=(index,), daemon=False, name=f"r5_eval_slot_{index}")
        for index in range(1, slot_count + 1)
    ]
    for slot in slots:
        slot.start()
    for slot in slots:
        slot.join()


if __name__ == "__main__":
    if sys.platform == "win32":
        # 当前 worker 主要在 Docker 中运行；保留入口兼容本地 Windows 启动。
        pass
    main()
