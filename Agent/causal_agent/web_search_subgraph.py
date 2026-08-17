"""联网搜索子图构建：线性 4 节点，私有 state，唯一出口 web_search_result。"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from Agent.causal_agent.context import AgentRunContext
from Agent.causal_agent.fault_tolerance import (
    degrade_web_search_content,
    degrade_web_search_planner,
    degrade_web_search_search,
    short_retry,
    timeout,
    tool_retry,
)
from Agent.causal_agent.graph_utils import bind_node, guarded_error_handler
from Agent.causal_agent.web_search_node import (
    WebSearchInput,
    WebSearchOutput,
    WebSearchState,
    content_fetch_node,
    searxng_search_node,
    web_search_planner_node,
    web_search_result_parser_node,
)


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
    # 特有的中间字段（planner/searxng/content）。这里显式指定 input_schema，
    # 让节点收到完整的子图状态，否则 searxng 读不到 planner 的产出。
    graph.add_node(
        "planner",
        bind_node(
            web_search_planner_node,
            event_node_name="web_search_planner",
            llm=llm,
        ),
        input_schema=WebSearchState,
        retry_policy=short_retry(max_attempts=2),
        timeout=timeout(run_timeout=60, idle_timeout=30),
        error_handler=guarded_error_handler(degrade_web_search_planner),
    )
    graph.add_node(
        "searxng_search",
        bind_node(searxng_search_node, event_node_name="searxng_search"),
        input_schema=WebSearchState,
        retry_policy=tool_retry(max_attempts=3),
        timeout=timeout(run_timeout=120, idle_timeout=45),
        error_handler=guarded_error_handler(degrade_web_search_search),
    )
    graph.add_node(
        "content_fetch",
        bind_node(content_fetch_node, event_node_name="content_fetch"),
        input_schema=WebSearchState,
        retry_policy=tool_retry(max_attempts=2),
        timeout=timeout(run_timeout=120, idle_timeout=45),
        error_handler=guarded_error_handler(degrade_web_search_content),
    )
    graph.add_node(
        "result_parser",
        bind_node(
            web_search_result_parser_node,
            event_node_name="web_search_result_parser",
            llm=llm,
        ),
        input_schema=WebSearchState,
        timeout=timeout(run_timeout=420, idle_timeout=120),
    )
    graph.set_entry_point("planner")
    graph.add_edge("planner", "searxng_search")
    graph.add_edge("searxng_search", "content_fetch")
    graph.add_edge("content_fetch", "result_parser")
    graph.add_edge("result_parser", END)
    return graph.compile(name="web_search")
