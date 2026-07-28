"辅助函数：规范化tool调用接口"
from __future__ import annotations

import ast
import json
from typing import Any

from langchain_core.messages import ToolMessage


def _normalize_payload(payload: Any) -> dict[str, Any]:
    """把 adapter 或手写工具返回载荷统一成业务 dict。"""
    if isinstance(payload, dict):
        return payload
    return {"success": True, "data": payload}


def _json_object_from_text(text: str) -> dict[str, Any] | None:
    """尝试从文本解析 JSON object；非 JSON 文本返回 None。"""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return _normalize_payload(parsed)


def _structured_content_from_artifact(artifact: Any) -> Any:
    """兼容 langchain-mcp-adapters 的 artifact structured_content。"""
    if isinstance(artifact, dict) and "structured_content" in artifact:
        return artifact["structured_content"]
    structured_content = getattr(artifact, "structured_content", None)
    if structured_content is not None:
        return structured_content
    return None


def _parse_content_blocks(tool_message: ToolMessage) -> dict[str, Any] | None:
    """从 ToolMessage content_blocks 中提取第一个可解析的文本或结构化块。"""
    blocks = getattr(tool_message, "content_blocks", None)
    if not blocks:
        return None
    for block in blocks:
        if isinstance(block, dict):
            if "structured_content" in block:
                return _normalize_payload(block["structured_content"])
            text = block.get("text")
            if isinstance(text, str) and (parsed := _json_object_from_text(text)) is not None:
                return parsed
        elif isinstance(block, str) and (parsed := _json_object_from_text(block)) is not None:
            return parsed
    return None


def _parse_content_block_list(content: Any) -> dict[str, Any] | None:
    """解析 MCP adapter 直接写入 ToolMessage.content 的文本块列表。"""
    if not isinstance(content, list):
        return None
    for block in content:
        if isinstance(block, dict):
            text = block.get("text")
            if isinstance(text, str) and (parsed := _json_object_from_text(text)) is not None:
                return parsed
    return None


def _parse_adapter_payload(payload: Any) -> dict[str, Any] | None:
    """从 adapter 的 structured_content 包装中递归取出业务 JSON。"""
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            try:
                decoded = ast.literal_eval(payload)
            except (ValueError, SyntaxError):
                return None
        return _parse_adapter_payload(decoded)
    if (parsed := _parse_content_block_list(payload)) is not None:
        return parsed
    if isinstance(payload, dict):
        text = payload.get("text")
        if isinstance(text, str) and (parsed := _json_object_from_text(text)) is not None:
            return parsed
        if "success" in payload:
            return payload
        for value in payload.values():
            if (parsed := _parse_adapter_payload(value)) is not None:
                return parsed
    return None


def parse_tool_message_json(tool_message: ToolMessage) -> dict[str, Any]:
    """解析 ToolMessage 多种有效载荷并将其转换为业务结果字典。"""
    artifact_payload = _structured_content_from_artifact(getattr(tool_message, "artifact", None))
    if artifact_payload is not None:
        if parsed := _parse_adapter_payload(artifact_payload):
            return parsed
        return _normalize_payload(artifact_payload)

    content = getattr(tool_message, "content", "")
    if isinstance(content, dict):
        if parsed := _parse_adapter_payload(content):
            return parsed
        return content
    if content_block_list_result := _parse_content_block_list(content):
        return content_block_list_result
    # 海象表达法，先赋值，后判断
    if content_blocks_result := _parse_content_blocks(tool_message):
        return content_blocks_result
    if not isinstance(content, str):
        return {"success": True, "data": content}
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        try:
            literal = ast.literal_eval(content)
        except (ValueError, SyntaxError):
            literal = None
        if parsed := _parse_adapter_payload(literal):
            return parsed
        return {
            "success": False,
            "error": f"ToolMessage content is not valid JSON: {exc}",
            "raw_content": content,
        }
    return parsed if isinstance(parsed, dict) else {"success": True, "data": parsed}


def _latest_tool_message(messages: list) -> ToolMessage | None:
    """从消息列表中获取最新的工具返回消息。"""
    tool_messages = [
        message for message in messages
        if isinstance(message, ToolMessage) or getattr(message, "type", None) == "tool"
    ]
    return tool_messages[-1] if tool_messages else None


def _latest_ai_tool_calls(messages: list) -> list[Any]:
    """获取最新 AI 工具调用消息中的 tool_calls 列表。"""
    for message in reversed(messages):
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            return list(tool_calls)
    return []


def _tool_call_id(tool_call: Any) -> str | None:
    """从 dict 或对象形态的 tool_call 中读取调用 ID。"""
    if isinstance(tool_call, dict):
        return tool_call.get("id")
    return getattr(tool_call, "id", None)


def _tool_call_name(tool_call: Any) -> str | None:
    """从 dict 或对象形态的 tool_call 中读取工具名。"""
    if isinstance(tool_call, dict):
        return tool_call.get("name")
    return getattr(tool_call, "name", None)


def latest_ai_tool_call_ids(messages: list) -> set[str]:
    """获取最新 AI 工具调用消息中的 tool_call id 集合。"""
    return {
        tool_call_id
        for tool_call_id in (_tool_call_id(tool_call) for tool_call in _latest_ai_tool_calls(messages))
        if tool_call_id
    }


def latest_matching_tool_result(messages: list) -> tuple[ToolMessage | None, Any | None]:
    """获取最新 AI tool_call 及其匹配的 ToolMessage。"""
    tool_calls = _latest_ai_tool_calls(messages)
    if not tool_calls:
        return _latest_tool_message(messages), None

    tool_calls_by_id = {
        tool_call_id: tool_call
        for tool_call in tool_calls
        if (tool_call_id := _tool_call_id(tool_call))
    }
    if not tool_calls_by_id:
        return None, None

    for message in reversed(messages):
        is_tool_message = isinstance(message, ToolMessage) or getattr(message, "type", None) == "tool"
        tool_call_id = getattr(message, "tool_call_id", None)
        if is_tool_message and tool_call_id in tool_calls_by_id:
            return message, tool_calls_by_id[tool_call_id]
    return None, None


def _tool_call_metadata(tool_message: ToolMessage, tool_call: Any, success: bool) -> dict[str, Any]:
    """把工具协议消息压缩成业务层可读的轻量元数据。"""
    return {
        "id": getattr(tool_message, "tool_call_id", None) or _tool_call_id(tool_call),
        "name": _tool_call_name(tool_call),
        "status": "success" if success else "error",
    }


def attach_tool_call_metadata(
    result: dict[str, Any],
    tool_message: ToolMessage,
    tool_call: Any,
) -> dict[str, Any]:
    """把工具调用元数据内嵌到对应业务结果，避免污染顶层 state。"""
    enriched_result = dict(result)
    enriched_result["_tool_call"] = _tool_call_metadata(
        tool_message,
        tool_call,
        bool(result.get("success")),
    )
    return enriched_result
