import unittest
from unittest.mock import patch

from app.agent.job_service import (
    _decode_input_record,
    _normalize_input_value,
    _validate_input_text,
    get_active_jobs,
)


class _ActiveJobsCursor:
    """记录活动 Job 公共摘要查询，不提供文件对象正文。"""

    def __init__(self):
        self.sql = ""

    def execute(self, sql, _params=None):
        self.sql = sql

    def fetchall(self):
        return []


class _ActiveJobsConnection:
    """提供活动 Job 查询所需的最小连接上下文。"""

    def __init__(self, cursor):
        self.cursor_value = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def cursor(self, **_kwargs):
        return self.cursor_value


class JobInputValidationTests(unittest.TestCase):
    """验证普通消息和结构化恢复回答的边界。"""

    def test_structured_resume_value_is_stored_as_json_and_keeps_runtime_value(self):
        """受限对象可以进入输入账本，并在 worker 侧恢复为对象。"""
        stored, runtime = _normalize_input_value({"target": "revenue", "confirmed": True})

        self.assertEqual(stored, '{"target":"revenue","confirmed":true}')
        self.assertEqual(runtime, {"target": "revenue", "confirmed": True})

    def test_plain_multiline_question_is_allowed(self):
        """普通多行问题只受通用文本长度限制。"""
        text = _validate_input_text("请解释下面的问题：\n为什么相关性不代表因果？")

        self.assertEqual(text, "请解释下面的问题：\n为什么相关性不代表因果？")

    def test_structured_value_only_uses_generic_limits(self):
        """结构化值中的多行文本不再做 CSV 猜测。"""
        stored, runtime = _normalize_input_value({"data": "a,b\n1,2"})
        self.assertEqual(runtime, {"data": "a,b\n1,2"})
        self.assertEqual(stored, '{"data":"a,b\\n1,2"}')

    def test_initial_json_text_remains_text(self):
        """初始消息即使以 JSON 形状开头，也必须保持字符串。"""
        record = _decode_input_record({
            "input_type": "initial",
            "input_text": '{"target":"revenue"}',
            "chat_message_id": 12,
        })
        self.assertEqual(record["runtime_value"], '{"target":"revenue"}')
        self.assertEqual(record["stored_text"], '{"target":"revenue"}')

    def test_resume_json_object_is_decoded_only_for_runtime(self):
        """只有 resume 输入才把 JSON 对象解析为 Command 的运行时值。"""
        record = _decode_input_record({
            "input_type": "resume",
            "input_text": '{"target":"revenue"}',
            "chat_message_id": 13,
        })
        self.assertEqual(record["runtime_value"], {"target": "revenue"})
        self.assertEqual(record["stored_text"], '{"target":"revenue"}')

    def test_invalid_resume_json_stays_text(self):
        """非法 JSON 不猜测类型，保留原始字符串。"""
        record = _decode_input_record({
            "input_type": "resume",
            "input_text": '{invalid',
            "chat_message_id": 14,
        })
        self.assertEqual(record["runtime_value"], "{invalid")

    def test_active_job_public_summary_does_not_select_blob_object_id(self):
        """刷新恢复接口不应把内部 BLOB 对象 ID 放进公开摘要。"""
        cursor = _ActiveJobsCursor()
        with patch(
            "app.agent.job_service.get_read_connection",
            return_value=_ActiveJobsConnection(cursor),
        ):
            get_active_jobs(7)

        self.assertNotIn("input_object_id", cursor.sql)


if __name__ == "__main__":
    unittest.main()
