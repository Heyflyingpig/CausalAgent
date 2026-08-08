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


class DatabaseMonitorSettingsMigrationTests(unittest.TestCase):
    """静态验证在线配置与管理员审计 migration。"""

    def test_settings_migration_extends_snapshot_head_and_seeds_singleton(self):
        """新 revision 必须承接快照 head 并创建全空覆盖单例。"""
        path = Path(
            "Database/migrations/versions/c2d3e4f5a6b7_add_monitor_settings_and_admin_audit.py"
        )
        text = path.read_text(encoding="utf-8")

        self.assertIn('revision: str = "c2d3e4f5a6b7"', text)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"', text)
        self.assertIn("CREATE TABLE database_monitor_settings", text)
        self.assertIn("INSERT INTO database_monitor_settings (id)", text)
        self.assertIn("VALUES (1)", text)
        self.assertIn("realtime_interval_seconds BETWEEN 5 AND 10", text)
        self.assertIn("sql_interval_seconds BETWEEN 30 AND 60", text)
        self.assertIn("table_capacity_interval_seconds BETWEEN 300 AND 900", text)
        self.assertIn("integrity_interval_seconds >= 3600", text)

    def test_audit_survives_user_deletion_and_keeps_request_id(self):
        """用户删除应保留审计快照，并支持 request ID 检索。"""
        path = Path(
            "Database/migrations/versions/c2d3e4f5a6b7_add_monitor_settings_and_admin_audit.py"
        )
        text = path.read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE admin_audit_events", text)
        self.assertIn("actor_username VARCHAR(255) NOT NULL", text)
        self.assertIn("ON DELETE SET NULL", text)
        self.assertIn("request_id VARCHAR(64) NOT NULL", text)
        self.assertIn("CHECK (result IN ('success', 'rejected', 'failed'))", text)
        self.assertIn("idx_admin_audit_request", text)

    def test_readiness_requires_both_new_tables(self):
        """Web、worker 与 monitor 启动检查必须发现未升级结构。"""
        text = Path("app/db.py").read_text(encoding="utf-8")

        self.assertIn('"database_monitor_settings"', text)
        self.assertIn('"admin_audit_events"', text)


class AdminReadIndexMigrationTests(unittest.TestCase):
    """静态验证 3.1 只读后台索引 migration 的链路与最小回滚范围。"""

    def test_read_index_migration_extends_current_head(self):
        """3.1 revision 必须直接承接监控配置与审计表 migration。"""
        path = Path(
            "Database/migrations/versions/d3e4f5a6b7c8_add_admin_read_indexes.py"
        )
        text = path.read_text(encoding="utf-8")

        self.assertIn('revision: str = "d3e4f5a6b7c8"', text)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "c2d3e4f5a6b7"', text)

    def test_read_index_migration_contains_all_bounded_query_indexes(self):
        """列表页需要的五组筛选/排序索引必须一次性存在。"""
        text = Path(
            "Database/migrations/versions/d3e4f5a6b7c8_add_admin_read_indexes.py"
        ).read_text(encoding="utf-8")

        for index_name in (
            "idx_users_admin_role_active",
            "idx_sessions_admin_activity",
            "idx_analysis_jobs_admin_created",
            "idx_uploaded_files_admin_uploaded",
            "idx_admin_audit_target_created",
        ):
            self.assertIn(index_name, text)

    def test_downgrade_only_drops_new_indexes(self):
        """回滚只能移除本 revision 新增的索引，不得删除业务表或字段。"""
        text = Path(
            "Database/migrations/versions/d3e4f5a6b7c8_add_admin_read_indexes.py"
        ).read_text(encoding="utf-8")

        self.assertIn("DROP INDEX idx_users_admin_role_active", text)
        self.assertIn("DROP INDEX idx_admin_audit_target_created", text)
        self.assertNotIn("DROP TABLE", text)
        self.assertNotIn("DROP COLUMN", text)


