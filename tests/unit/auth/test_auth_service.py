import os
import unittest
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

from app.auth.service import find_user, find_user_by_id, record_successful_login


class FakeCursor:
    """模拟返回单个认证用户的字典游标。"""

    def __init__(self, row):
        self.row = row
        self.sql = None
        self.params = None

    def execute(self, sql, params):
        """记录认证查询文本与参数。"""
        self.sql = " ".join(sql.split())
        self.params = params

    def fetchone(self):
        """返回预设的认证用户。"""
        return self.row


class FakeConnection:
    """模拟认证查询使用的只读连接。"""

    def __init__(self, row):
        self.fake_cursor = FakeCursor(row)
        self.committed = False

    def __enter__(self):
        """返回连接自身供 with 使用。"""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """模拟只读连接上下文退出。"""
        return False

    def cursor(self, dictionary=False):
        """返回唯一的模拟字典游标。"""
        self.dictionary = dictionary
        return self.fake_cursor

    def commit(self):
        """记录认证写入是否提交。"""
        self.committed = True


class AuthServiceReadTests(unittest.TestCase):
    """验证登录和权限查询固定使用主库强一致读。"""

    def test_find_user_uses_strong_read_and_returns_role_state(self):
        """用户名查询必须读取密码、角色和启用状态。"""
        row = {
            "id": 1,
            "username": "charchar",
            "password_hash": "hash",
            "role": "admin",
            "is_active": True,
        }
        connection = FakeConnection(row)
        with patch(
            "app.auth.service.get_read_connection",
            return_value=connection,
        ) as get_read:
            result = find_user("charchar")

        get_read.assert_called_once_with(consistency="strong")
        self.assertEqual(result, row)
        self.assertIn("password_hash, role, is_active", connection.fake_cursor.sql)

    def test_find_user_by_id_uses_strong_read_and_returns_role_state(self):
        """session 回查必须从主库取得当前角色和启用状态。"""
        row = {"id": 2, "username": "normal", "role": "user", "is_active": True}
        connection = FakeConnection(row)
        with patch(
            "app.auth.service.get_read_connection",
            return_value=connection,
        ) as get_read:
            result = find_user_by_id(2)

        get_read.assert_called_once_with(consistency="strong")
        self.assertEqual(result, row)
        self.assertIn("role, is_active", connection.fake_cursor.sql)

    def test_record_successful_login_updates_utc_time_on_primary(self):
        """密码验证成功后必须通过主库提交 UTC 最后登录时间。"""
        connection = FakeConnection(None)
        with patch(
            "app.auth.service.get_write_connection",
            return_value=connection,
        ) as get_write:
            result = record_successful_login(7)

        get_write.assert_called_once_with()
        self.assertTrue(result)
        self.assertTrue(connection.committed)
        self.assertIn("SET last_login_at = UTC_TIMESTAMP()", connection.fake_cursor.sql)
        self.assertEqual(connection.fake_cursor.params, (7,))

    def test_record_successful_login_failure_is_non_blocking(self):
        """最后登录时间写入异常应返回失败标记，由路由继续完成登录。"""
        with (
            patch(
                "app.auth.service.get_write_connection",
                side_effect=RuntimeError("write failed"),
            ),
            patch("app.auth.service.logging.error") as log_error,
        ):
            result = record_successful_login(8)

        self.assertFalse(result)
        log_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
