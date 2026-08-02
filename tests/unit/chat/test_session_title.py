"""会话标题生成规则回归测试。"""

import unittest

from app.chat.session_title import (
    DEFAULT_SESSION_TITLE,
    MAX_SESSION_TITLE_LENGTH,
    build_session_title,
)


class SessionTitleTests(unittest.TestCase):
    """验证标题内容完整性和数据库长度边界。"""

    def test_upload_filename_is_not_truncated_to_eight_characters(self):
        """文件上传消息应完整保留文件名，前端自行负责视觉省略。"""
        message = "上传文件: causal_analysis_dataset_2026.csv"

        self.assertEqual(build_session_title(message), message)

    def test_title_is_normalized_to_one_line(self):
        """标题应压平换行和连续空白，避免破坏列表布局。"""
        self.assertEqual(build_session_title("  第一行\n  第二行  "), "第一行 第二行")

    def test_title_only_truncates_at_database_limit(self):
        """超过 VARCHAR(500) 上限时保留明确省略标记且不越界。"""
        title = build_session_title("数" * (MAX_SESSION_TITLE_LENGTH + 20))

        self.assertEqual(len(title), MAX_SESSION_TITLE_LENGTH)
        self.assertTrue(title.endswith("…"))

    def test_empty_message_uses_default_title(self):
        """空白首条消息应回退为可识别的默认标题。"""
        self.assertEqual(build_session_title(" \n\t "), DEFAULT_SESSION_TITLE)


if __name__ == "__main__":
    unittest.main()
