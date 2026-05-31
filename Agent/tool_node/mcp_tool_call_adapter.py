"辅助函数，规范化MCP调用接口"
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from Agent.causal_agent.state import CausalChatState


def _tool_name(tool: Any) -> str | None:
    """从 LangChain tool 或 OpenAI-style dict 中读取稳定工具名。"""
    if isinstance(tool, dict):
        function = tool.get("function", {})
        return function.get("name") if isinstance(function, dict) else None
    return getattr(tool, "name", None)


def _valid_mcp_tool_names(mcp_tools: list) -> set[str]:
    """获取当前 ToolNode 可执行的 MCP 工具名集合。"""
    return {name for name in (_tool_name(tool) for tool in mcp_tools) if name}


def _inject_mcp_runtime_arguments(ai_message: AIMessage, state: CausalChatState) -> AIMessage:
    """在模型选定 MCP 工具后注入大体量运行时参数。"""
    file_content = state.get("file_content")
    if not file_content:
        return ai_message

    for tool_call in getattr(ai_message, "tool_calls", []) or []:
        args = tool_call.setdefault("args", {})
        args.setdefault("csv_data", file_content)

    return ai_message


def normalize_mcp_tool_call_message(
    ai_message: AIMessage,
    state: CausalChatState,
    mcp_tools: list,
) -> AIMessage:
    """校验并规范化 MCP planner 产出的 ToolNode 调用消息。保留第一个调用"""
    valid_names = _valid_mcp_tool_names(mcp_tools)
    tool_calls = list(getattr(ai_message, "tool_calls", []) or [])
    if not tool_calls:
        raise ValueError("MCP planner did not return tool_calls.")
    ## 只保留第一个调用接口
    selected_call = dict(tool_calls[0])
    tool_name = selected_call.get("name")
    if tool_name not in valid_names:
        raise ValueError(f"MCP planner returned unknown MCP tool: {tool_name}")

    normalized_message = AIMessage(
        content=getattr(ai_message, "content", "") or "",
        tool_calls=[selected_call],
    )

    return _inject_mcp_runtime_arguments(normalized_message, state)
