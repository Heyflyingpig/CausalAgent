"""兼容旧管理接口的数据库只读监控适配层。"""

from __future__ import annotations

from typing import Any

from Database.inspection import get_database_overview, inspect_slow_queries


def _legacy_replica_value(replica: dict[str, Any]) -> dict[str, Any] | None:
    """把标准从库检查结果映射回旧接口字段。"""
    value = replica.get("value")
    if not value or not value.get("available"):
        return None
    return {
        "Replica_IO_Running": value.get("io_running"),
        "Replica_SQL_Running": value.get("sql_running"),
        "Seconds_Behind_Source": value.get("lag_seconds"),
        "Last_IO_Error": value.get("last_io_error"),
        "Last_SQL_Error": value.get("last_sql_error"),
    }


def get_db_health() -> dict[str, Any]:
    """返回兼容旧字段并附带来源元数据的数据库健康摘要。"""
    overview = get_database_overview()
    connection_value = overview["connections"].get("value") or {}
    table_value = overview["tables"].get("value") or []
    return {
        "connections": {
            "Threads_connected": connection_value.get("threads_connected"),
            "Threads_running": connection_value.get("threads_running"),
            "max_connections": connection_value.get("max_connections"),
        },
        "slow_queries": connection_value.get("slow_queries"),
        "replica": _legacy_replica_value(overview["replica"]),
        "tables": table_value,
        "status": overview["status"],
        "observed_at": overview["observed_at"],
        "sources": {
            key: {
                "source_role": overview[key]["source_role"],
                "source_alias": overview[key]["source_alias"],
                "observed_at": overview[key]["observed_at"],
                "is_estimate": overview[key]["is_estimate"],
                "warning": overview[key]["warning"],
            }
            for key in ("connections", "replica", "tables")
        },
    }


def get_slow_query_summary(limit: int = 20) -> dict[str, Any]:
    """返回兼容旧字段并附带节点来源、配置和状态的慢查询摘要。"""
    result = inspect_slow_queries(limit=limit)
    value = result.get("value") or {}
    return {
        "Slow_queries": value.get("Slow_queries"),
        "top_statements": value.get("top_statements") or [],
        "slow_query_log": value.get("slow_query_log"),
        "long_query_time": value.get("long_query_time"),
        "limit": value.get("limit", limit),
        "status": result["status"],
        "observed_at": result["observed_at"],
        "source_role": result["source_role"],
        "source_alias": result["source_alias"],
        "is_estimate": result["is_estimate"],
        "warning": result["warning"],
    }
