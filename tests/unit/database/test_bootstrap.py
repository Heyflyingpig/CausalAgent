"""统一数据库 bootstrap 编排测试。"""

from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from Database import bootstrap


class BootstrapTests(TestCase):
    """验证 bootstrap 只负责编排既有数据库初始化职责。"""

    def test_run_bootstrap_uses_mysql_then_alembic_then_postgres(self):
        """统一入口必须按依赖顺序执行三个初始化阶段。"""
        events: list[str] = []
        mysql_bootstrap = MagicMock()
        mysql_bootstrap.bootstrap.side_effect = lambda: events.append("mysql") or True

        with (
            patch(
                "Database.bootstrap.create_mysql_bootstrap",
                return_value=mysql_bootstrap,
            ),
            patch(
                "Database.bootstrap.repair_legacy_revision_ids",
                side_effect=lambda connection: events.append("legacy_repair") or [],
            ),
            patch(
                "Database.bootstrap.check_upgrade_compatibility",
                side_effect=lambda mysql_config: events.append("preflight"),
            ),
            patch(
                "Database.bootstrap.upgrade_mysql_schema",
                side_effect=lambda project_root: events.append("alembic"),
            ),
            patch(
                "Database.bootstrap.setup_postgres_checkpoint_schema",
                side_effect=lambda: events.append("postgres"),
            ),
            patch("Database.bootstrap.LOGGER"),
        ):
            bootstrap.run_bootstrap(Path("C:/project"))

        self.assertEqual(events, ["mysql", "legacy_repair", "preflight", "alembic", "postgres"])

    def test_run_bootstrap_stops_before_migration_when_mysql_is_unavailable(self):
        """MySQL 连接检查失败时不能继续执行迁移或 PostgreSQL setup。"""
        mysql_bootstrap = MagicMock()
        mysql_bootstrap.bootstrap.return_value = False

        with (
            patch(
                "Database.bootstrap.create_mysql_bootstrap",
                return_value=mysql_bootstrap,
            ),
            patch("Database.bootstrap.upgrade_mysql_schema") as upgrade_mysql_schema,
            patch(
                "Database.bootstrap.setup_postgres_checkpoint_schema"
            ) as setup_postgres_checkpoint_schema,
            patch("Database.bootstrap.LOGGER"),
        ):
            with self.assertRaisesRegex(RuntimeError, "MySQL 数据库连接检查失败"):
                bootstrap.run_bootstrap()

        upgrade_mysql_schema.assert_not_called()
        setup_postgres_checkpoint_schema.assert_not_called()

    @patch("Database.bootstrap.command.upgrade")
    def test_upgrade_mysql_schema_targets_head(self, upgrade):
        """Alembic 编排必须使用仓库配置并升级到 head。"""
        project_root = Path("C:/project")

        bootstrap.upgrade_mysql_schema(project_root)

        config, revision = upgrade.call_args.args
        self.assertEqual(config.config_file_name, str(project_root / "alembic.ini"))
        self.assertEqual(revision, "head")
