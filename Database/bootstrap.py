"""统一执行 MySQL 和 PostgreSQL 数据库初始化。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from Database.checkpoint_setup import setup_checkpoint_schema_once
from Database.migration_version_repair import repair_legacy_revision_ids


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
    """执行 LangGraph 官方 PostgreSQL checkpoint schema setup。

    仅当配置了 PostgreSQL checkpoint 密码时执行；未配置（例如只部署隔离评测
    链路、无 LangGraph checkpoint 需求的生产拓扑）时优雅跳过，避免统一
    bootstrap 因缺少 PostgreSQL 而整体失败。
    """
    try:
        from config.checkpoint_settings import CheckpointPostgresConfig

        config = CheckpointPostgresConfig.from_env()
    except Exception as exc:
        LOGGER.warning("无法读取 PostgreSQL checkpoint 配置，跳过 schema setup: %s", exc)
        return
    if not config.password:
        LOGGER.warning("未配置 CHECKPOINT_POSTGRES_PASSWORD，跳过 PostgreSQL checkpoint schema setup")
        return
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

    connection = mysql_bootstrap.open_connection()
    try:
        repaired = repair_legacy_revision_ids(connection)
    finally:
        connection.close()
    if repaired:
        LOGGER.warning("已修复历史重复 Alembic revision: %s", ", ".join(repaired))

    upgrade_mysql_schema(project_root)
    setup_postgres_checkpoint_schema()
    LOGGER.info("统一数据库 bootstrap 完成")


def main() -> int:
    """命令行入口：python -m Database.bootstrap。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        force=True,
    )
    try:
        run_bootstrap()
    except Exception as exc:
        LOGGER.error("统一数据库 bootstrap 失败: %s", exc, exc_info=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
