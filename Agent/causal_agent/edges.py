from langchain_core.messages import AIMessage
import logging
from .state import CausalChatState

def decision_router(state: CausalChatState) -> str:
    """
    这是图中的主要“决策”边。
    它检查来自代理的最新消息以决定下一步行动。
    """
    logging.info("路由: 主决策")
    agent_decision = state["messages"][-1].content
    
    if "信息完备" in agent_decision:
        logging.info("路由决策 -> 前往[后处理]")
        return "postprocess"
    elif "信息不全" in agent_decision:
        logging.info("路由决策 -> 前往[文件加载]")
        return "fold"
    elif "报告" in agent_decision:
        logging.info("路由决策 -> 前往[追问模块]")
        return "inquiry_answer"
    else: 
        logging.info("路由决策 -> 前往[普通问答]")
        return "normal_chat"

def fold_router(state: CausalChatState) -> str:
    """
    这是图中的文件加载"决策"边。
    它检查来自代理的最新消息以决定下一步行动。
    
    - 如果信息完备，前往 preprocess
    - 如果收到用户输入，返回 agent 重新判断
    """
    logging.info("--- 路由: 文件加载决策 ---")
    fold_process_decision = state["messages"][-1].content
    
    if "信息完备" in fold_process_decision:
        logging.info("路由决策 -> 前往[执行预处理]")
        return "preprocess"
    elif "返回 agent" in fold_process_decision or "用户输入" in fold_process_decision:
        logging.info("路由决策 -> 收到用户输入，返回[agent]重新判断")
        return "agent"
    else:
        # 默认情况：返回 agent
        logging.info("路由决策 -> 默认返回[agent]")
        return "agent"

def preprocess_router(state: CausalChatState) -> str:
    """
    参数验证节点后的路由器。
    如果验证成功，则执行工具
    """
    logging.info("--- 路由: 预处理后决策 ---")
    logging.info("路由决策 -> 参数充足, 前往[MCP工具阶段]")
    return "mcp"


def execute_tool_router(state:CausalChatState) -> str:
    """
    旧 execute_tools 节点后的兼容路由器。
    当前父图已改为 preprocess -> mcp -> rag -> agent，本函数仅保留给历史调用。
    """
    logging.info("--- 路由: 执行工具后决策 ---")
    logging.info(f"前往decision_router")
    return "agent"

def mcp_router(state: CausalChatState) -> str:
    """检测mcp是否调用成功"""
    logging.info("--- 路由: MCP决策 ---")
    mcp_result =  state.get("causal_analysis_result")
    if isinstance(mcp_result, dict) and mcp_result.get("success") is True:
        logging.info("路由决策 -> MCP分析成功, 前往[RAG工具阶段]")
        return "rag"
    logging.info("路由决策 -> MCP分析缺失不充足, 前往[Agent决策路由]")
    return "agent"


def postprocess_router(state:CausalChatState) -> str:
    '''
    通向report_node
    '''
    logging.info("--- 路由: 后处理后决策 ---")
    logging.info(f"前往report_node")
    return "report"



