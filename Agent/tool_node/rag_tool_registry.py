"注册rag工具节点"
from __future__ import annotations
from typing import Any

from langchain_core.tools import tool
from Agent.tool_node.rag_query_task import rag_query_task
from Agent.knowledge_base.multimodal.retrieval import multimodal_rag_search as _multimodal_rag_search

@tool
async def rag_enrichment_search(
    questions: list[Any],
    max_results: int = 5,
) -> dict[str, Any]:
    """查询知识库Toolnode节点"""
    
    questions = questions[:max_results] if max_results > 0 else questions
    return await rag_query_task(questions)


@tool
async def multimodal_rag_search(
    questions: list[Any],
    max_results: int = 5,
) -> dict[str, Any]:
    """查询隔离的、已发布多模态公共知识库。"""
    return _multimodal_rag_search(questions, max_results=max_results)


def build_rag_tools() -> list[Any]:
    """Build LangChain tools for RAG enrichment."""
    return [rag_enrichment_search, multimodal_rag_search]
