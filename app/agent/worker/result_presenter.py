"""把 Agent 最终状态转换为聊天与 SSE 共用的公开结果。"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage

from app.chat.response_storage import render_summary_for_display
from observability.logging_runtime import log_context, log_event


LOGGER = logging.getLogger(__name__)


def process_final_result(final_state_data: dict[str, Any]) -> dict[str, Any]:
    """按消息、报告和因果图优先级生成稳定的最终响应。"""
    messages = final_state_data.get("messages", [])
    if messages:
        last_message = messages[-1]
        if isinstance(last_message, AIMessage):
            message_name = getattr(last_message, "name", None)
            if message_name in {"normal_chat", "inquiry_answer"}:
                return {"type": "text", "summary": last_message.content}

            if message_name == "report" and final_state_data.get("final_report"):
                result: dict[str, Any] = {
                    "summary": final_state_data["final_report"],
                    "layout": "report",
                }
                analysis_data = final_state_data.get("causal_analysis_result")
                if isinstance(analysis_data, dict) and analysis_data.get("success"):
                    original_graph = analysis_data.get("data")
                    postprocess_result = final_state_data.get("postprocess_result") or {}
                    revised_graph = postprocess_result.get("revised_graph")
                    has_valid_revised_graph = (
                        isinstance(revised_graph, dict)
                        and isinstance(revised_graph.get("nodes"), list)
                        and isinstance(revised_graph.get("edges"), list)
                        and not postprocess_result.get("error")
                    )
                    result["type"] = "causal_graph"
                    result["data"] = (
                        revised_graph if has_valid_revised_graph else original_graph
                    )
                    result["graph_source"] = (
                        "postprocessed" if has_valid_revised_graph else "original"
                    )
                    result["revision_summary"] = postprocess_result.get(
                        "revision_summary",
                        "",
                    )
                result.setdefault("type", "text")
                visualization_mapping = final_state_data.get("visualization_mapping")
                if visualization_mapping:
                    result["raw_summary"] = result["summary"]
                    result["visualization_mapping"] = visualization_mapping
                    result["summary"] = render_summary_for_display(
                        result["summary"],
                        visualization_mapping,
                    )
                return result

    final_report = final_state_data.get("final_report")
    if final_report:
        return {"type": "text", "summary": final_report, "layout": "report"}

    with log_context(node="result_presenter"):
        log_event(
            LOGGER,
            "job.node.degraded",
            details={
                "failure_kind": "missing_result",
                "final_attempt": 1,
                "fallback": "default_message",
            },
        )
    return {"type": "text", "summary": "抱歉，我在处理时遇到了问题。"}
