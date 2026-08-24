"""把 Agent 最终状态转换为聊天与 SSE 共用的公开结果。"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage

from app.chat.response_storage import render_summary_for_display


def _extract_references(web_search_result: Any) -> list[dict]:
    """从联网搜索结果投影前 5 条引用（仅 title + url）。"""
    if not web_search_result or not web_search_result.get("success"):
        return []
    return [
        {"title": c.get("title", ""), "url": c.get("url", "")}
        for c in web_search_result.get("content", [])[:5]
    ]


def process_final_result(final_state_data: dict[str, Any]) -> dict[str, Any]:
    """按消息、报告和因果图优先级生成稳定的最终响应。"""
    messages = final_state_data.get("messages", [])
    if messages:
        last_message = messages[-1]
        if isinstance(last_message, AIMessage):
            message_name = getattr(last_message, "name", None)
            if message_name in {"normal_chat", "inquiry_answer"}:
                logging.info("返回 %s 节点的回复", message_name)
                return {"type": "text", "summary": last_message.content}

            if message_name == "report" and final_state_data.get("final_report"):
                logging.info("返回完整的因果分析报告")
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
                    logging.info(
                        "返回因果图数据: source=%s",
                        result["graph_source"],
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
                    logging.info(
                        "已替换报告中的 %s 个可视化占位符",
                        len(visualization_mapping),
                    )
                references = _extract_references(final_state_data.get("web_search_result"))
                if references:
                    result["references"] = references
                return result

    final_report = final_state_data.get("final_report")
    if final_report:
        logging.info("未找到最新消息，降级返回 final_report")
        result = {"type": "text", "summary": final_report, "layout": "report"}
        references = _extract_references(final_state_data.get("web_search_result"))
        if references:
            result["references"] = references
        return result

    logging.warning("未找到任何可返回的内容，返回默认消息")
    return {"type": "text", "summary": "抱歉，我在处理时遇到了问题。"}
