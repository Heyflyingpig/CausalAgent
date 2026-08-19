"""联网搜索子图的私有 state、节点函数与底层工具函数。

子图采用线性 4 节点（planner → searxng_search → content_fetch → result_parser），
中间字段按节点嵌套分组（planner / searxng / content）只活在子图内，
唯一出口是写回父图的 web_search_result。
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
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
    knowledge_base_result: Optional[dict]


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


class ResearchQuestion(BaseModel):
    """第一步生成的具体问题：后续因果分析中最需解决/论证的问题。"""

    question: str = Field(..., description="后续因果分析中最需解决/论证的具体问题。")
    reason: str = Field(default="", description="为什么这是当前最需要外部补充的问题。")


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
    
def _format_knowledge_base_result(state: WebSearchState) -> str:
    knowledge_base_result = state.get("knowledge_base_result") or {}
    if not knowledge_base_result:
        return "当前还没有可用的知识库分析结果。"
    try:
        return json.dumps(knowledge_base_result, indent=2, ensure_ascii=False)
    except TypeError:
        return str(knowledge_base_result)

async def generate_research_question(state: WebSearchState, llm: ChatOpenAI) -> dict:
    """第一步：提炼后续因果分析中最需解决/论证的具体问题。"""
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
                system role: {system_role}

                你是因果推断领域资深研究者。你的任务不是泛泛`生成教材式问题，而是围绕当前分析任务，找出后续因果分析中最需要外部信息支撑的关键论证问题。现已获得该数据集的历史信息如下：

                # 最近对话
                {messages}

                # 数据摘要
                {data_summary}

                # 因果分析摘要
                {causal_summary}
                # rag分析摘要
                {knowledge_base_result}

                # 生成目标
                1. 直击当前分析最薄弱、最影响报告可信度的环节：识别假设是否成立、方法适用条件、算法局限、偏误来源或领域最新进展。
                2. 问题要能直接支撑后续报告的关键论证，而不是泛泛介绍概念。
                3. 问题必须具体、可检索，用该领域的专业术语表达，避免"什么是因果推断"这类空泛表述。
                4. 若因果分析尚未开始（无因果摘要），则聚焦目标变量与数据特征，找出最需论证的识别或估计问题。
                5. 只生成一个最关键的问题，不要为了凑数而罗列多个。

                # 输出格式
                必须只返回一个 JSON 对象，包含 question 和 reason 两个字段。

                示例：
                {{
                  "question": "PC算法在存在隐藏混杂变量时，边的定向会引入哪些系统性偏误？",
                  "reason": "当前分析使用PC算法做因果发现，需说明其边定向在未观测混杂下的局限，以支撑报告的可靠性结论"
                }}

                不要输出 Markdown，不要输出额外解释。
                """,
            ),
            (
                "human",
                "请判断当前因果分析中最需要解决或论证的具体问题。只返回 JSON 对象。",
            ),
        ]
    )

    result = await ainvoke_structured(
        llm=llm,
        schema=ResearchQuestion,
        prompt=prompt,
        inputs={
            "messages": _format_messages(state.get("messages", [])),
            "data_summary": json.dumps(
                state.get("analysis_parameters", {}), indent=2, ensure_ascii=False
            ),
            "causal_summary": _format_causal_summary(state),
            "knowledge_base_result": _format_knowledge_base_result(state),
            "system_role": causal_web_search_prompt(),
        },
        node_name="web_search_planner",
    )
    return result.model_dump()


async def get_web_search_query(
    state: WebSearchState, llm: ChatOpenAI, research_question: str
) -> dict:
    """第二步：针对具体问题生成结构化联网搜索查询，失败时抛 StructuredOutputError。"""
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
                system role: {system_role}

                你是一个因果推断领域的信息检索专家。你刚刚完成了对数据集的探索性分析。具体信息如下：

                # 最近对话
                {messages}

                # 数据摘要
                {data_summary}

                # 因果分析摘要
                {causal_summary}

                # 当前最需解决/论证的具体问题
                {research_question}

                请针对上述具体问题，先判断该数据集所属的领域（如社会劳动/生物医学/经济金融/神经科学/工业制造等），再思考该领域进行因果分析时最常见的特点或痛点（如未观测混杂、纵向数据的时变干预、高维小样本、选择偏误等），最后结合这些信息生成一个用于学术检索的查询串。

                # 生成目标
                1. 查询串的构造必须遵循「领域词打头 + 痛点词跟进」的结构：第一个术语是该数据集所属领域的核心词，后续术语是该领域因果分析中最典型的特点或痛点。
                2. 不要堆砌具体方法名（如 PC 算法、DAG、do-calculus），而要用领域词与痛点术语把检索范围锚定到该领域的方法学文献。
                3. 同时生成中英双语查询串：query 用中文关键词；query_en 用对应的英文核心术语。
                4. query_en 只输出 3-4 个英文核心术语，用空格分隔，第一个必须是领域词，后续为痛点术语；不要逗号、不要整句、不要停用词。
                # 输出格式
                必须只返回一个 JSON 对象，包含 query、query_en 和 reason 三个字段。

                示例：
                {{
                  "query": "生物医学 因果推断 未观测混杂",
                  "query_en": "biomedical causal inference unmeasured confounding",
                  "reason": "该数据集属生物医学领域，其因果分析核心痛点是未观测混杂，据此检索相关方法学文献"
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
            "research_question": research_question,
            "system_role": causal_web_search_prompt(),
        },
        node_name="web_search_planner",
    )
    return result.model_dump()


