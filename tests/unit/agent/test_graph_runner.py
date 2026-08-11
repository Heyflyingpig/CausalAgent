from types import SimpleNamespace
import unittest
from unittest.mock import patch

from langgraph.types import Command

from app.agent.checkpoint_recovery import checkpoint_identity
from app.agent.worker.graph_runner import ai_call_stream


class FakeGraph:
    """提供最小 compiled graph 协议，验证 Job root checkpoint 配置。"""

    def __init__(self, states):
        self.states = list(states)
        self.configs = []
        self.inputs = []

    async def aget_state(self, config):
        """按调用顺序返回 root StateSnapshot。"""
        self.configs.append(config)
        return self.states.pop(0)

    async def astream(self, input_data, config, **_kwargs):
        """记录执行输入，不产生额外公开事件。"""
        self.inputs.append((input_data, config))
        if False:
            yield {}


def _snapshot(*, interrupts=(), public_interrupts=None, values=None):
    """构造 graph_runner 所需的最小 StateSnapshot。"""
    return SimpleNamespace(
        interrupts=public_interrupts,
        tasks=tuple(SimpleNamespace(interrupts=items) for items in interrupts),
        values=values or {"messages": []},
        created_at=None,
        metadata={},
        config={},
        next=(),
    )


async def _collect(graph, text="hello", *, claim_kind="initial", input_record=None, initial_input_record=None, **file_snapshot):
    """收集一次 Job 执行产生的公开事件。"""
    return [
        event
        async for event in ai_call_stream(
            text,
            7,
            "user-7",
            "session-1",
            job_id="job-1",
            job_attempt=1,
            input_user_file_id=file_snapshot.get("input_user_file_id"),
            input_object_id=file_snapshot.get("input_object_id"),
            input_file_hash=file_snapshot.get("input_file_hash"),
            input_filename=file_snapshot.get("input_filename"),
            graph=graph,
            claim_kind=claim_kind,
            input_record=input_record,
            initial_input_record=initial_input_record,
        )
    ]


