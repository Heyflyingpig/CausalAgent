"""核对 3.1 隔离主从、访问副作用、审计脱敏与 deep 快照结果。"""

from __future__ import annotations

import json
import os
import time

import mysql.connector

from app.db import get_read_connection, get_replica_status

from tests.seed_admin_31_e2e import (
    ATTACHMENT_ID,
    FILE_ID,
    JOB_ID,
    USER_ID,
    USER_MESSAGE_ID,
)


SENSITIVE_MARKERS = (
    "E2E_MESSAGE_BODY_MARKER_31",
    "E2E_JOB_INPUT_MARKER_31",
    "E2E_JOB_RESULT_MARKER_31",
    "E2E_ATTACHMENT_RESULT_MARKER_31",
)


def _decode_json(value):
    """兼容 mysql-connector 的 JSON 字符串和原生对象。"""
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(value)


def verify() -> None:
    """从主库和真实从库核对已知主键、访问副作用和脱敏结果。"""
    with get_read_connection(consistency="strong") as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT version_num FROM alembic_version")
        assert (cursor.fetchone() or {}).get("version_num") == "d3e4f5a6b7c8"
        cursor.execute(
            """
            SELECT INDEX_NAME AS index_name
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND INDEX_NAME IN (
                  'idx_users_admin_role_active',
                  'idx_sessions_admin_activity',
                  'idx_analysis_jobs_admin_created',
                  'idx_uploaded_files_admin_uploaded',
                  'idx_admin_audit_target_created'
              )
            """
        )
        assert len({row["index_name"] for row in cursor.fetchall()}) == 5

        cursor.execute(
            "SELECT access_count, last_accessed_at FROM uploaded_files WHERE id = %s",
            (FILE_ID,),
        )
        file_row = cursor.fetchone() or {}
        assert int(file_row.get("access_count") or 0) >= 2
        assert file_row.get("last_accessed_at") is not None

        cursor.execute(
            """
            SELECT action, target_type, target_id, old_values_json,
                   new_values_json, result, error_code, request_id
            FROM admin_audit_events
            WHERE target_id IN (%s, %s, %s, %s)
               OR target_type = 'database_audit'
            ORDER BY id
            """,
            (
                str(FILE_ID),
                str(USER_MESSAGE_ID),
                str(ATTACHMENT_ID),
                JOB_ID,
            ),
        )
        audits = cursor.fetchall()
        actions = {row["action"] for row in audits}
        assert "business.file.preview" in actions
        assert "business.file.download" in actions
        assert "business.message.content.view" in actions
        assert "business.attachment.content.view" in actions
        assert "business.job.result.view" in actions
        assert "database.audit.run" in actions
        serialized_audits = json.dumps(audits, ensure_ascii=False, default=str)
        for marker in SENSITIVE_MARKERS:
            assert marker not in serialized_audits
        assert all(row.get("request_id") for row in audits)

        cursor.execute(
            """
            SELECT payload_json, observed_at, refresh_requested_at
            FROM database_monitor_snapshots
            WHERE snapshot_key = 'deep_audit'
            """
        )
        deep_row = cursor.fetchone() or {}
        deep = _decode_json(deep_row.get("payload_json")) or {}
        assert deep.get("mode") == "deep"
        assert deep.get("auto_scheduled") is False
        assert deep_row.get("observed_at") is not None
        assert (
            deep_row.get("refresh_requested_at") is None
            or deep_row["observed_at"] >= deep_row["refresh_requested_at"]
        )
        deep_text = json.dumps(deep, ensure_ascii=False, default=str)
        assert "@" not in deep_text
        assert "GRANT " not in deep_text.upper()

        cursor.execute(
            "SELECT COUNT(*) AS total FROM analysis_job_events WHERE job_id = %s",
            (JOB_ID,),
        )
        assert int((cursor.fetchone() or {}).get("total") or 0) == 2

    replica_row = None
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with mysql.connector.connect(
                host="127.0.0.2",
                port=int(os.environ["MYSQL_PORT"]),
                user=os.environ["MYSQL_READ_USER"],
                password=os.environ["MYSQL_READ_PASSWORD"],
                database=os.environ["MYSQL_DATABASE"],
            ) as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    "SELECT id, role FROM users WHERE id = %s",
                    (USER_ID,),
                )
                replica_row = cursor.fetchone()
            if replica_row:
                break
        except Exception:
            pass
        time.sleep(1)
    assert replica_row == {"id": USER_ID, "role": "user"}

    status = get_replica_status("127.0.0.2") or {}
    assert status.get("Replica_IO_Running") == "Yes"
    assert status.get("Replica_SQL_Running") == "Yes"


if __name__ == "__main__":
    verify()
    print("3.1 隔离主从与审计副作用核对通过。")
