"""真实网络 smoke：完整子图 + 真实 SearXNG 三学术引擎（arxiv/crossref/openalex）+ mock LLM。

默认被 pytest.ini 的 ``-m "not smoke"`` 跳过；显式运行：
    pytest -m smoke tests/smoke/test_web_search_smoke.py

前置条件：SearXNG 容器在线（http://searxng:8080）。
断言刻意放宽：真实网络下只要求「至少一路引擎返回结果」，crossref 偶发超时属正常
（SearXNG 会标记 unresponsive，arxiv/openalex 照常返回）。
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = pytest.mark.smoke
pytest.importorskip("langgraph")

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
from Agent.causal_agent.tool_subgraphs import build_web_search_subgraph  # noqa: E402


def _subgraph_input():
    return {
        "messages": [],
        "analysis_parameters": {"target": "Y"},
        "causal_analysis_result": {"success": True, "algorithm": "pc"},
        "knowledge_base_result": None,
    }


def test_web_search_real_network_smoke(monkeypatch):
    # 只 mock LLM（planner 两步），检索走真实 SearXNG 三学术引擎。
    async def fake_question(state, llm):
        return {"question": "因果推断在未观测混杂下的方法学局限？", "reason": "r"}

    async def fake_query(state, llm, research_question):
        return {
            "query": "因果推断 未观测混杂",
            "query_en": "causal inference unmeasured confounding",
            "reason": "why",
        }

    monkeypatch.setattr(nodes, "generate_research_question", fake_question)
    monkeypatch.setattr(nodes, "get_web_search_query", fake_query)

    graph = build_web_search_subgraph(object())
    result = asyncio.run(graph.ainvoke(_subgraph_input()))

    r = result["web_search_result"]
    assert r["success"] is True, r
    assert r["results"], "真实网络应至少一路引擎返回结果"
    assert all("source" in x for x in r["results"]), "每条 result 应带 source 引擎字段"
    assert r["content"], "content 应至少有一条 snippet"
    assert all(x["source"] == "snippet" for x in r["content"]), "content 应为纯 snippet"
    origins = {x["origin"] for x in r["content"]}
    print(
        f"smoke passed: results={len(r['results'])}, "
        f"origins={sorted(origins)}, content={len(r['content'])}"
    )
