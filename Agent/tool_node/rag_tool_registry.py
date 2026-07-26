"注册rag工具节点"
from __future__ import annotations
import logging
from typing import Any

from langchain_core.tools import tool
from Agent.knowledge_base.rag_service import UNAVAILABLE_RAG_RESULT
from Agent.tool_node.rag_query_task import rag_query_task


def build_rag_tools(rag_service: Any) -> list[Any]:
    """使用原工具名创建绑定多模态 RagService 的查询工具。"""

    @tool("rag_enrichment_search")
    async def rag_enrichment_search(
        questions: list[Any],
        max_results: int = 5,
    ) -> dict[str, Any]:
        """通过默认 RAG Runtime 查询已发布的多模态知识库。"""
        selected = questions[:max_results] if max_results > 0 else questions
        try:
            return await rag_query_task(selected, rag_service)
        except Exception:
            logging.error("RAG Tool 单次调用失败，本次结果降级。", exc_info=True)
            return dict(UNAVAILABLE_RAG_RESULT)

    return [rag_enrichment_search]
