"""
app.db - 数据库访问模块

提供写库连接、弱一致读连接、慢查询计时和数据库就绪检查。
"""

from __future__ import annotations

from contextlib import contextmanager
import logging
import random
import time
from typing import Any, Iterable

import mysql.connector
from mysql.connector import errorcode, pooling

from config.settings import settings

_write_pool: pooling.MySQLConnectionPool | None = None
_read_pools: dict[str, pooling.MySQLConnectionPool] = {}


def _base_connection_config(host: str) -> dict[str, Any]:
    return {
        "host": host,
        "port": settings.MYSQL_PORT,
        "charset": "utf8mb4",
        "use_unicode": True,
    }


def write_connection_config(host: str | None = None) -> dict[str, Any]:
    """写库连接配置，只用于业务写入和启动就绪检查。"""
    return {
        **_base_connection_config(host or settings.MYSQL_WRITE_HOST),
        "user": settings.MYSQL_WRITE_USER,
        "password": settings.MYSQL_WRITE_PASSWORD,
        "database": settings.MYSQL_DATABASE,
    }


def read_connection_config(host: str) -> dict[str, Any]:
    """业务读取连接配置，可连接主库或从库，但不做复制状态观测。"""
    return {
        **_base_connection_config(host),
        "user": settings.MYSQL_READ_USER,
        "password": settings.MYSQL_READ_PASSWORD,
        "database": settings.MYSQL_DATABASE,
    }


def replica_status_connection_config(host: str) -> dict[str, Any] | None:
    """复制状态观测连接配置；缺失专用账号时禁用从库状态检查。"""
    if not settings.MYSQL_REPLICA_STATUS_USER or not settings.MYSQL_REPLICA_STATUS_PASSWORD:
        logging.warning("未配置复制状态检查账号，eventual 读将回退主库。")
        return None
    return {
        **_base_connection_config(host),
        "user": settings.MYSQL_REPLICA_STATUS_USER,
        "password": settings.MYSQL_REPLICA_STATUS_PASSWORD,
    }


def _get_write_pool() -> pooling.MySQLConnectionPool:
    global _write_pool
    if _write_pool is None:
        _write_pool = pooling.MySQLConnectionPool(
            pool_name="causalchat_write_pool",
            pool_size=settings.MYSQL_POOL_SIZE_WRITE,
            pool_reset_session=True,
            **write_connection_config(settings.MYSQL_WRITE_HOST),
        )
    return _write_pool


def _get_read_pool(host: str) -> pooling.MySQLConnectionPool:
    pool = _read_pools.get(host)
    if pool is None:
        pool = pooling.MySQLConnectionPool(
            pool_name=f"causalchat_read_{abs(hash(host))}",
            pool_size=settings.MYSQL_POOL_SIZE_READ,
            pool_reset_session=True,
            **read_connection_config(host),
        )
        _read_pools[host] = pool
    return pool


def _get_replica_status_connection(host: str):
    config = replica_status_connection_config(host)
    if config is None:
        return None
    return mysql.connector.connect(**config)


def _log_connection_error(err: mysql.connector.Error, target: str) -> None:
    if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
        logging.error("MySQL %s连接错误: 用户或密码错误。", target)
    elif err.errno == errorcode.ER_BAD_DB_ERROR:
        logging.error("MySQL %s连接错误: 数据库 '%s' 不存在。", target, settings.MYSQL_DATABASE)
    else:
        logging.error("MySQL %s连接错误: %s", target, err)


def get_write_connection():
    """获取写库连接。"""
    try:
        return _get_write_pool().get_connection()
    except mysql.connector.Error as err:
        _log_connection_error(err, "写库")
        raise


def get_replica_status(host: str | None = None) -> dict[str, Any] | None:
    """使用专用状态账号读取从库状态；无法取得时返回 None。"""
    if host is None:
        if not settings.MYSQL_READ_HOSTS:
            return None
        host = settings.MYSQL_READ_HOSTS[0]
    conn = None
    try:
        conn = _get_replica_status_connection(host)
        if conn is None:
            return None
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SHOW REPLICA STATUS")
        row = cursor.fetchone()
        return row or None
    except mysql.connector.Error as err:
        logging.warning("读取从库复制状态失败，将回退主库: %s", err)
        return None
    finally:
        if conn is not None:
            conn.close()


def get_replica_lag_seconds(host: str | None = None) -> int | None:
    """读取从库延迟。无法取得时返回 None。"""
    row = get_replica_status(host)
    if not row:
        return None
    lag = row.get("Seconds_Behind_Source")
    return int(lag) if lag is not None else None


def should_use_replica(host: str) -> bool:
    """判断从库延迟是否满足弱一致读条件。"""
    row = get_replica_status(host)
    if not row:
        return False
    if row.get("Replica_IO_Running") != "Yes" or row.get("Replica_SQL_Running") != "Yes":
        logging.warning("从库 %s 复制线程未全部运行，回退主库。", host)
        return False
    lag = row.get("Seconds_Behind_Source")
    if lag is not None:
        lag = int(lag)
    return lag is not None and lag <= settings.MYSQL_REPLICA_MAX_LAG_SECONDS


