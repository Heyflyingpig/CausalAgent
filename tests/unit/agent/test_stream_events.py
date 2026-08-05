import os
import unittest

from langchain_core.messages import AIMessage, AIMessageChunk
from langgraph.graph import END, StateGraph
from langgraph.types import RetryPolicy


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

from app.agent.core import LangGraphEventAdapter  # noqa: E402
from app.agent.routes import _public_event_payload  # noqa: E402
from Agent.causal_agent.graph_utils import bind_node, bind_runnable_node  # noqa: E402
from Agent.causal_agent.state import CausalAgentState  # noqa: E402


def task_start(task_id: str, name: str) -> dict:
    """构造 LangGraph v2 tasks 开始事件。"""
    return {
        "type": "tasks",
        "ns": (),
        "data": {"id": task_id, "name": name, "input": {}, "triggers": []},
    }


class StreamEventAdapterTests(unittest.TestCase):
    """验证多流转换不会暴露内部内容，并保持阶段和文字实例有序。"""

    def setUp(self):
        self.adapter = LangGraphEventAdapter("job-1", 3)

    def test_repeated_node_tasks_get_distinct_step_ids(self):
        """父图循环再次进入同名节点时必须创建新的阶段实例。"""
        first = self.adapter.convert(task_start("task-a", "agent"))[0]
        second = self.adapter.convert(task_start("task-b", "agent"))[0]

        self.assertNotEqual(first["step_id"], second["step_id"])
        self.assertEqual(first["attempt"], 3)

    def test_only_public_answer_nodes_emit_text_chunks(self):
        """planner 和 report token 必须被过滤，普通回答 token 保持顺序。"""
        self.adapter.convert(task_start("task-chat", "normal_chat"))
        planner = self.adapter.convert({
            "type": "messages",
            "ns": (),
            "data": (AIMessageChunk(content="hidden"), {"langgraph_node": "mcp_planner"}),
        })
        report = self.adapter.convert({
            "type": "messages",
            "ns": (),
            "data": (AIMessageChunk(content="hidden"), {"langgraph_node": "report"}),
        })
        first = self.adapter.convert({
            "type": "messages",
            "ns": (),
            "data": (AIMessageChunk(content="你"), {"langgraph_node": "normal_chat"}),
        })[0]
        second = self.adapter.convert({
            "type": "messages",
            "ns": (),
            "data": (AIMessageChunk(content="好"), {"langgraph_node": "normal_chat"}),
        })[0]

        self.assertEqual(planner, [])
        self.assertEqual(report, [])
        self.assertEqual((first["sequence"], second["sequence"]), (1, 2))
        self.assertEqual(first["stream_id"], second["stream_id"])

    def test_retry_is_only_emitted_after_next_attempt_starts(self):
        """最终失败不算重试，只有失败后确实再次开始才产生 node_retry。"""
        self.adapter.convert(task_start("task-chat", "normal_chat"))
        chunk = self.adapter.convert({
            "type": "messages",
            "ns": (),
            "data": (AIMessageChunk(content="draft"), {"langgraph_node": "normal_chat"}),
        })[0]
        failed = self.adapter.convert({
            "type": "custom",
            "ns": (),
            "data": {
                "type": "node_attempt_failed",
                "task_id": "task-chat",
                "node_name": "normal_chat",
                "error_kind": "TimeoutError",
            },
        })
        retried = self.adapter.convert({
            "type": "custom",
            "ns": (),
            "data": {
                "type": "node_attempt_start",
                "task_id": "task-chat",
                "node_name": "normal_chat",
                "node_attempt": 1,
            },
        })[0]

        self.assertEqual(failed, [])
        self.assertEqual(retried["type"], "node_retry")
        self.assertEqual(retried["message"], "调用超时")
        self.assertEqual(retried["discard_stream_id"], chunk["stream_id"])
        self.assertNotIn("node_attempt", retried)

    def test_decision_uses_explicit_state_not_message_content(self):
        """展示消息内容变化不得影响显式 State 路由事件。"""
        self.adapter.convert(task_start("task-agent", "agent"))
        events = self.adapter.convert({
            "type": "updates",
            "ns": (),
            "data": {
                "agent": {
                    "messages": [AIMessage(content="route: report")],
                    "route_decision": "fold",
                }
            },
        })

        self.assertEqual([event["type"] for event in events], ["progress", "decision"])
        self.assertIn("因果分析", events[0]["summary"])
        self.assertIn("加载文件", events[1]["summary"])

    def test_tool_details_expose_names_and_keys_but_not_values_or_results(self):
        """工具事件不得持久化凭据、地址、完整 JSON 或结果正文。"""
        self.adapter.convert(task_start("task-mcp", "mcp"))
        started = self.adapter.convert({
            "type": "updates",
            "ns": ("mcp:task-mcp",),
            "data": {
                "mcp_planner": {
                    "messages": [AIMessage(
                        content="",
                        tool_calls=[{
                            "id": "call-1",
                            "name": "causal_pc",
                            "args": {
                                "api_key": "secret-value",
                                "endpoint": "https://internal.example",
                            },
                        }],
                    )],
                }
            },
        })[0]
        finished = self.adapter.convert({
            "type": "updates",
            "ns": ("mcp:task-mcp",),
            "data": {
                "mcp_result_parser": {
                    "causal_analysis_result": {
                        "success": True,
                        "data": {"csv": "private file body"},
                        "_tool_call": {"name": "causal_pc"},
                    }
                }
            },
        })[0]

        self.assertEqual(started["argument_keys"], ["api_key", "endpoint"])
        self.assertNotIn("secret-value", repr(started))
        self.assertNotIn("internal.example", repr(started))
        self.assertEqual(finished["summary"], "调用完成")
        self.assertNotIn("private file body", repr(finished))

    def test_sse_public_payload_removes_backend_attempt(self):
        """job attempt 可以持久化，但不能进入普通用户 SSE 协议。"""
        payload = {"type": "node_start", "attempt": 4, "step_id": "opaque"}
        public = _public_event_payload(payload)

        self.assertNotIn("attempt", public)
        self.assertEqual(payload["attempt"], 4)


