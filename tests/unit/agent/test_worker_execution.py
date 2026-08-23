"""验证 run_job 在失败/取消竞态和 cleanup fencing 下的收敛。"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch


for _key, _value in {
    "SECRET_KEY": "test-secret",
    "API_KEY": "test-api-key",
    "BASE_URL": "https://example.test",
    "MODEL": "test-model",
    "MYSQL_HOST": "test-mysql",
    "MYSQL_USER": "test-user",
    "MYSQL_PASSWORD": "test-password",
    "MYSQL_DATABASE": "test-database",
}.items():
    os.environ.setdefault(_key, _value)

from app.agent.job_service import FailJobResult  # noqa: E402
from app.agent.worker import execution  # noqa: E402
from app.agent.worker.execution_guard import JobExecutionRevoked  # noqa: E402


def _job() -> dict:
    """构造当前 worker lease 的最小 Job。"""
    return {
        "job_id": "job-1",
        "user_id": 7,
        "session_id": "session-1",
        "attempt_count": 2,
        "lease_epoch": 9,
        "claim_kind": "initial",
    }


class FakeWriter:
    """只记录 run_job 需要的 writer cleanup 行为。"""

    def __init__(self, job, worker_id, execution_guard=None):
        self.terminal_seen = False
        self.abort_calls = []
        self.close_calls = 0

    async def submit(self, payload):
        raise AssertionError("graph failure test should fail before submitting an event")

    async def close(self):
        self.close_calls += 1

    async def abort(self, error=None):
        self.abort_calls.append(error)


class FailingCleanupWriter(FakeWriter):
    """模拟 consumer 已经失败，abort 必须报告 cleanup failure。"""

    async def abort(self, error=None):
        self.abort_calls.append(error)
        raise RuntimeError("event consumer cleanup failed")


async def _failing_graph():
    """产生一个没有事件输出的 graph 异常。"""
    raise RuntimeError("graph failed")
    yield  # pragma: no cover


async def _blocking_graph():
    """保持 graph 调用悬挂，供 task-level CancelledError 测试 cleanup。"""
    await asyncio.Event().wait()
    yield  # pragma: no cover


class WorkerExecutionTests(IsolatedAsyncioTestCase):
    """验证 run_job 不会在取消获胜后再次写普通失败。"""

    def _patch_common(self, writer_cls):
        writer = writer_cls(_job(), "worker-a")
        patches = (
            patch("app.agent.worker.execution.OrderedEventWriter", return_value=writer),
            patch("app.agent.worker.execution.ai_call_stream", return_value=_failing_graph()),
            patch(
                "app.agent.worker.execution.heartbeat_until_stopped",
                new=AsyncMock(),
            ),
            patch(
                "app.agent.worker.execution.JobExecutionGuard.ensure_active",
                new=AsyncMock(),
            ),
            patch(
                "app.agent.worker.execution.JobExecutionGuard.check_after_call",
                new=AsyncMock(),
            ),
            patch(
                "app.agent.worker.execution.job_service.get_latest_input_value",
                return_value={
                    "input_type": "initial",
                    "runtime_value": "hello",
                    "stored_text": "hello",
                    "chat_message_id": 1,
                },
            ),
        )
        return writer, patches

    async def test_canceled_fencing_does_not_call_fail_job_again(self):
        """graph 异常后若 cancel 先提交，run_job 只走撤销释放路径。"""
        writer, patches = self._patch_common(FakeWriter)
        fail_job = Mock(return_value=FailJobResult.CANCELED_FENCED)
        release = Mock(return_value=True)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patch(
            "app.agent.worker.execution.job_service.fail_job",
            fail_job,
        ), patch(
            "app.agent.worker.execution.job_service.release_execution_ownership",
            release,
        ):
            await execution.run_job(_job(), SimpleNamespace(graph=object(), mcp_tools=[]), "worker-a")

        fail_job.assert_called_once()
        self.assertEqual(len(writer.abort_calls), 1)
        release.assert_called_once_with("job-1", "worker-a", 2, 9)

    async def test_cleanup_failure_keeps_draining_without_worker_confirmed_release(self):
        """EventWriter cleanup 失败时不能伪造 worker_confirmed 释放。"""
        writer, patches = self._patch_common(FailingCleanupWriter)
        fail_job = Mock(return_value=FailJobResult.CANCELED_FENCED)
        release = Mock(return_value=True)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patch(
            "app.agent.worker.execution.job_service.fail_job",
            fail_job,
        ), patch(
            "app.agent.worker.execution.job_service.release_execution_ownership",
            release,
        ):
            await execution.run_job(_job(), SimpleNamespace(graph=object(), mcp_tools=[]), "worker-a")

        fail_job.assert_called_once()
        self.assertEqual(len(writer.abort_calls), 1)
        release.assert_not_called()

    async def test_task_cancellation_aborts_writer_before_release(self):
        """worker task 被取消时也必须结束 writer，再条件释放执行占用。"""
        writer, patches = self._patch_common(FakeWriter)
        patches = list(patches)
        patches[1] = patch(
            "app.agent.worker.execution.ai_call_stream",
            return_value=_blocking_graph(),
        )
        release = Mock(return_value=True)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patch(
            "app.agent.worker.execution.job_service.release_execution_ownership",
            release,
        ):
            task = asyncio.create_task(
                execution.run_job(
                    _job(),
                    SimpleNamespace(graph=object(), mcp_tools=[]),
                    "worker-a",
                )
            )
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertEqual(len(writer.abort_calls), 1)
        release.assert_called_once_with("job-1", "worker-a", 2, 9)
