"""管理员数据库看板使用的统一只读检查服务。"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger(__name__)
MAX_SLOW_QUERY_LIMIT = 100


def _observed_at() -> str:
    """返回统一的 UTC ISO 8601 采集时间。"""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _result(
    status: str,
    value: Any,
    *,
    source_role: str,
    source_alias: str,
    is_estimate: bool = False,
    warning: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """构造带状态、来源、时间和估算标记的标准只读结果。"""
    return {
        "status": status,
        "value": value,
        "observed_at": observed_at or _observed_at(),
        "source_role": source_role,
        "source_alias": source_alias,
        "is_estimate": is_estimate,
        "warning": warning,
    }


def _failed_result(
    block_name: str,
    exc: Exception,
    *,
    source_role: str,
    source_alias: str,
    warning: str,
) -> dict[str, Any]:
    """记录完整服务端异常，并向前端返回不含连接细节的失败结果。"""
    LOGGER.warning("数据库只读检查失败 [%s]: %s", block_name, type(exc).__name__)
    LOGGER.debug("数据库只读检查异常详情 [%s]", block_name, exc_info=True)
    return _result(
        "unknown",
        None,
        source_role=source_role,
        source_alias=source_alias,
        warning=warning,
    )


def _timeout_hint(timeout_ms: int) -> str:
    """生成仅约束当前 SELECT 的 MySQL 最大执行时间 hint。"""
    return f"/*+ MAX_EXECUTION_TIME({int(timeout_ms)}) */"


def _int_or_none(value: Any) -> int | None:
    """把数据库数值安全转换为整数，同时保留 NULL。"""
    return int(value) if value is not None else None


def _show_values(cursor, statement: str, names: list[str]) -> dict[str, str]:
    """读取 SHOW VARIABLES/STATUS 结果并按变量名返回。"""
    placeholders = ", ".join(["%s"] * len(names))
    cursor.execute(f"{statement} WHERE Variable_name IN ({placeholders})", names)
    return {row["Variable_name"]: row["Value"] for row in cursor.fetchall()}


def inspect_revision() -> dict[str, Any]:
    """比较仓库 Alembic head 与主库实例 revision。"""
    repository_heads: list[str] | None = None
    instance_revisions: list[str] | None = None
    warnings: list[str] = []

    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        project_root = Path(__file__).resolve().parents[1]
        config = Config(str(project_root / "alembic.ini"))
        script = ScriptDirectory.from_config(config)
        repository_heads = sorted(script.get_heads())
    except Exception as exc:
        LOGGER.warning("读取仓库 Alembic head 失败: %s", exc, exc_info=True)
        warnings.append("无法读取仓库 Alembic head")

    try:
        from app.db import get_read_connection_with_source
        from config.settings import settings

        connection, _source = get_read_connection_with_source(consistency="strong")
        with connection as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                f"SELECT {_timeout_hint(settings.DB_INSPECTION_QUERY_TIMEOUT_MS)} "
                "version_num FROM alembic_version ORDER BY version_num"
            )
            instance_revisions = sorted(row["version_num"] for row in cursor.fetchall())
    except Exception as exc:
        LOGGER.warning("读取实例 Alembic revision 失败: %s", exc, exc_info=True)
        warnings.append("无法读取实例 Alembic revision")

    matches = (
        repository_heads is not None
        and instance_revisions is not None
        and repository_heads == instance_revisions
    )
    if repository_heads is None or instance_revisions is None:
        status = "unknown"
    elif matches:
        status = "healthy"
    else:
        status = "error"
        warnings.append("仓库 head 与实例 revision 不一致")

    return _result(
        status,
        {
            "repository_heads": repository_heads,
            "instance_revisions": instance_revisions,
            "matches": matches,
        },
        source_role="mixed",
        source_alias="repository+primary",
        warning="；".join(warnings) or None,
    )


def inspect_primary() -> dict[str, Any]:
    """检查主库只读连接并读取实际 MySQL 版本。"""
    try:
        from app.db import get_read_connection_with_source
        from config.settings import settings

        connection, source = get_read_connection_with_source(consistency="strong")
        with connection as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                f"SELECT {_timeout_hint(settings.DB_INSPECTION_QUERY_TIMEOUT_MS)} "
                "VERSION() AS version, UTC_TIMESTAMP(6) AS database_time"
            )
            row = cursor.fetchone() or {}
        return _result(
            "healthy",
            {
                "connected": True,
                "version": row.get("version"),
                "database_time": row.get("database_time"),
            },
            **source,
        )
    except Exception as exc:
        return _failed_result(
            "primary",
            exc,
            source_role="primary",
            source_alias="primary",
            warning="主库只读连接或版本查询失败",
        )


def inspect_replica() -> dict[str, Any]:
    """读取第一从库复制线程、延迟与最近错误。"""
    try:
        from app.db import get_replica_status
        from config.settings import settings

        if not settings.MYSQL_READ_HOSTS:
            return _result(
                "unknown",
                {"configured": False, "available": False},
                source_role="replica",
                source_alias="replica-1",
                warning="未配置从库",
            )

        row = get_replica_status(settings.MYSQL_READ_HOSTS[0])
        if not row:
            return _result(
                "unknown",
                {"configured": True, "available": False},
                source_role="replica",
                source_alias="replica-1",
                warning="无法读取第一从库复制状态",
            )

        io_running = row.get("Replica_IO_Running")
        sql_running = row.get("Replica_SQL_Running")
        lag_seconds = _int_or_none(row.get("Seconds_Behind_Source"))
        raw_io_error = row.get("Last_IO_Error") or None
        raw_sql_error = row.get("Last_SQL_Error") or None
        last_io_error_code = _int_or_none(row.get("Last_IO_Errno"))
        last_sql_error_code = _int_or_none(row.get("Last_SQL_Errno"))
        last_io_error = (
            f"复制 I/O 错误（错误号 {last_io_error_code or '未知'}）"
            if raw_io_error
            else None
        )
        last_sql_error = (
            f"复制 SQL 错误（错误号 {last_sql_error_code or '未知'}）"
            if raw_sql_error
            else None
        )
        warning = None
        if io_running != "Yes" or sql_running != "Yes" or last_io_error or last_sql_error:
            status = "error"
            warning = "从库复制线程异常或存在复制错误"
        elif lag_seconds is None:
            status = "warning"
            warning = "从库复制延迟未知"
        elif lag_seconds > settings.MYSQL_REPLICA_MAX_LAG_SECONDS:
            status = "warning"
            warning = "从库复制延迟超过应用读取阈值"
        else:
            status = "healthy"

        return _result(
            status,
            {
                "configured": True,
                "available": True,
                "io_running": io_running,
                "sql_running": sql_running,
                "lag_seconds": lag_seconds,
                "last_io_error": last_io_error,
                "last_io_error_code": last_io_error_code,
                "last_sql_error": last_sql_error,
                "last_sql_error_code": last_sql_error_code,
            },
            source_role="replica",
            source_alias="replica-1",
            warning=warning,
        )
    except Exception as exc:
        return _failed_result(
            "replica",
            exc,
            source_role="replica",
            source_alias="replica-1",
            warning="读取第一从库复制状态失败",
        )


def inspect_connections() -> dict[str, Any]:
    """读取主库连接指标并按可配置阈值计算状态。"""
    try:
        from app.db import get_read_connection_with_source
        from config.settings import settings

        connection, source = get_read_connection_with_source(consistency="strong")
        with connection as conn:
            cursor = conn.cursor(dictionary=True)
            values = _show_values(
                cursor,
                "SHOW GLOBAL STATUS",
                ["Threads_connected", "Threads_running", "Max_used_connections", "Slow_queries"],
            )
            variables = _show_values(cursor, "SHOW GLOBAL VARIABLES", ["max_connections"])

        connected = _int_or_none(values.get("Threads_connected"))
        running = _int_or_none(values.get("Threads_running"))
        max_used = _int_or_none(values.get("Max_used_connections"))
        maximum = _int_or_none(variables.get("max_connections"))
        utilization = round((connected / maximum) * 100, 2) if connected is not None and maximum else None

        warning = None
        if utilization is None:
            status = "unknown"
            warning = "无法计算连接使用率"
        elif utilization >= settings.DB_DASHBOARD_CONNECTION_CRITICAL_PERCENT:
            status = "error"
            warning = "连接使用率达到严重阈值"
        elif utilization >= settings.DB_DASHBOARD_CONNECTION_WARNING_PERCENT:
            status = "warning"
            warning = "连接使用率达到警告阈值"
        else:
            status = "healthy"

        return _result(
            status,
            {
                "threads_connected": connected,
                "threads_running": running,
                "max_used_connections": max_used,
                "max_connections": maximum,
                "slow_queries": _int_or_none(values.get("Slow_queries")),
                "utilization_percent": utilization,
                "warning_threshold_percent": settings.DB_DASHBOARD_CONNECTION_WARNING_PERCENT,
                "critical_threshold_percent": settings.DB_DASHBOARD_CONNECTION_CRITICAL_PERCENT,
            },
            **source,
            warning=warning,
        )
    except Exception as exc:
        return _failed_result(
            "connections",
            exc,
            source_role="primary",
            source_alias="primary",
            warning="读取主库连接指标失败",
        )


def inspect_table_capacity() -> dict[str, Any]:
    """从可延迟读取节点获取表容量估算，并明确实际来源。"""
    try:
        from app.db import get_read_connection_with_source
        from config.settings import settings

        connection, source = get_read_connection_with_source(consistency="eventual")
        with connection as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                f"""
                SELECT {_timeout_hint(settings.DB_INSPECTION_QUERY_TIMEOUT_MS)}
                    table_name AS table_name,
                    table_rows AS table_rows,
                    data_length AS data_length,
                    index_length AS index_length,
                    data_length + index_length AS total_length
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                ORDER BY total_length DESC
                LIMIT 200
                """
            )
            rows = cursor.fetchall()

        tables = [
            {
                "table_name": row["table_name"],
                "table_rows": _int_or_none(row.get("table_rows")),
                "data_length": _int_or_none(row.get("data_length")) or 0,
                "index_length": _int_or_none(row.get("index_length")) or 0,
                "total_length": _int_or_none(row.get("total_length")) or 0,
            }
            for row in rows
        ]
        return _result(
            "healthy",
            tables,
            **source,
            is_estimate=True,
            warning="InnoDB 行数为估算值",
        )
    except Exception as exc:
        return _failed_result(
            "tables",
            exc,
            source_role="database",
            source_alias="selected-read-node",
            warning="读取表容量失败",
        )


def _blocking_issues(blocks: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """从核心区块中提取会阻止健康判定的问题。"""
    labels = {
        "revision": "数据库版本不一致",
        "primary": "主库不可用",
        "replica": "从库复制异常",
        "connections": "主库连接使用率严重",
    }
    return [
        {"key": key, "label": labels[key], "message": block.get("warning") or labels[key]}
        for key, block in blocks.items()
        if block.get("status") == "error"
    ]


def _overall_status(results: list[dict[str, Any]]) -> str:
    """按 error、warning/unknown、healthy 的优先级汇总状态。"""
    statuses = {item.get("status") for item in results}
    if "error" in statuses:
        return "error"
    if statuses.intersection({"warning", "unknown"}):
        return "warning"
    return "healthy"


def get_database_overview() -> dict[str, Any]:
    """汇总 revision、节点、连接和表容量，单项失败不拖垮其他区块。"""
    blocks = {
        "revision": inspect_revision(),
        "primary": inspect_primary(),
        "replica": inspect_replica(),
        "connections": inspect_connections(),
        "tables": inspect_table_capacity(),
    }
    core_blocks = {key: value for key, value in blocks.items() if key != "tables"}
    return {
        "status": _overall_status(list(blocks.values())),
        "observed_at": _observed_at(),
        **blocks,
        "blocking_issues": _blocking_issues(core_blocks),
    }


def inspect_slow_queries(limit: int = 20) -> dict[str, Any]:
    """读取所选节点的慢查询配置、累计计数和受限 digest 摘要。"""
    normalized_limit = max(1, min(int(limit), MAX_SLOW_QUERY_LIMIT))
    try:
        from app.db import get_read_connection_with_source
        from config.settings import settings

        connection, source = get_read_connection_with_source(consistency="eventual")
        with connection as conn:
            cursor = conn.cursor(dictionary=True)
            statuses = _show_values(cursor, "SHOW GLOBAL STATUS", ["Slow_queries"])
            variables = _show_values(
                cursor,
                "SHOW GLOBAL VARIABLES",
                ["slow_query_log", "long_query_time"],
            )
            digest_warning = None
            try:
                cursor.execute(
                    f"""
                    SELECT {_timeout_hint(settings.DB_INSPECTION_QUERY_TIMEOUT_MS)}
                        DIGEST_TEXT AS digest_text,
                        COUNT_STAR AS count_star,
                        ROUND(SUM_TIMER_WAIT / 1000000000000, 6) AS total_seconds,
                        ROUND(AVG_TIMER_WAIT / 1000000000000, 6) AS avg_seconds,
                        SUM_ROWS_EXAMINED AS rows_examined,
                        SUM_ROWS_SENT AS rows_sent
                    FROM performance_schema.events_statements_summary_by_digest
                    WHERE SCHEMA_NAME = DATABASE()
                      AND DIGEST_TEXT IS NOT NULL
                    ORDER BY SUM_TIMER_WAIT DESC
                    LIMIT %s
                    """,
                    (normalized_limit,),
                )
                top_statements = cursor.fetchall()
            except Exception as exc:
                LOGGER.warning("读取 performance_schema digest 失败: %s", type(exc).__name__)
                LOGGER.debug("performance_schema digest 异常详情", exc_info=True)
                top_statements = []
                digest_warning = "performance_schema 摘要不可用（权限不足、未启用或查询超时）"

        slow_query_log = variables.get("slow_query_log")
        warnings = [message for message in [digest_warning] if message]
        if str(slow_query_log).upper() not in {"ON", "1"}:
            warnings.append("当前节点未开启 slow_query_log")
        return _result(
            "warning" if warnings else "healthy",
            {
                "Slow_queries": _int_or_none(statuses.get("Slow_queries")),
                "slow_query_log": slow_query_log,
                "long_query_time": float(variables["long_query_time"])
                if variables.get("long_query_time") is not None
                else None,
                "top_statements": top_statements,
                "limit": normalized_limit,
            },
            **source,
            warning="；".join(warnings) or None,
        )
    except Exception as exc:
        return _failed_result(
            "slow-queries",
            exc,
            source_role="database",
            source_alias="selected-read-node",
            warning="读取慢查询配置和摘要失败",
        )


def _integrity_definitions(timeout_ms: int) -> list[dict[str, Any]]:
    """定义快速完整性检查的只读 SQL、标签和阻塞级别。"""
    hint = _timeout_hint(timeout_ms)
    return [
        {
            "key": "orphan_chat_messages_session",
            "label": "孤立 chat_messages.session_id",
            "severity": "blocking",
            "sql": f"""SELECT {hint} COUNT(*) AS count_value FROM chat_messages cm
                LEFT JOIN sessions s ON s.id = cm.session_id WHERE s.id IS NULL""",
        },
        {
            "key": "orphan_chat_messages_user",
            "label": "孤立 chat_messages.user_id",
            "severity": "blocking",
            "sql": f"""SELECT {hint} COUNT(*) AS count_value FROM chat_messages cm
                LEFT JOIN users u ON u.id = cm.user_id WHERE u.id IS NULL""",
        },
        {
            "key": "orphan_chat_attachments_message",
            "label": "孤立 chat_attachments.message_id",
            "severity": "blocking",
            "sql": f"""SELECT {hint} COUNT(*) AS count_value FROM chat_attachments ca
                LEFT JOIN chat_messages cm ON cm.id = ca.message_id WHERE cm.id IS NULL""",
        },
        {
            "key": "invalid_chat_attachment_type",
            "label": "非法 chat_attachments.attachment_type",
            "severity": "blocking",
            "sql": f"""SELECT {hint} COUNT(*) AS count_value FROM chat_attachments
                WHERE attachment_type NOT IN (
                    'causal_graph', 'analysis_result', 'file_content', 'other', 'visualization'
                )""",
        },
        {
            "key": "orphan_analysis_jobs_user",
            "label": "孤立 analysis_jobs.user_id",
            "severity": "blocking",
            "sql": f"""SELECT {hint} COUNT(*) AS count_value FROM analysis_jobs aj
                LEFT JOIN users u ON u.id = aj.user_id WHERE u.id IS NULL""",
        },
        {
            "key": "orphan_analysis_jobs_session",
            "label": "孤立 analysis_jobs.session_id",
            "severity": "blocking",
            "sql": f"""SELECT {hint} COUNT(*) AS count_value FROM analysis_jobs aj
                LEFT JOIN sessions s ON s.id = aj.session_id WHERE s.id IS NULL""",
        },
        {
            "key": "orphan_analysis_job_events",
            "label": "孤立 analysis_job_events.job_id",
            "severity": "blocking",
            "sql": f"""SELECT {hint} COUNT(*) AS count_value FROM analysis_job_events aje
                LEFT JOIN analysis_jobs aj ON aj.job_id = aje.job_id WHERE aj.job_id IS NULL""",
        },
        {
            "key": "orphan_checkpoints_thread",
            "label": "孤立 checkpoints.thread_id",
            "severity": "blocking",
            "sql": f"""SELECT {hint} COUNT(*) AS count_value FROM checkpoints cp
                LEFT JOIN sessions s ON s.id = cp.thread_id WHERE s.id IS NULL""",
        },
        {
            "key": "orphan_checkpoint_writes",
            "label": "孤立 checkpoint_writes.checkpoint_id",
            "severity": "blocking",
            "sql": f"""SELECT {hint} COUNT(*) AS count_value FROM checkpoint_writes cw
                LEFT JOIN checkpoints cp
                  ON cp.thread_id = cw.thread_id
                 AND cp.checkpoint_ns = cw.checkpoint_ns
                 AND cp.checkpoint_id = cw.checkpoint_id
                WHERE cp.checkpoint_id IS NULL""",
        },
        {
            "key": "chat_messages_partitions",
            "label": "chat_messages 分区表",
            "severity": "info",
            "sql": f"""SELECT {hint} COUNT(*) AS count_value
                FROM information_schema.partitions
                WHERE table_schema = DATABASE()
                  AND table_name = 'chat_messages'
                  AND partition_name IS NOT NULL""",
        },
    ]


def execute_quick_integrity_checks(
    connection,
    *,
    timeout_ms: int,
    source_role: str = "primary",
    source_alias: str = "primary",
) -> list[dict[str, Any]]:
    """在调用方提供的只读连接上逐项执行快速完整性检查。"""
    cursor = connection.cursor(dictionary=True)
    checks: list[dict[str, Any]] = []
    for definition in _integrity_definitions(timeout_ms):
        observed_at = _observed_at()
        try:
            cursor.execute(definition["sql"])
            row = cursor.fetchone() or {}
            count = int(row.get("count_value") or 0)
            if definition["severity"] == "blocking":
                status = "error" if count > 0 else "healthy"
                warning = "发现阻塞性完整性问题" if count > 0 else None
            else:
                status = "healthy" if count > 0 else "warning"
                warning = None if count > 0 else "未检测到 chat_messages 分区"
            checks.append({
                "key": definition["key"],
                "label": definition["label"],
                "severity": definition["severity"],
                **_result(
                    status,
                    count,
                    source_role=source_role,
                    source_alias=source_alias,
                    warning=warning,
                    observed_at=observed_at,
                ),
            })
        except Exception as exc:
            LOGGER.warning("快速完整性检查失败 [%s]: %s", definition["key"], type(exc).__name__)
            LOGGER.debug("快速完整性检查异常详情 [%s]", definition["key"], exc_info=True)
            checks.append({
                "key": definition["key"],
                "label": definition["label"],
                "severity": definition["severity"],
                **_result(
                    "unknown",
                    None,
                    source_role=source_role,
                    source_alias=source_alias,
                    warning="检查失败（权限不足、查询超时或节点不可用）",
                    observed_at=observed_at,
                ),
            })
    return checks


def get_quick_integrity_report() -> dict[str, Any]:
    """通过主库强一致读执行快速完整性检查并汇总阻塞项。"""
    from app.db import get_read_connection_with_source
    from config.settings import settings

    try:
        connection, source = get_read_connection_with_source(consistency="strong")
        with connection as conn:
            checks = execute_quick_integrity_checks(
                conn,
                timeout_ms=settings.DB_INSPECTION_QUERY_TIMEOUT_MS,
                **source,
            )
    except Exception as exc:
        LOGGER.warning("快速完整性检查无法连接主库: %s", exc, exc_info=True)
        checks = [{
            "key": "integrity_connection",
            "label": "快速完整性检查连接",
            "severity": "blocking",
            **_result(
                "unknown",
                None,
                source_role="primary",
                source_alias="primary",
                warning="无法使用只读账号连接主库",
            ),
        }]

    blocking_count = sum(
        1
        for check in checks
        if check["severity"] == "blocking" and check["status"] == "error"
    )
    blocking_record_count = sum(
        int(check["value"] or 0)
        for check in checks
        if check["severity"] == "blocking" and check["status"] == "error"
    )
    return {
        "mode": "quick",
        "status": _overall_status(checks),
        "observed_at": _observed_at(),
        "blocking_count": blocking_count,
        "blocking_record_count": blocking_record_count,
        "checks": checks,
    }
