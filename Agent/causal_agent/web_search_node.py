"""联网搜索子图的私有 state、节点函数与底层工具函数。

子图采用线性 4 节点（planner → searxng_search → content_fetch → result_parser），
中间字段按节点嵌套分组（planner / searxng / content）只活在子图内，
唯一出口是写回父图的 web_search_result。
"""

from __future__ import annotations

import asyncio
import json
import logging
from operator import add
from typing import Annotated, Any, List, Optional, TypedDict
import xml.etree.ElementTree as ET

import httpx
import requests
import trafilatura
from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from Agent.causal_agent.back_prompt import causal_web_search_prompt
from Agent.llm_structured_output import StructuredOutputError, ainvoke_structured
from config.settings import settings


# 私有 state 边界：input_schema ⊆ state_schema，output_schema ⊆ state_schema。
# messages 既进 state_schema（planner 读它）又进 input_schema（框架从父图拷入），
# 但不进 output_schema（子图内只读，不回流父图）。

class WebSearchInput(TypedDict):
    messages: Annotated[List[BaseMessage], add]
    analysis_parameters: Optional[dict]
    causal_analysis_result: Optional[dict]


class WebSearchOutput(TypedDict):
    web_search_result: Optional[dict]


class WebSearchState(WebSearchInput, WebSearchOutput):
    planner: dict
    searxng: dict
    content: dict


class WebSearchQuery(BaseModel):
    """planner 生成的结构化联网搜索查询。"""

    query: str = Field(..., description="面向通用搜索的中文查询串，用于报告展示。")
    query_en: str = Field(..., description="面向 arXiv 等英文文献库的英文查询串，用于检索。")
    reason: str = Field(default="", description="为什么要检索这个查询。")


def _format_messages(messages: List[BaseMessage], max_messages: int = 6) -> str:
    formatted = []
    for message in messages[-max_messages:]:
        role = getattr(message, "type", message.__class__.__name__)
        content = getattr(message, "content", "")
        formatted.append(f"[{role}] {content}")
    return "\n".join(formatted) if formatted else "无可用对话历史。"


def _format_causal_summary(state: WebSearchState) -> str:
    causal_result = state.get("causal_analysis_result") or {}
    if not causal_result:
        return "当前还没有可用的因果分析结果。"
    try:
        return json.dumps(causal_result, indent=2, ensure_ascii=False)
    except TypeError:
        return str(causal_result)


