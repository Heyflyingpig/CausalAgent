"注册rag工具节点"
from __future__ import annotations
from typing import Any

from langchain_core.tools import tool
from Agent.tool_node.rag_query_task import rag_query_task

@tool
async def rag_enrichment_search(
    questions: list[Any],
    max_results: int = 5,
) -> dict[str, Any]:
    """查询知识库Toolnode节点"""
    
    questions = questions[:max_results] if max_results > 0 else questions
    return await rag_query_task(questions)


def build_rag_tools() -> list[Any]:
    """Build LangChain tools for RAG enrichment."""
    return [rag_enrichment_search]
