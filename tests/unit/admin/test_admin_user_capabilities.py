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


from app.agent.routes import agent_bp
from app.agent.job_service import IdempotencyConflictError
from app.chat.routes import chat_bp
from app.files.routes import _file_payload, files_bp


ADMIN = {
    "id": 73,
    "username": "chat-admin",
    "role": "admin",
    "is_active": True,
}
JOB_IDEMPOTENCY_KEY = "00000000-0000-4000-8000-000000000001"


class RecordingCursor:
    """记录查询参数并返回空列表，供用户归属测试复用。"""

    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        """记录一次 SQL 与参数调用。"""
        self.calls.append((sql, params))

    def fetchall(self):
        """返回稳定空结果，避免测试依赖业务数据。"""
        return []


class RecordingConnection:
    """提供最小上下文管理与字典游标接口。"""

    def __init__(self, cursor):
        self.recording_cursor = cursor

    def __enter__(self):
        """进入模拟数据库连接上下文。"""
        return self

    def __exit__(self, exc_type, exc, traceback):
        """离开模拟数据库连接上下文且不吞掉异常。"""
        return False

    def cursor(self, dictionary=False):
        """返回记录型游标。"""
        return self.recording_cursor


def build_app():
    """构造仅包含普通用户能力接口的最小 Flask 应用。"""
    app = Flask(__name__)
    app.secret_key = "admin-user-capability-test"
    app.register_blueprint(chat_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(agent_bp)
    return app


class AdminUserCapabilityTests(unittest.TestCase):
    """验证管理员调用普通接口时只能使用自身用户 ID。"""

    def test_user_file_payload_does_not_expose_blob_object_id(self):
        """普通用户文件 DTO 只暴露逻辑 user_file_id，不返回 BLOB 对象 ID。"""
        payload = _file_payload({
            "id": 11,
            "object_id": 22,
            "filename": "data.csv",
            "mime_type": "text/csv",
            "file_size": 12,
            "uploaded_at": None,
            "last_accessed_at": None,
            "access_count": 0,
        })

        self.assertEqual(payload["user_file_id"], 11)
        self.assertNotIn("object_id", payload)

    def test_admin_session_list_is_scoped_to_own_user_id(self):
        """管理员读取会话列表时沿用普通用户的 user_id 条件。"""
        app = build_app()
        cursor = RecordingCursor()
        connection = RecordingConnection(cursor)
        with (
            patch("app.chat.routes.get_current_session_user", return_value=ADMIN),
            patch("app.db.get_read_connection", return_value=connection),
            app.test_client() as client,
        ):
            response = client.get("/api/sessions")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])
        self.assertEqual(cursor.calls[0][1], (ADMIN["id"],))

    def test_admin_file_list_is_scoped_to_own_user_id(self):
        """管理员读取文件列表时沿用普通用户的 user_id 条件。"""
        app = build_app()
        cursor = RecordingCursor()
        connection = RecordingConnection(cursor)
        with (
            patch("app.files.routes.get_current_session_user", return_value=ADMIN),
            patch("app.files.routes.get_read_connection", return_value=connection),
            app.test_client() as client,
        ):
            response = client.get("/api/files")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])
        self.assertEqual(cursor.calls[0][1], (ADMIN["id"],))

    def test_admin_job_creation_is_scoped_to_own_user_id(self):
        """管理员创建分析任务时把自身 user_id 交给任务服务。"""
        app = build_app()
        created_job = {"job_id": "job-admin-1", "status": "queued"}
        with (
            patch("app.agent.routes.get_current_session_user", return_value=ADMIN),
            patch(
                "app.agent.routes.job_service.create_job",
                return_value=(created_job, False),
            ) as create_job,
            app.test_client() as client,
        ):
            response = client.post(
                "/api/agent/jobs",
                json={"session_id": "session-admin-1", "message": "分析数据"},
                headers={"Idempotency-Key": JOB_IDEMPOTENCY_KEY},
            )

        self.assertEqual(response.status_code, 202)
        create_job.assert_called_once_with(
            ADMIN["id"],
            "session-admin-1",
            "分析数据",
            JOB_IDEMPOTENCY_KEY,
            None,
        )

    def test_agent_job_creation_requires_idempotency_key(self):
        """分析任务创建缺少幂等键时应在入队前拒绝。"""
        app = build_app()
        with (
            patch("app.agent.routes.get_current_session_user", return_value=ADMIN),
            patch("app.agent.routes.job_service.create_job") as create_job,
            app.test_client() as client,
        ):
            response = client.post(
                "/api/agent/jobs",
                json={"session_id": "session-admin-1", "message": "分析数据"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Idempotency-Key", response.get_json()["error"])
        create_job.assert_not_called()

    def test_agent_job_creation_rejects_idempotency_key_reuse_with_new_request(self):
        """路由应把同键异参转换为客户端可处理的 409 冲突。"""
        app = build_app()
        with (
            patch("app.agent.routes.get_current_session_user", return_value=ADMIN),
            patch(
                "app.agent.routes.job_service.create_job",
                side_effect=IdempotencyConflictError(
                    "Idempotency-Key 已用于不同的分析请求"
                ),
            ),
            app.test_client() as client,
        ):
            response = client.post(
                "/api/agent/jobs",
                json={"session_id": "session-admin-1", "message": "分析数据"},
                headers={"Idempotency-Key": JOB_IDEMPOTENCY_KEY},
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn("不同的分析请求", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