class RealLangGraphStreamTests(unittest.IsolatedAsyncioTestCase):
    """用锁定版 LangGraph 的真实图验证 tasks 与 custom attempt 流。"""

    async def test_tasks_wrap_whole_task_while_custom_exposes_retry(self):
        """一次内部 retry 应对应一组 task 生命周期和两次 attempt 开始。"""
        calls = 0

        async def flaky_node(state):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TimeoutError("private endpoint must not leak")
            return {"messages": [AIMessage(content="done", name="normal_chat")]}

        graph = StateGraph(CausalAgentState)
        graph.add_node(
            "normal_chat",
            bind_node(flaky_node, event_node_name="normal_chat"),
            retry_policy=RetryPolicy(
                initial_interval=0.001,
                backoff_factor=1.0,
                max_interval=0.001,
                max_attempts=2,
                jitter=False,
                retry_on=lambda _exc: True,
            ),
        )
        graph.set_entry_point("normal_chat")
        graph.add_edge("normal_chat", END)
        compiled = graph.compile()

        raw = [
            event
            async for event in compiled.astream(
                {"messages": []},
                stream_mode=["updates", "custom", "tasks"],
                subgraphs=True,
                version="v2",
            )
        ]
        task_events = [event for event in raw if event["type"] == "tasks"]
        custom = [event["data"] for event in raw if event["type"] == "custom"]

        self.assertEqual(calls, 2)
        self.assertEqual(len(task_events), 2)
        self.assertEqual(
            [event["type"] for event in custom],
            ["node_attempt_start", "node_attempt_failed", "node_attempt_start"],
        )
        self.assertEqual(custom[0]["task_id"], custom[2]["task_id"])

        adapter = LangGraphEventAdapter("job-real", 1)
        public_events = [converted for event in raw for converted in adapter.convert(event)]
        self.assertEqual(
            [event["type"] for event in public_events],
            ["node_start", "node_retry", "node_end"],
        )
        self.assertEqual(public_events[1]["message"], "调用超时")

    async def test_runnable_wrapper_preserves_langgraph_config(self):
        """ToolNode 包装器必须把 LangGraph config 原样传给底层 Runnable。"""
        received_config = None

        class FakeRunnable:
            """记录 ainvoke config 的最小 ToolNode 替身。"""

            async def ainvoke(self, state, config):
                nonlocal received_config
                received_config = config
                return {"messages": [AIMessage(content="tool done")]}

        graph = StateGraph(CausalAgentState)
        graph.add_node(
            "mcp_tool_node",
            bind_runnable_node(FakeRunnable(), event_node_name="mcp_tool_node"),
        )
        graph.set_entry_point("mcp_tool_node")
        graph.add_edge("mcp_tool_node", END)
        compiled = graph.compile()

        events = [
            event
            async for event in compiled.astream(
                {"messages": []},
                {"configurable": {"marker": "kept"}},
                stream_mode=["custom", "tasks"],
                version="v2",
            )
        ]

        self.assertEqual(received_config["configurable"]["marker"], "kept")
        custom = [event["data"] for event in events if event["type"] == "custom"]
        self.assertEqual(custom[0]["type"], "node_attempt_start")
        self.assertEqual(custom[0]["node_name"], "mcp_tool_node")


if __name__ == "__main__":
    unittest.main()
