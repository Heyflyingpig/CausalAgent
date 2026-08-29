import os
import unittest
from datetime import datetime
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


from app.admin import business_service, write_service
from app.admin.contracts import AdminApiError, decode_cursor


class FakeCursor:
    """为有界查询测试记录 SQL、参数和预设返回值。"""

    def __init__(self, *, rows=None, row=None, rowcount=1):
        self.rows = list(rows or [])
        self.row = row
        self.rowcount = rowcount
        self.executions = []

    def execute(self, sql, params=None):
        """记录一次查询，不解释 SQL。"""
        self.executions.append((sql, params))

    def fetchall(self):
        """返回预设列表。"""
        return list(self.rows)

    def fetchone(self):
        """返回预设单行。"""
        return self.row


class FakeConnection:
    """提供数据库上下文和事务计数的最小连接替身。"""

    def __init__(self, cursor):
        self.cursor_value = cursor
        self.commits = 0
        self.rollbacks = 0
        self.started_transactions = 0

    def __enter__(self):
        """进入连接上下文。"""
        return self

    def __exit__(self, exc_type, exc, traceback):
        """保留异常给调用方处理。"""
        return False

    def cursor(self, **_kwargs):
        """返回固定游标。"""
        return self.cursor_value

    def commit(self):
        """记录事务提交。"""
        self.commits += 1

    def start_transaction(self):
        """记录显式主库事务开始。"""
        self.started_transactions += 1

    def rollback(self):
        """记录事务回滚。"""
        self.rollbacks += 1


