"工具节点子图"
from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from Agent.causal_agent import nodes
from Agent.causal_agent.fault_tolerance import (
    recover_mcp_tool_failure,
    timeout,
    tool_retry,
)
from Agent.causal_agent.graph_utils import bind_node
from Agent.causal_agent.state import CausalChatState


def build_mcp_subgraph(llm, mcp_tools):
    """Build the MCP tool-calling subgraph used as one parent-graph stage."""
    graph = StateGraph(CausalChatState)
    graph.add_node("mcp_planner", bind_node(nodes.mcp_planner_node, llm=llm, mcp_tools=mcp_tools))
    graph.add_node(
        "mcp_tool_node",
        ToolNode(mcp_tools),
        retry_policy=tool_retry(max_attempts=3),
        timeout=timeout(run_timeout=360, idle_timeout=120),
        error_handler=recover_mcp_tool_failure,
    )
    graph.add_node("mcp_result_parser", nodes.mcp_result_parser_node)
    graph.set_entry_point("mcp_planner")

    graph.add_edge("mcp_planner", "mcp_tool_node")
    graph.add_edge("mcp_tool_node", "mcp_result_parser")
    graph.add_edge("mcp_result_parser", END)
    return graph.compile(name="mcp")
