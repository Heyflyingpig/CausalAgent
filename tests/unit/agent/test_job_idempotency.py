import os
import unittest
from unittest.mock import patch

import mysql.connector
from mysql.connector import errorcode


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

from app.agent.job_service import (  # noqa: E402
    IdempotencyConflictError,
    _request_fingerprint,
    create_job,
)


JOB_REQUEST_KEY = "123e4567-e89b-42d3-a456-426614174000"
JOB_REQUEST_ID = "create.req-1"


class FakeCursor:
    """按顺序返回 session 和幂等记录，并记录 job 创建 SQL。"""

    def __init__(self, fetch_results=None, rowcount=1, insert_error=None):
        self.fetch_results = list(fetch_results or [])
        self.rowcount = rowcount
        self.insert_error = insert_error
        self.lastrowid = 17
        self.statements = []

    def execute(self, sql, params=None):
        """记录 SQL 和参数。"""
        normalized_sql = " ".join(sql.split())
        self.statements.append((normalized_sql, params))
        if self.insert_error and "INSERT INTO analysis_jobs" in normalized_sql:
            raise self.insert_error

    def fetchone(self):
        """返回下一条预设查询结果。"""
        return self.fetch_results.pop(0) if self.fetch_results else None


class FakeConnection:
    """模拟请求幂等查询和 job 插入使用的 MySQL 事务连接。"""

    def __init__(self, fetch_results=None, insert_error=None):
        self.fake_cursor = FakeCursor(fetch_results, insert_error=insert_error)
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self, **kwargs):
        """返回记录型游标。"""
        return self.fake_cursor

    def start_transaction(self):
        """记录事务开始，保持 fake 连接协议完整。"""

    def commit(self):
        """记录事务提交。"""
        self.commits += 1

    def rollback(self):
        """记录事务回滚。"""
        self.rollbacks += 1

    def close(self):
        """记录连接关闭。"""
        self.closed = True


class JobIdempotencyTests(unittest.TestCase):
    """验证分析任务创建的请求级幂等边界。"""

    def test_same_key_and_request_returns_existing_job_without_insert(self):
        """重放同一请求只返回原 job，不创建第二条任务记录。"""
        fingerprint = _request_fingerprint("session-1", "hello")
        existing = {
            "job_id": "job-1",
            "status": "succeeded",
            "request_fingerprint": fingerprint,
            "request_id": "first-request",
        }
        connection = FakeConnection(
            fetch_results=[existing]
        )

        with patch("app.agent.job_service.get_write_connection", return_value=connection):
            job, was_existing = create_job(
                7,
                "session-1",
                "hello",
                JOB_REQUEST_KEY,
                request_id="retry-request",
            )

        self.assertEqual(job, existing)
        self.assertEqual(job["request_id"], "first-request")
        self.assertTrue(was_existing)
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        self.assertFalse(any("INSERT INTO analysis_jobs" in sql for sql, _ in connection.fake_cursor.statements))

    def test_same_key_with_different_request_is_rejected(self):
        """同一幂等键不能被改用于另一个会话或消息。"""
        connection = FakeConnection(
            fetch_results=[
                {"job_id": "job-1", "request_fingerprint": "0" * 64},
            ]
        )

        with patch("app.agent.job_service.get_write_connection", return_value=connection):
            with self.assertRaises(IdempotencyConflictError):
                create_job(
                    7,
                    "session-1",
                    "hello",
                    JOB_REQUEST_KEY,
                    request_id=JOB_REQUEST_ID,
                )

        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)

    def test_new_job_persists_key_and_fingerprint_in_same_transaction(self):
        """新 job 必须在同一事务中写入幂等键和请求指纹。"""
        connection = FakeConnection(
            fetch_results=[
                None,
                None,
                {"id": "session-1"},
                {"message_count": 0, "title": ""},
            ]
        )
        created = {"job_id": "job-new", "status": "queued"}

        with (
            patch("app.agent.job_service.get_write_connection", return_value=connection),
            patch("app.agent.job_service.get_job_for_user", return_value=created),
        ):
            job, was_existing = create_job(
                7,
                "session-1",
                "hello",
                JOB_REQUEST_KEY,
                request_id=JOB_REQUEST_ID,
            )

        insert_params = next(
            params
            for sql, params in connection.fake_cursor.statements
            if "INSERT INTO analysis_jobs" in sql
        )
        self.assertEqual(job, created)
        self.assertFalse(was_existing)
        self.assertEqual(insert_params[3], JOB_REQUEST_ID)
        self.assertEqual(insert_params[-2], JOB_REQUEST_KEY)
        self.assertEqual(insert_params[-1], _request_fingerprint("session-1", "hello"))
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)

    def test_duplicate_key_race_returns_committed_job_after_insert_conflict(self):
        """唯一键并发冲突后应读取已经提交的原 job，而不是再次入队。"""
        duplicate_error = mysql.connector.Error("duplicate")
        duplicate_error.errno = errorcode.ER_DUP_ENTRY
        fingerprint = _request_fingerprint("session-1", "hello")
        existing = {
            "job_id": "job-1",
            "status": "succeeded",
            "request_fingerprint": fingerprint,
            "request_id": "first-request",
        }
        connection = FakeConnection(
            fetch_results=[None, None, {"id": "session-1"}],
            insert_error=duplicate_error,
        )

        with (
            patch("app.agent.job_service.get_write_connection", return_value=connection),
            patch(
                "app.agent.job_service.get_job_by_idempotency_key",
                return_value=existing,
            ),
        ):
            job, was_existing = create_job(
                7,
                "session-1",
                "hello",
                JOB_REQUEST_KEY,
                request_id="retry-request",
            )

        self.assertEqual(job, existing)
        self.assertTrue(was_existing)
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)

    def test_invalid_request_id_is_rejected_before_database_write(self):
        """服务层不能被绕过 HTTP 入口写入不符合契约的 request ID。"""
        with self.assertRaises(ValueError):
            create_job(
                7,
                "session-1",
                "hello",
                JOB_REQUEST_KEY,
                request_id="invalid/request-id",
            )


if __name__ == "__main__":
    unittest.main()
