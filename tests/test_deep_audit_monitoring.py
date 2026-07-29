import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch


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


from Database import monitoring


POLICY = {
    "auto_refresh_enabled": True,
    "realtime_interval_seconds": 10,
    "sql_interval_seconds": 60,
    "table_capacity_interval_seconds": 900,
    "slow_query_warning_delta": 1,
    "integrity_enabled": True,
    "integrity_interval_seconds": 86400,
}


class DeepAuditMonitoringTests(unittest.TestCase):
    """验证 deep 审计只由手动请求调度并通过共享快照读取。"""

    def test_deep_audit_is_never_scheduled_periodically(self):
        """即便自动刷新和完整性定时审计已开启，deep 仍不得自动到期。"""
        self.assertFalse(monitoring._scheduled("deep_audit", POLICY))
        self.assertFalse(
            monitoring._record_is_due(
                "deep_audit",
                {
                    "observed_at": None,
                    "refresh_requested_at": None,
                    "database_now": datetime.now(timezone.utc),
                },
                policy=POLICY,
            )
        )

    def test_manual_request_makes_deep_audit_due(self):
        """未完成的 refresh_requested_at 必须让 deep 被 monitor 领取。"""
        self.assertTrue(
            monitoring._record_is_due(
                "deep_audit",
                {
                    "observed_at": datetime(2026, 7, 26, 11, 0, 0),
                    "refresh_requested_at": datetime(2026, 7, 26, 12, 0, 0),
                    "database_now": datetime(2026, 7, 26, 12, 0, 1),
                },
                policy=POLICY,
            )
        )

    def test_deep_collector_is_loaded_only_for_deep_key(self):
        """deep 快照采集必须委托独立审计实现并保持手动语义。"""
        report = {
            "mode": "deep",
            "status": "healthy",
            "auto_scheduled": False,
            "checks": [],
        }
        with patch("Database.deep_audit.get_deep_audit_report", return_value=report) as audit:
            result = monitoring._collect_payload(
                "deep_audit",
                previous=None,
                policy=POLICY,
            )

        self.assertEqual(result, report)
        audit.assert_called_once_with()

    def test_reading_deep_snapshot_never_collects_live_data(self):
        """GET 路径只解析数据库中的最近共享快照，不得现场审计。"""
        with (
            patch(
                "Database.monitoring._read_snapshot_records",
                return_value={
                    "deep_audit": {
                        "snapshot_key": "deep_audit",
                        "payload_json": {
                            "mode": "deep",
                            "status": "healthy",
                            "checks": [{"key": "revision", "status": "healthy"}],
                        },
                        "observed_at": datetime(2026, 7, 26, 12, 0, 0),
                        "refresh_requested_at": None,
                    }
                },
            ),
            patch("Database.monitoring._collect_payload") as collector,
        ):
            result = monitoring.get_deep_audit_snapshot()

        self.assertEqual(result["mode"], "deep")
        self.assertFalse(result["scheduled"])
        self.assertEqual(result["checks"][0]["key"], "revision")
        collector.assert_not_called()


if __name__ == "__main__":
    unittest.main()
