from langgraph.graph import StateGraph, END
from .state import CausalChatState
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


from Database.mysql_checkpointer import MySQLSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


def _build_default_checkpointer():
    """Create the default MySQL checkpointer when configuration allows it."""
    try:
        # 从配置文件加载数据库连接信息
        from config.settings import settings

        connection_config = {
            'host': settings.MYSQL_WRITE_HOST,
            'port': settings.MYSQL_PORT,
            'user': settings.MYSQL_WRITE_USER,
            'password': settings.MYSQL_WRITE_PASSWORD,
            'database': settings.MYSQL_DATABASE
        }

        # 创建 MySQLSaver 实例
        # serde 使用 JsonPlusSerializer(pickle_fallback=True) 处理 DataFrame 等复杂对象
        checkpointer = MySQLSaver(
            connection_config=connection_config,
            serde=JsonPlusSerializer(pickle_fallback=True)
        )

        logging.info("MySQL Checkpointer 已启用")
        return checkpointer

    except Exception as e:
        logging.warning(f" Checkpointer 初始化失败，将不启用持久化: {e}")
        return None




def build_graph(llm: "ChatOpenAI", mcp_tools: list, rag_tools: list, checkpointer=None):
    """
    构建父图。

    父图只表达业务阶段顺序，MCP/RAG 的 tool-calling 细节封装在各自子图内。
    """
    workflow = StateGraph(CausalChatState)

    agent_node_with_llm = bind_node(nodes.agent_node, llm=llm)#将普通节点函数绑定llm，这些普通节点函数内部要调用大模型，但 LangGraph 执行节点时主要只传一个参数：state
    fold_node_with_llm = bind_node(nodes.fold_node, llm=llm)
    preprocess_node_with_llm = bind_node(nodes.preprocess_node, llm=llm)
    mcp_subgraph = build_mcp_subgraph(llm=llm, mcp_tools=mcp_tools)#创建mcp子图
    rag_subgraph = build_rag_subgraph(llm=llm, rag_tools=rag_tools)#创建rag子图
    postprocess_node_with_llm = bind_node(nodes.postprocess_node, llm=llm)
    inquiry_answer_node_with_llm = bind_node(nodes.inquiry_answer_node, llm=llm)
    report_node_with_llm = bind_node(nodes.report_node, llm=llm)
    normal_chat_node_with_llm = bind_node(nodes.normal_chat_node, llm=llm)

#节点注册部分
    workflow.add_node(
        "agent",
        agent_node_with_llm,#这个节点真正执行的函数
        retry_policy=short_retry(),#出错怎么重试
        timeout=timeout(run_timeout=45, idle_timeout=20),#执行多久算超时
        error_handler=route_to_normal_chat,#最后失败怎么兜底
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

    workflow.add_node("mcp", mcp_subgraph)#mcp子图注册成节点
    workflow.add_node("rag", rag_subgraph)#rag子图注册成节点
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

    workflow.set_entry_point("agent")#节点入口
    workflow.add_conditional_edges(#节点的边
        "agent",#从agent节点出发
        edges.decision_router,#由decision_router函数决定路由？
        {
            "fold": "fold",#"路由函数返回值": "要跳转到的节点名"
            "normal_chat": "normal_chat",
            "postprocess": "postprocess",
            "inquiry_answer": "inquiry_answer"
        }
    )
    workflow.add_conditional_edges(
        "fold",
        edges.fold_router,#由fold_router函数决定路由
        {
            "preprocess": "preprocess",
            "agent": "agent"
        }
    )

    workflow.add_edge("preprocess", "mcp")#从preprocess节点到mcp子图节点的边

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

    if checkpointer is False:
        compile_checkpointer = None
    elif checkpointer is None:
        compile_checkpointer = _build_default_checkpointer()
    else:
        compile_checkpointer = checkpointer

    return workflow.compile(checkpointer=compile_checkpointer)



def create_graph_from_tools(llm: "ChatOpenAI", mcp_tools: list):
    """使用已加载的 MCP tools 构建父图，返回可直接执行的 compiled graph。"""
    from Agent.tool_node.rag_tool_registry import build_rag_tools
    # graph 层不再关心 MCP session。
    rag_tools = build_rag_tools()
    return build_graph(llm=llm, mcp_tools=mcp_tools, rag_tools=rag_tools)


agent_graph = None
