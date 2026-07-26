"工具节点子图"
from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from Agent.causal_agent import nodes
from Agent.causal_agent.fault_tolerance import (
    degrade_rag_tool_result,
    recover_mcp_tool_failure,
    short_retry,
    timeout,
    tool_retry,
)
from Agent.causal_agent.graph_utils import bind_node
from Agent.causal_agent.state import CausalChatState


def route_rag_planner(state: CausalChatState) -> str:
    """仅在 RAG planner 产生标准 tool_calls 时进入 ToolNode。当失败时，跳过子图"""
    messages = state.get("messages", [])
    latest_message = messages[-1] if messages else None
    return "tool" if getattr(latest_message, "tool_calls", None) else "skip"


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


def build_rag_subgraph(llm, rag_tools):
    """Build the RAG enrichment subgraph used as one parent-graph stage."""
    graph = StateGraph(CausalChatState)
    graph.add_node(
        "rag_question_planner",
        bind_node(nodes.rag_question_planner_node, llm=llm, rag_tools=rag_tools),
        retry_policy=short_retry(max_attempts=2),
        timeout=timeout(run_timeout=60, idle_timeout=30),
        error_handler=degrade_rag_tool_result,
    )
    graph.add_node(
        "rag_tool_node",
        ToolNode(rag_tools),
        retry_policy=tool_retry(max_attempts=2),
        timeout=timeout(run_timeout=120, idle_timeout=45),
        error_handler=degrade_rag_tool_result,
    )
    graph.add_node("rag_result_parser", nodes.rag_result_parser_node)
    graph.set_entry_point("rag_question_planner")
    
    graph.add_conditional_edges(
        "rag_question_planner",
        route_rag_planner,
        {"tool": "rag_tool_node", "skip": END},
    )
    graph.add_edge("rag_tool_node", "rag_result_parser")
    graph.add_edge("rag_result_parser", END)
    return graph.compile(name="rag")
