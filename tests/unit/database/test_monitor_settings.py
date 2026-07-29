import os
import unittest
from copy import deepcopy
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


from Database import monitor_settings
from Database.monitor_settings import (
    FIELD_NAMES,
    MonitorSettingsValidationError,
    MonitorSettingsVersionConflict,
    get_monitor_settings,
    reset_monitor_settings,
    save_monitor_settings,
    validate_monitor_overrides,
)


BASE_OVERRIDES = {
    "auto_refresh_enabled": None,
    "realtime_interval_seconds": None,
    "sql_interval_seconds": None,
    "table_capacity_interval_seconds": None,
    "slow_query_warning_delta": None,
    "integrity_enabled": None,
    "integrity_interval_seconds": None,
}


def settings_row(**updates):
    """构造数据库监控配置单例行。"""
    row = {
        "id": 1,
        **BASE_OVERRIDES,
        "version": 1,
        "updated_by_user_id": None,
        "updated_by_username": None,
        "updated_at": None,
    }
    row.update(updates)
    return row


class WriteCursor:
    """模拟配置行锁、更新和审计写入游标。"""

    def __init__(self, row):
        self.row = deepcopy(row)
        self.rowcount = 0
        self.calls = []

    def execute(self, sql, params=None):
        """记录 SQL 并模拟成功更新的影响行数。"""
        self.calls.append((" ".join(sql.split()), params))
        if sql.lstrip().upper().startswith("UPDATE DATABASE_MONITOR_SETTINGS"):
            self.rowcount = 1

    def fetchone(self):
        """返回锁定的当前配置行。"""
        return deepcopy(self.row)


class WriteConnection:
    """提供可断言提交、回滚和游标调用的连接替身。"""

    def __init__(self, row):
        self.cursor_instance = WriteCursor(row)
        self.commit_count = 0
        self.rollback_count = 0

    def __enter__(self):
        """进入连接上下文。"""
        return self

    def __exit__(self, *_args):
        """退出连接上下文。"""
        return False

    def cursor(self, dictionary=False):
        """返回同一个游标，覆盖字典和普通游标调用。"""
        self.dictionary = dictionary
        return self.cursor_instance

    def commit(self):
        """记录事务提交。"""
        self.commit_count += 1

    def rollback(self):
        """记录事务回滚。"""
        self.rollback_count += 1


class MonitorSettingsValidationTests(unittest.TestCase):
    """验证七项在线覆盖的完整快照和边界契约。"""

    def test_accepts_nulls_and_all_documented_boundaries(self):
        """全部可空且数值最小/最大边界应被接受。"""
        minimums = {
            **BASE_OVERRIDES,
            "auto_refresh_enabled": False,
            "realtime_interval_seconds": 5,
            "sql_interval_seconds": 30,
            "table_capacity_interval_seconds": 300,
            "slow_query_warning_delta": 1,
            "integrity_enabled": True,
            "integrity_interval_seconds": 3600,
        }
        maximums = {
            **minimums,
            "realtime_interval_seconds": 10,
            "sql_interval_seconds": 60,
            "table_capacity_interval_seconds": 900,
        }

        self.assertEqual(validate_monitor_overrides(BASE_OVERRIDES), BASE_OVERRIDES)
        self.assertEqual(validate_monitor_overrides(minimums), minimums)
        self.assertEqual(validate_monitor_overrides(maximums), maximums)

    def test_rejects_partial_unknown_wrong_type_and_out_of_range_values(self):
        """服务端必须拒绝部分快照、未知字段、宽松布尔和越界数值。"""
        invalid_cases = (
            ({}, "overrides"),
            ({**BASE_OVERRIDES, "future": 1}, "unknown_fields"),
            ({**BASE_OVERRIDES, "auto_refresh_enabled": 1}, "auto_refresh_enabled"),
            ({**BASE_OVERRIDES, "realtime_interval_seconds": 4}, "realtime_interval_seconds"),
            ({**BASE_OVERRIDES, "sql_interval_seconds": 61}, "sql_interval_seconds"),
            ({**BASE_OVERRIDES, "table_capacity_interval_seconds": 299}, "table_capacity_interval_seconds"),
            ({**BASE_OVERRIDES, "slow_query_warning_delta": 0}, "slow_query_warning_delta"),
            ({**BASE_OVERRIDES, "integrity_interval_seconds": 3599}, "integrity_interval_seconds"),
        )

        for overrides, expected_field in invalid_cases:
            with self.subTest(field=expected_field):
                with self.assertRaises(MonitorSettingsValidationError) as caught:
                    validate_monitor_overrides(overrides)
                self.assertIn(expected_field, caught.exception.errors)


