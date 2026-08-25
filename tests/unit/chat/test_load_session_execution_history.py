import json
import os
from datetime import datetime, timedelta
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

from app.chat.routes import chat_bp  # noqa: E402


BASE = datetime(2026, 8, 11, 8, 0, 0)


class HistoryCursor:
    def __init__(self):
        self.current_sql = ""
        self.statements = []

    def execute(self, sql, params=None):
        self.current_sql = " ".join(sql.split())
        self.statements.append((self.current_sql, params))

    def fetchone(self):
        if "FROM sessions" in self.current_sql:
            return {
                "id": "session-1",
                "user_id": 7,
                "snapshot_at": BASE + timedelta(seconds=5),
            }
        return None

    def fetchall(self):
        if "FROM chat_messages" in self.current_sql:
            return [
                {
                    "id": 10,
                    "message_type": "user",
                    "content": "问题",
                    "has_attachment": False,
                    "analysis_job_id": "job-1",
                    "analysis_job_input_id": 1,
                    "source_event_id": None,
                    "created_at": BASE,
                },
                {
                    "id": 11,
                    "message_type": "ai",
                    "content": "回答",
                    "has_attachment": False,
                    "analysis_job_id": "job-1",
                    "analysis_job_input_id": 1,
                    "source_event_id": 102,
                    "created_at": BASE + timedelta(seconds=3),
                },
            ]
        if "FROM analysis_jobs" in self.current_sql:
            return [{"job_id": "job-1", "status": "succeeded", "created_at": BASE}]
        if "FROM analysis_job_inputs" in self.current_sql:
            return [{
                "input_id": 1,
                "job_id": "job-1",
                "sequence": 0,
                "input_type": "initial",
                "chat_message_id": 10,
                "created_at": BASE,
            }]
        if "FROM analysis_job_events" in self.current_sql:
            return [
                {
                    "id": 101,
                    "job_id": "job-1",
                    "event_type": "node_start",
                    "payload_json": json.dumps({
                        "type": "node_start",
                        "step_id": "step-1",
                        "title": "分析",
                        "attempt": 7,
                    }),
                    "created_at": BASE + timedelta(seconds=1),
                },
                {
                    "id": 102,
                    "job_id": "job-1",
                    "event_type": "final_result",
                    "payload_json": json.dumps({"type": "final_result", "data": {"secret": "not returned"}}),
                    "created_at": BASE + timedelta(seconds=3),
                },
            ]
        return []


class HistoryConnection:
    def __init__(self):
        self.cursor_value = HistoryCursor()
        self.transaction_options = None
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def start_transaction(self, **kwargs):
        self.transaction_options = kwargs

    def cursor(self, **_kwargs):
        return self.cursor_value

    def commit(self):
        self.committed = True

    def rollback(self):
        pass


class DeniedHistoryCursor(HistoryCursor):
    def fetchone(self):
        return None


class DeniedHistoryConnection(HistoryConnection):
    def __init__(self):
        super().__init__()
        self.cursor_value = DeniedHistoryCursor()
        self.rolled_back = False

    def rollback(self):
        self.rolled_back = True


def _app():
    app = Flask(__name__)
    app.secret_key = "history-test"
    app.register_blueprint(chat_bp)
    return app


def test_load_session_returns_phase_and_uses_fixed_batch_queries():
    connection = HistoryConnection()
    with (
        patch("app.chat.routes.get_current_session_user", return_value={"id": 7, "username": "owner"}),
        patch("app.db.get_read_connection", return_value=connection),
        _app().test_client() as client,
    ):
        response = client.get("/api/load_session?session=session-1")

    assert response.status_code == 200
    messages = response.get_json()["messages"]
    assert [message["sender"] for message in messages] == ["user", "ai"]
    phase = messages[0]["thinking_after"]
    assert phase["status"] == "completed"
    assert [event["event_id"] for event in phase["events"]] == [101]
    assert "attempt" not in phase["events"][0]
    assert "secret" not in repr(phase)
    assert connection.transaction_options == {"readonly": True}
    assert connection.committed is True
    assert len(connection.cursor_value.statements) == 5
    assert sum("FROM analysis_job_events" in sql for sql, _ in connection.cursor_value.statements) == 1


def test_load_session_rejects_unknown_or_unauthorized_session_before_history_queries():
    connection = DeniedHistoryConnection()
    with (
        patch("app.chat.routes.get_current_session_user", return_value={"id": 7, "username": "owner"}),
        patch("app.db.get_read_connection", return_value=connection),
        _app().test_client() as client,
    ):
        response = client.get("/api/load_session?session=not-owned")

    assert response.status_code == 404
    assert connection.rolled_back is True
    assert len(connection.cursor_value.statements) == 2
