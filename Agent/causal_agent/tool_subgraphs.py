"工具节点子图"
from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from Agent.causal_agent import nodes
from Agent.causal_agent.context import AgentRunContext
from Agent.causal_agent.fault_tolerance import (
    degrade_academic_search,
    degrade_rag_tool_result,
    degrade_rag_parser_failure,
    degrade_rag_finalize_failure,
    degrade_web_search_parser_failure,
    degrade_web_search_planner,
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
from Agent.causal_agent.state import (
    CausalAgentState,
    RagSubgraphState,
    WebSearchInput,
    WebSearchOutput,
    WebSearchState,
)


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

    def __init__(self, tools, *, enabled: bool = True):
        self._tool_node = ToolNode(tools) if enabled else None

    async def ainvoke(self, state: RagSubgraphState, config):
        if self._tool_node is None:
            raise RuntimeError("RAG 工具不可用")
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
        error_handler=guarded_error_handler(
            recover_mcp_tool_failure,
            event_node_name="mcp_planner",
            timeout_ms=60_000,
        ),
    )
    graph.add_node(
        "mcp_tool_node",
        bind_runnable_node(ToolNode(mcp_tools), event_node_name="mcp_tool_node"),
        retry_policy=tool_retry(max_attempts=3),
        timeout=timeout(run_timeout=360, idle_timeout=120),
        error_handler=guarded_error_handler(
            recover_mcp_tool_failure,
            event_node_name="mcp_tool_node",
            timeout_ms=360_000,
            mcp_transport=True,
        ),
    )
    graph.add_node(
        "mcp_result_parser",
        bind_node(nodes.mcp_result_parser_node, event_node_name="mcp_result_parser"),
        error_handler=guarded_error_handler(
            recover_mcp_tool_failure,
            event_node_name="mcp_result_parser",
        ),
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
        error_handler=guarded_error_handler(
            degrade_rag_tool_result,
            event_node_name="rag_question_planner",
            timeout_ms=60_000,
        ),
    )
    graph.add_node(
        "rag_tool_node",
        bind_runnable_node(
            _RagToolNode(rag_tools, enabled=bool(rag_available and rag_tools)),
            event_node_name="rag_tool_node",
        ),
        retry_policy=tool_retry(max_attempts=2),
        timeout=timeout(run_timeout=120, idle_timeout=45),
        error_handler=guarded_error_handler(
            degrade_rag_tool_result,
            event_node_name="rag_tool_node",
            timeout_ms=120_000,
        ),
    )
    graph.add_node(
        "rag_result_parser",
        bind_node(nodes.rag_result_parser_node, event_node_name="rag_result_parser"),
        error_handler=guarded_error_handler(
            degrade_rag_parser_failure,
            event_node_name="rag_result_parser",
        ),
    )
    graph.add_node(
        "rag_finalize",
        bind_node(nodes.rag_finalize_node, event_node_name="rag_finalize"),
        error_handler=guarded_error_handler(
            degrade_rag_finalize_failure,
            event_node_name="rag_finalize",
        ),
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


def build_web_search_subgraph(llm):
    """构建联网搜索子图，返回 compiled subgraph。"""
    graph = StateGraph(
        WebSearchState,
        input_schema=WebSearchInput,
        output_schema=WebSearchOutput,
        context_schema=AgentRunContext,
    )
    # 注意：bind_node 的包装函数把 state 标注成了 CausalAgentState，
    # LangGraph 会据此推断每个节点的 input_schema 并过滤掉 WebSearchState
    # 特有的中间字段（planner/search）。这里显式指定 input_schema，让节点
    # 收到完整的子图状态，否则 academic_search 读不到 planner 的产出。
    graph.add_node(
        "planner",
        bind_node(
            nodes.web_search_planner_node,
            event_node_name="web_search_planner",
            llm=llm,
        ),
        input_schema=WebSearchState,
        retry_policy=short_retry(max_attempts=2),
        timeout=timeout(run_timeout=120, idle_timeout=70),
        error_handler=guarded_error_handler(
            degrade_web_search_planner,
            event_node_name="web_search_planner",
            timeout_ms=120_000,
        ),
    )
    graph.add_node(
        "academic_search",
        bind_node(nodes.academic_search_node, event_node_name="academic_search"),
        input_schema=WebSearchState,
        retry_policy=tool_retry(max_attempts=3),
        timeout=timeout(run_timeout=120, idle_timeout=45),
        error_handler=guarded_error_handler(
            degrade_academic_search,
            event_node_name="academic_search",
            timeout_ms=120_000,
        ),
    )
    graph.add_node(
        "result_parser",
        bind_node(
            nodes.web_search_result_parser_node,
            event_node_name="web_search_result_parser",
        ),
        input_schema=WebSearchState,
        timeout=timeout(run_timeout=120, idle_timeout=45),
        error_handler=guarded_error_handler(
            degrade_web_search_parser_failure,
            event_node_name="web_search_result_parser",
            timeout_ms=120_000,
        ),
    )
    graph.set_entry_point("planner")
    graph.add_edge("planner", "academic_search")
    graph.add_edge("academic_search", "result_parser")
    graph.add_edge("result_parser", END)
    return graph.compile(name="web_search")
