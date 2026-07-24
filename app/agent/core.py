"""
app.agent.core - agent核心模块

- 初始化llm
- 初始化mcp
- 启动期初始化可选RAG Runtime
- 初始化agent
"""
import asyncio, threading, logging, sys, os, json, time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from config.settings import settings
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.tools import BaseTool
from typing import Any, Type, List
from pydantic import BaseModel, create_model
from langgraph.types import Command 
from Agent.causal_agent.state import CausalChatState
from app.chat.response_storage import render_summary_for_display

## die manager
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
mcp_dir = os.path.join(BASE_DIR, "Agent")
mcp_server_path = os.path.join(mcp_dir, "CausalChatMCP", "mcp_server.py")


@dataclass
class McpClientResources:
    """worker slot 级 MCP 资源，生命周期由传入的 AsyncExitStack 管理。"""
    client: Any
    session: Any
    tools: list

# 将 MCP 和事件循环,llm和rag链的相关的状态集中管理
mcp_session: ClientSession | None = None
mcp_tools: list = []
mcp_process_stack = AsyncExitStack()
background_loop: asyncio.AbstractEventLoop | None = None
llm = None
agent_graph = None
NODE_DESCRIPTIONS = {
    "agent": "Analyze user intent",
    "fold": "Load file and validate data",
    "preprocess": "Data preprocessing - generate summary and visualization",
    "mcp": "Run causal analysis through MCP ToolNode subgraph",
    "rag": "Run knowledge-base enrichment through RAG ToolNode subgraph",
    "postprocess": "Postprocessing - loop detection and edge evaluation",
    "report": "Generate report - integrate analysis results",
    "normal_chat": "Normal chat",
    "inquiry_answer": "Answer questions based on the report"
}

def initialize_llm():
    """在应用启动时初始化全局LLM实例。"""
    global llm
    # 使用新的配置对象
    if not all([settings.MODEL, settings.BASE_URL, settings.API_KEY]):
        logging.error("LLM 配置不完整，无法初始化。")
        return False
    
    logging.info(f"正在初始化 LLM 模型: {settings.MODEL}")
    llm = ChatOpenAI(
        model=settings.MODEL,
        base_url=settings.BASE_URL,
        api_key=settings.API_KEY,
        streaming=False,
    )
    logging.info("LLM 实例初始化成功。")

    return True



async def open_mcp_client_resources(process_stack: AsyncExitStack) -> McpClientResources:
    """
    使用 LangChain MCP adapter 打开 slot 级持久 session 并加载 tools。

    这里显式使用 client.session("causal")，避免 MultiServerMCPClient 默认
    stateless get_tools() 路径在每次工具调用时重新创建 ClientSession。
    """
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from langchain_mcp_adapters.tools import load_mcp_tools
    except ImportError as exc:
        raise RuntimeError(
            "缺少 langchain-mcp-adapters，无法初始化 LangChain MCP adapter。"
        ) from exc

    client = MultiServerMCPClient(
        {
            "causal": {
                "transport": "stdio",
                "command": sys.executable,
                "args": [mcp_server_path],
            }
        }
    )
    logging.info("MCP 初始化。")
    session = await process_stack.enter_async_context(client.session("causal"))
    tools = await load_mcp_tools(session)
    return McpClientResources(client=client, session=session, tools=tools)


def initialize_rag_system():
    """
    兼容入口：使用已初始化的主 LLM 创建进程级 RAG Service。
    """
    return initialize_rag_service(llm)


def initialize_rag_service(answer_llm):
    """严格初始化 Runtime；失败时返回本进程固定的不可用 Service。"""
    from Agent.knowledge_base.rag_runtime import RagRuntimeConfig, create_rag_runtime
    from Agent.knowledge_base.rag_service import RagService, UnavailableRagService

    try:
        runtime = create_rag_runtime(RagRuntimeConfig.from_environment(), answer_llm)
    except Exception:
        logging.error(
            "RAG Runtime 初始化失败；当前 worker 进程将使用不可用 Service，修复后需重启 worker。",
            exc_info=True,
        )
        return UnavailableRagService()
    return RagService(runtime)


