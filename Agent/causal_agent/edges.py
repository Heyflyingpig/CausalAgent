import logging
from .state import CausalAgentState


ROUTE_DECISIONS = {"fold", "postprocess", "normal_chat", "inquiry_answer"}
FOLD_DECISIONS = {"preprocess", "agent", "normal_chat"}

def decision_router(state: CausalAgentState) -> str:
    """
    只读取 agent 写入的显式 route_decision，不从展示消息推断控制流。
    """
    logging.info("路由: 主决策")
    decision = state.get("route_decision")
    if decision not in ROUTE_DECISIONS:
        logging.warning("route_decision 缺失或非法: %r；降级到 normal_chat", decision)
        return "normal_chat"
    logging.info("路由决策 -> %s", decision)
    return decision

def fold_router(state: CausalAgentState) -> str:
    """
    只读取 fold 写入的显式 fold_decision，不从展示消息推断控制流。
    """
    logging.info("--- 路由: 文件加载决策 ---")
    decision = state.get("fold_decision")
    if decision not in FOLD_DECISIONS:
        logging.warning("fold_decision 缺失或非法: %r；降级到 agent", decision)
        return "agent"
    logging.info("路由决策 -> %s", decision)
    return decision

def preprocess_router(state: CausalAgentState) -> str:
    """
    参数验证节点后的路由器。
    如果验证成功，则执行工具
    """
    logging.info("--- 路由: 预处理后决策 ---")
    logging.info("路由决策 -> 参数充足, 前往[MCP工具阶段]")
    return "mcp"


def execute_tool_router(state:CausalAgentState) -> str:
    """
    旧 execute_tools 节点后的兼容路由器。
    当前父图已改为 preprocess -> mcp -> rag -> agent，本函数仅保留给历史调用。
    """
    logging.info("--- 路由: 执行工具后决策 ---")
    logging.info(f"前往decision_router")
    return "agent"

def mcp_router(state: CausalAgentState) -> str:
    """检测mcp是否调用成功"""
    logging.info("--- 路由: MCP决策 ---")
    mcp_result =  state.get("causal_analysis_result")
    if isinstance(mcp_result, dict) and mcp_result.get("success") is True:
        logging.info("路由决策 -> MCP分析成功, 前往[RAG工具阶段]")
        return "rag"
    if isinstance(mcp_result, dict) and mcp_result.get("success") is False:
        logging.info("路由决策 -> MCP分析失败, 前往[普通问答]终止本轮")
        return "normal_chat"
    logging.info("路由决策 -> MCP分析缺失不充足, 前往[Agent决策路由]")
    return "agent"


def postprocess_router(state:CausalAgentState) -> str:
    '''
    通向report_node
    '''
    logging.info("--- 路由: 后处理后决策 ---")
    logging.info(f"前往report_node")
    return "report"



