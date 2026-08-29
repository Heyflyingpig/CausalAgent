"""独立数据库监控采集进程。

启动方式：
    python -m Database.monitor_worker
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import logging
import time

from observability.logging_runtime import configure_logging, current_environment, log_event

if __name__ == "__main__":
    configure_logging("monitor", current_environment(), logging.INFO)

CONTROL_POLL_SECONDS = 1.0
LOGGER = logging.getLogger(__name__)
_STARTUP_READY = False

try:
    from Database.monitoring import SNAPSHOT_KEYS, collect_snapshot, get_due_snapshot_keys
    from app.db import check_database_readiness
    from config.settings import settings
except Exception as exc:
    if __name__ == "__main__":
        log_event(
            LOGGER,
            "monitor.startup.failed",
            details={
                "phase": "module_initialization",
                "dependency": "monitor_runtime",
                "reason_code": "initialization_failed",
            },
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        raise SystemExit(1) from None
    raise


def run_forever() -> None:
    """按快照类型并行调度采集，避免低频慢任务阻塞实时状态更新。"""
    global _STARTUP_READY
    _STARTUP_READY = False
    phase = "database_readiness"
    dependency = "mysql"
    try:
        check_database_readiness()
        phase = "runtime_initialization"
        dependency = "monitor_runtime"
        max_workers = max(1, min(
            len(SNAPSHOT_KEYS),
            settings.MYSQL_POOL_SIZE_WRITE,
            settings.MYSQL_POOL_SIZE_READ,
        ))
        if max_workers < len(SNAPSHOT_KEYS):
            log_event(
                LOGGER,
                "monitor.config.degraded",
                details={
                    "reason_code": "pool_capacity_below_snapshot_count",
                    "suppressed_count": 0,
                },
            )
        active: dict[str, Future[bool]] = {}
        with ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="db-monitor",
        ) as executor:
            log_event(
                LOGGER,
                "monitor.startup.ready",
            )
            _STARTUP_READY = True
            while True:
                for snapshot_key, future in tuple(active.items()):
                    if not future.done():
                        continue
                    del active[snapshot_key]
                    try:
                        future.result()
                    except Exception:
                        pass
                for snapshot_key in get_due_snapshot_keys():
                    if snapshot_key not in active:
                        active[snapshot_key] = executor.submit(
                            collect_snapshot,
                            snapshot_key,
                            require_due=True,
                        )
                time.sleep(CONTROL_POLL_SECONDS)
    except Exception:
        if not _STARTUP_READY:
            log_event(
                LOGGER,
                "monitor.startup.failed",
                details={
                    "phase": phase,
                    "dependency": dependency,
                    "reason_code": (
                        "readiness_failed"
                        if phase == "database_readiness"
                        else "initialization_failed"
                    ),
                },
                exc_info=True,
            )
        raise


def main() -> None:
    """配置日志并运行数据库监控主循环。"""
    configure_logging("monitor", current_environment(), logging.INFO)
    try:
        run_forever()
    except KeyboardInterrupt:
        return
    except Exception:
        if _STARTUP_READY:
            log_event(
                LOGGER,
                "monitor.snapshot.failed",
                details={
                    "snapshot_key": "scheduler",
                    "reason_code": "runtime_failed",
                    "duration_ms": 0,
                    "suppressed_count": 0,
                },
                exc_info=True,
            )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