async def ai_call_stream(text, user_id, username, session_id, graph=None):
    """
    流式版本的 ai_call，使用 astream() 捕获节点执行更新。
    这是一个生成器函数，会yield SSE格式的事件数据。
    """
    logging.info(f"[流式] 处理用户 {username} 的消息，会话ID: {session_id}")
    target_graph = graph or agent_graph
    if target_graph is None:
        raise RuntimeError("Agent Graph 尚未初始化")
    
    # 配置：使用 session_id 作为 thread_id
    config = {
        "configurable": {
            "thread_id": session_id,
            "user_id": user_id
        }
    }
    
    # 检查当前状态，判断是否是恢复中断的会话
    try:
        state = await target_graph.aget_state(config)
        ## 检查是否中断
        is_interrupted = state.next == () and state.tasks
        
        if is_interrupted:
            logging.info(f"[流式] 检测到会话 {session_id} 处于中断状态，使用Command(resume=...)恢复")
            input_data = Command(resume=text)
        else:
            logging.info(f"[流式] 正常对话或第一次对话")
            input_data = {
                "messages": [HumanMessage(content=text)],
                "user_id": user_id,
                "username": username,
                "session_id": session_id
            }
    except Exception as e:
        logging.warning(f"[流式] 无法获取状态，假设为新对话: {e}")
        input_data = {
            "messages": [HumanMessage(content=text)],
            "user_id": user_id,
            "username": username,
            "session_id": session_id
        }
    
    import time
    node_start_times = {}
    final_state_data = None
    interrupt_info = None
    last_node = None
    
    try:
        # 使用 astream 流式执行，捕获节点更新
        # stream_mode="updates" 会在每个节点执行后返回更新
        async for chunk in target_graph.astream(input_data, config, stream_mode="updates"):
            logging.info(f"[SSE] 收到更新: {list(chunk.keys())}")
            
            # chunk的格式: {node_name: node_output}
            for node_name, node_output in chunk.items():
                if node_name in NODE_DESCRIPTIONS:

                    # 如果有上一个节点，且当前节点与上一个不同，先发送上一个节点的结束事件
                    if last_node and last_node != node_name and last_node in node_start_times:
                        start_time = node_start_times[last_node]
                        duration = round(time.time() - start_time, 2)
                        
                        event_data = {
                            "type": "node_end",
                            "node_name": last_node,
                            "duration": duration,
                            "timestamp": time.time()
                        }
                        yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                        logging.info(f"[SSE] 节点完成: {last_node} (耗时: {duration}s)")
                    
                    # 发送当前节点的开始事件
                    if last_node != node_name:
                        node_start_times[node_name] = time.time()
                        
                        event_data = {
                            "type": "node_start",
                            "node_name": node_name,
                            "node_desc": NODE_DESCRIPTIONS[node_name],
                            "timestamp": time.time()
                        }
                        yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                        logging.info(f"[SSE] 节点开始: {node_name}")
                        
                        last_node = node_name
                
                # 保存节点输出
                if isinstance(node_output, dict):
                    final_state_data = node_output
        
        # === 流结束后，发送最后一个节点的结束事件 ===
        if last_node and last_node in node_start_times:
            start_time = node_start_times[last_node]
            duration = round(time.time() - start_time, 2)
            
            event_data = {
                "type": "node_end",
                "node_name": last_node,
                "duration": duration,
                "timestamp": time.time()
            }
            yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
            logging.info(f"[SSE] 节点完成: {last_node} (耗时: {duration}s)")
        
        # 获取最终状态以检查interrupt
        state = await target_graph.aget_state(config)
        final_state_data = state.values
        
        # 检查是否有interrupt
        if "__interrupt__" in final_state_data:
            interrupt_info = final_state_data["__interrupt__"]
            
            # 提取问题文本
            interrupt_obj = interrupt_info[0] if isinstance(interrupt_info, (list, tuple)) else interrupt_info
            question = interrupt_obj.value if hasattr(interrupt_obj, 'value') else str(interrupt_obj)
            
            event_data = {
                "type": "interrupt",
                "message": question
            }
            yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
            logging.info(f"[SSE] 图已暂停，等待用户输入")
        else:
            # 发送最终结果
            result = process_final_result(final_state_data)
            event_data = {
                "type": "final_result",
                "data": result
            }
            yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
            logging.info(f"[SSE] 发送最终结果")
            
    except Exception as e:
        logging.error(f"[流式] 执行 LangGraph Agent 时发生错误: {e}", exc_info=True)
        error_data = {
            "type": "error",
            "message": f"处理请求时出现错误: {str(e)}"
        }
        yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"

