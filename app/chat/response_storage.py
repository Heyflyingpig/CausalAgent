"""
app.chat.response_storage - AI 响应展示与持久化格式转换。
"""

import json
from typing import Any

from Agent.Report.Metadata_sum import replace_placeholders


def render_summary_for_display(summary: str | None, visualization_mapping: dict | None) -> str | None:
    """把原始报告占位符渲染成图片标签，并避免已经渲染过的 HTML 被二次替换。"""
    if not summary or not visualization_mapping:
        return summary

    if "data:image/" in summary or "<img" in summary.lower():
        return summary

    return replace_placeholders(summary, visualization_mapping)


def prepare_ai_response_for_storage(ai_response: Any) -> tuple[str, list[dict[str, str]]]:
    """把 AI 响应转换为聊天主表内容和附件列表，报告正文入库时保留原始占位符。"""
    attachment_to_save: list[dict[str, str]] = []

    if isinstance(ai_response, dict):
        raw_summary = ai_response.get("raw_summary") or ai_response.get("summary")
        ai_content = raw_summary

        if ai_content is None:
            ai_content = json.dumps(ai_response, ensure_ascii=False)

        if ai_response.get("type") == "causal_graph" and "data" in ai_response:
            persisted_response = dict(ai_response)
            if raw_summary is not None:
                persisted_response["summary"] = raw_summary
            persisted_response.pop("raw_summary", None)
            persisted_response.pop("visualization_mapping", None)
            persisted_response.pop("references", None)
            attachment_to_save.append({
                "type": "causal_graph",
                "content": json.dumps(persisted_response, ensure_ascii=False),
            })

        if ai_response.get("visualization_mapping"):
            attachment_to_save.append({
                "type": "visualization",
                "content": json.dumps(ai_response["visualization_mapping"], ensure_ascii=False),
            })

        if ai_response.get("references"):
            attachment_to_save.append({
                "type": "web_search_references",
                "content": json.dumps(ai_response["references"], ensure_ascii=False),
            })

        return ai_content, attachment_to_save

    if isinstance(ai_response, str):
        return ai_response, attachment_to_save

    return json.dumps(ai_response, ensure_ascii=False), attachment_to_save
