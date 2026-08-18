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

from app.agent.job_service import create_job


class FakeCursor:
    """记录 session 校验 SQL，并模拟不存在的查询结果。"""

    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((" ".join(sql.split()), params))

    def fetchone(self):
        return None


class FakeConnection:
    """模拟 job 创建事务。"""

    def __init__(self):
        self.fake_cursor = FakeCursor()
        self.rolled_back = False
        self.closed = False

    def cursor(self, **kwargs):
        return self.fake_cursor

    def start_transaction(self):
        pass

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class JobSessionValidationTests(unittest.TestCase):
    """验证 job 创建不会因为未知 session 自动插入会话。"""

    def test_create_job_rejects_unknown_session_without_insert(self):
        connection = FakeConnection()
        with patch("app.agent.job_service.get_write_connection", return_value=connection):
            with self.assertRaises(PermissionError):
                create_job(
                    7,
                    "missing-session",
                    "hello",
                    "123e4567-e89b-42d3-a456-426614174000",
                    request_id="create.req-1",
                )

        self.assertTrue(connection.rolled_back)
        self.assertTrue(connection.closed)
        self.assertEqual(len(connection.fake_cursor.statements), 3)
        self.assertTrue(
            all("INSERT INTO sessions" not in sql for sql, _ in connection.fake_cursor.statements)
        )
        self.assertIn("FOR UPDATE", connection.fake_cursor.statements[2][0])


if __name__ == "__main__":
    unittest.main()
