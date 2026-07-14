from __future__ import annotations

from typing import Any, Type
from langchain_core.tools import StructuredTool

async def build_mcp_algorithm_tools(mcp_session: Any) -> list[StructuredTool]:
    """使用 LangChain MCP adapter 从持久 session 加载 MCP 工具。"""
    try:
        from langchain_mcp_adapters.tools import load_mcp_tools
    except ImportError as exc:
        raise RuntimeError(
            "缺少 langchain-mcp-adapters，无法从 MCP session 加载 LangChain tools。"
        ) from exc

    return await load_mcp_tools(mcp_session)

