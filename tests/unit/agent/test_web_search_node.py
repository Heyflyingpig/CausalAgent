"""web_search 节点层单元测试：纯函数、I/O 函数、异步节点。

分层
- ① 纯函数（零 mock）：_merge_by_engine_top3 / format_web_search_summary_for_prompt
- ② I/O 函数（mock requests.get）：web_search（统一走 SearXNG 三学术引擎）
- ③ 异步节点（mock LLM + 底层 search）：planner / academic_search / result_parser
"""

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
from Agent.causal_agent import web_search_node as ws  # noqa: E402
from Agent.llm_structured_output import StructuredOutputError  # noqa: E402


# ---------------------------------------------------------------------------
# ① 纯函数
# ---------------------------------------------------------------------------


def test_merge_by_engine_top3_interleaves_by_rank():
    # rank 轮转：各引擎第 1 名依次在前，再第 2 名、第 3 名。
    results = (
        [{"title": f"a{i}", "source": "arxiv"} for i in range(5)]
        + [{"title": f"c{i}", "source": "crossref"} for i in range(5)]
        + [{"title": f"o{i}", "source": "openalex"} for i in range(5)]
    )
    merged = ws._merge_by_engine_top3(results)
    assert [r["source"] for r in merged] == ["arxiv", "crossref", "openalex"] * 3
    assert [r["title"] for r in merged] == ["a0", "c0", "o0", "a1", "c1", "o1", "a2", "c2", "o2"]


def test_merge_by_engine_top3_sorts_within_engine_then_interleaves():
    # 引擎内按 score 降序；跨引擎不比较，openalex rank1(0.8) 仍排自身第 1 位不被压后。
    results = [
        {"title": "a_r3", "source": "arxiv", "score": 0.1},
        {"title": "c_r1", "source": "crossref", "score": 0.9},
        {"title": "a_r1", "source": "arxiv", "score": 1.0},
        {"title": "o_r2", "source": "openalex", "score": 0.5},
        {"title": "c_r2", "source": "crossref", "score": 0.4},
        {"title": "a_r2", "source": "arxiv", "score": 0.5},
        {"title": "o_r1", "source": "openalex", "score": 0.8},
        {"title": "c_r3", "source": "crossref", "score": 0.2},
        {"title": "o_r3", "source": "openalex", "score": 0.3},
    ]
    merged = ws._merge_by_engine_top3(results)
    assert [r["title"] for r in merged] == [
        "a_r1", "c_r1", "o_r1",
        "a_r2", "c_r2", "o_r2",
        "a_r3", "c_r3", "o_r3",
    ]


def test_merge_by_engine_top3_skips_missing_rank():
    # crossref 只有 1 条，轮转到第 2、3 轮时跳过，其余引擎继续。
    results = [
        {"title": "a1", "source": "arxiv"},
        {"title": "c1", "source": "crossref"},
        {"title": "a2", "source": "arxiv"},
        {"title": "a3", "source": "arxiv"},
    ]
    merged = ws._merge_by_engine_top3(results)
    assert [r["title"] for r in merged] == ["a1", "c1", "a2", "a3"]


def test_merge_by_engine_top3_missing_engine_degrades():
    results = [{"title": f"a{i}", "source": "arxiv"} for i in range(5)]
    merged = ws._merge_by_engine_top3(results)
    assert len(merged) == 3
    assert all(r["source"] == "arxiv" for r in merged)


def test_merge_by_engine_top3_empty():
    assert ws._merge_by_engine_top3([]) == []


def test_format_summary_none():
    assert ws.format_web_search_summary_for_prompt(None) == "无可用联网搜索结果。"


def test_format_summary_failure():
    assert "失败" in ws.format_web_search_summary_for_prompt({"success": False})


def test_format_summary_empty_content():
    result = {"success": True, "query": "q", "content": []}
    assert "未获取到有效正文" in ws.format_web_search_summary_for_prompt(result)


