"""联网搜索子图的底层工具函数与结构化 schema。

子图节点函数在 nodes.py；本模块只提供 planner 的 LLM 辅助、SearXNG 查询、
引擎合并与结果渲染等底层工具，以及结构化输出 schema。
唯一出口 web_search_result 是纯 snippet（无 BM25/抓正文/总结）。
"""

from __future__ import annotations

import json
import re
from typing import List, Optional

import requests
from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from Agent.causal_agent.back_prompt import causal_web_search_prompt
from Agent.causal_agent.state import WebSearchState
from Agent.llm_structured_output import ainvoke_structured
from config.settings import settings


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
                1. query_en 必须恰好 3-4 个英文术语，用空格分隔；第一个是领域词，后续是因果方法学痛点词；超过 4 个词视为失败。
                2. 痛点词只能从因果方法学痛点里选：unmeasured confounding（未观测混杂）、selection bias（选择偏误）、time-varying treatment（时变干预）、sample selection（样本选择）、measurement error（测量误差）、high-dimensional（高维）等。
                3. 严禁出现具体方法名（PC、DAG、do-calculus、nonparametric、conditional independence 等）和数据分布描述词（skewed、sparse、noisy、small sample 等）。
                4. query 用中文关键词、query_en 用英文核心术语，两者语义对应；不要逗号、不要整句、不要停用词。
                # 输出格式
                必须只返回一个 JSON 对象，包含 query、query_en 和 reason 三个字段。

                示例：
                {{
                  "query": "生物医学 因果推断 未观测混杂",
                  "query_en": "biomedical causal inference unmeasured confounding",
                  "reason": "该数据集属生物医学领域，其因果分析核心痛点是未观测混杂，据此检索相关方法学文献"
                }}

                反例（禁止，视为失败）：
                "query_en": "biomedical signaling pathway nonparametric conditional independence skewed data"
                （错在：8 个词超限；含方法名 nonparametric/conditional independence；含数据分布词 skewed data）

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
    data = result.model_dump()
    terms = data["query_en"].split()
    if len(terms) > 4:
        data["query_en"] = " ".join(terms[:4])
    return data


def web_search(query: str) -> dict:
    """同步调用 SearXNG JSON API（arxiv/crossref/openalex 三学术引擎）。

    SearXNG 内部并行查三引擎，返回合并结果（每条带 engine 字段）。
    arxiv 结果按 tags 白名单过滤；crossref content 含 HTML 需清理；
    content 为空（无摘要正文）的结果直接丢弃，保证下游注入的 snippet 条条有正文。
    网络异常直接抛出，交 tool_retry。
    """
    resp = requests.get(
        f"{settings.SEARXNG_URL}/search",
        params={"q": query, "format": "json", "engines": "arxiv,crossref,openalex"},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    results = []
    for r in data.get("results", []):
        engine = r.get("engine", "")
        if engine == "arxiv" and not (set(r.get("tags") or []) & CAUSAL_ARXIV_CATEGORIES):
            continue
        snippet = re.sub(r"<[^>]+>", "", r.get("content") or "").strip()
        if not snippet:
            continue
        results.append(
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": snippet,
                "score": float(r.get("score") or 0.0),
                "source": engine,
            }
        )
    return {
        "number_of_results": len(results),
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


_ENGINE_ORDER = ("arxiv", "crossref", "openalex")


WEB_SEARCH_MAX_RESULTS = 9


def _merge_by_engine_top3(
    results: List[dict],
    top_per_engine: int = 3,
    max_results: int = WEB_SEARCH_MAX_RESULTS,
) -> List[dict]:
    """按引擎分组，各引擎内部按 score 降序取 top-N，再按 rank 轮转交错拼接。

    score 跨引擎不可比（各引擎尺度不同），故不做跨引擎比较；每轮依次取
    各引擎的第 i 名（arxiv→crossref→openalex），既保证引擎均衡，又让各引擎
    最相关的结果靠前。合并结果总量受 max_results 封顶，保证与引用投影一致。
    """
    buckets: dict[str, List[dict]] = {}
    for r in results:
        buckets.setdefault(r.get("source", ""), []).append(r)
    for engine in buckets:
        buckets[engine].sort(key=lambda r: r.get("score", 0.0), reverse=True)
    merged: List[dict] = []
    for i in range(top_per_engine):
        for engine in _ENGINE_ORDER:
            engine_results = buckets.get(engine, [])
            if i < len(engine_results):
                merged.append(engine_results[i])
    return merged[:max_results]


def format_web_search_summary_for_prompt(
    web_search_result: Optional[dict],
    max_content_items: int = WEB_SEARCH_MAX_RESULTS,
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
    for i, item in enumerate(content, 1):
        origin = item.get("origin", "") or "摘要"
        blocks.append(
            f"[{i}] {item.get('title', '')}\n"
            f"URL: {item.get('url', '')}\n"
            f"来源: {origin}\n"
            f"内容: {item.get('text', '')}"
        )
    return "\n\n".join(blocks)
