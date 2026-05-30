from __future__ import annotations

from typing import Any

from langchain_core.tools import tool


@tool
async def rag_enrichment_search(
    questions: list[Any],
    max_results: int = 5,
) -> dict[str, Any]:
    """Search the knowledge base after causal analysis and return supporting evidence."""
    from Agent.tool_node.rag_query_task import rag_query_task

    questions = questions[:max_results] if max_results > 0 else questions
    return await rag_query_task(questions)


def build_rag_tools() -> list[Any]:
    """Build LangChain tools for RAG enrichment."""
    return [rag_enrichment_search]
