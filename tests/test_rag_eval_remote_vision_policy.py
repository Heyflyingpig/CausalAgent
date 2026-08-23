"""验证上传来源在隔离评测中的远程视觉授权策略。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.rag_eval import isolated_runs


class RagEvalRemoteVisionPolicyTests(unittest.TestCase):
    def test_uploaded_source_is_authorized_for_remote_vision_by_default_in_internal_testing(self):
        """内测开关开启时，上传来源允许按策略进入远程视觉链路。"""
        with tempfile.TemporaryDirectory() as directory:
            uploaded = Path(directory) / "upload_example__private.pdf"
            uploaded.write_bytes(b"private")
            with patch.dict(os.environ, {"VISION_ALLOW_REMOTE_DATA": "true"}, clear=False):
                self.assertTrue(isolated_runs._remote_data_enabled_for_sources([uploaded]))
