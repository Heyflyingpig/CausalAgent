import os
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from flask import Flask


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


from app.admin.routes import admin_bp, admin_page_bp


ADMIN_GET_ENDPOINTS = (
    "/api/admin/db/health",
    "/api/admin/db/overview",
    "/api/admin/db/dashboard",
    "/api/admin/db/integrity?mode=quick",
    "/api/admin/db/slow-queries?limit=20",
    "/api/admin/jobs/workers",
)
ADMIN_POST_ENDPOINTS = (
    "/api/admin/db/refresh",
    "/api/admin/db/integrity/run",
)
ADMIN_PAGE = "/admin/database"


def build_app():
    """构建只注册管理接口和后台页面蓝图的最小测试应用。"""
    app = Flask(__name__)
    app.secret_key = "admin-test-secret"
    app.register_blueprint(admin_bp)
    app.register_blueprint(admin_page_bp)
    return app


def admin_service_patches():
    """返回所有管理员只读服务的稳定测试替身。"""
    return (
        patch("app.admin.routes.get_db_health", return_value={"connections": {}, "tables": []}),
        patch("app.admin.routes.get_database_overview_snapshot", return_value={"status": "healthy"}),
        patch(
            "app.admin.routes.get_dashboard_snapshots",
            return_value={
                "realtime": {},
                "sql_performance": {},
                "capacity": {},
                "integrity": {},
                "refresh_policy": {},
            },
        ),
        patch("app.admin.routes.get_integrity_snapshot", return_value={"checks": []}),
        patch(
            "app.admin.routes.get_sql_performance_snapshot",
            return_value={"Slow_queries": 0, "top_statements": []},
        ),
        patch(
            "app.admin.routes.get_worker_snapshot_from_cache",
            return_value={
                "jobs": [],
                "summary": {"queued": 0, "running": 0, "stale": 0, "max_attempts_running": 0},
                "status": "healthy",
                "observed_at": "2026-07-22T00:00:00.000Z",
                "source_role": "primary",
                "source_alias": "primary",
                "is_estimate": False,
                "warning": None,
            },
        ),
        patch(
            "app.admin.routes.request_snapshot_refresh",
            return_value={
                "groups": ["realtime"],
                "requested_at": "2026-07-22T00:00:00.000Z",
            },
        ),
    )