class AdminBusinessServiceTests(unittest.TestCase):
    """验证真实查询服务的脱敏、有界读取和文件副作用边界。"""

    def test_file_delete_impact_hides_internal_blob_object_id(self):
        """删除预览可以返回引用统计，但不能返回 BLOB 对象主键。"""
        class ImpactCursor:
            def __init__(self):
                self.rows = [
                    {
                        "id": 3,
                        "user_id": 7,
                        "username": "admin",
                        "object_id": 99,
                        "filename": "report.csv",
                        "original_filename": "report.csv",
                        "file_hash": "a" * 64,
                        "mime_type": "text/csv",
                        "file_size": 12,
                        "upload_timestamp": datetime(2026, 7, 26, 12, 0, 0),
                        "last_accessed_at": None,
                        "access_count": 0,
                        "object_reference_count": 1,
                    },
                    {"count_value": 0},
                ]

            def execute(self, _sql, _params=None):
                pass

            def fetchone(self):
                return self.rows.pop(0)

        cursor = ImpactCursor()
        with patch(
            "app.admin.write_service.get_read_connection",
            return_value=FakeConnection(cursor),
        ):
            result = write_service.get_file_delete_impact(3)

        self.assertNotIn("object_id", result["file"])

    def test_job_list_uses_created_index_order_and_omits_error_body(self):
        """任务列表必须与新增创建时间索引同序且不返回错误正文摘要。"""
        created = datetime(2026, 7, 26, 12, 0, 0)
        cursor = FakeCursor(rows=[
            {
                "row_id": 9,
                "job_id": "job-9",
                "user_id": 1,
                "username": "alice",
                "session_id": "session-1",
                "status": "failed",
                "worker_id": None,
                "attempt_count": 3,
                "max_attempts": 3,
                "has_result": 0,
                "locked_at": None,
                "heartbeat_at": None,
                "created_at": created,
                "started_at": None,
                "finished_at": created,
                "chat_saved_at": None,
            },
            {
                "row_id": 8,
                "job_id": "job-8",
                "created_at": created,
                "has_result": 0,
            },
        ])
        with patch(
            "app.admin.business_service.get_read_connection",
            return_value=FakeConnection(cursor),
        ):
            result = business_service.list_jobs(
                limit=1,
                cursor=None,
                q=None,
                status=None,
                user_id=None,
                session_id=None,
            )

        sql = cursor.executions[0][0]
        self.assertIn("ORDER BY j.created_at DESC, j.id DESC", sql)
        self.assertNotIn("error_message", sql)
        self.assertNotIn("last_error", sql)
        self.assertNotIn("error_preview", result["items"][0])
        self.assertEqual(
            decode_cursor(result["next_cursor"], size=2),
            ["2026-07-26T12:00:00.000", 9],
        )

    def test_message_list_returns_length_summary_without_body_prefix(self):
        """消息列表不得因正文较短而把完整内容作为所谓摘要返回。"""
        cursor = FakeCursor(
            rows=[
                {
                    "id": 11,
                    "session_id": "session-1",
                    "user_id": 1,
                    "username": "alice",
                    "message_type": "user",
                    "content_preview": "正文 27 字符",
                    "content_length": 27,
                    "has_attachment": 0,
                    "created_at": datetime(2026, 7, 26, 12, 0, 0),
                    "attachment_count": 0,
                }
            ],
            row={"present": 1},
        )
        with patch(
            "app.admin.business_service.get_read_connection",
            return_value=FakeConnection(cursor),
        ):
            result = business_service.list_session_messages(
                session_id="session-1",
                limit=20,
                cursor=None,
                message_type=None,
            )

        sql = cursor.executions[1][0]
        self.assertIn("CONCAT('正文 ', CHAR_LENGTH(m.content), ' 字符')", sql)
        self.assertNotIn("LEFT(m.content", sql)
        self.assertEqual(result["items"][0]["content_preview"], "正文 27 字符")

    def test_file_list_uses_upload_time_cursor_matching_new_index(self):
        """文件分页的排序和游标必须与 user_files.uploaded_at 索引一致。"""
        uploaded = datetime(2026, 7, 26, 13, 0, 0)
        cursor = FakeCursor(rows=[
            {
                "id": 5,
                "user_id": 1,
                "username": "alice",
                "filename": "report.csv",
                "mime_type": "text/csv",
                "file_size": 10,
                "upload_timestamp": uploaded,
                "last_accessed_at": uploaded,
                "access_count": 0,
            },
            {"id": 4, "upload_timestamp": uploaded},
        ])
        with patch(
            "app.admin.business_service.get_read_connection",
            return_value=FakeConnection(cursor),
        ):
            result = business_service.list_files(
                limit=1,
                cursor=None,
                q=None,
                user_id=None,
                mime_type=None,
            )

        self.assertIn(
            "ORDER BY f.uploaded_at DESC, f.id DESC",
            cursor.executions[0][0],
        )
        self.assertEqual(
            decode_cursor(result["next_cursor"], size=2),
            ["2026-07-26T13:00:00.000", 5],
        )

    def test_multibyte_content_chunk_never_exceeds_64_kib_or_splits_character(self):
        """中文正文必须按源字节分块，并把 next_offset 对齐到完整字符。"""
        raw = ("中" * 22000).encode("utf-8")
        cursor = FakeCursor(row={
            "content": raw[:business_service.CSV_PREVIEW_BYTES],
            "total_length": len(raw),
        })
        with patch(
            "app.admin.business_service.get_read_connection",
            return_value=FakeConnection(cursor),
        ):
            result = business_service.get_message_content(
                10,
                offset=0,
                limit=64 * 1024,
            )

        returned = result["content"].encode("utf-8")
        self.assertLessEqual(len(returned), 64 * 1024)
        self.assertEqual(len(returned) % 3, 0)
        self.assertEqual(result["next_offset"], len(returned))
        self.assertFalse(result["complete"])
        self.assertEqual(cursor.executions[0][1][1], 64 * 1024 + 4)

    def test_csv_preview_applies_all_limits_then_records_access(self):
        """CSV 仅返回 100 行、50 列和 1000 字符单元格并在成功后记账。"""
        header = ",".join(f"c{index}" for index in range(51))
        long_row = ",".join(["x" * 1001] * 51)
        csv_bytes = (
            header
            + "\n"
            + long_row
            + "\n"
            + "\n".join(["1,2"] * 101)
        ).encode("utf-8")
        cursor = FakeCursor(row={
            "id": 3,
            "original_filename": "limits.csv",
            "mime_type": "text/csv",
            "file_size": len(csv_bytes),
            "preview_content": csv_bytes[: business_service.CSV_PREVIEW_BYTES + 4],
        })
        actor = {"id": 7, "username": "admin"}
        with (
            patch(
                "app.admin.business_service.get_write_connection",
                return_value=FakeConnection(cursor),
            ),
            patch("app.admin.business_service._record_file_access") as record_access,
        ):
            result = business_service.preview_file_csv(3, actor=actor)

        self.assertEqual(len(result["rows"]), 100)
        self.assertLessEqual(len(result["columns"]), 50)
        self.assertTrue(all(len(row) <= 50 for row in result["rows"]))
        self.assertTrue(
            all(len(cell) <= 1000 for row in result["rows"] for cell in row)
        )
        self.assertTrue(result["truncated"])
        record_access.assert_called_once_with(
            file_id=3,
            actor=actor,
            action="business.file.preview",
            cursor=cursor,
        )

    def test_file_access_count_and_audit_share_one_transaction(self):
        """访问计数和审计必须使用同一游标且只提交一次。"""
        cursor = FakeCursor(rowcount=1)
        connection = FakeConnection(cursor)
        actor = {"id": 7, "username": "admin"}
        with (
            patch(
                "app.admin.business_service.get_write_connection",
                return_value=connection,
            ),
            patch(
                "app.admin.business_service.insert_admin_audit_event",
            ) as insert_audit,
            patch(
                "app.admin.business_service.get_request_id",
                return_value="file-access-1",
            ),
        ):
            business_service._record_file_access(
                file_id=3,
                actor=actor,
                action="business.file.download",
            )

        self.assertIn("access_count = access_count + 1", cursor.executions[0][0])
        insert_audit.assert_called_once()
        self.assertIs(insert_audit.call_args.args[0], cursor)
        self.assertEqual(insert_audit.call_args.kwargs["request_id"], "file-access-1")
        self.assertEqual(connection.commits, 1)

    def test_file_access_audit_failure_closes_without_commit(self):
        """审计写入异常时不得提交已经增加的访问计数。"""
        cursor = FakeCursor(rowcount=1)
        connection = FakeConnection(cursor)
        with (
            patch(
                "app.admin.business_service.get_write_connection",
                return_value=connection,
            ),
            patch(
                "app.admin.business_service.insert_admin_audit_event",
                side_effect=RuntimeError("audit offline"),
            ),
        ):
            with self.assertRaises(AdminApiError) as context:
                business_service._record_file_access(
                    file_id=3,
                    actor={"id": 7, "username": "admin"},
                    action="business.file.preview",
                )

        self.assertEqual(context.exception.code, "audit_unavailable")
        self.assertEqual(connection.commits, 0)


if __name__ == "__main__":
    unittest.main()
