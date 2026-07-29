"""向明确隔离的 3.1/3.2 主库写入可核对的管理员后台验收数据。"""

from __future__ import annotations

import json
import os

import bcrypt

from app.db import get_write_connection
from Database.mysql_checkpointer import _pending_write_identity_hash


ADMIN_ID = 3101
USER_ID = 3102
ADMIN_SESSION_ID = "31-admin-session"
USER_SESSION_ID = "31-user-session"
ARCHIVED_SESSION_ID = "31-archived-session"
JOB_ID = "31-job-succeeded"
FILE_ID = 3101
USER_MESSAGE_ID = 3101
AI_MESSAGE_ID = 3102
ATTACHMENT_ID = 3101
CONTROL_USER_A_ID = 3103
CONTROL_USER_B_ID = 3104
DELETE_USER_ID = 3105
CONTROL_FILE_ID = 3201
DELETE_FILE_ID = 3205
DELETE_SESSION_ID = "32-delete-session"
DELETE_ARCHIVED_SESSION_ID = "32-delete-archived-session"
DELETE_JOB_ID = "32-delete-job"
DELETE_MESSAGE_ID = 3205
DELETE_ATTACHMENT_ID = 3205


def _required_secret(name: str) -> str:
    """读取仅在当前验收进程存在的临时凭据。"""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"缺少隔离验收变量 {name}")
    return value


