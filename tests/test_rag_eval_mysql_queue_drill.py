"""队列演练脚本的参数解析与安全检查单元测试"""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


class RagEvalMysqlQueueDrillTests(unittest.TestCase):
    def test_requires_explicit_drill_environment_flag(self):
        from scripts.run_rag_eval_mysql_queue_drill import require_drill_environment

        with patch.dict(os.environ, {"RAG_EVAL_DRILL": ""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "RAG_EVAL_DRILL"):
                require_drill_environment()

    def test_accepts_explicit_drill_environment_flag(self):
        from scripts.run_rag_eval_mysql_queue_drill import require_drill_environment

        with patch.dict(os.environ, {"RAG_EVAL_DRILL": "true"}, clear=False):
            require_drill_environment()

    def test_direct_script_execution_reaches_environment_guard(self):
        completed = subprocess.run(
            [sys.executable, str(Path.cwd() / "scripts/run_rag_eval_mysql_queue_drill.py"), "--output", "ignored.json"],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": "", "RAG_EVAL_DRILL": ""},
            cwd="/tmp",
            check=False,
        )
        self.assertIn("RAG_EVAL_DRILL=true", completed.stderr)
