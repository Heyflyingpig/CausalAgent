"""预发 Compose 的 TCP readiness 与远程 VLM 注入契约。"""

from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class StagingComposeContractTests(unittest.TestCase):
    def test_mysql_readiness_uses_tcp_port_not_init_socket(self) -> None:
        expected = 'mysqladmin ping --protocol=tcp -h 127.0.0.1 -P 3306 -u root'
        for filename in (
            "docker-compose.yml",
            "docker-compose.prod.yml",
            "docker-compose.replica.yml",
            "docker-compose.staging.yml",
            "docker-compose.rag-eval-drill.yml",
        ):
            with self.subTest(filename=filename):
                self.assertIn(expected, (REPOSITORY_ROOT / filename).read_text(encoding="utf-8"))

    def test_staging_requires_remote_vlm_credentials_when_egress_is_enabled(self) -> None:
        compose = (REPOSITORY_ROOT / "docker-compose.staging.yml").read_text(encoding="utf-8")
        example = (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8")

        self.assertIn('VISION_ALLOW_REMOTE_DATA: "true"', compose)
        self.assertIn("VISION_API_KEY: ${VISION_API_KEY:?", compose)
        self.assertIn("VISION_BASE_URL: ${VISION_BASE_URL:?", compose)
        self.assertIn("VISION_MODEL: ${VISION_MODEL:-qwen/qwen3-vl-8b-instruct}", compose)
        for key in ("VISION_API_KEY=", "VISION_BASE_URL=", "VISION_MODEL=qwen/qwen3-vl-8b-instruct"):
            self.assertIn(key, example)
