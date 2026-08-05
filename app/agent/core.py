"""
app.agent.core - agent核心模块

- 初始化llm
- 初始化mcp
- 启动期检查rag
- 初始化agent
"""
import asyncio, threading, logging, sys, os, time
import hashlib
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
from Agent.causal_agent.state import CausalAgentState
from app.chat.response_storage import render_summary_for_display

## die manager
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
mcp_dir = os.path.join(BASE_DIR, "Agent")
mcp_server_path = os.path.join(mcp_dir, "CausalAgentMCP", "mcp_server.py")
knowledge_base_dir = os.path.join(BASE_DIR, "Agent","knowledge_base")


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
    "agent": "分析用户意图",
    "fold": "加载文件并验证数据",
    "preprocess": "预处理数据",
    "mcp": "执行因果分析",
    "rag": "检索知识库",
    "postprocess": "校验并修正因果图",
    "report": "生成分析报告",
    "normal_chat": "生成回答",
    "inquiry_answer": "回答报告追问",
}
TEXT_STREAM_NODES = {"normal_chat", "inquiry_answer"}
TOOL_STAGE_NODES = {
    "mcp_planner": "mcp",
    "mcp_tool_node": "mcp",
    "mcp_result_parser": "mcp",
    "rag_question_planner": "rag",
    "rag_tool_node": "rag",
    "rag_result_parser": "rag",
}
DECISION_PROGRESS = {
    "fold": "已识别为因果分析请求",
    "normal_chat": "已识别为普通问答",
    "inquiry_answer": "已识别为报告追问",
    "postprocess": "已识别为已有结果的后续处理",
    "preprocess": "文件与数据验证完成",
    "agent": "需要补充分析输入",
}


def _opaque_id(*parts: Any) -> str:
    """根据内部标识生成不暴露 attempt/task 内容的稳定 ID。"""
    raw = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def sanitize_public_error(error: Any) -> str:
    """把内部异常归类为有限的用户可见错误，避免泄露连接和路径信息。"""
    name = error if isinstance(error, str) else type(error).__name__
    normalized = str(name).lower()
    if "timeout" in normalized:
        return "调用超时"
    if any(token in normalized for token in ("connection", "connect", "network")):
        return "服务连接失败"
    if any(token in normalized for token in ("rate", "limit")):
        return "服务当前繁忙"
    if any(token in normalized for token in ("permission", "auth")):
        return "服务授权失败"
    return "节点执行失败"


