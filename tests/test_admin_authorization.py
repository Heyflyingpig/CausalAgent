import os
import unittest
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


from app.admin.routes import admin_bp


ADMIN_ENDPOINTS = (
    "/api/admin/db/health",
    "/api/admin/db/slow-queries",
    "/api/admin/jobs/workers",
)


def build_app():
    """构建只注册管理蓝图的最小测试应用。"""
    app = Flask(__name__)
    app.secret_key = "admin-test-secret"
    app.register_blueprint(admin_bp)
    return app


class AdminAuthorizationTests(unittest.TestCase):
    """验证所有现有管理接口共用同一个角色授权边界。"""

    def test_missing_session_returns_401_for_all_admin_endpoints(self):
        """无有效会话时所有管理接口都应返回 401。"""
        app = build_app()
        with patch("app.auth.authorization.get_current_session_user", return_value=None):
            with app.test_client() as client:
                for endpoint in ADMIN_ENDPOINTS:
                    response = client.get(endpoint)
                    self.assertEqual(response.status_code, 401, endpoint)
                    self.assertEqual(
                        response.get_json(),
                        {"success": False, "error": "用户未登录或会话已过期"},
                    )

    def test_normal_user_returns_403_for_all_admin_endpoints(self):
        """普通用户登录后仍不能读取任何管理接口。"""
        app = build_app()
        user = {"id": 1, "username": "normal", "role": "user", "is_active": True}
        with patch("app.auth.authorization.get_current_session_user", return_value=user):
            with app.test_client() as client:
                for endpoint in ADMIN_ENDPOINTS:
                    response = client.get(endpoint)
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

    def test_active_admin_can_access_all_admin_endpoints(self):
        """已启用管理员应通过三个现有接口的权限校验。"""
        app = build_app()
        admin = {"id": 2, "username": "admin", "role": "admin", "is_active": True}
        with (
            patch("app.auth.authorization.get_current_session_user", return_value=admin),
            patch("app.admin.routes.get_db_health", return_value={"status": "ok"}),
            patch("app.admin.routes.get_slow_query_summary", return_value={"queries": []}),
            patch("app.admin.routes.get_worker_snapshot", return_value={"workers": []}),
        ):
            with app.test_client() as client:
                for endpoint in ADMIN_ENDPOINTS:
                    response = client.get(endpoint)
                    self.assertEqual(response.status_code, 200, endpoint)
                    self.assertTrue(response.get_json()["success"])


if __name__ == "__main__":
    unittest.main()