class MonitorSettingsResolutionTests(unittest.TestCase):
    """验证数据库优先级、五秒缓存与安全降级。"""

    def setUp(self):
        """隔离每个测试的进程级配置缓存。"""
        monitor_settings.invalidate_monitor_settings_cache()
        monitor_settings._last_good_payload = None

    def tearDown(self):
        """清理进程级配置缓存。"""
        monitor_settings.invalidate_monitor_settings_cache()
        monitor_settings._last_good_payload = None

    def test_database_override_wins_and_sources_are_per_field(self):
        """非空数据库值覆盖环境基础值，空值继续继承。"""
        row = settings_row(
            realtime_interval_seconds=5,
            integrity_enabled=1,
            updated_by_user_id=8,
            updated_by_username="root-admin",
        )
        with patch("Database.monitor_settings._read_settings_row", return_value=row):
            payload = get_monitor_settings(force_refresh=True)

        self.assertEqual(payload["effective"]["realtime_interval_seconds"], 5)
        self.assertTrue(payload["effective"]["integrity_enabled"])
        self.assertEqual(payload["sources"]["realtime_interval_seconds"], "database")
        self.assertEqual(payload["sources"]["integrity_enabled"], "database")
        self.assertNotEqual(payload["sources"]["sql_interval_seconds"], "database")
        self.assertEqual(payload["updated_by"]["username"], "root-admin")

    def test_cache_is_reused_for_five_seconds_then_refreshed(self):
        """同一进程五秒内只读一次，过期后读取新版本。"""
        rows = [settings_row(version=1), settings_row(version=2)]
        with (
            patch("Database.monitor_settings._read_settings_row", side_effect=rows) as read_row,
            patch("Database.monitor_settings.time.monotonic", side_effect=[100.0, 104.9, 105.1]),
        ):
            first = get_monitor_settings()
            cached = get_monitor_settings()
            refreshed = get_monitor_settings()

        self.assertEqual(first["version"], 1)
        self.assertEqual(cached["version"], 1)
        self.assertEqual(refreshed["version"], 2)
        self.assertEqual(read_row.call_count, 2)

    def test_read_failure_uses_last_good_payload_before_environment_fallback(self):
        """读取失败时保留最后有效值并标记降级，不中断调用方。"""
        with patch(
            "Database.monitor_settings._read_settings_row",
            side_effect=[settings_row(realtime_interval_seconds=5), RuntimeError("offline")],
        ):
            current = get_monitor_settings(force_refresh=True)
            degraded = get_monitor_settings(force_refresh=True)

        self.assertEqual(current["state"], "current")
        self.assertEqual(degraded["state"], "degraded")
        self.assertEqual(degraded["effective"], current["effective"])
        self.assertIsNotNone(degraded["warning"])

    def test_first_read_failure_returns_environment_default_shape(self):
        """没有最后有效值时仍返回完整七项基础配置。"""
        with patch(
            "Database.monitor_settings._read_settings_row",
            side_effect=RuntimeError("missing table"),
        ):
            payload = get_monitor_settings(force_refresh=True)

        self.assertEqual(payload["state"], "degraded")
        self.assertIsNone(payload["version"])
        self.assertEqual(set(payload["effective"]), set(FIELD_NAMES))


class MonitorSettingsTransactionTests(unittest.TestCase):
    """验证乐观锁、成功审计、拒绝审计和重置事务。"""

    def test_save_updates_and_audits_in_one_commit(self):
        """成功保存应更新版本字段并在同一连接写入成功审计。"""
        connection = WriteConnection(settings_row(version=3))
        resolved = {"version": 4, "effective": {}, "state": "current"}
        with (
            patch("Database.monitor_settings.get_write_connection", return_value=connection),
            patch("Database.monitor_settings.insert_admin_audit_event") as insert_audit,
            patch("Database.monitor_settings.get_monitor_settings", return_value=resolved),
        ):
            result = save_monitor_settings(
                version=3,
                overrides={**BASE_OVERRIDES, "realtime_interval_seconds": 5},
                actor={"id": 7, "username": "admin"},
                request_id="req-save",
            )

        self.assertEqual(result, resolved)
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        self.assertTrue(any(call[0].startswith("UPDATE database_monitor_settings") for call in connection.cursor_instance.calls))
        self.assertEqual(insert_audit.call_args.kwargs["result"], "success")
        self.assertEqual(insert_audit.call_args.kwargs["request_id"], "req-save")

    def test_version_conflict_rolls_back_and_records_rejection(self):
        """过期版本不得更新，并记录可关联的 rejected 审计。"""
        connection = WriteConnection(settings_row(version=4))
        current = {"version": 4, "effective": {}, "state": "current"}
        with (
            patch("Database.monitor_settings.get_write_connection", return_value=connection),
            patch("Database.monitor_settings.get_monitor_settings", return_value=current),
            patch("Database.monitor_settings.record_admin_audit_event") as record_audit,
        ):
            with self.assertRaises(MonitorSettingsVersionConflict) as caught:
                save_monitor_settings(
                    version=3,
                    overrides=BASE_OVERRIDES,
                    actor={"id": 7, "username": "admin"},
                    request_id="req-conflict",
                )

        self.assertEqual(caught.exception.current, current)
        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.rollback_count, 1)
        self.assertEqual(record_audit.call_args.kwargs["result"], "rejected")
        self.assertEqual(record_audit.call_args.kwargs["error_code"], "version_conflict")

    def test_validation_rejection_is_audited_without_opening_update_transaction(self):
        """字段错误应在写配置事务前拒绝并留下 rejected 审计。"""
        with (
            patch("Database.monitor_settings.get_write_connection") as get_write,
            patch("Database.monitor_settings.record_admin_audit_event") as record_audit,
        ):
            with self.assertRaises(MonitorSettingsValidationError):
                save_monitor_settings(
                    version=1,
                    overrides={},
                    actor={"id": 7, "username": "admin"},
                    request_id="req-invalid",
                )

        get_write.assert_not_called()
        self.assertEqual(record_audit.call_args.kwargs["result"], "rejected")
        self.assertEqual(record_audit.call_args.kwargs["error_code"], "validation_error")

    def test_reset_submits_seven_null_overrides(self):
        """重置复用保存服务，并把全部数据库覆盖恢复为 NULL。"""
        with patch("Database.monitor_settings.save_monitor_settings", return_value={"version": 2}) as save:
            result = reset_monitor_settings(
                version=1,
                actor={"id": 7, "username": "admin"},
                request_id="req-reset",
            )

        self.assertEqual(result["version"], 2)
        self.assertEqual(save.call_args.kwargs["overrides"], BASE_OVERRIDES)
        self.assertEqual(save.call_args.kwargs["action"], "db_monitor_settings.reset")


if __name__ == "__main__":
    unittest.main()
