"""ToolRuntime identity, terminal Ledger and Command State update tests."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from Agent.deep_agent import AgentRunContext, TrustedJobIdentity
from Agent.deep_agent.state import ProjectDeepAgentState
from Agent.deep_agent.memory import build_in_memory_backend
from Agent.deep_agent_tools import (
    DataProfile,
    FakeAlgorithmExecutor,
    RagEvidenceTool,
    SafeErrorCode,
    WebEvidenceTool,
    build_algorithm_tools,
    build_default_registry,
)
from Agent.deep_agent_tools.adapters import build_default_adapters


IDENTITY = TrustedJobIdentity(
    job_id="00000000-0000-0000-0000-000000000001",
    session_id="00000000-0000-0000-0000-000000000002",
    user_id=7,
    attempt_count=0,
    lease_epoch=1,
    worker_id="worker-1",
    input_identity="input-sha",
)


def _context(executor=None) -> AgentRunContext:
    return AgentRunContext(
        execution_guard=None,
        trusted_identity=IDENTITY,
        algorithm_executor=executor or FakeAlgorithmExecutor(),
    )


def _runtime(context: AgentRunContext, *, call_id: str):
    return SimpleNamespace(
        tool_call_id=call_id,
        state={"message_execution_id": "message-execution-1"},
        context=context,
    )


def _algorithm_tool(*, executor: FakeAlgorithmExecutor):
    context = _context(executor)
    registry = build_default_registry(
        build_default_adapters(
            executor=executor,
            raw_backend=build_in_memory_backend(user_id=7),
        )
    )
    tools = build_algorithm_tools(
        registry,
        runtime_context=context,
        data_profile=DataProfile(
            row_count=100,
            column_count=2,
            column_names=("x", "y"),
            numeric_columns=("x", "y"),
        ),
    )
    wrapped = next(tool for tool in tools if tool.name == "causal_pc").to_langchain_tool()
    return context, wrapped


def test_algorithm_langchain_tool_writes_result_and_terminal_ledger() -> None:
    context, tool = _algorithm_tool(executor=FakeAlgorithmExecutor())

    command = asyncio.run(
        tool.coroutine(
            runtime=_runtime(context, call_id="provider-call-1"),
            alpha=0.05,
        )
    )

    assert "runtime" not in tool.tool_call_schema.model_json_schema()["properties"]
    result = next(iter(command.update["algorithm_results"].values()))
    ledger = next(iter(command.update["action_ledger"].values()))
    assert result.status == "valid"
    assert ledger.provider_call_id == "provider-call-1"
    assert ledger.response_identity_source == "message_execution_id"
    assert ledger.final_status == "succeeded"
    assert ledger.result_ref == result.result_ref
    assert ledger.attempts[0].revision == 2
    assert ledger.attempts[0].status == "succeeded"
    assert command.update["messages"][0].tool_call_id == "provider-call-1"


def test_tool_node_injects_runtime_and_reducers_commit_command_update() -> None:
    context, tool = _algorithm_tool(executor=FakeAlgorithmExecutor())
    builder = StateGraph(ProjectDeepAgentState, context_schema=AgentRunContext)
    builder.add_node("tools", ToolNode([tool], handle_tool_errors=False))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile()

    state = asyncio.run(
        graph.ainvoke(
            {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "causal_pc",
                                "args": {"alpha": 0.05},
                                "id": "tool-node-call-1",
                                "type": "tool_call",
                            }
                        ],
                    )
                ],
                "message_execution_id": "message-execution-1",
                "algorithm_results": {},
                "action_ledger": {},
                "rag_evidence": {},
                "web_evidence": {},
            },
            context=context,
        )
    )

    assert state["algorithm_results"], state["messages"][-1].content
    result = next(iter(state["algorithm_results"].values()))
    ledger = next(iter(state["action_ledger"].values()))
    assert result.status == "valid"
    assert ledger.provider_call_id == "tool-node-call-1"
    assert ledger.result_ref == result.result_ref
    assert state["messages"][-1].tool_call_id == "tool-node-call-1"


def test_algorithm_execution_failed_is_returned_and_recorded() -> None:
    executor = FakeAlgorithmExecutor(
        failures={"causal.pc": SafeErrorCode.ALGORITHM_EXECUTION_FAILED}
    )
    context, tool = _algorithm_tool(executor=executor)

    command = asyncio.run(
        tool.coroutine(
            runtime=_runtime(context, call_id="provider-call-failed"),
            alpha=0.05,
        )
    )

    result = next(iter(command.update["algorithm_results"].values()))
    ledger = next(iter(command.update["action_ledger"].values()))
    message_payload = json.loads(command.update["messages"][0].content)
    assert result.status == "execution_failed"
    assert message_payload["status"] == "execution_failed"
    assert ledger.final_status == "failed"
    assert ledger.result_ref == result.result_ref
    assert ledger.attempts[0].safe_error_code == "ALGORITHM_EXECUTION_FAILED"


def test_rag_and_web_tools_write_evidence_and_terminal_ledgers() -> None:
    context = _context()

    class Retriever:
        def get_evidence(self, query, *, max_contexts=None):
            return {
                "status": "available",
                "evidence": [
                    {"evidence_ref": "rag:1", "snippet": "RAG evidence"}
                ],
            }

    rag_tool = RagEvidenceTool(Retriever()).to_langchain_tool()
    rag_command = asyncio.run(
        rag_tool.coroutine(
            runtime=_runtime(context, call_id="rag-call-1"),
            query="causal inference",
        )
    )
    assert set(rag_command.update["rag_evidence"]) == {"rag:1"}
    rag_ledger = next(iter(rag_command.update["action_ledger"].values()))
    assert rag_ledger.final_status == "succeeded"

    def search(query, *, max_results):
        return {
            "results": [
                {
                    "source": "arxiv",
                    "title": "Paper",
                    "url": "https://example.invalid/paper",
                    "snippet": "Web evidence",
                }
            ]
        }

    web_tool = WebEvidenceTool(search).to_langchain_tool()
    web_command = asyncio.run(
        web_tool.coroutine(
            runtime=_runtime(context, call_id="web-call-1"),
            query="causal inference",
        )
    )
    assert len(web_command.update["web_evidence"]) == 1
    web_ledger = next(iter(web_command.update["action_ledger"].values()))
    assert web_ledger.final_status == "succeeded"


def test_evidence_unavailable_is_recorded_without_leaking_exception() -> None:
    context = _context()

    class BrokenRetriever:
        def get_evidence(self, query, *, max_contexts=None):
            raise RuntimeError("private failure")

    tool = RagEvidenceTool(BrokenRetriever()).to_langchain_tool()
    command = asyncio.run(
        tool.coroutine(
            runtime=_runtime(context, call_id="rag-call-failed"),
            query="q",
        )
    )
    ledger = next(iter(command.update["action_ledger"].values()))
    payload = json.loads(command.update["messages"][0].content)
    assert payload["status"] == "unavailable"
    assert "private failure" not in str(payload)
    assert ledger.final_status == "failed"
    assert ledger.attempts[0].safe_error_code == "RAG_RETRIEVAL_UNAVAILABLE"


def test_runtime_identity_has_no_static_fallback() -> None:
    context, tool = _algorithm_tool(executor=FakeAlgorithmExecutor())
    runtime = SimpleNamespace(
        tool_call_id=None,
        state={"message_execution_id": "message-execution-1"},
        context=context,
    )

    try:
        asyncio.run(tool.coroutine(runtime=runtime, alpha=0.05))
    except RuntimeError as exc:
        assert "tool_call_id" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("missing runtime identity must fail closed")
