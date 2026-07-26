from langgraph.graph import StateGraph, END
from .state import CausalAgentState
from . import nodes, edges
from .graph_utils import bind_node
from .tool_subgraphs import build_mcp_subgraph
from .fault_tolerance import (
    degrade_rag_tool_result,
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




def build_graph(llm: "ChatOpenAI", mcp_tools: list, rag_service, checkpointer):
    """
    构建父图。

    父图保留 MCP 工具子图；默认多模态 RAG 作为单一普通节点执行。
    """
    workflow = StateGraph(CausalAgentState)

    agent_node_with_llm = bind_node(nodes.agent_node, llm=llm)
    fold_node_with_llm = bind_node(nodes.fold_node, llm=llm)
    preprocess_node_with_llm = bind_node(nodes.preprocess_node, llm=llm)
    mcp_subgraph = build_mcp_subgraph(llm=llm, mcp_tools=mcp_tools)
    rag_node_with_resources = bind_node(nodes.rag_node, llm=llm, rag_service=rag_service)
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
    workflow.add_node(
        "rag",
        rag_node_with_resources,
        retry_policy=tool_retry(max_attempts=2),
        timeout=timeout(run_timeout=180, idle_timeout=60),
        error_handler=degrade_rag_tool_result,
    )
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



def create_graph_from_tools(
    llm: "ChatOpenAI",
    mcp_tools: list,
    rag_service,
    checkpointer,
):
    """使用已加载的 MCP tools、显式 RAG Service 和 checkpoint 构建父图。"""
    return build_graph(
        llm=llm,
        mcp_tools=mcp_tools,
        rag_service=rag_service,
        checkpointer=checkpointer,
    )


agent_graph = None
