"""
app.agent.core - agent核心模块

- 初始化llm
- 初始化mcp
- 启动期检查rag
- 初始化agent
"""
import asyncio, threading, logging, sys, os, json, time
from contextlib import AsyncExitStack
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
knowledge_base_dir = os.path.join(BASE_DIR, "Agent","knowledge_base")

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
    "execute_tools": "Execute analysis - run causal analysis and knowledge base query",
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

async def initialize_mcp_connection(ready_event: threading.Event):
    """
    旧 Web 内执行模式使用的全局 MCP 初始化入口。

    当前生产路径已经改为 worker slot 调用 open_mcp_session() 创建独立会话；
    本函数仅保留给历史兼容或本地调试，不应由 Flask Web 入口自动调用。
    完成后通过 ready_event 通知调用线程。
    """
    global mcp_session, mcp_tools
    logging.info("正在初始化持久 MCP 连接...")
    try:
        mcp_session, mcp_tools = await open_mcp_session(mcp_process_stack)
        logging.info(f"MCP服务器连接成功，会话已激活。发现工具: {[tool['function']['name'] for tool in mcp_tools]}")
        
    except Exception as e:
        logging.error(f"严重错误：应用启动时初始化MCP连接失败: {e}", exc_info=True)
        mcp_session = None
    finally:
        logging.info("MCP 初始化过程结束，通知主线程。")
        ready_event.set()


async def open_mcp_session(process_stack: AsyncExitStack):
    """
    创建一组独立 MCP 进程和 ClientSession。

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

def shutdown_mcp_connection():
    """
    已废弃
    关闭旧全局 MCP 会话。

    当前 worker slot 使用自己的 AsyncExitStack 管理 MCP 生命周期；
    本函数只对应 initialize_mcp_connection() 创建的历史全局会话。
    """
    if background_loop and background_loop.is_running():
        logging.info("请求关闭 MCP 服务器...")
        future = asyncio.run_coroutine_threadsafe(mcp_process_stack.aclose(), background_loop)
        try:
            future.result(timeout=5)
            logging.info("MCP 服务器已成功关闭。")
        except Exception as e:
            logging.error(f"关闭 MCP 服务器时出错: {e}")
    else:
        logging.warning("无法关闭 MCP 服务器：事件循环未运行。")

def start_event_loop(loop: asyncio.AbstractEventLoop, ready_event: threading.Event):
    """
    已废弃
    旧 Web 内执行模式的后台事件循环启动器。

    新的长任务队列模式不再让 Web 进程启动 MCP；worker 进程直接在
    asyncio 主循环中为每个 slot 初始化 MCP session 和 Agent graph。
    """
    global background_loop
    asyncio.set_event_loop(loop)
    background_loop = loop
    
    loop.create_task(initialize_mcp_connection(ready_event))
    
    logging.info("后台事件循环已启动，MCP 初始化任务已安排。")
    loop.run_forever()

def initialize_rag_system():
    """
    启动期仅做知识库可用性检查。
    并在首次查询时延迟初始化 LLM、Embedding 和 Chroma。
    """
    logging.info("正在检查 RAG 知识库目录...")
    persist_directory = os.path.join(knowledge_base_dir, "db")
    if not os.path.exists(persist_directory):
        logging.warning(
            "知识库持久化目录不存在。请先运行 Agent/knowledge_base/build_knowledge.py 构建知识库。",
            persist_directory,
        )
        return False

    logging.info("RAG 启动检查通过；向量库将在首次实际查询时由 query_rag.py 延迟初始化。")
    return True

#  LangChain Agent 的 MCP 工具封装 
# 这里是对mcp格式的langchain翻译，翻译成一个类
# 目前的逻辑下，并没有使用该方法
def create_pydantic(schema: dict, model_name: str) -> Type[BaseModel]:
    """
    根据 MCP 工具提供的 JSON Schema 动态创建 Pydantic 模型。
    这是让 LangChain Agent 理解工具参数的关键。
    """
    fields = {}
    properties = schema.get('properties', {})
    required_fields = schema.get('required', [])
    ## 转换为键值对应的列表
    for prop_name, prop_schema in properties.items():
        # 这里对类型做了简化映射，可以根据未来工具的复杂性进行扩展
        field_type: Type[Any] = str  # 默认为字符串类型
        if prop_schema.get('type') == 'integer':
            field_type = int
        elif prop_schema.get('type') == 'number':
            field_type = float
        elif prop_schema.get('type') == 'boolean':
            field_type = bool
        
        # Pydantic 的 create_model 需要一个元组: (类型, 默认值)
        # 对于必需字段，默认值是 ... (Ellipsis)
        if prop_name in required_fields:
            fields[prop_name] = (field_type, ...)
        else:
            fields[prop_name] = (field_type, None)
    
    # 使用 Pydantic 的 create_model 动态创建模型类
    return create_model(model_name, **fields)

class McpTool(BaseTool):
    """
    一个自定义的 LangChain 工具 (BaseTool)，用于封装 MCP 会话的工具调用功能。
    它充当了 LangChain Agent 和我们现有 MCP 服务之间的桥梁。
    """
    name: str
    description: str
    args_schema: Type[BaseModel]  # 强制工具必须有参数结构
    session: "ClientSession"      # 类型前向引用（类型前向引用指的是在类型注解中使用尚未在当前作用域定义的类型名）
    username: str

 # mcp定于的异步执行方法 _arun表示这个方法可以接收任意数量的关键字参数，并将它们收集到一个名为 kwargs 的字典中
    async def _arun(self, **kwargs: Any) -> Any:
        """
        通过 MCP 会话异步执行工具。
        Agent Executor 会将从 LLM 获取的参数作为关键字参数传递到这里。
        """
        # 将 MCP server 工具所需的 'username' 参数补充进去
        kwargs['username'] = self.username
        logging.info(f"LangChain Agent 正在调用工具 '{self.name}'，参数: {kwargs}")
        
        # 通过已建立的 mcp_session 调用真实的工具
        # 相当于调用mcp
        response_obj = await self.session.call_tool(self.name, kwargs)
        
        # 提取文本内容并返回给 Agent
        function_response_text = response_obj.content[0].text
        logging.debug(f"工具 '{self.name}' 返回了原始数据 (前200字符): {function_response_text[:200]}...")
        
        return function_response_text


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
                        result["type"] = "causal_graph"
                        result["data"] = analysis_data.get("data")
                        logging.info("返回因果图数据")

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