def process_final_result(final_state_data):
    """
    处理图正常完成后的最终结果
    
    优先级策略：
    1. 优先返回最新的 AI 消息（messages[-1]）
    2. 如果最新消息是决策消息，则检查是否有 final_report
    3. 如果有因果图数据，返回结构化响应
    """
    
    # 检查最后一条消息 
    messages = final_state_data.get("messages", [])
    if messages:
        last_message = messages[-1]
        
        # 如果最后一条是 AI 消息
        if isinstance(last_message, AIMessage):
            message_name = getattr(last_message, 'name', None)
            
            # 检查是否是有实际内容的回复节点
            # （不是决策消息，而是真正的回复）
            if message_name in ['normal_chat', 'inquiry_answer']:
                logging.info(f"返回 {message_name} 节点的回复")
                return {
                    "type": "text",
                    "summary": last_message.content
                }
            
            # 如果是 report 节点生成的决策消息
            # 检查是否同时有 final_report
            if message_name == 'report' and final_state_data.get("final_report"):
                logging.info("返回完整的因果分析报告")
                result = {
                    "summary": final_state_data["final_report"],
                    "layout": "report"
                }
                # 检查是否有因果图数据（结构化返回）
                if final_state_data.get("causal_analysis_result"):
                    analysis_data = final_state_data["causal_analysis_result"]
                    if analysis_data.get("success"):
                        original_graph = analysis_data.get("data")
                        postprocess_result = final_state_data.get("postprocess_result") or {}
                        revised_graph = postprocess_result.get("revised_graph")
                        has_valid_revised_graph = (
                            isinstance(revised_graph, dict)
                            and isinstance(revised_graph.get("nodes"), list)
                            and isinstance(revised_graph.get("edges"), list)
                            and not postprocess_result.get("error")
                        )
                        result["type"] = "causal_graph"
                        result["data"] = revised_graph if has_valid_revised_graph else original_graph
                        result["graph_source"] = (
                            "postprocessed" if has_valid_revised_graph else "original"
                        )
                        result["revision_summary"] = postprocess_result.get(
                            "revision_summary",
                            "",
                        )
                        logging.info("返回因果图数据: source=%s", result["graph_source"])

                if "type" not in result:
                    result["type"] = "text"

                # 检查是否有可视化映射，并替换占位符
                if final_state_data.get("visualization_mapping"):
                    visualization_mapping = final_state_data["visualization_mapping"]
                    if visualization_mapping:  # 确保不是空字典
                        # 保存映射数据（用于数据库存储）
                        result["raw_summary"] = result["summary"]
                        result["visualization_mapping"] = visualization_mapping
                        logging.info(f"包含 {len(visualization_mapping)} 个可视化图表")

                        # 替换 summary 中的占位符为真实图表
                        result["summary"] = render_summary_for_display(
                            result["summary"],
                            visualization_mapping
                        )
                        logging.info("已替换报告中的占位符为真实图表")

                return result
    
    # 返回 final_report（如果有）
    final_report = final_state_data.get("final_report")
    if final_report:
        logging.info("未找到最新消息，降级返回 final_report")
        return {"type": "text", "summary": final_report, "layout": "report"}
    
    logging.warning("未找到任何可返回的内容，返回默认消息")
    return {"type": "text", "summary": "抱歉，我在处理时遇到了问题。"}

async def open_mcp_session(process_stack: AsyncExitStack):
    """
    旧函数：创建一组独立 MCP 进程和 ClientSession。

    Web 旧模式只使用一个全局会话；worker 池会为每个 slot 调用本函数，
    确保 slot = MCP session/process = graph instance。
    """
    server_params = StdioServerParameters(command=sys.executable, args=[mcp_server_path])
    ## 这里enter_async_context(...) 会立刻执行它的 __aenter__()，真正打开资源
    ## 同时，它的 __aexit__() 被登记到 process_stack这个栈，也就是只有__aexit__()被登记到栈里
    read_stream, write_stream = await process_stack.enter_async_context(stdio_client(server_params))
    session = await process_stack.enter_async_context(ClientSession(read_stream, write_stream))
    await session.initialize()

    tools_response = await session.list_tools()
    tools = [{
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.inputSchema,
        }
    } for tool in tools_response.tools]
    return session, tools