def _password_hash(value: str) -> str:
    """为隔离用户生成 bcrypt 哈希，不输出明文。"""
    return bcrypt.hashpw(value.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode(
        "utf-8"
    )


def seed() -> None:
    """在空的隔离数据库中原子写入用户、业务记录、checkpoint 与快照。"""
    admin_password = _required_secret("E2E_ADMIN_PASSWORD")
    user_password = _required_secret("E2E_USER_PASSWORD")
    with get_write_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT COUNT(*) AS total FROM users "
            "WHERE id IN (%s, %s, %s, %s, %s)",
            (
                ADMIN_ID,
                USER_ID,
                CONTROL_USER_A_ID,
                CONTROL_USER_B_ID,
                DELETE_USER_ID,
            ),
        )
        if int((cursor.fetchone() or {}).get("total") or 0):
            raise RuntimeError("隔离验收主键已存在，拒绝覆盖或重复种入")

        cursor.executemany(
            """
            INSERT INTO users (
                id, username, password_hash, role, is_active,
                created_at, last_login_at
            ) VALUES (%s, %s, %s, %s, TRUE, UTC_TIMESTAMP(), UTC_TIMESTAMP())
            """,
            (
                (
                    ADMIN_ID,
                    "e2e-admin-31",
                    _password_hash(admin_password),
                    "admin",
                ),
                (
                    USER_ID,
                    "e2e-user-31",
                    _password_hash(user_password),
                    "user",
                ),
                (
                    CONTROL_USER_A_ID,
                    "e2e-control-a-32",
                    _password_hash(user_password),
                    "user",
                ),
                (
                    CONTROL_USER_B_ID,
                    "e2e-control-b-32",
                    _password_hash(user_password),
                    "user",
                ),
                (
                    DELETE_USER_ID,
                    "e2e-delete-32",
                    _password_hash(user_password),
                    "user",
                ),
            ),
        )
        cursor.executemany(
            """
            INSERT INTO sessions (
                id, user_id, title, created_at, last_activity_at,
                message_count, is_archived
            ) VALUES (%s, %s, %s, UTC_TIMESTAMP(), UTC_TIMESTAMP(), %s, FALSE)
            """,
            (
                (ADMIN_SESSION_ID, ADMIN_ID, "管理员空态会话", 0),
                (USER_SESSION_ID, USER_ID, "3.1 可核对会话", 2),
                (DELETE_SESSION_ID, DELETE_USER_ID, "3.2 删除生命周期", 1),
            ),
        )
        cursor.execute(
            """
            INSERT INTO archived_sessions (
                id, user_id, original_session_data, message_count,
                archived_at, archive_reason
            ) VALUES (%s, %s, %s, 2, UTC_TIMESTAMP(), 'user_request')
            """,
            (
                ARCHIVED_SESSION_ID,
                USER_ID,
                json.dumps(
                    {"title": "已归档验收会话", "marker": "archive-metadata-marker"},
                    ensure_ascii=False,
                ),
            ),
        )
        cursor.execute(
            """
            INSERT INTO archived_sessions (
                id, user_id, original_session_data, message_count,
                archived_at, archive_reason
            ) VALUES (%s, %s, %s, 1, UTC_TIMESTAMP(), 'user_request')
            """,
            (
                DELETE_ARCHIVED_SESSION_ID,
                DELETE_USER_ID,
                json.dumps({"title": "3.2 删除归档"}, ensure_ascii=False),
            ),
        )
        cursor.executemany(
            """
            INSERT INTO chat_messages (
                id, session_id, user_id, message_type, content,
                has_attachment, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, UTC_TIMESTAMP())
            """,
            (
                (
                    USER_MESSAGE_ID,
                    USER_SESSION_ID,
                    USER_ID,
                    "user",
                    "E2E_MESSAGE_BODY_MARKER_31",
                    False,
                ),
                (
                    AI_MESSAGE_ID,
                    USER_SESSION_ID,
                    USER_ID,
                    "ai",
                    "E2E_AI_FALLBACK_MARKER_31",
                    True,
                ),
            ),
        )
        cursor.execute(
            """
            INSERT INTO chat_attachments (
                id, message_id, attachment_type, content, created_at
            ) VALUES (%s, %s, 'causal_graph', %s, UTC_TIMESTAMP())
            """,
            (
                ATTACHMENT_ID,
                AI_MESSAGE_ID,
                json.dumps(
                    {
                        "summary": "E2E_ATTACHMENT_RESULT_MARKER_31",
                        "nodes": [],
                        "edges": [],
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        cursor.execute(
            """
            INSERT INTO chat_messages (
                id, session_id, user_id, message_type, content,
                has_attachment, created_at
            ) VALUES (%s, %s, %s, 'user', %s, TRUE, UTC_TIMESTAMP())
            """,
            (
                DELETE_MESSAGE_ID,
                DELETE_SESSION_ID,
                DELETE_USER_ID,
                "E2E_DELETE_MESSAGE_MARKER_32",
            ),
        )
        cursor.execute(
            """
            INSERT INTO chat_attachments (
                id, message_id, attachment_type, content, created_at
            ) VALUES (%s, %s, 'other', %s, UTC_TIMESTAMP())
            """,
            (
                DELETE_ATTACHMENT_ID,
                DELETE_MESSAGE_ID,
                json.dumps({"marker": "E2E_DELETE_ATTACHMENT_MARKER_32"}),
            ),
        )
        file_content = (
            "name,value,formula\n"
            "alpha,1,=2+2\n"
            "html,<script>alert(1)</script>,safe-text\n"
        ).encode("utf-8")
        cursor.execute(
            """
            INSERT INTO uploaded_files (
                id, user_id, filename, original_filename, mime_type,
                file_size, file_hash, file_content, upload_timestamp,
                last_accessed_at, access_count
            ) VALUES (
                %s, %s, %s, %s, 'text/csv',
                %s, %s, %s, UTC_TIMESTAMP(), UTC_TIMESTAMP(), 0
            )
            """,
            (
                FILE_ID,
                USER_ID,
                "31-stored.csv",
                "31-report.csv",
                len(file_content),
                "31" * 32,
                file_content,
            ),
        )
        controlled_file_content = b"name,value\ncontrolled,32\n"
        cursor.execute(
            """
            INSERT INTO uploaded_files (
                id, user_id, filename, original_filename, mime_type,
                file_size, file_hash, file_content, upload_timestamp,
                last_accessed_at, access_count
            ) VALUES (
                %s, %s, '32-controlled-stored.csv', '32-delete-file.csv',
                'text/csv', %s, %s, %s, UTC_TIMESTAMP(), UTC_TIMESTAMP(), 0
            )
            """,
            (
                CONTROL_FILE_ID,
                CONTROL_USER_A_ID,
                len(controlled_file_content),
                "32" * 32,
                controlled_file_content,
            ),
        )
        deleted_user_file_content = b"name,value\ndelete-user,32\n"
        cursor.execute(
            """
            INSERT INTO uploaded_files (
                id, user_id, filename, original_filename, mime_type,
                file_size, file_hash, file_content, upload_timestamp,
                last_accessed_at, access_count
            ) VALUES (
                %s, %s, '32-user-delete-stored.csv', '32-user-delete.csv',
                'text/csv', %s, %s, %s, UTC_TIMESTAMP(), UTC_TIMESTAMP(), 0
            )
            """,
            (
                DELETE_FILE_ID,
                DELETE_USER_ID,
                len(deleted_user_file_content),
                "33" * 32,
                deleted_user_file_content,
            ),
        )
        cursor.execute(
            """
            INSERT INTO analysis_jobs (
                id, job_id, user_id, session_id, message, status,
                result_json, worker_id, attempt_count, max_attempts,
                created_at, started_at, finished_at, chat_saved_at,
                active_session_key
            ) VALUES (
                3101, %s, %s, %s, %s, 'succeeded',
                %s, 'e2e-worker-31', 1, 3,
                UTC_TIMESTAMP(6), UTC_TIMESTAMP(6), UTC_TIMESTAMP(6),
                UTC_TIMESTAMP(6), NULL
            )
            """,
            (
                JOB_ID,
                USER_ID,
                USER_SESSION_ID,
                "E2E_JOB_INPUT_MARKER_31",
                json.dumps(
                    {"summary": "E2E_JOB_RESULT_MARKER_31"},
                    ensure_ascii=False,
                ),
            ),
        )
        cursor.executemany(
            """
            INSERT INTO analysis_job_events (job_id, event_type, payload_json)
            VALUES (%s, %s, %s)
            """,
            (
                (
                    JOB_ID,
                    "progress",
                    json.dumps(
                        {"type": "progress", "message": "E2E_PROGRESS_MARKER_31"},
                        ensure_ascii=False,
                    ),
                ),
                (
                    JOB_ID,
                    "final_result",
                    json.dumps(
                        {
                            "type": "final_result",
                            "result": {"summary": "E2E_JOB_RESULT_MARKER_31"},
                        },
                        ensure_ascii=False,
                    ),
                ),
            ),
        )
        cursor.execute(
            """
            INSERT INTO analysis_jobs (
                id, job_id, user_id, session_id, message, status,
                result_json, worker_id, attempt_count, max_attempts,
                created_at, started_at, finished_at, chat_saved_at,
                active_session_key
            ) VALUES (
                3205, %s, %s, %s, 'E2E_DELETE_JOB_INPUT_32', 'succeeded',
                %s, 'e2e-worker-32', 1, 3,
                UTC_TIMESTAMP(6), UTC_TIMESTAMP(6), UTC_TIMESTAMP(6),
                UTC_TIMESTAMP(6), NULL
            )
            """,
            (
                DELETE_JOB_ID,
                DELETE_USER_ID,
                DELETE_SESSION_ID,
                json.dumps({"summary": "E2E_DELETE_JOB_RESULT_32"}),
            ),
        )
        cursor.execute(
            """
            INSERT INTO analysis_job_events (job_id, event_type, payload_json)
            VALUES (%s, 'final_result', %s)
            """,
            (
                DELETE_JOB_ID,
                json.dumps({"type": "final_result", "marker": "delete-32"}),
            ),
        )
        cursor.execute(
            """
            INSERT INTO checkpoints (
                thread_id, checkpoint_ns, checkpoint_id,
                checkpoint, metadata_data, created_at
            ) VALUES (%s, '', '31-checkpoint', %s, %s, UTC_TIMESTAMP())
            """,
            (
                USER_SESSION_ID,
                b"E2E_CHECKPOINT_MARKER_31",
                json.dumps({"source": "3.1-e2e"}, ensure_ascii=False),
            ),
        )
        cursor.execute(
            """
            INSERT INTO checkpoint_writes (
                thread_id, checkpoint_ns, checkpoint_id, task_id,
                idx, channel, value, created_at, write_identity_hash
            ) VALUES (
                %s, '', '31-checkpoint', '31-task', 0, 'result', %s,
                UTC_TIMESTAMP(), %s
            )
            """,
            (
                USER_SESSION_ID,
                b"E2E_PENDING_WRITE_MARKER_31",
                _pending_write_identity_hash(
                    USER_SESSION_ID,
                    "",
                    "31-checkpoint",
                    "31-task",
                    0,
                ),
            ),
        )
        cursor.execute(
            """
            INSERT INTO checkpoints (
                thread_id, checkpoint_ns, checkpoint_id,
                checkpoint, metadata_data, created_at
            ) VALUES (%s, '', '32-delete-checkpoint', %s, %s, UTC_TIMESTAMP())
            """,
            (
                DELETE_SESSION_ID,
                b"E2E_DELETE_CHECKPOINT_MARKER_32",
                json.dumps({"source": "3.2-e2e"}, ensure_ascii=False),
            ),
        )
        cursor.execute(
            """
            INSERT INTO checkpoint_writes (
                thread_id, checkpoint_ns, checkpoint_id, task_id,
                idx, channel, value, created_at, write_identity_hash
            ) VALUES (
                %s, '', '32-delete-checkpoint', '32-delete-task', 0,
                'result', %s, UTC_TIMESTAMP(), %s
            )
            """,
            (
                DELETE_SESSION_ID,
                b"E2E_DELETE_PENDING_WRITE_MARKER_32",
                _pending_write_identity_hash(
                    DELETE_SESSION_ID,
                    "",
                    "32-delete-checkpoint",
                    "32-delete-task",
                    0,
                ),
            ),
        )
        for snapshot_key, payload in {
            "realtime": {
                "status": "healthy",
                "source_alias": "primary",
                "primary": {"status": "healthy", "value": {"connected": True}},
                "replica": {
                    "status": "healthy",
                    "value": {
                        "configured": True,
                        "available": True,
                        "lag_seconds": 0,
                        "io_running": "Yes",
                        "sql_running": "Yes",
                    },
                },
                "connections": {
                    "status": "healthy",
                    "value": {
                        "utilization_percent": 1,
                        "threads_connected": 1,
                        "max_connections": 100,
                        "threads_running": 1,
                        "max_used_connections": 1,
                    },
                },
                "jobs": {
                    "status": "healthy",
                    "value": {
                        "summary": {
                            "queued": 0,
                            "running": 0,
                            "stale": 0,
                            "max_attempts_running": 0,
                        },
                        "data": [],
                    },
                },
            },
            "sql_performance": {
                "status": "healthy",
                "source_alias": "primary",
                "slow_queries_delta": 0,
                "high_load_statements": [],
            },
            "capacity": {
                "status": "healthy",
                "source_alias": "primary",
                "is_estimate": True,
                "tables": {"status": "healthy", "is_estimate": True, "value": []},
            },
            "integrity": {
                "status": "healthy",
                "source_alias": "primary",
                "blocking_count": 0,
                "checks": [],
            },
        }.items():
            cursor.execute(
                """
                UPDATE database_monitor_snapshots
                SET payload_json = %s, observed_at = UTC_TIMESTAMP(6),
                    refresh_requested_at = NULL
                WHERE snapshot_key = %s
                """,
                (json.dumps(payload, ensure_ascii=False), snapshot_key),
            )
        conn.commit()


def refresh_login_passwords() -> None:
    """仅为已知隔离用户刷新本次进程的临时登录密码。"""
    admin_password = _required_secret("E2E_ADMIN_PASSWORD")
    user_password = _required_secret("E2E_USER_PASSWORD")
    with get_write_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany(
            """
            UPDATE users
            SET password_hash = %s
            WHERE id = %s AND username = %s
            """,
            (
                (_password_hash(admin_password), ADMIN_ID, "e2e-admin-31"),
                (_password_hash(user_password), USER_ID, "e2e-user-31"),
            ),
        )
        if cursor.rowcount != 2:
            conn.rollback()
            raise RuntimeError("隔离验收用户不完整，拒绝刷新其他账号密码")
        conn.commit()


if __name__ == "__main__":
    if os.environ.get("E2E_REFRESH_PASSWORDS_ONLY") == "true":
        refresh_login_passwords()
        print("3.1/3.2 隔离验收临时登录凭据已刷新。")
    else:
        seed()
        print("3.1/3.2 隔离验收数据已种入。")
