"""
@task封装的RAG查询任务
"""
import logging
import asyncio
from typing import Dict, List, Union

from langgraph.func import task

from Agent.knowledge_base.query_rag import get_rag_response


@task
async def rag_query_task(questions: List[Union[str, Dict]]) -> Dict:
    """
    Task: 查询知识库（RAG）

    Args:
        questions: 要查询的问题列表，支持字符串问题和结构化问题对象。

    Returns:
        dict: 结构化的知识库查询结果。
    """
    logging.info("正在启动RAG查询任务...")
    try:
        rag_response = await asyncio.to_thread(get_rag_response, questions)
        logging.info("Task: 知识库查询完成")
        return rag_response
    
    except Exception as exc:
        logging.error(f"Task: 知识库查询失败: {exc}", exc_info=True)
        return {
            "success": False,
            "summary": f"知识库查询失败：{exc}",
            "questions": [],
            "evidence_count": 0,
            "error": str(exc),
        }