class GraphRunnerTests(unittest.IsolatedAsyncioTestCase):
    """验证 Job root State 查询、输入边界和 stale recovery。"""

    async def test_job_root_identity_is_not_a_subgraph_namespace(self):
        """普通问答的两次状态查询都必须使用 Job ID 根 identity。"""
        graph = FakeGraph([
            _snapshot(),
            _snapshot(values={"messages": []}),
        ])

        events = await _collect(graph)

        self.assertEqual(events[-1]["type"], "final_result")
        self.assertEqual(len(graph.configs), 2)
        for config in graph.configs:
            self.assertEqual(config["configurable"]["thread_id"], "job-1")
            self.assertNotIn("checkpoint_ns", config["configurable"])
            self.assertEqual(config["metadata"]["job_id"], "job-1")
            self.assertEqual(config["metadata"]["session_id"], "session-1")

    def test_checkpoint_identity_requires_job_id_and_keeps_root_namespace_empty(self):
        """运行时和恢复查询共用 Job ID 根 identity，不能生成 unknown namespace。"""
        self.assertEqual(checkpoint_identity("job-1"), ("job-1", ""))
        with self.assertRaises(ValueError):
            checkpoint_identity(" ")

    async def test_public_snapshot_interrupts_are_used_for_resume(self):
        """优先读取 LangGraph 公共 interrupts 字段，兼容根 checkpoint 恢复。"""
        interrupt = SimpleNamespace(id="question-public", value="请补充信息")
        graph = FakeGraph([
            _snapshot(public_interrupts=(interrupt,)),
            _snapshot(public_interrupts=(interrupt,)),
        ])

        events = await _collect(
            graph,
            input_record={
                "input_type": "resume",
                "runtime_value": "补充回答",
                "stored_text": "补充回答",
                "chat_message_id": 42,
            },
        )

        self.assertEqual(events[-1]["type"], "interrupt")
        self.assertIsInstance(graph.inputs[0][0], Command)

    async def test_same_job_resume_uses_existing_state_and_structured_value(self):
        """同一 Job 的 interrupt 恢复必须继续原 State，并保留结构化回答。"""
        interrupt = SimpleNamespace(id="question-1", value={"target": "sales"})
        graph = FakeGraph([
            _snapshot(interrupts=((interrupt,),)),
            _snapshot(interrupts=((interrupt,),)),
        ])

        events = await _collect(
            graph,
            input_record={
                "input_type": "resume",
                "runtime_value": {"target": "revenue"},
                "stored_text": '{"target":"revenue"}',
                "chat_message_id": 42,
            },
        )

        self.assertEqual(events[-1]["type"], "interrupt")
        self.assertIsInstance(graph.inputs[0][0], Command)
        self.assertEqual(graph.inputs[0][0].resume, {"target": "revenue"})
        self.assertIs(graph.inputs[0][1], graph.configs[0])

    async def test_initial_state_uses_job_history_without_appending_current_message(self):
        """初始输入从 chat_message_id 截止的历史启动，当前消息不额外追加。"""
        history = [
            SimpleNamespace(type="human", content="旧问题"),
            SimpleNamespace(type="ai", content="旧回答"),
            SimpleNamespace(type="human", content="当前问题"),
        ]
        graph = FakeGraph([_snapshot(), _snapshot(values={"messages": []})])
        with patch(
            "app.agent.worker.graph_runner.get_job_chat_history",
            return_value=history,
        ):
            await _collect(
                graph,
                input_record={
                    "input_type": "initial",
                    "runtime_value": "当前问题",
                    "stored_text": "当前问题",
                    "chat_message_id": 99,
                },
            )

        self.assertEqual(graph.inputs[0][0]["messages"], history)
        self.assertEqual(
            [message.content for message in graph.inputs[0][0]["messages"]],
            ["旧问题", "旧回答", "当前问题"],
        )

    async def test_initial_state_groups_frozen_file_snapshot_under_file_summary(self):
        """新 Job 初始 State 将冻结文件四元组写入 file_summary。"""
        graph = FakeGraph([
            _snapshot(),
            _snapshot(values={"messages": []}),
        ])

        await _collect(
            graph,
            input_user_file_id=11,
            input_object_id=22,
            input_file_hash="a" * 64,
            input_filename="data.csv",
        )

        input_data = graph.inputs[0][0]
        self.assertEqual(
            input_data["file_summary"],
            {
                "user_file_id": 11,
                "object_id": 22,
                "file_hash": "a" * 64,
                "filename": "data.csv",
            },
        )
        self.assertNotIn("input_user_file_id", input_data)
        self.assertNotIn("input_object_id", input_data)
        self.assertNotIn("input_file_hash", input_data)
        self.assertNotIn("input_filename", input_data)

    async def test_stale_recovery_with_checkpoint_uses_none_input(self):
        """stale recovery 有 checkpoint 时继续原 State，不追加原始问题。"""
        graph = FakeGraph([
            SimpleNamespace(
                tasks=(),
                values={"messages": ["existing"]},
                created_at="2026-08-08T00:00:00Z",
                metadata={"source": "loop"},
                config={"configurable": {"checkpoint_id": "cp-1"}},
                next=("agent",),
            ),
            _snapshot(values={"messages": []}),
        ])

        await _collect(graph, claim_kind="stale_recovery")

        self.assertIsNone(graph.inputs[0][0])

    async def test_stale_recovery_after_resume_uses_existing_checkpoint(self):
        """恢复输入执行中失联时，不能因最后一条输入是 resume 而误判失败。"""
        graph = FakeGraph([
            SimpleNamespace(
                tasks=(),
                values={"messages": ["existing"]},
                created_at="2026-08-08T00:00:00Z",
                metadata={"source": "loop"},
                config={"configurable": {"checkpoint_id": "cp-2"}},
                next=("agent",),
            ),
            _snapshot(values={"messages": []}),
        ])

        await _collect(
            graph,
            claim_kind="stale_recovery",
            input_record={
                "input_type": "resume",
                "runtime_value": "补充回答",
                "stored_text": "补充回答",
                "chat_message_id": 43,
            },
        )

        self.assertIsNone(graph.inputs[0][0])

    async def test_stale_recovery_without_checkpoint_reuses_initial_input(self):
        """stale recovery 没有 checkpoint 时只重用序号 0 的初始消息窗口。"""
        history = [SimpleNamespace(type="human", content="初始问题")]
        graph = FakeGraph([_snapshot(), _snapshot(values={"messages": []})])
        with patch(
            "app.agent.worker.graph_runner.get_job_chat_history",
            return_value=history,
        ):
            await _collect(
                graph,
                claim_kind="stale_recovery",
                input_record={
                    "input_type": "initial",
                    "runtime_value": "初始问题",
                    "stored_text": "初始问题",
                    "chat_message_id": 11,
                },
            )

        self.assertEqual(graph.inputs[0][0]["messages"], history)

    async def test_resume_without_pending_interrupt_is_rejected(self):
        """没有 interrupt 时不能把 resume 答案重新当作新问题执行。"""
        graph = FakeGraph([_snapshot()])
        with self.assertRaisesRegex(RuntimeError, "resume 输入没有对应"):
            await _collect(
                graph,
                input_record={
                    "input_type": "resume",
                    "runtime_value": "回答",
                    "stored_text": "回答",
                    "chat_message_id": 43,
                },
            )

    async def test_state_read_failure_does_not_fallback_to_new_conversation(self):
        """checkpoint 读取失败时不能静默丢失同一 Job 的上下文。"""

        class BrokenGraph(FakeGraph):
            async def aget_state(self, _config):
                raise RuntimeError("checkpoint unavailable")

        with self.assertRaisesRegex(RuntimeError, "checkpoint unavailable"):
            await _collect(BrokenGraph([]))
