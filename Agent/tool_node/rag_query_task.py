"""
@task封装的RAG查询任务
"""
import asyncio
from typing import Dict, List, Union

from langgraph.func import task

from Agent.knowledge_base.query_rag import get_rag_response
from app.agent.worker.execution_guard import JobExecutionRevoked


@task
async def rag_query_task(questions: List[Union[str, Dict]]) -> Dict:
    """
    Task: 查询知识库（RAG）

    Args:
        questions: 要查询的问题列表，支持字符串问题和结构化问题对象。

    Returns:
        dict: 结构化的知识库查询结果。
    """
    try:
        rag_response = await asyncio.to_thread(get_rag_response, questions)
        return rag_response
    
    except (JobExecutionRevoked, asyncio.CancelledError):
        raise
    except Exception as exc:
        return {
            "success": False,
            "status": "unavailable",
            "error_type": "RAGQueryError",
            "summary": f"知识库查询失败：{exc}",
            "questions": [],
            "evidence_count": 0,
            "error": str(exc),
        }
