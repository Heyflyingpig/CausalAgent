"注册rag工具节点"
from __future__ import annotations
import logging
from typing import Any

from langchain_core.tools import tool
from Agent.knowledge_base.rag_service import UNAVAILABLE_RAG_RESULT
from Agent.tool_node.rag_query_task import rag_query_task
from Agent.knowledge_base.multimodal.retrieval import multimodal_rag_search as _multimodal_rag_search


def build_rag_tools(rag_service: Any) -> list[Any]:
    """创建闭包绑定 Service、但 schema 只暴露查询参数的 RAG Tool。"""

    @tool("rag_enrichment_search")
    async def rag_enrichment_search(
        questions: list[Any],
        max_results: int = 5,
    ) -> dict[str, Any]:
        """查询知识库以增强因果分析报告。"""
        selected = questions[:max_results] if max_results > 0 else questions
        try:
            return await rag_query_task(selected, rag_service)
        except Exception:
            logging.error("RAG Tool 单次调用失败，本次结果降级。", exc_info=True)
            return dict(UNAVAILABLE_RAG_RESULT)

    return [rag_enrichment_search, multimodal_rag_search]


@tool("multimodal_rag_search")
async def multimodal_rag_search(
    questions: list[Any],
    max_results: int = 5,
) -> dict[str, Any]:
    """查询隔离的、已发布多模态公共知识库。"""
    return _multimodal_rag_search(questions, max_results=max_results)