class AdminAuthorizationTests(unittest.TestCase):
    """验证全部管理接口和页面共用同一个实时管理员授权边界。"""

    def test_missing_session_returns_401_for_all_admin_surfaces(self):
        """无有效会话时所有管理接口和后台页面都应返回 401。"""
        app = build_app()
        with patch("app.auth.authorization.get_current_session_user", return_value=None):
            with app.test_client() as client:
                for endpoint in (*ADMIN_GET_ENDPOINTS, ADMIN_PAGE):
                    response = client.get(endpoint)
                    self.assertEqual(response.status_code, 401, endpoint)
                    self.assertEqual(
                        response.get_json(),
                        {"success": False, "error": "用户未登录或会话已过期"},
                    )
                for endpoint in ADMIN_POST_ENDPOINTS:
                    response = client.post(endpoint)
                    self.assertEqual(response.status_code, 401, endpoint)
                    self.assertEqual(
                        response.get_json(),
                        {"success": False, "error": "用户未登录或会话已过期"},
                    )

    def test_normal_user_returns_403_for_all_admin_surfaces(self):
        """普通用户登录后仍不能读取管理接口或后台 HTML。"""
        app = build_app()
        user = {"id": 1, "username": "normal", "role": "user", "is_active": True}
        with patch("app.auth.authorization.get_current_session_user", return_value=user):
            with app.test_client() as client:
                for endpoint in (*ADMIN_GET_ENDPOINTS, ADMIN_PAGE):
                    response = client.get(endpoint)
                    self.assertEqual(response.status_code, 403, endpoint)
                    self.assertEqual(
                        response.get_json(),
                        {"success": False, "error": "需要管理员权限"},
                    )
                for endpoint in ADMIN_POST_ENDPOINTS:
                    response = client.post(endpoint)
                    self.assertEqual(response.status_code, 403, endpoint)
                    self.assertEqual(
                        response.get_json(),
                        {"success": False, "error": "需要管理员权限"},
                    )

    def test_disabled_admin_is_not_accepted(self):
        """防御性校验不得放行未启用的管理员对象。"""
        app = build_app()
        admin = {"id": 2, "username": "disabled", "role": "admin", "is_active": False}
        with patch("app.auth.authorization.get_current_session_user", return_value=admin):
            with app.test_client() as client:
                response = client.get("/api/admin/db/health")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.get_json(),
            {"success": False, "error": "用户未登录或会话已过期"},
        )

    def test_active_admin_can_access_all_admin_surfaces(self):
        """已启用管理员应访问全部只读接口和受保护后台 HTML。"""
        app = build_app()
        admin = {"id": 2, "username": "admin", "role": "admin", "is_active": True}
        patches = admin_service_patches()
        with ExitStack() as stack:
            stack.enter_context(
                patch("app.auth.authorization.get_current_session_user", return_value=admin)
            )
            for service_patch in patches:
                stack.enter_context(service_patch)
            with app.test_client() as client:
                for endpoint in ADMIN_GET_ENDPOINTS:
                    response = client.get(endpoint)
                    self.assertEqual(response.status_code, 200, endpoint)
                    self.assertTrue(response.get_json()["success"])

                for endpoint in ADMIN_POST_ENDPOINTS:
                    response = client.post(endpoint)
                    self.assertEqual(response.status_code, 202, endpoint)
                    self.assertTrue(response.get_json()["success"])

                page_response = client.get(ADMIN_PAGE)
                self.assertEqual(page_response.status_code, 200)
                self.assertIn("数据库状态看板", page_response.get_data(as_text=True))
                page_response.close()

    def test_legacy_admin_response_shapes_remain_compatible(self):
        """旧接口继续保留 health 对象、slow 对象和 worker 列表数据类型。"""
        app = build_app()
        admin = {"id": 2, "username": "admin", "role": "admin", "is_active": True}
        patches = admin_service_patches()
        with ExitStack() as stack:
            stack.enter_context(
                patch("app.auth.authorization.get_current_session_user", return_value=admin)
            )
            for service_patch in patches:
                stack.enter_context(service_patch)
            with app.test_client() as client:
                health = client.get("/api/admin/db/health").get_json()
                slow = client.get("/api/admin/db/slow-queries?limit=20").get_json()
                workers = client.get("/api/admin/jobs/workers").get_json()

        self.assertIsInstance(health["data"], dict)
        self.assertIn("connections", health["data"])
        self.assertIn("tables", health["data"])
        self.assertIsInstance(slow["data"], dict)
        self.assertIn("Slow_queries", slow["data"])
        self.assertIn("top_statements", slow["data"])
        self.assertIsInstance(workers["data"], list)
        self.assertIn("summary", workers)
        self.assertIn("meta", workers)

    def test_refresh_posts_register_expected_shared_snapshot_groups(self):
        """普通刷新与完整性审计使用互不耦合的共享请求分组。"""
        app = build_app()
        admin = {"id": 2, "username": "admin", "role": "admin", "is_active": True}
        with (
            patch("app.auth.authorization.get_current_session_user", return_value=admin),
            patch(
                "app.admin.routes.request_snapshot_refresh",
                return_value={"groups": [], "requested_at": "2026-07-22T00:00:00.000Z"},
            ) as request_refresh,
        ):
            with app.test_client() as client:
                dashboard_refresh = client.post("/api/admin/db/refresh")
                integrity_refresh = client.post("/api/admin/db/integrity/run")

        self.assertEqual(dashboard_refresh.status_code, 202)
        self.assertEqual(integrity_refresh.status_code, 202)
        self.assertEqual(request_refresh.call_args_list[0].args[0], (
            "realtime",
            "sql_performance",
            "capacity",
        ))
        self.assertEqual(request_refresh.call_args_list[1].args[0], ("integrity",))

    def test_read_only_query_parameters_are_bounded(self):
        """慢查询上限和完整性模式必须在服务端白名单范围内。"""
        app = build_app()
        admin = {"id": 2, "username": "admin", "role": "admin", "is_active": True}
        with patch("app.auth.authorization.get_current_session_user", return_value=admin):
            with app.test_client() as client:
                self.assertEqual(client.get("/api/admin/db/slow-queries?limit=abc").status_code, 400)
                self.assertEqual(client.get("/api/admin/db/slow-queries?limit=101").status_code, 400)
                self.assertEqual(client.get("/api/admin/db/integrity?mode=deep").status_code, 400)


if __name__ == "__main__":
    unittest.main()
