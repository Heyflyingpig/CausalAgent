import subprocess
import unittest
from pathlib import Path


class AdminFrontendDeploymentTests(unittest.TestCase):
    """静态验证管理员 Vue 构建、托管和无 Node 运行时边界。"""

    def test_dockerfile_uses_node_builder_and_python_final_stage(self):
        """Node 24 只用于前端构建，最终阶段复制产物并运行 Python。"""
        text = Path("Dockerfile").read_text(encoding="utf-8")

        self.assertIn("FROM node:24-alpine AS admin-builder", text)
        self.assertIn("RUN npm ci", text)
        self.assertIn("RUN npm run build", text)
        self.assertIn("FROM python:3.11-slim AS runtime", text)
        self.assertIn(
            "COPY --from=admin-builder /frontend/dist /opt/causalagent-admin",
            text,
        )
        self.assertIn(
            "ENV ADMIN_FRONTEND_DIST_DIR=/opt/causalagent-admin",
            text,
        )
        final_stage = text.split("FROM python:3.11-slim AS runtime", 1)[1]
        self.assertNotIn("npm ", final_stage)
        self.assertNotIn("vite", final_stage.lower())
        self.assertIn("gunicorn", final_stage)

    def test_admin_production_build_is_present_and_not_gitignored(self):
        """管理员生产入口必须存在，且不能再被根 Git 忽略规则排除。"""
        index_path = Path("admin-frontend/dist/index.html")

        self.assertTrue(index_path.is_file())
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", str(index_path)],
            check=False,
        )
        self.assertEqual(
            result.returncode,
            1,
            "admin-frontend/dist/index.html must be tracked as a release artifact",
        )

    def test_compose_files_add_no_node_service_or_port(self):
        """各套 Compose 不得启动 Vite/Node 服务或开放 5173。"""
        for filename in (
            "docker-compose.yml",
            "docker-compose.prod.yml",
            "docker-compose.test.yml",
            "docker-compose.admin-e2e.yml",
        ):
            with self.subTest(filename=filename):
                text = Path(filename).read_text(encoding="utf-8")
                self.assertNotIn("5173:", text)
                self.assertNotIn("command: npm", text)
                self.assertNotIn("command: vite", text)

    def test_vite_base_and_flask_dist_path_match(self):
        """Vite 产物 URL、Flask 静态路由和镜像目录必须一致。"""
        vite = Path("admin-frontend/vite.config.ts").read_text(encoding="utf-8")
        routes = Path("app/admin/routes.py").read_text(encoding="utf-8")
        settings = Path("config/settings.py").read_text(encoding="utf-8")

        self.assertIn("base: '/admin/'", vite)
        self.assertIn('@admin_page_bp.route("/assets/<path:filename>")', routes)
        self.assertIn("ADMIN_FRONTEND_DIST_DIR", routes)
        self.assertIn("ADMIN_FRONTEND_DIST_DIR", settings)

    def test_runtime_routes_do_not_reference_legacy_admin_files(self):
        """生产路由必须只返回 Vue index，不保留 legacy 路由或旧文件引用。"""
        routes = Path("app/admin/routes.py").read_text(encoding="utf-8")

        self.assertNotIn("legacy", routes.lower())
        self.assertNotIn("db_admin.html", routes)
        self.assertNotIn("db_admin.css", routes)
        self.assertNotIn("db_admin.js", routes)

    def test_read_account_has_only_digest_table_monitoring_grant(self):
        """主库初始化只给读账号增加 SQL digest 表级读取，不得授予全局 SELECT。"""
        script = Path(
            "Database/mysql/init/primary/01-create-replication-user.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "GRANT SELECT ON performance_schema.events_statements_summary_by_digest "
            "TO '${APP_READ_USER}'@'%';",
            script,
        )
        self.assertNotIn("GRANT SELECT ON performance_schema.*", script)
        self.assertNotIn("GRANT SELECT ON *.* TO '${APP_READ_USER}'", script)


if __name__ == "__main__":
    unittest.main()
