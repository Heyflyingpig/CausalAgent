"辅助函数，规范化MCP调用接口"
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from Agent.causal_agent.state import CausalAgentState
from observability.logging_runtime import current_log_context


_TRUSTED_ARGUMENTS = (
    "user_id",
    "session_id",
    "job_id",
    "input_user_file_id",
    "input_object_id",
    "request_id",
    "worker_slot",
)


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


def _required_tool_arguments(tool: Any) -> set[str]:
    """读取 OpenAI/Pydantic schema 中声明为必填的参数名。"""
    if isinstance(tool, dict):
        function = tool.get("function", {})
        parameters = function.get("parameters", {}) if isinstance(function, dict) else {}
        required = parameters.get("required", []) if isinstance(parameters, dict) else []
        return {name for name in required if isinstance(name, str)}

    args_schema = getattr(tool, "args_schema", None)
    if args_schema is None:
        return set()
    model_fields = getattr(args_schema, "model_fields", None)
    if isinstance(model_fields, dict):
        required: set[str] = set()
        for name, field in model_fields.items():
            checker = getattr(field, "is_required", None)
            if callable(checker) and checker():
                required.add(name)
        return required
    fields = getattr(args_schema, "__fields__", None)
    if isinstance(fields, dict):
        return {
            name
            for name, field in fields.items()
            if bool(getattr(field, "required", False))
        }
    return set()


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
    """向 MCP 工具注入可信 Job 身份，不把 CSV 正文放入 ToolMessage。"""
    file_summary = state.get("file_summary") or {}
    log_values = current_log_context()
    raw_worker_slot = log_values.get("worker_slot")
    worker_slot = (
        int(raw_worker_slot)
        if isinstance(raw_worker_slot, str) and raw_worker_slot.isdigit()
        else None
    )
    runtime_values = {
        "user_id": state.get("user_id"),
        "session_id": state.get("session_id"),
        "job_id": state.get("job_id"),
        "input_user_file_id": file_summary.get("user_file_id"),
        "input_object_id": file_summary.get("object_id"),
        "request_id": log_values.get("request_id"),
        "worker_slot": worker_slot,
    }
    tool_index = _tools_by_name(mcp_tools)
    for tool_call in getattr(ai_message, "tool_calls", []) or []:
        tool = tool_index.get(tool_call.get("name"))
        if tool is None:
            continue
        args = tool_call.setdefault("args", {})
        if not isinstance(args, dict):
            raise ValueError("MCP tool arguments must be an object.")
        # 模型提供的可信字段一律先删除；缺失权威值时不得回退使用模型值。
        args.pop("csv_data", None)
        for name in _TRUSTED_ARGUMENTS:
            args.pop(name, None)

        required = _required_tool_arguments(tool)
        for name in _TRUSTED_ARGUMENTS:
            value = runtime_values.get(name)
            accepts = _tool_accepts_argument(tool, name)
            if accepts and value is not None:
                args[name] = value
            elif accepts and name in required:
                raise ValueError("Required MCP runtime context is unavailable.")

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
    selected_args = selected_call.get("args", {})
    if not isinstance(selected_args, dict):
        raise ValueError("MCP planner returned invalid tool arguments.")
    selected_call["args"] = dict(selected_args)
    tool_name = selected_call.get("name")
    if tool_name not in valid_names:
        raise ValueError(f"MCP planner returned unknown MCP tool: {tool_name}")

    normalized_message = AIMessage(
        content=getattr(ai_message, "content", "") or "",
        tool_calls=[selected_call],
    )

    return _inject_mcp_runtime_arguments(normalized_message, state, mcp_tools)
