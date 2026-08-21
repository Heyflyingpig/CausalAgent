"""web_search 子图集成测试：线性 3 节点、短路降级、degrade handler、父图 router。"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest

for _key, _value in {
    "SECRET_KEY": "test-secret",
    "API_KEY": "test-api-key",
    "BASE_URL": "https://example.test",
    "MODEL": "test-model",
    "MYSQL_HOST": "mysql",
    "MYSQL_USER": "app",
    "MYSQL_PASSWORD": "password",
    "MYSQL_DATABASE": "causalagent",
}.items():
    os.environ.setdefault(_key, _value)

from Agent.causal_agent import nodes  # noqa: E402
from Agent.causal_agent.edges import web_search_router  # noqa: E402
from Agent.causal_agent.fault_tolerance import (  # noqa: E402
    degrade_academic_search,
    degrade_web_search_planner,
)
from Agent.causal_agent.tool_subgraphs import build_web_search_subgraph  # noqa: E402
from Agent.llm_structured_output import StructuredOutputError  # noqa: E402


def _subgraph_input():
    return {
        "messages": [],
        "analysis_parameters": {"target": "Y"},
        "causal_analysis_result": {"success": True, "algorithm": "pc"},
        "knowledge_base_result": None,
    }


def _mock_search_paths(monkeypatch):
    """mock planner 与单次 SearXNG 检索，返回调用记录器。"""
    calls = {"web": []}

    async def fake_question(state, llm):
        return {"question": "PC算法在隐藏混杂下的偏误？", "reason": "r"}

    async def fake_query(state, llm, research_question):
        return {
            "query": "生物医学 因果推断",
            "query_en": "causal inference",
            "reason": "why",
        }

    def fake_web(q):
        calls["web"].append(q)
        return {
            "number_of_results": 2,
            "results": [
                {
                    "title": "Causal discovery",
                    "url": "http://a1",
                    "snippet": "s",
                    "source": "arxiv",
                },
                {
                    "title": "Web material",
                    "url": "http://w1",
                    "snippet": "s",
                    "source": "crossref",
                },
            ],
        }

    monkeypatch.setattr(nodes, "generate_research_question", fake_question)
    monkeypatch.setattr(nodes, "get_web_search_query", fake_query)
    monkeypatch.setattr(nodes, "web_search", fake_web)
    return calls


def test_subgraph_happy_path(monkeypatch):
    _mock_search_paths(monkeypatch)
    graph = build_web_search_subgraph(object())
    result = asyncio.run(graph.ainvoke(_subgraph_input()))

    r = result["web_search_result"]
    assert r["success"] is True
    assert r["query"] == "生物医学 因果推断"
    assert len(r["results"]) == 2
    assert len(r["content"]) == 2
    assert r["content"][0]["source"] == "snippet"
    assert r["content"][0]["origin"] == "arxiv"


def test_subgraph_runs_single_search_with_query_en(monkeypatch):
    calls = _mock_search_paths(monkeypatch)
    graph = build_web_search_subgraph(object())
    asyncio.run(graph.ainvoke(_subgraph_input()))

    assert calls["web"] == ["causal inference"]


def test_subgraph_short_circuits_when_planner_fails(monkeypatch):
    async def fail_question(state, llm):
        raise StructuredOutputError(
            node_name="web_search_planner",
            schema_name="ResearchQuestion",
            cause=ValueError("invalid"),
        )

    monkeypatch.setattr(nodes, "generate_research_question", fail_question)

    web_calls = []
    monkeypatch.setattr(nodes, "web_search", lambda q: web_calls.append(q))

    graph = build_web_search_subgraph(object())
    result = asyncio.run(graph.ainvoke(_subgraph_input()))

    assert result["web_search_result"]["success"] is False
    assert web_calls == []  # planner 失败 → academic_search 短路


# ---------------------------------------------------------------------------
# degrade handler
# ---------------------------------------------------------------------------


def _node_error(msg):
    return SimpleNamespace(node="web_search", error=ConnectionError(msg))


def test_degrade_planner_writes_failure_group():
    result = degrade_web_search_planner({}, _node_error("timeout"))
    assert result["planner"]["success"] is False
    assert result["planner"]["query_en"] == ""
    assert result["planner"]["error"] == "调用超时"


def test_degrade_academic_writes_failure_group():
    result = degrade_academic_search({}, _node_error("timeout"))
    assert result["search"]["success"] is False
    assert result["search"]["results"] == []
    assert result["search"]["number_of_results"] == 0
    assert result["search"]["error"] == "调用超时"


# ---------------------------------------------------------------------------
# 父图 router
# ---------------------------------------------------------------------------


def test_web_search_router_enabled():
    assert web_search_router({}, SimpleNamespace(web_search_enabled=True)) == "web_search"


def test_web_search_router_disabled():
    assert web_search_router({}, SimpleNamespace(web_search_enabled=False)) == "agent"


def test_web_search_router_no_context_defaults_to_agent():
    assert web_search_router({}, None) == "agent"
