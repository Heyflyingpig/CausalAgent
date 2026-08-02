"辅助函数，规范化MCP调用接口"
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from Agent.causal_agent.state import CausalAgentState


def _tool_name(tool: Any) -> str | None:
    """从 LangChain tool 或 OpenAI-style dict 中读取稳定工具名。"""
    if isinstance(tool, dict):
        function = tool.get("function", {})
        return function.get("name") if isinstance(function, dict) else None
    return getattr(tool, "name", None)


def _valid_mcp_tool_names(mcp_tools: list) -> set[str]:
    """获取当前 ToolNode 可执行的 MCP 工具名集合。"""
    return {name for name in (_tool_name(tool) for tool in mcp_tools) if name}


def _tool_accepts_argument(tool: Any, argument_name: str) -> bool:
    """判断 LangChain tool 或 OpenAI-style schema 是否声明了某个入参。"""
    if isinstance(tool, dict):
        function = tool.get("function", {})
        parameters = function.get("parameters", {}) if isinstance(function, dict) else {}
        properties = parameters.get("properties", {}) if isinstance(parameters, dict) else {}
        return argument_name in properties

    args_schema = getattr(tool, "args_schema", None)
    if args_schema is not None:
        model_fields = getattr(args_schema, "model_fields", None)
        if isinstance(model_fields, dict):
            return argument_name in model_fields
        fields = getattr(args_schema, "__fields__", None)
        if isinstance(fields, dict):
            return argument_name in fields

    args = getattr(tool, "args", None)
    return isinstance(args, dict) and argument_name in args


def _tools_by_name(mcp_tools: list) -> dict[str, Any]:
    """按工具名索引当前可执行 MCP tools。"""
    return {
        name: tool
        for tool in mcp_tools
        if (name := _tool_name(tool))
    }


def _inject_mcp_runtime_arguments(
    ai_message: AIMessage,
    state: CausalAgentState,
    mcp_tools: list,
) -> AIMessage:
    """在模型选定 MCP 工具后，只向声明 csv_data 的工具补充运行时数据。"""
    file_content = state.get("file_content")
    if not file_content:
        return ai_message

    tool_index = _tools_by_name(mcp_tools)
    for tool_call in getattr(ai_message, "tool_calls", []) or []:
        tool = tool_index.get(tool_call.get("name"))
        if tool is None or not _tool_accepts_argument(tool, "csv_data"):
            continue
        args = tool_call.setdefault("args", {})
        args["csv_data"] = file_content

    return ai_message


def normalize_mcp_tool_call_message(
    ai_message: AIMessage,
    state: CausalAgentState,
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

    return _inject_mcp_runtime_arguments(normalized_message, state, mcp_tools)