def web_search(query: str,top_k:int=5) -> dict:
    """同步调用 SearXNG JSON API，网络异常直接抛出让 tool_retry 生效。"""
    resp = requests.get(
        f"{settings.SEARXNG_URL}/search",
        params={"q": query, "format": "json", "num": top_k},
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
    """把 arxiv abs 链接转成 html 全文链接，但仅对 2023-12 之后的论文生效。

    arXiv 的原生 HTML 全文页（/html/）只对 2023 年 12 月之后宣布的论文提供，
    更早的论文 /html/ 会 404，因此保留 abs 页（摘要页始终存在）。
    trafilatura 对 abs 页抽到摘要，对 html 页抽到完整正文。
    """
    if not url:
        return url
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    match = re.search(r"/abs/(\d{4})\.", url)
    if match and int(match.group(1)) >= 2312:
        return url.replace("/abs/", "/html/")
    return url


def _arxiv_fetch(search_query: str, max_results: int) -> dict:
    """执行一次 arXiv 查询并解析 Atom XML，返回与 web_search 兼容的结构。"""
    resp = requests.get(
        settings.ARXIV_API_URL,
        params={
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
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


CAUSAL_ARXIV_CATEGORIES = {
    "stat.ML",
    "stat.ME",
    "cs.LG",
    "cs.AI",
    "cs.CL",
    "econ.EM",
    "q-bio.QM",
    "math.ST",
    "stat.AP",
}


def _tokenize(text: str) -> List[str]:
    """小写 + 正则提取字母数字词（不做 stemming）。"""
    return re.findall(r"[a-z0-9]+", (text or "").lower())


class BM25Okapi:
    """自实现 BM25Okapi（k1=1.5, b=0.75），避免引入 rank_bm25 依赖。"""

    def __init__(self, corpus: List[List[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus_size = len(corpus)
        self.doc_len = [len(doc) for doc in corpus]
        self.avgdl = sum(self.doc_len) / self.corpus_size if self.corpus_size else 0.0
        self.doc_freqs: List[dict] = []
        self.idf: dict = {}
        self._initialize(corpus)

    def _initialize(self, corpus: List[List[str]]) -> None:
        for doc in corpus:
            freqs: dict = {}
            for token in doc:
                freqs[token] = freqs.get(token, 0) + 1
            self.doc_freqs.append(freqs)
        for doc_freq in self.doc_freqs:
            for token in doc_freq:
                self.idf[token] = self.idf.get(token, 0) + 1
        # n(q) = 包含该词条的文档数；+1 平滑避免全命中时 IDF 为负。
        self.idf = {
            token: math.log((self.corpus_size - freq + 0.5) / (freq + 0.5) + 1)
            for token, freq in self.idf.items()
        }

    def _score(self, query: List[str], index: int) -> float:
        score = 0.0
        doc_len = self.doc_len[index]
        doc_freq = self.doc_freqs[index]
        norm_len = doc_len / self.avgdl if self.avgdl > 0 else 0.0
        for token in query:
            tf = doc_freq.get(token, 0)
            if tf == 0:
                continue
            idf = self.idf.get(token, 0.0)
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * norm_len)
            score += idf * numerator / denominator
        return score

    def get_scores(self, query: List[str]) -> List[float]:
        if self.corpus_size == 0:
            return []
        return [self._score(query, i) for i in range(self.corpus_size)]


def _filter_by_category(results: List[dict]) -> List[dict]:
    """硬白名单：只保留落入因果相关 arXiv 分类的候选。"""
    return [r for r in results if r.get("category") in CAUSAL_ARXIV_CATEGORIES]


def _rerank_by_bm25(query: str, candidates: List[dict], top_k: int = 5) -> List[dict]:
    """title×2 + snippet×1 加权构造文档，BM25 打分后取 top_k，并把分数写回 score。"""
    if not candidates:
        return []
    query_tokens = _tokenize(query)
    if not query_tokens:
        return candidates[:top_k]
    docs = [
        _tokenize(r.get("title", "")) * 2 + _tokenize(r.get("snippet", ""))
        for r in candidates
    ]
    scores = BM25Okapi(docs).get_scores(query_tokens)
    ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
    out = []
    for r, score in ranked[:top_k]:
        r = dict(r)
        r["score"] = score
        out.append(r)
    return out


def search_arxiv(query: str, max_results: int = 5) -> dict:
    """宽检索(OR)→硬白名单过滤→BM25 重排序。

    query_en 先截断到前 4 词避免过长导致检索分散；用 OR 语义宽检索 25 条候选，
    再按因果相关分类白名单过滤，最后对 title×2+snippet×1 打分取 top_k。

    网络异常 / XML 解析异常直接抛出，交由上层 tool_retry 处理。
    """
    tokens = [t for t in query.replace('"', " ").replace(",", " ").split() if t]
    if not tokens:
        return {"number_of_results": 0, "results": []}
    tokens = tokens[:4]
    or_q = " OR ".join(tokens)
    payload = _arxiv_fetch(f"ti:({or_q}) OR abs:({or_q})", max_results=25)
    candidates = _filter_by_category(payload["results"])
    logging.info(
        "arXiv OR 检索 %s 条，白名单过滤后 %s 条 query=%s",
        len(payload["results"]),
        len(candidates),
        " ".join(tokens),
    )
    reranked = _rerank_by_bm25(" ".join(tokens), candidates, top_k=max_results)
    return {"number_of_results": len(reranked), "results": reranked}


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
    """两步生成联网搜索 query：先提炼具体问题，再针对问题生成 query。"""
    try:
        question = await generate_research_question(state, llm)
        r = await get_web_search_query(state, llm, question["question"])
        return {
            "planner": {
                "success": True,
                "research_question": question["question"],
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
                "research_question": "",
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
