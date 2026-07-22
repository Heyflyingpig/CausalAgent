import unittest
from pathlib import Path


MIGRATION_PATH = Path(
    "Database/migrations/versions/a8b9c0d1e2f3_add_user_role.py"
)


class UserRoleMigrationTests(unittest.TestCase):
    """静态验证用户角色 migration 的链路与最小结构。"""

    def test_role_migration_is_appended_to_current_head(self):
        """新 revision 必须直接承接 analysis jobs migration。"""
        text = MIGRATION_PATH.read_text(encoding="utf-8")
        self.assertIn('revision: str = "a8b9c0d1e2f3"', text)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "e7a9b2c3d4f5"', text)

    def test_role_migration_uses_two_non_null_roles_with_user_default(self):
        """角色字段只能包含 user/admin，且历史用户默认保持 user。"""
        text = MIGRATION_PATH.read_text(encoding="utf-8")
        self.assertIn("ENUM('user', 'admin') NOT NULL DEFAULT 'user'", text)
        self.assertNotIn("super_admin", text)

    def test_downgrade_only_drops_role_column(self):
        """回滚不得修改或删除 users 表的其他结构。"""
        text = MIGRATION_PATH.read_text(encoding="utf-8")
        self.assertIn('op.execute("ALTER TABLE users DROP COLUMN role")', text)
        self.assertNotIn("DROP TABLE users", text)

    def test_readiness_checks_role_column(self):
        """应用启动检查必须发现未执行角色 migration 的数据库。"""
        text = Path("app/db.py").read_text(encoding="utf-8")
        self.assertIn("column_name = 'role'", text)
        self.assertIn("数据库关键字段缺失: users.role", text)


class DatabaseMonitorSnapshotMigrationTests(unittest.TestCase):
    """静态验证共享监控快照 migration 及启动就绪检查。"""

    def test_snapshot_migration_extends_role_head_and_seeds_all_layers(self):
        """快照 revision 必须承接当前 head，并预建四个分层快照键。"""
        path = Path(
            "Database/migrations/versions/b1c2d3e4f5a6_add_database_monitor_snapshots.py"
        )
        text = path.read_text(encoding="utf-8")

        self.assertIn('revision: str = "b1c2d3e4f5a6"', text)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"', text)
        self.assertIn("CREATE TABLE database_monitor_snapshots", text)
        for snapshot_key in ("realtime", "sql_performance", "capacity", "integrity"):
            self.assertIn(f"'{snapshot_key}'", text)

    def test_snapshot_migration_supports_payload_observation_and_refresh_request(self):
        """共享表同时保存负载、采集时间和待处理手动刷新时间。"""
        path = Path(
            "Database/migrations/versions/b1c2d3e4f5a6_add_database_monitor_snapshots.py"
        )
        text = path.read_text(encoding="utf-8")

        self.assertIn("payload_json JSON", text)
        self.assertIn("observed_at DATETIME(6)", text)
        self.assertIn("refresh_requested_at DATETIME(6)", text)
        self.assertIn("DROP TABLE IF EXISTS database_monitor_snapshots", text)

    def test_readiness_requires_snapshot_table(self):
        """应用和 monitor 启动前都能发现未执行快照 migration 的数据库。"""
        text = Path("app/db.py").read_text(encoding="utf-8")
        self.assertIn('"database_monitor_snapshots"', text)


if __name__ == "__main__":
    unittest.main()
