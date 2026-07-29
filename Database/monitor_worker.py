"""独立数据库监控采集进程。

启动方式：
    python -m Database.monitor_worker
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import logging
import time

from Database.monitoring import SNAPSHOT_KEYS, collect_snapshot, get_due_snapshot_keys
from app.db import check_database_readiness
from config.settings import settings


CONTROL_POLL_SECONDS = 1.0


def run_forever() -> None:
    """按快照类型并行调度采集，避免低频慢任务阻塞实时状态更新。"""
    check_database_readiness()
    max_workers = max(1, min(
        len(SNAPSHOT_KEYS),
        settings.MYSQL_POOL_SIZE_WRITE,
        settings.MYSQL_POOL_SIZE_READ,
    ))
    logging.info("数据库 monitor 已启动，分层采集并发数=%s。", max_workers)
    if max_workers < len(SNAPSHOT_KEYS):
        logging.warning(
            "数据库连接池小于快照类型数，慢速审计可能延后实时采集；"
            "建议 monitor 的 MYSQL_POOL_SIZE_WRITE/READ 均至少为 %s。",
            len(SNAPSHOT_KEYS),
        )
    active: dict[str, Future[bool]] = {}
    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="db-monitor",
    ) as executor:
        while True:
            for snapshot_key, future in tuple(active.items()):
                if not future.done():
                    continue
                del active[snapshot_key]
                try:
                    if future.result():
                        logging.info("数据库监控快照已更新: %s", snapshot_key)
                except Exception as exc:
                    logging.error(
                        "数据库监控快照采集失败 [%s]: %s",
                        snapshot_key,
                        exc,
                        exc_info=True,
                    )
            for snapshot_key in get_due_snapshot_keys():
                if snapshot_key not in active:
                    active[snapshot_key] = executor.submit(
                        collect_snapshot,
                        snapshot_key,
                        require_due=True,
                    )
            time.sleep(CONTROL_POLL_SECONDS)


def main() -> None:
    """配置日志并运行数据库监控主循环。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        force=True,
    )
    try:
        run_forever()
    except KeyboardInterrupt:
        logging.info("数据库 monitor 已停止。")


if __name__ == "__main__":
    main()
