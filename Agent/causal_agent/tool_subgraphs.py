"工具节点子图"
from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from Agent.causal_agent import nodes
from Agent.causal_agent.fault_tolerance import (
    recover_mcp_tool_failure,
    short_retry,
    timeout,
    tool_retry,
)
from Agent.causal_agent.graph_utils import bind_node
from Agent.causal_agent.state import CausalAgentState


def route_mcp_planner(state: CausalAgentState) -> str:
    """MCP planner 只有产生标准 tool_calls 时才进入 ToolNode。"""
    messages = state.get("messages", [])
    latest_message = messages[-1] if messages else None
    return "tool" if getattr(latest_message, "tool_calls", None) else "failed"


def route_mcp_tool_result(state: CausalAgentState) -> str:
    """ToolNode 异常恢复后直接结束子图，正常 ToolMessage 交给 parser。"""
    messages = state.get("messages", [])
    latest_message = messages[-1] if messages else None
    if getattr(latest_message, "type", None) == "tool":
        return "parse"

    result = state.get("causal_analysis_result")
    if isinstance(result, dict) and result.get("success") is False:
        return "failed"
    return "parse"


def build_mcp_subgraph(llm, mcp_tools):
    """Build the MCP tool-calling subgraph used as one parent-graph stage."""
    graph = StateGraph(CausalAgentState)
    graph.add_node(
        "mcp_planner",
        bind_node(nodes.mcp_planner_node, llm=llm, mcp_tools=mcp_tools),
        retry_policy=short_retry(max_attempts=2),
        timeout=timeout(run_timeout=60, idle_timeout=30),
        error_handler=recover_mcp_tool_failure,
    )
    graph.add_node(
        "mcp_tool_node",
        ToolNode(mcp_tools),
        retry_policy=tool_retry(max_attempts=3),
        timeout=timeout(run_timeout=360, idle_timeout=120),
        error_handler=recover_mcp_tool_failure,
    )
    graph.add_node(
        "mcp_result_parser",
        nodes.mcp_result_parser_node,
        error_handler=recover_mcp_tool_failure,
    )
    graph.set_entry_point("mcp_planner")

    graph.add_conditional_edges(
        "mcp_planner",
        route_mcp_planner,
        {"tool": "mcp_tool_node", "failed": END},
    )
    graph.add_conditional_edges(
        "mcp_tool_node",
        route_mcp_tool_result,
        {"parse": "mcp_result_parser", "failed": END},
    )
    graph.add_edge("mcp_result_parser", END)
    return graph.compile(name="mcp")
