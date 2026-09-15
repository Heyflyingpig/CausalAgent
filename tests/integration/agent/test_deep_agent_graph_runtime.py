"""目标依赖存在时验证真实 Deep Agents graph 的最小构造契约。"""

from __future__ import annotations

import pytest


deepagents = pytest.importorskip("deepagents")
pytest.importorskip("langchain.agents.middleware")


def test_real_deep_agent_graph_builds_without_default_subagent() -> None:
    from deepagents.backends import StateBackend
    from langchain_openai import ChatOpenAI
    from langgraph.store.memory import InMemoryStore

    from Agent.deep_agent.context import AgentRunContext
    from Agent.deep_agent.graph import DeepAgentGraphConfig, build_deep_agent
    from Agent.deep_agent.state import ProjectDeepAgentState
    from Agent.deep_agent_tools import RagEvidenceTool

    class Retriever:
        def get_evidence(self, query, *, max_contexts=None):
            return {"status": "no_relevant_evidence", "evidence": []}

    model = ChatOpenAI(
        api_key="test-only",
        base_url="https://example.invalid/v1",
        model="deepseek-v4-flash",
    )
    graph = build_deep_agent(
        model=model,
        domain_tools=[RagEvidenceTool(Retriever())],
        backend=StateBackend(),
        store=InMemoryStore(),
        config=DeepAgentGraphConfig(context_window_tokens=4096),
    )

    assert type(graph).__name__ == "CompiledStateGraph"
    node_names = set(graph.get_graph().nodes)
    assert "SubAgentMiddleware.before_agent" not in node_names
    assert "SummarizationMiddleware.before_model" in node_names
    assert "ModelCallLimitMiddleware.before_model" in node_names
    assert "ToolCallLimitMiddleware.after_model" in node_names
    assert ProjectDeepAgentState.__annotations__["algorithm_results"]
    assert AgentRunContext.__dataclass_fields__["trusted_identity"]
