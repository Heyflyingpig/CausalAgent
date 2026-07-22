import os
import unittest
from unittest.mock import Mock, patch


TEST_ENV = {
    "SECRET_KEY": "test-secret",
    "API_KEY": "test-api-key",
    "BASE_URL": "https://example.test",
    "MODEL": "test-model",
    "MYSQL_HOST": "test-mysql",
    "MYSQL_USER": "test-user",
    "MYSQL_PASSWORD": "test-password",
    "MYSQL_DATABASE": "test-database",
}
for key, value in TEST_ENV.items():
    os.environ.setdefault(key, value)


from Database.inspection import (
    execute_quick_integrity_checks,
    get_database_overview,
    inspect_slow_queries,
)
from Database.monitoring import get_db_health, get_slow_query_summary
from app.agent.job_service import get_worker_snapshot_report
from app.db import get_read_connection_with_source
from config.settings import settings


def result(status="healthy", value=None, source_alias="primary", warning=None):
    """构造测试使用的标准检查结果。"""
    return {
        "status": status,
        "value": value,
        "observed_at": "2026-07-22T00:00:00.000Z",
        "source_role": "primary" if source_alias == "primary" else "replica",
        "source_alias": source_alias,
        "is_estimate": False,
        "warning": warning,
    }


class IntegrityCursor:
    """逐项返回完整性计数，并可让单项查询失败。"""

    def __init__(self, counts, failing_index=None):
        self.counts = counts
        self.failing_index = failing_index
        self.index = -1

    def execute(self, _sql):
        """前进到下一检查，并在指定位置模拟超时。"""
        self.index += 1
        if self.index == self.failing_index:
            raise TimeoutError("simulated timeout")

    def fetchone(self):
        """返回当前检查的计数。"""
        return {"count_value": self.counts[self.index]}


class IntegrityConnection:
    """为完整性检查提供唯一字典游标。"""

    def __init__(self, cursor):
        self.fake_cursor = cursor

    def cursor(self, dictionary=False):
        """确认调用方申请字典游标并返回替身。"""
        self.dictionary = dictionary
        return self.fake_cursor


class SlowCursor:
    """返回 SHOW 结果，并模拟 performance_schema 无权限。"""

    def __init__(self):
        self.rows = []

    def execute(self, sql, params=None):
        """根据只读语句设置结果或抛出权限异常。"""
        normalized = " ".join(sql.split())
        if normalized.startswith("SHOW GLOBAL STATUS"):
            self.rows = [{"Variable_name": "Slow_queries", "Value": "7"}]
        elif normalized.startswith("SHOW GLOBAL VARIABLES"):
            self.rows = [
                {"Variable_name": "slow_query_log", "Value": "ON"},
                {"Variable_name": "long_query_time", "Value": "2.0"},
            ]
        elif "performance_schema.events_statements_summary_by_digest" in normalized:
            raise PermissionError("performance_schema denied")
        else:
            raise AssertionError(normalized)
        self.params = params

    def fetchall(self):
        """返回当前 SHOW 查询结果。"""
        return self.rows


class ContextConnection:
    """支持 with 语法并返回指定游标的连接替身。"""

    def __init__(self, cursor):
        self.fake_cursor = cursor

    def __enter__(self):
        """返回连接自身。"""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """不吞掉异常。"""
        return False

    def cursor(self, dictionary=False):
        """返回唯一游标。"""
        self.dictionary = dictionary
        return self.fake_cursor


class WorkerCursor:
    """依次返回 worker 聚合计数和活动任务明细。"""

    def __init__(self):
        self.query_index = 0

    def execute(self, _sql):
        """记录当前是聚合查询还是明细查询。"""
        self.query_index += 1

    def fetchone(self):
        """返回包含异常任务的聚合结果。"""
        return {"queued": 2, "running": 1, "stale": 1, "max_attempts_running": 0}

    def fetchall(self):
        """返回一个活动任务。"""
        return [{
            "job_id": "job-1",
            "status": "running",
            "worker_id": "worker-1",
            "heartbeat_at": None,
            "attempt_count": 1,
            "max_attempts": 3,
            "created_at": None,
        }]


