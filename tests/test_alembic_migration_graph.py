"""Alembic revision 图必须保持单一、无重复的可升级 head。"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class AlembicMigrationGraphTests(unittest.TestCase):
    def test_heads_has_one_unique_merge_revision(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "heads"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("present more than once", result.stderr)
        heads = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(heads, ["s4d5e6f7a8b9 (head)"])
