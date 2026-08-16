"工具节点子图"
from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from Agent.causal_agent import nodes
from Agent.causal_agent.fault_tolerance import (
    degrade_rag_tool_result,
    degrade_rag_parser_failure,
    degrade_rag_finalize_failure,
    recover_mcp_tool_failure,
    short_retry,
    timeout,
    tool_retry,
)
from Agent.causal_agent.graph_utils import (
    bind_node,
    bind_runnable_node,
    guarded_error_handler,
    guarded_router,
)
from Agent.causal_agent.state import CausalAgentState, RagSubgraphState


def route_rag_planner(state: RagSubgraphState) -> str:
    """根据 Planner 写入的显式 route 决定调用工具或进入 Finalize。"""
    return "call_tool" if state.get("rag_route") == "call_tool" else "finish"


def route_rag_tool_result(state: RagSubgraphState) -> str:
    """ToolNode 正常返回（包括 success=False）统一进入 Parser。"""
    return "finish" if state.get("rag_route") == "finish" else "parse"


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


class _RagToolNode:
    """给 ToolNode 的正常结果补写私有 parse route，不污染父 State。"""

    def __init__(self, tools):
        self._tool_node = ToolNode(tools)

    async def ainvoke(self, state: RagSubgraphState, config):
        result = await self._tool_node.ainvoke(state, config)
        if not isinstance(result, dict):
            raise TypeError("RAG ToolNode 必须返回 State update dict。")
        return {**result, "rag_route": "parse"}


def build_mcp_subgraph(llm, mcp_tools):
    """Build the MCP tool-calling subgraph used as one parent-graph stage."""
    graph = StateGraph(CausalAgentState)
    graph.add_node(
        "mcp_planner",
        bind_node(
            nodes.mcp_planner_node,
            event_node_name="mcp_planner",
            llm=llm,
            mcp_tools=mcp_tools,
        ),
        retry_policy=short_retry(max_attempts=2),
        timeout=timeout(run_timeout=60, idle_timeout=30),
        error_handler=guarded_error_handler(recover_mcp_tool_failure),
    )
    graph.add_node(
        "mcp_tool_node",
        bind_runnable_node(ToolNode(mcp_tools), event_node_name="mcp_tool_node"),
        retry_policy=tool_retry(max_attempts=3),
        timeout=timeout(run_timeout=360, idle_timeout=120),
        error_handler=guarded_error_handler(recover_mcp_tool_failure),
    )
    graph.add_node(
        "mcp_result_parser",
        bind_node(nodes.mcp_result_parser_node, event_node_name="mcp_result_parser"),
        error_handler=guarded_error_handler(recover_mcp_tool_failure),
    )
    graph.set_entry_point("mcp_planner")

    graph.add_conditional_edges(
        "mcp_planner",
        guarded_router(route_mcp_planner),
        {"tool": "mcp_tool_node", "failed": END},
    )
    graph.add_conditional_edges(
        "mcp_tool_node",
        guarded_router(route_mcp_tool_result),
        {"parse": "mcp_result_parser", "failed": END},
    )
    graph.add_edge("mcp_result_parser", END)
    return graph.compile(name="mcp")


def build_rag_subgraph(llm, rag_tools, rag_available: bool = True):
    """Build the RAG enrichment subgraph used as one parent-graph stage."""
    graph = StateGraph(RagSubgraphState)
    graph.add_node(
        "rag_question_planner",
        bind_node(
            nodes.rag_question_planner_node,
            event_node_name="rag_question_planner",
            llm=llm,
            rag_tools=rag_tools,
            rag_available=rag_available,
        ),
        retry_policy=short_retry(max_attempts=2),
        timeout=timeout(run_timeout=60, idle_timeout=30),
        error_handler=guarded_error_handler(degrade_rag_tool_result),
    )
    graph.add_node(
        "rag_tool_node",
        bind_runnable_node(_RagToolNode(rag_tools), event_node_name="rag_tool_node"),
        retry_policy=tool_retry(max_attempts=2),
        timeout=timeout(run_timeout=120, idle_timeout=45),
        error_handler=guarded_error_handler(degrade_rag_tool_result),
    )
    graph.add_node(
        "rag_result_parser",
        bind_node(nodes.rag_result_parser_node, event_node_name="rag_result_parser"),
        error_handler=guarded_error_handler(degrade_rag_parser_failure),
    )
    graph.add_node(
        "rag_finalize",
        bind_node(nodes.rag_finalize_node, event_node_name="rag_finalize"),
        error_handler=guarded_error_handler(degrade_rag_finalize_failure),
    )
    graph.set_entry_point("rag_question_planner")

    graph.add_conditional_edges(
        "rag_question_planner",
        guarded_router(route_rag_planner),
        {"call_tool": "rag_tool_node", "finish": "rag_finalize"},
    )
    graph.add_conditional_edges(
        "rag_tool_node",
        guarded_router(route_rag_tool_result),
        {"parse": "rag_result_parser", "finish": "rag_finalize"},
    )
    graph.add_edge("rag_result_parser", "rag_finalize")
    graph.add_edge("rag_finalize", END)
    return graph.compile(name="rag")
