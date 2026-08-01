import os
import unittest
from unittest.mock import patch
from uuid import UUID

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

from app.chat.routes import chat_bp
from app.chat.services import SessionNotFoundError, save_chat


class FakeCursor:
    """记录 SQL，并按顺序返回预设查询结果。"""

    def __init__(self, fetch_results=None):
        self.fetch_results = list(fetch_results or [])
        self.statements = []
        self.rowcount = 1
        self.lastrowid = 10

    def execute(self, sql, params=None):
        self.statements.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.fetch_results.pop(0) if self.fetch_results else None


class FakeConnection:
    """模拟会话创建和聊天保存使用的事务连接。"""

    def __init__(self, fetch_results=None):
        self.fake_cursor = FakeCursor(fetch_results)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def cursor(self, **kwargs):
        return self.fake_cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def build_app():
    """构建仅包含聊天蓝图的最小 Flask 测试应用。"""
    app = Flask(__name__)
    app.secret_key = "session-lifecycle-test-secret"
    app.register_blueprint(chat_bp)
    return app


class SessionLifecycleTests(unittest.TestCase):
    """验证会话创建和聊天写入都不依赖延迟建行。"""

    def test_new_chat_persists_session_before_returning_id(self):
        """new_chat 返回 ID 前必须先提交 sessions 记录。"""
        connection = FakeConnection()
        app = build_app()
        with (
            patch("app.chat.routes.get_current_session_user", return_value={"id": 7, "username": "owner"}),
            patch("app.db.get_write_connection", return_value=connection),
            patch("app.chat.routes.uuid.uuid4", return_value=UUID("12345678-1234-5678-1234-567812345678")),
            app.test_client() as client,
        ):
            response = client.post("/api/new_chat")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["new_session_id"], "12345678-1234-5678-1234-567812345678")
        self.assertTrue(connection.committed)
        self.assertEqual(
            connection.fake_cursor.statements[0],
            (
                "INSERT INTO sessions ( id, user_id, title, created_at, last_activity_at, message_count ) "
                "VALUES (%s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)",
                ("12345678-1234-5678-1234-567812345678", 7, "新对话"),
            ),
        )

    def test_save_chat_rejects_unknown_session_without_insert(self):
        """聊天写入遇到未知 session 时回滚并且不能自动创建。"""
        connection = FakeConnection(fetch_results=[None])
        with patch("app.chat.services.get_write_connection", return_value=connection):
            with self.assertRaises(SessionNotFoundError):
                save_chat(7, "missing-session", "hello", {"type": "text", "summary": "world"})

        self.assertTrue(connection.rolled_back)
        self.assertEqual(len(connection.fake_cursor.statements), 1)
        self.assertIn("FROM sessions", connection.fake_cursor.statements[0][0])
        self.assertIn("FOR UPDATE", connection.fake_cursor.statements[0][0])


if __name__ == "__main__":
    unittest.main()
