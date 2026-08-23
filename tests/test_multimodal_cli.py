"""多模态维护 CLI 的公开命令契约。"""

import unittest

from Agent.knowledge_base.multimodal.cli import build_parser


class MultimodalCliTests(unittest.TestCase):
    def test_exposes_only_current_maintenance_commands(self):
        commands = set(build_parser()._subparsers._group_actions[0].choices)

        self.assertFalse({"omnidocbench-audit", "omnidocbench-evaluate", "omnidocbench-export-official"} & commands)
        self.assertTrue({"inspect", "ingest", "run", "evaluate", "publish", "status", "rollback"} <= commands)