async def get_web_search_query(state: WebSearchState, llm: ChatOpenAI) -> dict:
    """生成结构化联网搜索查询，失败时抛 StructuredOutputError 由 planner 降级。"""
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
                system role: {system_role}

                你是一个因果推断领域的信息检索专家。根据当前分析任务生成一个能检索到最新公开信息的搜索查询串。

                # 最近对话
                {messages}

                # 数据摘要
                {data_summary}

                # 因果分析摘要
                {causal_summary}

                # 生成目标
                1. 查询串要直击当前分析最需要外部补充的信息（最新方法、工具文档、领域进展、公开数据源）。
                2. 用搜索引擎友好的关键词，避免冗长或过于口语化的整句。
                3. 同时生成中英双语查询串：query 用中文关键词；query_en 用对应的英文核心短语——恰好 2 个实义词，去掉 latest/new/recent 等修饰词，也不含 PC/DiBS 等具体算法名（用领域核心主题，如 "causal discovery"、"causal inference"、"overcontrol bias"）。

                # 输出格式
                必须只返回一个 JSON 对象，包含 query、query_en 和 reason 三个字段。

                示例：
                {{
                  "query": "因果发现 最新算法",
                  "query_en": "causal discovery",
                  "reason": "补充报告所需的最新方法论进展"
                }}

                不要输出 Markdown，不要输出额外解释。
                """,
            ),
            ("human", "请根据当前任务生成联网搜索查询。只返回 JSON 对象。"),
        ]
    )

    result = await ainvoke_structured(
        llm=llm,
        schema=WebSearchQuery,
        prompt=prompt,
        inputs={
            "messages": _format_messages(state.get("messages", [])),
            "data_summary": json.dumps(
                state.get("analysis_parameters", {}), indent=2, ensure_ascii=False
            ),
            "causal_summary": _format_causal_summary(state),
            "system_role": causal_web_search_prompt(),
        },
        node_name="web_search_planner",
    )
    return result.model_dump()


def web_search(query: str) -> dict:
    """同步调用 SearXNG JSON API，网络异常直接抛出让 tool_retry 生效。"""
    resp = requests.get(
        f"{settings.SEARXNG_URL}/search",
        params={"q": query, "format": "json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    raw_results = data.get("results", [])
    results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", "") or r.get("snippet", ""),
            "score": float(r.get("score") or 0.0),
            "category": r.get("category") or r.get("engine", ""),
        }
        for r in raw_results
    ]
    return {
        "number_of_results": int(data.get("number_of_results") or 0),
        "results": results,
    }


def _arxiv_abs_to_html_url(url: str) -> str:
    """把 arxiv abs 链接（/abs/XXXXvN）转成 html 全文链接（/html/XXXXvN）。

    arXiv 的 abs 页面是摘要页，html 页面才有可抽取的全文正文，
    trafilatura 对 abs 页只能抽到摘要，对 html 页能抽到完整正文。
    """
    if not url:
        return url
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    return url.replace("/abs/", "/html/")


def _arxiv_fetch(search_query: str, max_results: int) -> dict:
    """执行一次 arXiv 查询并解析 Atom XML，返回与 web_search 兼容的结构。"""
    resp = requests.get(
        settings.ARXIV_API_URL,
        params={
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        },
        timeout=30,
    )
    resp.raise_for_status()

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(resp.text)

    total = 0
    total_node = root.find("atom:totalResults", ns)
    if total_node is not None and total_node.text:
        try:
            total = int(total_node.text)
        except ValueError:
            total = 0

    results = []
    for entry in root.findall("atom:entry", ns):
        title_el = entry.find("atom:title", ns)
        summary_el = entry.find("atom:summary", ns)
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""

        url = ""
        for link in entry.findall("atom:link", ns):
            if link.get("rel") == "alternate" and link.get("type") == "text/html":
                url = link.get("href", "")
                break
        if not url:
            id_el = entry.find("atom:id", ns)
            url = id_el.text.strip() if id_el is not None and id_el.text else ""

        summary = ""
        if summary_el is not None:
            summary = " ".join("".join(summary_el.itertext()).split())

        category = "arxiv"
        category_node = entry.find("atom:category", ns)
        if category_node is not None:
            category = category_node.get("term", "arxiv")

        results.append(
            {
                "title": title,
                "url": _arxiv_abs_to_html_url(url),
                "snippet": summary,
                "score": 1.0,
                "category": category,
            }
        )

    return {
        "number_of_results": total or len(results),
        "results": results,
    }


def search_arxiv(query: str, max_results: int = 5) -> dict:
    """精确短语检索；长 query 命中 0 条时回退 all 宽匹配兜底。

    网络异常 / XML 解析异常直接抛出，交由上层 tool_retry 处理。
    """
    q = query.replace('"', " ").strip()
    result = _arxiv_fetch(f'ti:"{q}" OR abs:"{q}"', max_results)
    if result["results"]:
        return result
    logging.info("arXiv 精确短语命中 0 条，回退 all 宽匹配 query=%s", q)
    return _arxiv_fetch(f"all:{q}", max_results)


async def fetch_page_text(url: str) -> dict:
    """httpx 拿 HTML + trafilatura 抽正文；单条失败返回 success=False。"""
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        logging.warning("fetch_page_text 请求失败 url=%s: %s", url, exc)
        return {"success": False, "markdown": "", "metadata": {}}

    try:
        markdown = await asyncio.to_thread(
            trafilatura.extract, html, output_format="markdown"
        )
    except Exception as exc:
        logging.warning("fetch_page_text 正文抽取失败 url=%s: %s", url, exc)
        return {"success": False, "markdown": "", "metadata": {}}

    if not markdown:
        return {"success": False, "markdown": "", "metadata": {}}
    return {"success": True, "markdown": markdown, "metadata": {}}


# 针对 query 的分块总结参数
_SUMMARIZE_CHUNK_SIZE = 12000  # 每块最大字符数
_SUMMARIZE_CHUNK_POINTS_MAX = 150  # 每块提炼关键点字数上限
_SUMMARIZE_FINAL_TARGET = "200-300 字"  # 最终摘要目标长度


async def _llm_text(llm: ChatOpenAI, messages) -> str:
    """调 llm 并返回纯文本；失败抛异常，由上层兜底。"""
    resp = await llm.ainvoke(messages)
    return resp.content if isinstance(resp.content, str) else str(resp.content)


async def _summarize_single(llm: ChatOpenAI, query: str, title: str, text: str) -> str:
    """小文（≤单块）直接总结成一段摘要。"""
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你是因果推断领域的研究助理。请针对检索目标，从下面这篇论文中提炼一段中文摘要，聚焦与检索目标最相关的方法、结论或进展。",
            ),
            (
                "human",
                "检索目标（query）：{query}\n论文标题：{title}\n论文内容：\n{text}\n\n"
                f"请输出 {_SUMMARIZE_FINAL_TARGET} 的中文摘要，不要 Markdown，不要输出与检索目标无关的内容。",
            ),
        ]
    )
    return (
        await _llm_text(llm, prompt.format_messages(query=query, title=title, text=text))
    ).strip()


async def _summarize_chunk(llm: ChatOpenAI, query: str, title: str, chunk: str) -> str:
    """从单块提炼与 query 相关的关键信息点；无关则返回空。"""
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你是因果推断领域的研究助理。下面是论文的一个片段，请提炼其中与检索目标相关的关键信息点。",
            ),
            (
                "human",
                "检索目标（query）：{query}\n论文标题：{title}\n片段内容：\n{chunk}\n\n"
                f"只输出与检索目标相关的关键信息点（中文，≤{_SUMMARIZE_CHUNK_POINTS_MAX} 字）。"
                "若该片段与检索目标无关，只输出\"[无关]\"。",
            ),
        ]
    )
    return (
        await _llm_text(llm, prompt.format_messages(query=query, title=title, chunk=chunk))
    ).strip()


async def _merge_points(llm: ChatOpenAI, query: str, title: str, points: List[str]) -> str:
    """把各块关键点合并成一段针对 query 的摘要。"""
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你是因果推断领域的研究助理。请把从论文各片段提炼出的关键信息点，综合成一段针对检索目标的中文摘要。",
            ),
            (
                "human",
                "检索目标（query）：{query}\n论文标题：{title}\n关键信息点：\n{points}\n\n"
                f"请输出 {_SUMMARIZE_FINAL_TARGET} 的中文摘要，聚焦与检索目标最相关的方法、结论或进展，不要 Markdown。",
            ),
        ]
    )
    points_text = "\n".join(f"- {p}" for p in points)
    return (
        await _llm_text(
            llm, prompt.format_messages(query=query, title=title, points=points_text)
        )
    ).strip()


async def _summarize_for_query(
    llm: ChatOpenAI, query: str, title: str, full_text: str
) -> str:
    """对全文针对 query 总结：小文直接总结，长文分块提炼后再合并。"""
    full_text = (full_text or "").strip()
    if not full_text:
        return ""
    chunks = [
        full_text[i : i + _SUMMARIZE_CHUNK_SIZE]
        for i in range(0, len(full_text), _SUMMARIZE_CHUNK_SIZE)
    ]
    if len(chunks) == 1:
        return await _summarize_single(llm, query, title, chunks[0])

    points_raw = await asyncio.gather(
        *[_summarize_chunk(llm, query, title, ch) for ch in chunks],
        return_exceptions=True,
    )
    points = []
    for pr in points_raw:
        if isinstance(pr, Exception):
            logging.warning("分块总结失败 title=%s: %s", title, pr)
            continue
        if pr and "[无关]" not in pr:
            points.append(pr)
    if not points:
        return ""
    return await _merge_points(llm, query, title, points)


async def web_search_planner_node(state: WebSearchState, llm: ChatOpenAI) -> dict:
    """生成联网搜索 query；业务降级在函数内 catch StructuredOutputError。"""
    try:
        r = await get_web_search_query(state, llm)
        return {
            "planner": {
                "success": True,
                "query": r["query"],
                "query_en": r.get("query_en", ""),
                "reason": r.get("reason", ""),
                "error": None,
            }
        }
    except StructuredOutputError as exc:
        logging.warning("联网搜索 query 生成失败: %s", exc)
        return {
            "planner": {
                "success": False,
                "query": "",
                "query_en": "",
                "reason": "",
                "error": "无法生成搜索 query",
            }
        }


async def searxng_search_node(state: WebSearchState) -> dict:
    """短路读 planner.success；调 search_arxiv，网络异常交给 tool_retry。"""
    if not state.get("planner", {}).get("success"):
        return {
            "searxng": {
                "success": False,
                "results": [],
                "number_of_results": 0,
                "error": None,
            }
        }
    search_query = state["planner"].get("query_en") or state["planner"].get("query", "")
    logging.info(
        "联网搜索 query=%r (query_en=%r)", search_query, state["planner"].get("query_en")
    )
    payload = await asyncio.to_thread(search_arxiv, search_query)
    logging.info("联网搜索命中 %s 条", payload["number_of_results"])
    return {
        "searxng": {
            "success": True,
            "results": payload["results"],
            "number_of_results": payload["number_of_results"],
            "error": None,
        }
    }


async def content_fetch_node(state: WebSearchState) -> dict:
    """短路读 searxng.success；Top-3 高评分 URL 抓正文，单条失败只记该条。"""
    if not state.get("searxng", {}).get("success"):
        return {"content": {"success": False, "fetched": [], "error": None}}

    results = state["searxng"]["results"]
    top = sorted(results, key=lambda r: r.get("score") or 0.0, reverse=True)[:3]

    fetched = []
    for r in top:
        res = await fetch_page_text(r["url"])
        fetched.append(
            {
                "url": r["url"],
                "success": res["success"],
                "markdown": res["markdown"],
                "metadata": res.get("metadata", {}),
            }
        )
    return {"content": {"success": True, "fetched": fetched, "error": None}}


async def web_search_result_parser_node(state: WebSearchState, llm: ChatOpenAI) -> dict:
    """组装结构化 web_search_result；抓到的全文先针对 query 总结，失败用 snippet 兜底。"""
    p = state.get("planner", {})
    s = state.get("searxng", {})
    c = state.get("content", {})

    query = p.get("query", "") or ""
    query_en = p.get("query_en", "") or ""
    summarize_query = " ".join(x for x in (query_en, query) if x)

    by_url = {f["url"]: f for f in c.get("fetched", [])}
    content = []
    for r in s.get("results", []):
        f = by_url.get(r["url"])
        text, source = r.get("snippet", ""), "snippet"
        if f and f.get("success") and f.get("markdown"):
            try:
                summary = await _summarize_for_query(
                    llm, summarize_query, r.get("title", ""), f["markdown"]
                )
                if summary:
                    text, source = summary, "summarized"
            except Exception as exc:
                logging.warning("全文总结失败 url=%s: %s", r["url"], exc)
        content.append(
            {
                "url": r["url"],
                "title": r.get("title", ""),
                "text": text,
                "source": source,
            }
        )

    return {
        "web_search_result": {
            "success": s.get("success", False),
            "query": p.get("query", ""),
            "results": s.get("results", []),
            "content": content,
        }
    }


def format_web_search_summary_for_prompt(
    web_search_result: Optional[dict],
    max_content_items: int = 5,
) -> str:
    """把 web_search_result 渲染成注入 report / inquiry prompt 的文本。"""
    if not web_search_result:
        return "无可用联网搜索结果。"

    if not web_search_result.get("success", False):
        return "联网搜索失败或未启用，本次分析不包含外部检索信息。"

    query = web_search_result.get("query", "")
    content = web_search_result.get("content", [])[:max_content_items]
    if not content:
        return f"联网搜索（query={query}）未获取到有效正文。"

    blocks = [f"联网搜索 query：{query}"]
    source_map = {
        "summarized": "针对 query 的总结",
        "fetched": "正文",
        "snippet": "摘要兜底",
    }
    for i, item in enumerate(content, 1):
        source = source_map.get(item.get("source"), item.get("source", "摘要兜底"))
        blocks.append(
            f"[{i}] {item.get('title', '')}\n"
            f"URL: {item.get('url', '')}\n"
            f"来源: {source}\n"
            f"内容: {item.get('text', '')}"
        )
    return "\n\n".join(blocks)
