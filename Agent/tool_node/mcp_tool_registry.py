from __future__ import annotations

import json
from typing import Any, Type

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, create_model


def _json_schema_type_to_python(prop_schema: dict[str, Any]) -> type:
    """Map a simple MCP JSON Schema property to a Python type."""
    schema_type = prop_schema.get("type")
    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        return list
    if schema_type == "object":
        return dict
    return str


def _build_args_model(tool_name: str, input_schema: dict[str, Any]) -> Type[BaseModel]:
    """Create a Pydantic args model from an MCP inputSchema."""
    fields: dict[str, tuple[type, Any]] = {}
    properties = input_schema.get("properties", {}) if isinstance(input_schema, dict) else {}
    required = set(input_schema.get("required", [])) if isinstance(input_schema, dict) else set()

    for prop_name, prop_schema in properties.items():
        field_type = _json_schema_type_to_python(prop_schema)
        default = ... if prop_name in required else None
        fields[prop_name] = (field_type, default)

    model_name = "".join(part.capitalize() for part in tool_name.split("_")) or "McpTool"
    return create_model(f"{model_name}Args", **fields)


def _normalize_mcp_response(response: Any) -> dict[str, Any]:
    """把 MCP call_tool 返回值严格规范化为 JSON object 对应的 dict。"""
    if isinstance(response, dict):
        return response

    content = getattr(response, "content", None)
    if content:
        text = getattr(content[0], "text", None)
        if text is not None:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                raise ValueError("MCP tool response text must be valid JSON.") from None
            if not isinstance(parsed, dict):
                raise ValueError("MCP tool response JSON must be a JSON object.")
            return parsed

    raise ValueError("MCP tool response must be a dict or text JSON object.")


async def build_mcp_algorithm_tools(mcp_session: Any) -> list[StructuredTool]:
    """从会话中暴露的MCP算法工具构建LangChain工具。"""
    tool_list = await mcp_session.list_tools()
    tools: list[StructuredTool] = []

    for mcp_tool in getattr(tool_list, "tools", []):
        tool_name = mcp_tool.name
        description = getattr(mcp_tool, "description", "") or f"Run MCP tool {tool_name}."
        input_schema = getattr(mcp_tool, "inputSchema", None) or {
            "type": "object",
            "properties": {},
        }
        args_model = _build_args_model(tool_name, input_schema)

        def make_call(name: str):
            async def _call_tool(**kwargs: Any) -> Any:
                response = await mcp_session.call_tool(name, kwargs)
                return _normalize_mcp_response(response)

            _call_tool.__name__ = name
            return _call_tool

        tools.append(
            StructuredTool.from_function(
                coroutine=make_call(tool_name),
                name=tool_name,
                description=description,
                args_schema=args_model,
            )
        )

    return tools
