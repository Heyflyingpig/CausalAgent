"""
数据库初始化引导脚本。

本脚本只负责加载配置、确保数据库存在、检查连接，并提示使用 Alembic 维护业务表结构。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import mysql.connector
from mysql.connector import errorcode

from observability.logging_runtime import configure_logging, current_environment


class DatabaseBootstrap:
    def __init__(self):
        self.project_root = Path(__file__).resolve().parents[1]
        self.mysql_config: dict[str, str | int] = {}
        self.load_database_config()

    def load_database_config(self) -> None:
        try:
            from dotenv import load_dotenv

            env_path = self.project_root / ".env"
            if env_path.exists():
                load_dotenv(dotenv_path=env_path)
                logging.info("已加载环境变量")
        except ImportError:
            logging.info("未安装 python-dotenv，使用系统环境变量")

        host = os.environ.get("MYSQL_WRITE_HOST") or os.environ.get("MYSQL_HOST")
        write_user = os.environ.get("MYSQL_WRITE_USER") or os.environ.get("MYSQL_USER")
        write_password = os.environ.get("MYSQL_WRITE_PASSWORD") or os.environ.get("MYSQL_PASSWORD")
        required = {
            "MYSQL_HOST 或 MYSQL_WRITE_HOST": host,
            "MYSQL_WRITE_USER 或 MYSQL_USER": write_user,
            "MYSQL_WRITE_PASSWORD 或 MYSQL_PASSWORD": write_password,
            "MYSQL_DATABASE": os.environ.get("MYSQL_DATABASE"),
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError(f"缺少数据库环境变量: {missing}")

        self.mysql_config = {
            "host": host,
            "port": int(os.environ.get("MYSQL_PORT", "3306")),
            "user": write_user,
            "password": write_password,
            "database": os.environ["MYSQL_DATABASE"],
        }
        logging.info(
            "数据库配置已加载",
        )

    def create_database_if_not_exists(self) -> None:
        root_password = os.environ.get("MYSQL_ROOT_PASSWORD") or str(self.mysql_config["password"])
        database_name = str(self.mysql_config["database"])
        try:
            conn = mysql.connector.connect(
                host=self.mysql_config["host"],
                port=self.mysql_config["port"],
                user="root",
                password=root_password,
            )
            cursor = conn.cursor()
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            conn.commit()
            cursor.close()
            conn.close()
            logging.info("数据库已确保存在")
        except mysql.connector.Error as err:
            if err.errno in (errorcode.ER_DBACCESS_DENIED_ERROR, errorcode.ER_ACCESS_DENIED_ERROR):
                logging.error("当前账号没有创建数据库权限，请使用具备权限的账号初始化。")
            raise

    def check_database_connection(self) -> bool:
        try:
            conn = mysql.connector.connect(**self.mysql_config)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            ok = bool(row and row[0] == 1)
            if ok:
                logging.info("数据库连接检查通过")
            return ok
        except mysql.connector.Error:
            logging.error(
                "数据库连接检查失败",
                extra={
                    "event_code": "maintenance.database.connection_failed",
                    "category": "dependency",
                    "details": {"component": "mysql"},
                },
                exc_info=True,
            )
            return False

    def bootstrap(self) -> bool:
        self.create_database_if_not_exists()
        return self.check_database_connection()


def main() -> int:
    configure_logging("maintenance", current_environment(), logging.INFO)
    print("CausalAgent 数据库初始化引导")
    bootstrap = DatabaseBootstrap()
    if not bootstrap.bootstrap():
        print("\n数据库初始化引导失败，请查看 stderr 中的结构化日志。")
        return 1

    print("\n数据库已存在且连接可用。")
    print("\n如需完成 MySQL 和 PostgreSQL 的完整初始化，请执行：")
    print("  python -m Database.bootstrap")
    print("\n说明：业务表结构由 Alembic 迁移维护，本脚本不再创建或修改业务表。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