class DatabaseInspectionTests(unittest.TestCase):
    """验证只读检查的来源、降级和旧接口兼容行为。"""

    def test_integrity_single_failure_does_not_stop_other_checks(self):
        """单项超时只标记该项未知，其余检查继续返回。"""
        connection = IntegrityConnection(IntegrityCursor([0] * 10, failing_index=4))
        checks = execute_quick_integrity_checks(
            connection,
            timeout_ms=3000,
            source_role="primary",
            source_alias="primary",
        )

        self.assertEqual(len(checks), 10)
        self.assertEqual(checks[4]["status"], "unknown")
        self.assertEqual(checks[5]["status"], "healthy")
        self.assertTrue(all(check["source_alias"] == "primary" for check in checks))
        self.assertTrue(all("observed_at" in check for check in checks))

    def test_read_connection_reports_logical_source_without_hostname(self):
        """强一致和副本读取只返回 primary/replica-N 逻辑别名。"""
        primary_connection = object()
        primary_pool = Mock()
        primary_pool.get_connection.return_value = primary_connection
        with (
            patch.object(settings, "MYSQL_WRITE_HOST", "internal-primary-host"),
            patch.object(settings, "MYSQL_READ_HOSTS", []),
            patch("app.db._get_read_pool", return_value=primary_pool),
        ):
            connection, source = get_read_connection_with_source("strong")

        self.assertIs(connection, primary_connection)
        self.assertEqual(source, {"source_role": "primary", "source_alias": "primary"})
        self.assertNotIn("internal-primary-host", source.values())

        replica_connection = object()
        replica_pool = Mock()
        replica_pool.get_connection.return_value = replica_connection
        with (
            patch.object(settings, "MYSQL_READ_HOSTS", ["internal-replica-host"]),
            patch("app.db.should_use_replica", return_value=True),
            patch("app.db.random.shuffle"),
            patch("app.db._get_read_pool", return_value=replica_pool),
        ):
            connection, source = get_read_connection_with_source("eventual")

        self.assertIs(connection, replica_connection)
        self.assertEqual(source, {"source_role": "replica", "source_alias": "replica-1"})
        self.assertNotIn("internal-replica-host", source.values())

    def test_overview_preserves_partial_results(self):
        """主库区块未知时 revision、从库、连接和容量结果仍被保留。"""
        with (
            patch("Database.inspection.inspect_revision", return_value=result(value={"matches": True})),
            patch(
                "Database.inspection.inspect_primary",
                return_value=result("unknown", warning="主库检查失败"),
            ),
            patch("Database.inspection.inspect_replica", return_value=result(value={"available": True})),
            patch("Database.inspection.inspect_connections", return_value=result(value={"utilization_percent": 2})),
            patch("Database.inspection.inspect_table_capacity", return_value=result(value=[])),
        ):
            overview = get_database_overview()

        self.assertEqual(overview["status"], "warning")
        self.assertEqual(overview["revision"]["status"], "healthy")
        self.assertEqual(overview["primary"]["status"], "unknown")
        self.assertEqual(overview["tables"]["value"], [])

    def test_slow_query_permission_failure_returns_warning_metadata(self):
        """performance_schema 无权限时保留配置和累计计数，不返回 500。"""
        connection = ContextConnection(SlowCursor())
        with patch(
            "app.db.get_read_connection_with_source",
            return_value=(connection, {"source_role": "replica", "source_alias": "replica-1"}),
        ):
            slow = inspect_slow_queries(limit=20)

        self.assertEqual(slow["status"], "warning")
        self.assertEqual(slow["source_alias"], "replica-1")
        self.assertEqual(slow["value"]["Slow_queries"], 7)
        self.assertEqual(slow["value"]["top_statements"], [])
        self.assertIn("performance_schema", slow["warning"])

    def test_legacy_monitoring_fields_are_kept_with_additive_metadata(self):
        """兼容层继续返回旧字段，并追加来源与采集信息。"""
        overview = {
            "status": "healthy",
            "observed_at": "2026-07-22T00:00:00.000Z",
            "connections": result(value={
                "threads_connected": 2,
                "threads_running": 1,
                "max_connections": 100,
                "slow_queries": 3,
            }),
            "replica": result(value={
                "available": True,
                "io_running": "Yes",
                "sql_running": "Yes",
                "lag_seconds": 0,
                "last_io_error": None,
                "last_sql_error": None,
            }, source_alias="replica-1"),
            "tables": result(value=[{"table_name": "users"}], source_alias="replica-1"),
        }
        with patch("Database.monitoring.get_database_overview", return_value=overview):
            health = get_db_health()

        self.assertEqual(health["connections"]["Threads_connected"], 2)
        self.assertEqual(health["slow_queries"], 3)
        self.assertEqual(health["replica"]["Replica_IO_Running"], "Yes")
        self.assertIsInstance(health["tables"], list)
        self.assertIn("sources", health)

        with patch(
            "Database.monitoring.inspect_slow_queries",
            return_value=result(value={
                "Slow_queries": 4,
                "top_statements": [],
                "slow_query_log": "ON",
                "long_query_time": 2.0,
                "limit": 20,
            }),
        ):
            slow = get_slow_query_summary(20)
        self.assertEqual(slow["Slow_queries"], 4)
        self.assertEqual(slow["top_statements"], [])
        self.assertIn("source_alias", slow)

    def test_worker_report_adds_summary_without_changing_job_list(self):
        """worker 报告保留列表明细并追加聚合和来源元数据。"""
        connection = ContextConnection(WorkerCursor())
        with (
            patch(
                "app.agent.job_service.get_read_connection_with_source",
                return_value=(connection, {"source_role": "primary", "source_alias": "primary"}),
            ),
            patch.object(settings, "JOB_STALE_AFTER_SECONDS", 120),
            patch.object(settings, "DB_INSPECTION_QUERY_TIMEOUT_MS", 3000),
        ):
            report = get_worker_snapshot_report()

        self.assertIsInstance(report["jobs"], list)
        self.assertEqual(report["summary"]["queued"], 2)
        self.assertEqual(report["summary"]["stale"], 1)
        self.assertEqual(report["status"], "warning")
        self.assertEqual(report["source_alias"], "primary")


if __name__ == "__main__":
    unittest.main()
