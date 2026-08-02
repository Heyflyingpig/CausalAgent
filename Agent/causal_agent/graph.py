from langgraph.graph import StateGraph, END
from .state import CausalAgentState
from . import nodes, edges
from .graph_utils import bind_node
from .tool_subgraphs import build_mcp_subgraph, build_rag_subgraph
from .fault_tolerance import (
    recover_postprocess_to_report,
    recover_report,
    recover_terminal_message,
    recover_tools_to_agent,
    recover_fold_to_agent,
    recover_preprocess_to_agent,
    route_to_normal_chat,
    short_retry,
    timeout,
    tool_retry,
)
import logging




def build_graph(llm: "ChatOpenAI", mcp_tools: list, rag_tools: list, checkpointer):
    """
    构建父图。

    父图只表达业务阶段顺序，MCP/RAG 的 tool-calling 细节封装在各自子图内。
    """
    workflow = StateGraph(CausalAgentState)

    agent_node_with_llm = bind_node(nodes.agent_node, llm=llm)
    fold_node_with_llm = bind_node(nodes.fold_node, llm=llm)
    preprocess_node_with_llm = bind_node(nodes.preprocess_node, llm=llm)
    mcp_subgraph = build_mcp_subgraph(llm=llm, mcp_tools=mcp_tools)
    rag_subgraph = build_rag_subgraph(llm=llm, rag_tools=rag_tools)
    postprocess_node_with_llm = bind_node(nodes.postprocess_node, llm=llm)
    inquiry_answer_node_with_llm = bind_node(nodes.inquiry_answer_node, llm=llm)
    report_node_with_llm = bind_node(nodes.report_node, llm=llm)
    normal_chat_node_with_llm = bind_node(nodes.normal_chat_node, llm=llm)

    workflow.add_node(
        "agent",
        agent_node_with_llm,
        retry_policy=short_retry(),
        timeout=timeout(run_timeout=45, idle_timeout=20),
        error_handler=route_to_normal_chat,
    )
    workflow.add_node(
        "fold",
        fold_node_with_llm,
        retry_policy=short_retry(),
        timeout=timeout(run_timeout=120, idle_timeout=45),
        error_handler=recover_fold_to_agent,
    )
    workflow.add_node(
        "preprocess",
        preprocess_node_with_llm,
        retry_policy=short_retry(),
        timeout=timeout(run_timeout=180, idle_timeout=60),
        error_handler=recover_preprocess_to_agent,
    )
    workflow.add_node("mcp", mcp_subgraph)
    workflow.add_node("rag", rag_subgraph)
    workflow.add_node(
        "postprocess",
        postprocess_node_with_llm,
        timeout=timeout(run_timeout=240, idle_timeout=90),
        error_handler=recover_postprocess_to_report,
    )
    workflow.add_node(
        "report",
        report_node_with_llm,
        retry_policy=short_retry(),
        timeout=timeout(run_timeout=180, idle_timeout=60),
        error_handler=recover_report,
    )
    workflow.add_node(
        "normal_chat",
        normal_chat_node_with_llm,
        retry_policy=short_retry(),
        timeout=timeout(run_timeout=60, idle_timeout=30),
        error_handler=recover_terminal_message,
    )
    workflow.add_node(
        "inquiry_answer",
        inquiry_answer_node_with_llm,
        retry_policy=short_retry(),
        timeout=timeout(run_timeout=90, idle_timeout=30),
        error_handler=recover_terminal_message,
    )

    workflow.set_entry_point("agent")
    workflow.add_conditional_edges(
        "agent",
        edges.decision_router,
        {
            "fold": "fold",
            "normal_chat": "normal_chat",
            "postprocess": "postprocess",
            "inquiry_answer": "inquiry_answer"
        }
    )
    workflow.add_conditional_edges(
        "fold",
        edges.fold_router,
        {
            "preprocess": "preprocess",
            "agent": "agent"
        }
    )
    workflow.add_edge("preprocess", "mcp")
    workflow.add_conditional_edges(
        "mcp", 
        edges.mcp_router, 
        {
            "rag": "rag", 
            "agent": "agent"
        }
    )
    workflow.add_edge(
        "rag", 
        "agent"
    )
    workflow.add_conditional_edges(
        "postprocess", 
        edges.postprocess_router, 
        {
            "report": "report"
        }
    )

    workflow.add_edge("report", END)
    workflow.add_edge("normal_chat", END)
    workflow.add_edge("inquiry_answer", END)

    if checkpointer is None or checkpointer is False:
        raise RuntimeError("必须提供 PostgreSQL Checkpointer，禁止无持久化降级")

    return workflow.compile(checkpointer=checkpointer)



def create_graph_from_tools(llm: "ChatOpenAI", mcp_tools: list, checkpointer):
    """使用已加载的 MCP tools 构建父图，返回可直接执行的 compiled graph。"""
    from Agent.tool_node.rag_tool_registry import build_rag_tools
    # graph 层不再关心 MCP session。
    rag_tools = build_rag_tools()
    return build_graph(
        llm=llm,
        mcp_tools=mcp_tools,
        rag_tools=rag_tools,
        checkpointer=checkpointer,
    )


agent_graph = None
