"""注册 RAG 检索工具。"""
from __future__ import annotations
from typing import Any

from langchain_core.tools import tool
from Agent.tool_node.rag_query_task import rag_query_task


@tool("rag_enrichment_search")
async def rag_enrichment_search(
    questions: list[Any],
    max_results: int = 5,
) -> dict[str, Any]:
    """通过默认检索链路查询知识库。"""
    selected = questions[:max_results] if max_results > 0 else questions
    return await rag_query_task(selected)


def build_rag_tools() -> list[Any]:
    """返回供 RAG 子图 ToolNode 使用的 LangChain 工具列表。"""
    return [rag_enrichment_search]
