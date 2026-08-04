import unittest
from contextlib import contextmanager
from unittest.mock import patch

from Database.checkpoint_inspection import (
    EXPECTED_TABLE_COLUMNS,
    _unknown_quick_checks,
    inspect_checkpoint_quick,
)


class CheckpointCursor:
    """为 PostgreSQL quick 检查提供固定的只读查询结果。"""

    def __init__(self, tables):
        self.tables = tables
        self.statement_index = -1

    def __enter__(self):
        """返回游标替身。"""
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        """结束游标上下文。"""
        return False

    def execute(self, _statement, _params=None):
        """记录当前查询阶段。"""
        self.statement_index += 1

    def fetchone(self):
        """返回连接或 migration 版本查询结果。"""
        if self.statement_index == 0:
            return {"connected": 1}
        return {"v": 8}

    def fetchall(self):
        """返回完整的官方 checkpoint 表集合。"""
        return [{"table_name": table_name} for table_name in self.tables]


class CheckpointConnection:
    """提供 PostgreSQL quick 检查所需的上下文游标。"""

    def __init__(self, cursor):
        self.cursor_instance = cursor

    def cursor(self):
        """返回可进入上下文的游标替身。"""
        return self.cursor_instance


class CheckpointInspectionTests(unittest.TestCase):
    """验证 PostgreSQL checkpoint Quick 检查的说明契约。"""

    def test_unknown_checks_keep_purpose_and_failure_reason(self):
        """连接不可用时三项检查仍保留检查目的和统一原因。"""
        checks = _unknown_quick_checks()

        self.assertEqual(len(checks), 3)
        self.assertTrue(all(check["description"] for check in checks))
        self.assertTrue(all(check["warning"] == "PostgreSQL checkpoint 只读检查不可用" for check in checks))

    def test_healthy_checks_include_purpose(self):
        """连接、官方表集合和 migration 版本正常时均返回说明。"""
        connection = CheckpointConnection(
            CheckpointCursor(EXPECTED_TABLE_COLUMNS.keys())
        )

        @contextmanager
        def fake_read_connection(*, timeout_ms):
            """提供不触碰真实数据库的只读连接。"""
            del timeout_ms
            yield connection

        with (
            patch(
                "Database.checkpoint_inspection.checkpoint_read_connection",
                side_effect=fake_read_connection,
            ),
            patch(
                "Database.checkpoint_inspection._expected_migration_version",
                return_value=8,
            ),
        ):
            checks = inspect_checkpoint_quick(timeout_ms=3000)

        self.assertEqual([check["status"] for check in checks], ["healthy"] * 3)
        self.assertTrue(all(check["description"] for check in checks))
        self.assertIn("四张表", checks[1]["description"])
        self.assertIn("setup 版本", checks[2]["description"])


if __name__ == "__main__":
    unittest.main()
