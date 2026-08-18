"""统一执行 MySQL 和 PostgreSQL 数据库初始化。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from observability.logging_runtime import configure_logging, current_environment

if __name__ == "__main__":
    configure_logging("maintenance", current_environment(), logging.INFO)

from alembic import command
from alembic.config import Config


LOGGER = logging.getLogger(__name__)


def _project_root() -> Path:
    """返回仓库根目录，保证从任意当前工作目录执行都能定位 Alembic 配置。"""
    return Path(__file__).resolve().parents[1]


def upgrade_mysql_schema(project_root: Path | None = None) -> None:
    """使用项目现有 Alembic 迁移将 MySQL schema 升级到当前 head。"""
    root = project_root or _project_root()
    alembic_config = Config(str(root / "alembic.ini"))
    LOGGER.info("开始执行 MySQL Alembic migration")
    command.upgrade(alembic_config, "head")


def setup_postgres_checkpoint_schema() -> None:
    """执行 LangGraph 官方 PostgreSQL checkpoint schema setup。"""
    from Database.checkpoint_setup import setup_checkpoint_schema_once

    LOGGER.info("开始执行 PostgreSQL checkpoint schema setup")
    asyncio.run(setup_checkpoint_schema_once())


def create_mysql_bootstrap():
    """延迟加载 MySQL bootstrap，避免仅导入模块时创建日志文件。"""
    from Database.database_init import DatabaseBootstrap

    return DatabaseBootstrap()


def run_bootstrap(project_root: Path | None = None) -> None:
    """按依赖顺序完成 MySQL 建库、Alembic 迁移和 PostgreSQL setup。"""
    LOGGER.info("开始执行统一数据库 bootstrap")

    mysql_bootstrap = create_mysql_bootstrap()
    if not mysql_bootstrap.bootstrap():
        raise RuntimeError("MySQL 数据库连接检查失败，停止执行后续初始化。")

    upgrade_mysql_schema(project_root)
    setup_postgres_checkpoint_schema()
    LOGGER.info(
        "统一数据库 bootstrap 完成",
        extra={
            "event_code": "maintenance.startup.ready",
            "category": "lifecycle",
            "details": {"component": "db-bootstrap"},
        },
    )


def main() -> int:
    """命令行入口：python -m Database.bootstrap。"""
    configure_logging("maintenance", current_environment(), logging.INFO)
    try:
        run_bootstrap()
    except Exception:
        LOGGER.error(
            "统一数据库 bootstrap 失败",
            extra={
                "event_code": "maintenance.startup.failed",
                "category": "dependency",
                "details": {"component": "db-bootstrap"},
            },
            exc_info=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
