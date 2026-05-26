from langgraph.graph import StateGraph, END
from .state import CausalChatState
from . import nodes, edges
from .fault_tolerance import (
    recover_postprocess_to_report,
    recover_report,
    recover_terminal_message,
    recover_tools_to_agent,
    recover_to_agent,
    route_to_normal_chat,
    short_retry,
    timeout,
    tool_retry,
)
import logging

# === 导入 Checkpoint 相关 ===
from Database.mysql_checkpointer import MySQLSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


def _bind_node(func, **bound_kwargs):
    """
    将共享资源绑定到 async LangGraph 节点。

    使用显式 async wrapper，避免 functools.partial 包装 async function 后被运行时误判为同步节点。
    """
    async def _node(state: CausalChatState):
        return await func(state, **bound_kwargs)

    _node.__name__ = getattr(func, "__name__", "bound_node")
    return _node


def create_graph(llm: "ChatOpenAI", mcp_session: "ClientSession"):
    """
    组件node和edge成为边
    """
    workflow = StateGraph(CausalChatState)

    # 使用 functools.partial 将 llm 实例绑定到节点函数上
    # 这使得节点在被 LangGraph 调用时，除了 state 之外，还能接收到 llm 对象
    agent_node_with_llm = _bind_node(nodes.agent_node, llm=llm)
    fold_node_with_llm = _bind_node(nodes.fold_node, llm=llm)
    preprocess_node_with_llm = _bind_node(nodes.preprocess_node, llm=llm)
    execute_tools_node_with_session = _bind_node(nodes.execute_tools_node, mcp_session=mcp_session, llm=llm)
    postprocess_node_with_llm = _bind_node(nodes.postprocess_node, llm=llm)
    inquiry_answer_node_with_llm = _bind_node(nodes.inquiry_answer_node, llm=llm)
    report_node_with_llm = _bind_node(nodes.report_node, llm=llm)
    normal_chat_node_with_llm = _bind_node(nodes.normal_chat_node, llm=llm)

    # Add all the nodes to the graph
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
        error_handler=recover_to_agent,
    )
    workflow.add_node(
        "preprocess",
        preprocess_node_with_llm,
        retry_policy=short_retry(),
        timeout=timeout(run_timeout=180, idle_timeout=60),
        error_handler=recover_to_agent,
    )
    workflow.add_node(
        "execute_tools",
        execute_tools_node_with_session,
        retry_policy=tool_retry(),
        timeout=timeout(run_timeout=360, idle_timeout=120),
        error_handler=recover_tools_to_agent,
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

    
    # Set the entry point of the graph
    workflow.set_entry_point("agent")

    # Add conditional edges that determine the flow based on router functions
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
    
    workflow.add_conditional_edges(
        "preprocess",
        edges.preprocess_router,
        {
            "execute_tools": "execute_tools",
        }
    )
    workflow.add_conditional_edges(
        "execute_tools",
        edges.execute_tool_router,
        {
            "agent": "agent"
        }
    )

    workflow.add_conditional_edges(
        "postprocess",
        edges.postprocess_router,
        {
            "report": "report"
        }
    )

 
    # Define the end points of the graph. A graph can have multiple finishing points.
    workflow.add_edge("report", END)
    workflow.add_edge("normal_chat", END)
    workflow.add_edge("inquiry_answer", END)
    

    checkpointer = None
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
        # 虽然现在没有
        checkpointer = MySQLSaver(
            connection_config=connection_config,
            serde=JsonPlusSerializer(pickle_fallback=True)
        )
        
        
        logging.info("MySQL Checkpointer 已启用")
        
    except Exception as e:
        logging.warning(f" Checkpointer 初始化失败，将不启用持久化: {e}")
        checkpointer = None


    app = workflow.compile(
        checkpointer=checkpointer  
    )
    
    return app


agent_graph = None