class LangGraphEventAdapter:
    """把 LangGraph v2 多流事件转换为稳定、可持久化的公开事件协议。"""

    def __init__(self, job_id: str | None, job_attempt: int):
        """初始化单次 job attempt 的阶段、重试和文字流状态。"""
        self.job_id = job_id or "untracked"
        self.job_attempt = job_attempt
        self.steps: dict[str, dict[str, Any]] = {}
        self.active_by_node: dict[str, str] = {}
        self.failed_attempts: dict[str, str] = {}
        self.streams: dict[str, dict[str, Any]] = {}

    def _base(self, event_type: str, step: dict[str, Any]) -> dict[str, Any]:
        """构造所有阶段事件共享的持久化字段。"""
        return {
            "type": event_type,
            "step_id": step["step_id"],
            "node_name": step["node_name"],
            "title": NODE_DESCRIPTIONS[step["node_name"]],
            "attempt": self.job_attempt,
        }

    def _active_step(self, node_name: str) -> dict[str, Any] | None:
        """获取指定父图节点当前尚未结束的阶段实例。"""
        task_id = self.active_by_node.get(node_name)
        return self.steps.get(task_id) if task_id else None

    def _parent_tool_step(self, node_name: str) -> dict[str, Any] | None:
        """把子图内部节点映射到当前 MCP/RAG 父阶段。"""
        parent_name = TOOL_STAGE_NODES.get(node_name)
        return self._active_step(parent_name) if parent_name else None

    def _task_event(self, namespace: Any, data: Any) -> list[dict[str, Any]]:
        """将根图 tasks 开始/结束转换为阶段生命周期事件。"""
        if namespace or not isinstance(data, dict):
            return []
        task_id = str(data.get("id") or "")
        node_name = data.get("name")
        if not task_id or node_name not in NODE_DESCRIPTIONS:
            return []
        if "input" in data:
            step = {
                "step_id": _opaque_id(self.job_id, self.job_attempt, task_id),
                "node_name": node_name,
                "started_at": time.monotonic(),
            }
            self.steps[task_id] = step
            self.active_by_node[node_name] = task_id
            return [self._base("node_start", step)]
        step = self.steps.get(task_id)
        if not step:
            return []
        event = self._base("node_end", step)
        event["duration"] = round(max(0.0, time.monotonic() - step["started_at"]), 2)
        event["status"] = "failed" if data.get("error") else "completed"
        if data.get("error"):
            event["message"] = sanitize_public_error(data.get("error"))
        if self.active_by_node.get(node_name) == task_id:
            self.active_by_node.pop(node_name, None)
        return [event]

    def _custom_event(self, data: Any) -> list[dict[str, Any]]:
        """只有失败后再次开始时，才把内部 attempt 转换为真正的重试。"""
        if not isinstance(data, dict):
            return []
        event_type = data.get("type")
        task_id = str(data.get("task_id") or "")
        node_name = data.get("node_name")
        if event_type == "node_attempt_failed" and task_id:
            self.failed_attempts[task_id] = sanitize_public_error(data.get("error_kind"))
            return []
        if event_type != "node_attempt_start" or not task_id:
            return []
        failure = self.failed_attempts.pop(task_id, None)
        if not failure:
            return []
        step = (
            self.steps.get(task_id)
            or self._active_step(node_name)
            or self._parent_tool_step(node_name)
        )
        if not step:
            return []
        discarded = self.streams.pop(step["step_id"], None)
        event = self._base("node_retry", step)
        event["message"] = failure
        if discarded:
            event["discard_stream_id"] = discarded["stream_id"]
        return [event]

    @staticmethod
    def _tool_call(message: Any) -> tuple[str | None, list[str]]:
        """只读取工具名和参数字段名，不返回参数值。"""
        calls = getattr(message, "tool_calls", None) or []
        if not calls:
            return None, []
        call = calls[0]
        if isinstance(call, dict):
            name = call.get("name")
            args = call.get("args")
        else:
            name = getattr(call, "name", None)
            args = getattr(call, "args", None)
        keys = sorted(str(key) for key in args)[:12] if isinstance(args, dict) else []
        return name, keys

    def _update_event(self, namespace: Any, data: Any) -> list[dict[str, Any]]:
        """从显式 State 和规范化结果生成 decision、progress 与工具摘要。"""
        if not isinstance(data, dict):
            return []
        events: list[dict[str, Any]] = []
        for node_name, output in data.items():
            if not isinstance(output, dict):
                continue
            step = self._active_step(node_name)
            if step:
                decision = output.get("route_decision") or output.get("fold_decision")
                if decision:
                    progress = self._base("progress", step)
                    progress["summary"] = DECISION_PROGRESS.get(decision, "路由判断完成")
                    events.append(progress)
                    event = self._base("decision", step)
                    event["summary"] = f"已决定进入：{NODE_DESCRIPTIONS.get(decision, decision)}"
                    events.append(event)
            tool_step = self._parent_tool_step(node_name)
            if not tool_step:
                continue
            messages = output.get("messages") or []
            latest = messages[-1] if messages else None
            tool_name, argument_keys = self._tool_call(latest)
            if tool_name:
                event = self._base("tool_call_start", tool_step)
                event.update({"tool_name": tool_name, "argument_keys": argument_keys})
                events.append(event)
            result_key = "causal_analysis_result" if TOOL_STAGE_NODES[node_name] == "mcp" else "knowledge_base_result"
            result = output.get(result_key)
            if isinstance(result, dict):
                metadata = result.get("_tool_call") or {}
                event = self._base("tool_call_result", tool_step)
                event.update({
                    "tool_name": metadata.get("name") or tool_name or "工具",
                    "summary": "调用完成" if result.get("success") is not False else "调用失败",
                })
                events.append(event)
        return events

    def _message_event(self, data: Any) -> list[dict[str, Any]]:
        """仅转换普通问答和报告追问的非空字符串 token。"""
        if not isinstance(data, (tuple, list)) or len(data) != 2:
            return []
        chunk, metadata = data
        if not isinstance(metadata, dict):
            return []
        node_name = metadata.get("langgraph_node")
        content = getattr(chunk, "content", None)
        if node_name not in TEXT_STREAM_NODES or not isinstance(content, str) or not content:
            return []
        step = self._active_step(node_name)
        if not step:
            return []
        stream = self.streams.get(step["step_id"])
        if not stream:
            stream = {
                "stream_id": _opaque_id(step["step_id"], time.monotonic_ns()),
                "sequence": 0,
            }
            self.streams[step["step_id"]] = stream
        stream["sequence"] += 1
        event = self._base("text_chunk", step)
        event.update({
            "stream_id": stream["stream_id"],
            "sequence": stream["sequence"],
            "delta": content,
        })
        return [event]

    def convert(self, chunk: Any) -> list[dict[str, Any]]:
        """转换一个 v2 StreamPart；无法识别的内部流会被忽略。"""
        if not isinstance(chunk, dict):
            return []
        stream_type = chunk.get("type")
        namespace = chunk.get("ns") or ()
        data = chunk.get("data")
        if stream_type == "tasks":
            return self._task_event(namespace, data)
        if stream_type == "custom":
            return self._custom_event(data)
        if stream_type == "updates":
            return self._update_event(namespace, data)
        if stream_type == "messages":
            return self._message_event(data)
        return []

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