class AgentJobIdempotencyMigrationTests(unittest.TestCase):
    """静态验证分析任务请求幂等 migration 和启动检查。"""

    def test_idempotency_migration_extends_postgres_checkpoint_head(self):
        """请求幂等 revision 必须承接当前合并后的 migration head。"""
        path = Path(
            "Database/migrations/versions/f9a0b1c2d3e4_add_agent_job_idempotency.py"
        )
        text = path.read_text(encoding="utf-8")

        self.assertIn('revision: str = "f9a0b1c2d3e4"', text)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "f8b9c0d1e2f3"', text)
        self.assertIn("ADD COLUMN idempotency_key VARCHAR(128)", text)
        self.assertIn("ADD COLUMN request_fingerprint CHAR(64)", text)
        self.assertIn("uq_analysis_jobs_user_idempotency", text)

    def test_readiness_and_deep_audit_require_idempotency_schema(self):
        """应用启动和 deep audit 都必须识别请求幂等结构缺失。"""
        db_text = Path("app/db.py").read_text(encoding="utf-8")
        audit_text = Path("Database/deep_audit.py").read_text(encoding="utf-8")

        self.assertIn("table_name = 'analysis_jobs'", db_text)
        self.assertIn("'idempotency_key', 'request_fingerprint', 'lease_epoch'", db_text)
        self.assertIn("uq_analysis_jobs_user_idempotency", db_text)
        self.assertIn('"idempotency_key"', audit_text)
        self.assertIn('"request_fingerprint"', audit_text)
        self.assertIn('"uq_analysis_jobs_user_idempotency"', audit_text)


class FileLibraryAndJobRecoveryMigrationTests(unittest.TestCase):
    """静态验证测试库文件库替换、Job 输入账本和回滚边界。"""

    PATH = Path(
        "Database/migrations/versions/a1b2c3d4e5f6_add_file_library_and_job_recovery.py"
    )

    def test_migration_extends_current_head_and_replaces_legacy_files_directly(self):
        """新 revision 必须直接删除旧文件表，不读取或回填旧数据。"""
        text = self.PATH.read_text(encoding="utf-8")

        self.assertIn('revision: str = "a1b2c3d4e5f6"', text)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "f9a0b1c2d3e4"', text)
        self.assertIn('op.execute("DROP TABLE IF EXISTS uploaded_files")', text)
        self.assertIn("CREATE TABLE file_objects", text)
        self.assertIn("CREATE TABLE user_files", text)
        self.assertNotIn("INSERT INTO file_objects", text)
        self.assertNotIn("INSERT INTO user_files", text)
        self.assertNotIn("INSERT INTO uploaded_files", text)
        self.assertNotIn("拒绝迁移", text)

    def test_migration_adds_frozen_inputs_and_recovery_schema(self):
        """升级必须覆盖可恢复状态、冻结文件快照和用户输入账本。"""
        text = self.PATH.read_text(encoding="utf-8")

        for fragment in (
            "waiting_input",
            "lease_epoch",
            "recovery_count",
            "resume_count",
            "input_user_file_id",
            "input_object_id",
            "current_question_id",
            "analysis_job_inputs",
            "uq_analysis_job_inputs_sequence",
            "uq_analysis_job_inputs_idempotency",
            "event_key",
            "source_event_id",
        ):
            self.assertIn(fragment, text)

    def test_downgrade_restores_empty_legacy_table_without_old_partition_layout(self):
        """回滚只恢复空旧文件表，并保持当前 head 的非分区聊天表结构。"""
        text = self.PATH.read_text(encoding="utf-8")
        downgrade = text.split("def downgrade()", 1)[1]

        self.assertIn("CREATE TABLE uploaded_files", downgrade)
        self.assertNotIn("INSERT INTO uploaded_files", downgrade)
        self.assertNotIn("PARTITION BY RANGE", downgrade)
        self.assertNotIn("REMOVE PARTITIONING", text)


if __name__ == "__main__":
    unittest.main()