def test_format_summary_renders_origin_and_truncates():
    result = {
        "success": True,
        "query": "q",
        "content": [
            {"title": "T1", "url": "u1", "text": "text1", "source": "snippet", "origin": "arxiv"},
            {"title": "T2", "url": "u2", "text": "text2", "source": "snippet", "origin": "crossref"},
            {"title": "T3", "url": "u3", "text": "text3", "source": "snippet", "origin": "openalex"},
        ],
    }
    out = ws.format_web_search_summary_for_prompt(result, max_content_items=2)
    assert "T1" in out and "T2" in out
    assert "T3" not in out
    assert "arxiv" in out
    assert "crossref" in out


# ---------------------------------------------------------------------------
# ② I/O 函数：web_search 统一走 SearXNG 三学术引擎
# ---------------------------------------------------------------------------


def _fake_requests_response(*, json_body=None, text=None, raise_http=False):
    resp = SimpleNamespace()

    def raise_for_status():
        if raise_http:
            raise RuntimeError("HTTP error")

    resp.raise_for_status = raise_for_status
    if json_body is not None:
        resp.json = lambda: json_body
        resp.text = ""
    if text is not None:
        resp.text = text
    return resp


def test_web_search_requests_searxng_engines(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return _fake_requests_response(json_body={"results": []})

    monkeypatch.setattr(ws.requests, "get", fake_get)
    ws.web_search("causal inference")
    assert captured["url"].endswith("/search")
    assert captured["params"]["format"] == "json"
    assert captured["params"]["engines"] == "arxiv,crossref,openalex"


def test_web_search_unifies_three_engines_and_cleans_html(monkeypatch):
    body = {
        "results": [
            {
                "title": "T1",
                "url": "http://a",
                "content": "<p>snippet1</p>",
                "score": 1.0,
                "engine": "arxiv",
                "tags": ["stat.ML"],
            },
            {
                "title": "T2",
                "url": "http://b",
                "content": "snippet2",
                "score": 0.5,
                "engine": "crossref",
            },
            {
                "title": "T3",
                "url": "http://c",
                "content": "snippet3",
                "score": 0.33,
                "engine": "openalex",
            },
        ],
    }
    monkeypatch.setattr(
        ws.requests, "get", lambda *a, **k: _fake_requests_response(json_body=body)
    )
    out = ws.web_search("causal inference")
    assert out["number_of_results"] == 3
    assert [r["source"] for r in out["results"]] == ["arxiv", "crossref", "openalex"]
    assert out["results"][0]["snippet"] == "snippet1"  # HTML 标签被清理


def test_web_search_filters_arxiv_by_tags_whitelist(monkeypatch):
    body = {
        "results": [
            {
                "title": "keep",
                "url": "u1",
                "content": "s",
                "score": 1.0,
                "engine": "arxiv",
                "tags": ["stat.ML"],
            },
            {
                "title": "drop",
                "url": "u2",
                "content": "s",
                "score": 0.9,
                "engine": "arxiv",
                "tags": ["astro-ph"],
            },
        ],
    }
    monkeypatch.setattr(
        ws.requests, "get", lambda *a, **k: _fake_requests_response(json_body=body)
    )
    out = ws.web_search("causal")
    assert [r["title"] for r in out["results"]] == ["keep"]


def test_web_search_drops_empty_snippet(monkeypatch):
    # content 为空（或仅 HTML 标签剥完为空）的结果被丢弃，保证 snippet 条条有正文。
    body = {
        "results": [
            {
                "title": "keep",
                "url": "u1",
                "content": "<p>has abstract</p>",
                "score": 1.0,
                "engine": "crossref",
            },
            {
                "title": "drop-empty",
                "url": "u2",
                "content": "",
                "score": 0.9,
                "engine": "openalex",
            },
            {
                "title": "drop-tags-only",
                "url": "u3",
                "content": "<p></p>",
                "score": 0.8,
                "engine": "arxiv",
                "tags": ["stat.ML"],
            },
        ],
    }
    monkeypatch.setattr(
        ws.requests, "get", lambda *a, **k: _fake_requests_response(json_body=body)
    )
    out = ws.web_search("causal")
    assert [r["title"] for r in out["results"]] == ["keep"]
    assert out["number_of_results"] == 1


def test_web_search_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(
        ws.requests, "get", lambda *a, **k: _fake_requests_response(raise_http=True)
    )
    with pytest.raises(RuntimeError):
        ws.web_search("causal")


# ---------------------------------------------------------------------------
# ③ 异步节点
# ---------------------------------------------------------------------------


def test_planner_node_success(monkeypatch):
    async def fake_question(state, llm):
        return {"question": "PC算法在隐藏混杂下的偏误？", "reason": "r"}

    async def fake_query(state, llm, research_question):
        return {
            "query": "生物医学 因果推断",
            "query_en": "biomedical causal inference",
            "reason": "why",
        }

    monkeypatch.setattr(nodes, "generate_research_question", fake_question)
    monkeypatch.setattr(nodes, "get_web_search_query", fake_query)

    result = asyncio.run(nodes.web_search_planner_node({}, object()))
    p = result["planner"]
    assert p["success"] is True
    assert p["query_en"] == "biomedical causal inference"
    assert p["research_question"] == "PC算法在隐藏混杂下的偏误？"


def test_planner_node_degrades_on_structured_output_error(monkeypatch):
    async def fake_question(state, llm):
        raise StructuredOutputError(
            node_name="web_search_planner",
            schema_name="ResearchQuestion",
            cause=ValueError("invalid"),
        )

    monkeypatch.setattr(nodes, "generate_research_question", fake_question)

    result = asyncio.run(nodes.web_search_planner_node({}, object()))
    assert result["planner"]["success"] is False
    assert result["planner"]["query_en"] == ""


def test_academic_search_node_short_circuits_when_planner_failed(monkeypatch):
    called = []

    def fake_search(q):
        called.append(q)
        return {"number_of_results": 1, "results": []}

    monkeypatch.setattr(nodes, "web_search", fake_search)
    result = asyncio.run(
        nodes.academic_search_node({"planner": {"success": False, "query_en": "q"}})
    )
    assert result["search"]["success"] is False
    assert called == []


def test_academic_search_node_success(monkeypatch):
    monkeypatch.setattr(
        nodes,
        "web_search",
        lambda q: {
            "number_of_results": 2,
            "results": [
                {"title": "a", "url": "u1", "snippet": "s", "source": "arxiv"},
                {"title": "b", "url": "u2", "snippet": "s", "source": "crossref"},
            ],
        },
    )
    result = asyncio.run(
        nodes.academic_search_node({"planner": {"success": True, "query_en": "causal"}})
    )
    assert result["search"]["success"] is True
    assert result["search"]["number_of_results"] == 2
    assert [r["source"] for r in result["search"]["results"]] == ["arxiv", "crossref"]


def test_result_parser_projects_pure_snippet():
    state = {
        "planner": {"query": "q", "query_en": "q_en"},
        "search": {
            "success": True,
            "results": [
                {"title": "T1", "url": "u1", "snippet": "snip1", "source": "arxiv"},
                {"title": "T2", "url": "u2", "snippet": "snip2", "source": "crossref"},
            ],
        },
    }
    result = asyncio.run(nodes.web_search_result_parser_node(state))
    r = result["web_search_result"]
    assert r["success"] is True
    assert r["query"] == "q"
    assert len(r["results"]) == 2
    assert r["content"][0] == {
        "url": "u1",
        "title": "T1",
        "text": "snip1",
        "source": "snippet",
        "origin": "arxiv",
    }
    assert r["content"][1]["origin"] == "crossref"


def test_result_parser_success_false_when_search_failed():
    state = {
        "planner": {"query": "q", "query_en": "q_en"},
        "search": {"success": False, "results": []},
    }
    result = asyncio.run(nodes.web_search_result_parser_node(state))
    r = result["web_search_result"]
    assert r["success"] is False
    assert r["content"] == []
