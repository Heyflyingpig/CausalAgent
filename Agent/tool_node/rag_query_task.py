"""显式 RagQueryService 的异步兼容适配器。"""

import asyncio
from typing import Any, Dict, List, Union


async def rag_query_task(
    questions: List[Union[str, Dict]],
    rag_service: Any,
) -> Dict:
    """
    Task: 查询知识库（RAG）

    Args:
        questions: 要查询的问题列表，支持字符串问题和结构化问题对象。

    Returns:
        dict: 结构化的知识库查询结果。
    """
    return await asyncio.to_thread(rag_service.get_response, questions)
