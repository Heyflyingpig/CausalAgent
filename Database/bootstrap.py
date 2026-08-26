"""统一执行 MySQL 和 PostgreSQL 数据库初始化。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from Database.job_execution_upgrade_repair import (
    JobExecutionUpgradeBlockedError,
    check_upgrade_compatibility,
)
from Database.migration_version_repair import repair_legacy_revision_ids
from observability.logging_runtime import configure_logging, current_environment, log_event

LOGGER = logging.getLogger(__name__)

if __name__ == "__main__":
    configure_logging("maintenance", current_environment(), logging.INFO)

try:
    from alembic import command
    from alembic.config import Config
except Exception as exc:
    if __name__ == "__main__":
        log_event(
            LOGGER,
            "maintenance.startup.failed",
            details={
                "phase": "module_initialization",
                "dependency": "alembic",
                "reason_code": "initialization_failed",
            },
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        raise SystemExit(1) from None
    raise


def _project_root() -> Path:
    """返回仓库根目录，保证从任意当前工作目录执行都能定位 Alembic 配置。"""
    return Path(__file__).resolve().parents[1]


def upgrade_mysql_schema(project_root: Path | None = None) -> None:
    """使用项目现有 Alembic 迁移将 MySQL schema 升级到当前 head。"""
    root = project_root or _project_root()
    alembic_config = Config(str(root / "alembic.ini"))
    # 编排入口已经配置共享 JSON handler，避免 Alembic fileConfig 覆盖它。
    alembic_config.attributes["configure_logger"] = False
    command.upgrade(alembic_config, "head")


def setup_postgres_checkpoint_schema() -> None:
    """执行 LangGraph 官方 PostgreSQL checkpoint schema setup。"""
    from Database.checkpoint_setup import setup_checkpoint_schema_once

    asyncio.run(setup_checkpoint_schema_once())


def create_mysql_bootstrap():
    """延迟加载 MySQL bootstrap，避免仅导入模块时创建日志文件。"""
    from Database.database_init import DatabaseBootstrap

    return DatabaseBootstrap()


def run_bootstrap(project_root: Path | None = None) -> None:
    """按依赖顺序完成 MySQL 建库、Alembic 迁移和 PostgreSQL setup。"""
    mysql_bootstrap = create_mysql_bootstrap()
    if not mysql_bootstrap.bootstrap():
        raise RuntimeError("MySQL 数据库连接检查失败，停止执行后续初始化。")

    connection = mysql_bootstrap.open_connection()
    try:
        repair_legacy_revision_ids(connection)
    finally:
        connection.close()
    # 旧 revision 修复只做一次安全的物理 schema 判定；结果不含敏感信息，
    # 成功状态统一由末尾的 maintenance.startup.ready 事件表示。
    check_upgrade_compatibility(mysql_bootstrap.mysql_config)
    upgrade_mysql_schema(project_root)
    setup_postgres_checkpoint_schema()
    log_event(LOGGER, "maintenance.startup.ready")


def main() -> int:
    """命令行入口：python -m Database.bootstrap。"""
    configure_logging("maintenance", current_environment(), logging.INFO)
    try:
        run_bootstrap()
    except JobExecutionUpgradeBlockedError as exc:
        log_event(
            LOGGER,
            "maintenance.startup.failed",
            details={
                "phase": "migration_preflight",
                "dependency": "mysql_schema",
                "reason_code": "migration_precondition_failed",
            },
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return 1
    except Exception as exc:
        log_event(
            LOGGER,
            "maintenance.startup.failed",
            details={
                "phase": "database_bootstrap",
                "dependency": "database",
                "reason_code": "initialization_failed",
            },
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
