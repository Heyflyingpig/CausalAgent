import asyncio
import os
import unittest
from unittest.mock import AsyncMock


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

from app.agent.worker import (  # noqa: E402
    OrderedEventWriter,
    TEXT_FLUSH_CHARACTER_LIMIT,
)


def build_job() -> dict:
    """构造不访问数据库的最小 worker job。"""
    return {"job_id": "job-1", "attempt_count": 2}


def text_chunk(delta: str, stream_id: str = "stream-1") -> dict:
    """构造 core 到 worker 的内部文字 chunk。"""
    return {
        "type": "text_chunk",
        "step_id": "step-1",
        "stream_id": stream_id,
        "node_name": "normal_chat",
        "title": "生成回答",
        "sequence": 1,
        "delta": delta,
        "attempt": 2,
    }


class OrderedEventWriterTests(unittest.IsolatedAsyncioTestCase):
    """验证文字批处理的时间、字符和事件边界。"""

    async def test_flushes_after_150ms_without_another_graph_event(self):
        """模型暂停时也必须由 timeout 主动刷新，而非等待下一事件。"""
        writer = OrderedEventWriter(build_job(), "worker-a")
        persisted = []
        writer._persist = AsyncMock(side_effect=lambda payload: persisted.append(payload))

        await writer.submit(text_chunk("hello"))
        await asyncio.sleep(0.20)
        await writer.close()

        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0]["type"], "text_delta")
        self.assertEqual(persisted[0]["delta"], "hello")

    async def test_150ms_is_measured_from_batch_start_not_last_chunk(self):
        """持续到达的小 token 也不能无限延后时间阈值。"""
        writer = OrderedEventWriter(build_job(), "worker-a")
        persisted = []
        writer._persist = AsyncMock(side_effect=lambda payload: persisted.append(payload))

        await writer.submit(text_chunk("a"))
        await asyncio.sleep(0.08)
        await writer.submit(text_chunk("b"))
        await asyncio.sleep(0.09)
        await writer.close()

        self.assertGreaterEqual(len(persisted), 1)
        self.assertEqual(persisted[0]["delta"], "ab")

    async def test_flushes_at_character_limit(self):
        """累计达到 384 字符时必须立即写入。"""
        writer = OrderedEventWriter(build_job(), "worker-a")
        persisted = []
        writer._persist = AsyncMock(side_effect=lambda payload: persisted.append(payload))

        await writer.submit(text_chunk("x" * TEXT_FLUSH_CHARACTER_LIMIT))
        await writer.close()

        self.assertEqual(len(persisted), 1)
        self.assertEqual(len(persisted[0]["delta"]), TEXT_FLUSH_CHARACTER_LIMIT)

    async def test_flushes_text_before_node_end_and_terminal_event(self):
        """阶段和终态事件不得越过尚未落库的文字。"""
        writer = OrderedEventWriter(build_job(), "worker-a")
        persisted = []
        writer._persist = AsyncMock(side_effect=lambda payload: persisted.append(payload))

        await writer.submit(text_chunk("draft"))
        await writer.submit({"type": "node_end", "step_id": "step-1"})
        await writer.submit({"type": "final_result", "data": {"summary": "draft"}})
        await writer.close()

        self.assertEqual(
            [payload["type"] for payload in persisted],
            ["text_delta", "node_end", "final_result"],
        )

    async def test_persisted_sequence_is_per_stream_and_not_token_sequence(self):
        """数据库 sequence 应按批次递增，不能沿用 token 序号。"""
        writer = OrderedEventWriter(build_job(), "worker-a")
        persisted = []
        writer._persist = AsyncMock(side_effect=lambda payload: persisted.append(payload))

        await writer.submit(text_chunk("a"))
        await writer.submit({"type": "progress", "step_id": "step-1"})
        second = text_chunk("b")
        second["sequence"] = 99
        await writer.submit(second)
        await writer.close()

        deltas = [payload for payload in persisted if payload["type"] == "text_delta"]
        self.assertEqual([payload["sequence"] for payload in deltas], [1, 2])


if __name__ == "__main__":
    unittest.main()
