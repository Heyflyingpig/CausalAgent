"""执行单个 LangGraph graph 并生成稳定的内部流事件。"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.agent.worker.event_adapter import (
    LangGraphEventAdapter,
    sanitize_public_error,
)
from app.agent.worker.result_presenter import process_final_result


def _snapshot_interrupts(snapshot: Any) -> list[Any]:
    """汇总 LangGraph StateSnapshot 中尚待恢复的 task interrupts。"""
    return [
        item
        for task in (getattr(snapshot, "tasks", None) or ())
        for item in (getattr(task, "interrupts", None) or ())
    ]


async def ai_call_stream(
    text: str,
    user_id: int,
    username: str,
    session_id: str,
    *,
    job_id: str | None,
    job_attempt: int,
    graph: Any,
) -> AsyncIterator[dict[str, Any]]:
    """在显式传入的 graph 上执行一次调用并产出公开事件。"""
    if graph is None:
        raise RuntimeError("Agent Graph 尚未初始化")

    logging.info("[流式] 处理用户 %s 的消息，会话ID: %s", username, session_id)
    config = {
        "configurable": {
            "thread_id": session_id,
            "user_id": user_id,
        },
        "metadata": {"job_id": job_id} if job_id else {},
    }

    try:
        state = await graph.aget_state(config)
        if _snapshot_interrupts(state):
            logging.info("[流式] 检测到会话 %s 处于中断状态", session_id)
            input_data: Any = Command(resume=text)
        else:
            input_data = {
                "messages": [HumanMessage(content=text)],
                "user_id": user_id,
                "username": username,
                "session_id": session_id,
            }
    except Exception as exc:
        logging.warning("[流式] 无法获取状态，按新对话处理: %s", exc)
        input_data = {
            "messages": [HumanMessage(content=text)],
            "user_id": user_id,
            "username": username,
            "session_id": session_id,
        }

    adapter = LangGraphEventAdapter(job_id, job_attempt)
    streamed_interrupts: list[Any] = []
    try:
        async for chunk in graph.astream(
            input_data,
            config,
            stream_mode=["updates", "messages", "custom", "tasks"],
            subgraphs=True,
            version="v2",
        ):
            if chunk.get("type") == "updates" and isinstance(chunk.get("data"), dict):
                interrupt_data = chunk["data"].get("__interrupt__")
                if interrupt_data:
                    streamed_interrupts.extend(
                        interrupt_data
                        if isinstance(interrupt_data, (list, tuple))
                        else [interrupt_data]
                    )
            for event_data in adapter.convert(chunk):
                yield event_data

        state = await graph.aget_state(config)
        interrupts = _snapshot_interrupts(state) or streamed_interrupts
        if interrupts:
            interrupt_obj = interrupts[0]
            question = (
                interrupt_obj.value
                if hasattr(interrupt_obj, "value")
                else str(interrupt_obj)
            )
            yield {
                "type": "interrupt",
                "message": question,
                "attempt": job_attempt,
            }
            logging.info("[SSE] 图已暂停，等待用户输入")
            return

        yield {
            "type": "final_result",
            "data": process_final_result(state.values),
            "attempt": job_attempt,
        }
        logging.info("[SSE] 发送最终结果")
    except Exception as exc:
        logging.error("[流式] 执行 LangGraph Agent 时发生错误: %s", exc, exc_info=True)
        yield {
            "type": "error",
            "message": sanitize_public_error(exc),
            "attempt": job_attempt,
        }