def get_read_connection(consistency: str = "strong"):
    """
    获取读连接。

    strong 固定走主库；eventual 在从库健康且延迟可接受时走从库，否则回退主库。
    """
    connection, _source = get_read_connection_with_source(consistency=consistency)
    return connection


def get_read_connection_with_source(
    consistency: str = "strong",
) -> tuple[Any, dict[str, str]]:
    """
    获取读连接并返回不暴露真实主机名的逻辑来源。

    strong 固定返回主库读连接；eventual 仅在副本健康且延迟合格时返回副本，
    否则回退主库。来源别名供只读看板解释数据口径，不包含连接信息。
    """
    if consistency not in {"strong", "eventual"}:
        raise ValueError("consistency 必须是 'strong' 或 'eventual'")

    primary_source = {"source_role": "primary", "source_alias": "primary"}
    if consistency == "strong" or not settings.MYSQL_READ_HOSTS:
        return _get_read_pool(settings.MYSQL_WRITE_HOST).get_connection(), primary_source

    aliases = {
        host: f"replica-{index}"
        for index, host in enumerate(settings.MYSQL_READ_HOSTS, start=1)
    }
    hosts = list(settings.MYSQL_READ_HOSTS)
    random.shuffle(hosts)
    for host in hosts:
        if not should_use_replica(host):
            logging.warning("从库 %s 状态不可用或延迟超过阈值，回退主库。", host)
            continue
        try:
            return _get_read_pool(host).get_connection(), {
                "source_role": "replica",
                "source_alias": aliases[host],
            }
        except mysql.connector.Error as err:
            logging.warning("从库 %s 不可用，回退主库: %s", host, err)

    return _get_read_pool(settings.MYSQL_WRITE_HOST).get_connection(), primary_source


def get_db_connection():
    """兼容旧代码：默认获取主库连接。"""
    return get_write_connection()


def execute_with_timing(cursor, sql: str, params: Iterable[Any] | None = None):
    """执行 SQL 并记录慢查询 warning。"""
    start = time.perf_counter()
    try:
        if params is None:
            return cursor.execute(sql)
        return cursor.execute(sql, params)
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        if elapsed_ms >= settings.MYSQL_QUERY_WARN_MS:
            logging.warning("慢查询 %.1fms: %s", elapsed_ms, " ".join(sql.split()))


@contextmanager
def db_cursor(write: bool = True, consistency: str = "strong", dictionary: bool = False):
    """轻量上下文：统一创建连接和游标。"""
    conn = get_write_connection() if write else get_read_connection(consistency=consistency)
    try:
        cursor = conn.cursor(dictionary=dictionary)
        yield conn, cursor
    finally:
        conn.close()


def check_database_readiness():
    """检查数据库是否已准备就绪。"""
    try:
        logging.info("检查数据库连接和表结构就绪状态...")

        with get_write_connection() as conn:
            cursor = conn.cursor()
            required_tables = [
                "users",
                "sessions",
                "chat_messages",
                "chat_attachments",
                "uploaded_files",
                "archived_sessions",
                "checkpoints",
                "checkpoint_writes",
                "analysis_jobs",
                "analysis_job_events",
            ]
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                """,
                (settings.MYSQL_DATABASE,),
            )
            existing_tables = [row[0] for row in cursor.fetchall()]

            missing_tables = set(required_tables) - set(existing_tables)
            if missing_tables:
                error_msg = (
                    f"数据库表缺失: {sorted(missing_tables)}。"
                    "请先运行 'python Database/database_init.py' 并执行 'alembic upgrade head'。"
                )
                logging.error(error_msg)
                raise RuntimeError(error_msg)

            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = 'users'
                  AND column_name = 'role'
                """,
                (settings.MYSQL_DATABASE,),
            )
            if cursor.fetchone() is None:
                error_msg = (
                    "数据库关键字段缺失: users.role。"
                    "请先执行 'alembic upgrade head'。"
                )
                logging.error(error_msg)
                raise RuntimeError(error_msg)

            cursor.execute("SELECT 1")
            test_result = cursor.fetchone()
            if not test_result or test_result[0] != 1:
                raise RuntimeError("数据库连接测试失败")

            logging.info("数据库 '%s' 就绪检查通过。", settings.MYSQL_DATABASE)
            return True

    except mysql.connector.Error as e:
        if e.errno == errorcode.ER_BAD_DB_ERROR:
            error_msg = (
                f"数据库 '{settings.MYSQL_DATABASE}' 不存在。"
                "请先运行 'python Database/database_init.py' 创建数据库。"
            )
            logging.error(error_msg)
            raise RuntimeError(error_msg) from e
        if e.errno == errorcode.ER_ACCESS_DENIED_ERROR:
            error_msg = "无法访问数据库。请检查数据库账号权限配置。"
            logging.error(error_msg)
            raise RuntimeError(error_msg) from e
        logging.error("数据库就绪性检查失败: %s", e)
        raise
    except Exception as e:
        logging.error("数据库就绪性检查过程中发生未知错误: %s", e)
        raise