def _snapshot_interrupts(snapshot) -> list[Any]:
    """汇总 LangGraph StateSnapshot 中尚待恢复的 task interrupts。"""
    return [
        item
        for task in (getattr(snapshot, "tasks", None) or ())
        for item in (getattr(task, "interrupts", None) or ())
    ]


async def ai_call_stream(
    text,
    user_id,
    username,
    session_id,
    *,
    job_id=None,
    job_attempt=1,
    graph=None,
):
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
        },
        "metadata": {
            "job_id": job_id,
        } if job_id else {},
    }
    
    # 检查当前状态，判断是否是恢复中断的会话
    try:
        state = await target_graph.aget_state(config)
        is_interrupted = bool(_snapshot_interrupts(state))
        
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
    
    adapter = LangGraphEventAdapter(job_id, job_attempt)
    streamed_interrupts = []
    
    try:
        async for chunk in target_graph.astream(
            input_data,
            config,
            stream_mode=["updates", "messages", "custom", "tasks"],
            subgraphs=True,
            version="v2",
        ):
            if chunk.get("type") == "updates" and isinstance(chunk.get("data"), dict):
                interrupt_data = chunk["data"].get("__interrupt__")
                if interrupt_data:
                    streamed_interrupts.extend(
                        interrupt_data if isinstance(interrupt_data, (list, tuple)) else [interrupt_data]
                    )
            for event_data in adapter.convert(chunk):
                yield event_data
        
        # 获取最终状态以检查interrupt
        state = await target_graph.aget_state(config)
        final_state_data = state.values
        pending_interrupts = _snapshot_interrupts(state)
        interrupts = pending_interrupts or streamed_interrupts
        
        # 检查是否有interrupt
        if interrupts:
            # 提取问题文本
            interrupt_obj = interrupts[0]
            question = interrupt_obj.value if hasattr(interrupt_obj, 'value') else str(interrupt_obj)
            
            event_data = {
                "type": "interrupt",
                "message": question
            }
            event_data["attempt"] = job_attempt
            yield event_data
            logging.info(f"[SSE] 图已暂停，等待用户输入")
            return
        else:
            # 发送最终结果
            result = process_final_result(final_state_data)
            event_data = {
                "type": "final_result",
                "data": result
            }
            event_data["attempt"] = job_attempt
            yield event_data
            logging.info(f"[SSE] 发送最终结果")
            
    except Exception as e:
        logging.error(f"[流式] 执行 LangGraph Agent 时发生错误: {e}", exc_info=True)
        yield {
            "type": "error",
            "message": sanitize_public_error(e),
            "attempt": job_attempt,
        }

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
