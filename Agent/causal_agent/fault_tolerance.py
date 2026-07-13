"""
LangGraph 节点级容错策略。

本模块只定义图运行时策略和错误恢复状态，不直接写数据库、不直接操作 SSE。
worker 仍负责把 graph 产出的终态或异常转换为 analysis_job_events。
"""

from __future__ import annotations

from typing import Callable

from langchain_core.messages import AIMessage
from langgraph.errors import NodeError
from langgraph.types import Command, RetryPolicy, TimeoutPolicy, default_retry_on

from .state import CausalChatState


def retry_transient_errors(exc: BaseException) -> bool:
    """
    判断异常是否适合交给 LangGraph 进行节点级重试。

    默认策略已排除常见编程错误，并会重试 NodeTimeoutError 以及常见 5xx/网络类异常；
    这里单独排除 LangGraph interrupt 相关异常，避免“需要用户输入”的业务中断被当作故障重试。
    """
    exc_name = exc.__class__.__name__.lower()
    if "interrupt" in exc_name:
        return False
    return default_retry_on(exc)


def short_retry(max_attempts: int = 2) -> RetryPolicy:
    """生成短重试策略，适用于 LLM 路由、总结和普通回答节点。"""
    return RetryPolicy(
        max_attempts=max_attempts,
        initial_interval=0.5,
        backoff_factor=2.0,
        max_interval=4.0,
        retry_on=retry_transient_errors,
    )


def tool_retry(max_attempts: int = 3) -> RetryPolicy:
    """生成工具调用重试策略，适用于 MCP/RAG 等外部依赖节点。"""
    return RetryPolicy(
        max_attempts=max_attempts,
        initial_interval=1.0,
        backoff_factor=2.0,
        max_interval=8.0,
        retry_on=retry_transient_errors,
    )


def timeout(run_timeout: float, idle_timeout: float | None = None) -> TimeoutPolicy:
    """生成节点 timeout 策略，run_timeout 是单次 attempt 的硬上限。"""
    return TimeoutPolicy(run_timeout=run_timeout, idle_timeout=idle_timeout)


def _error_message(error: NodeError) -> str:
    return f"{error.node} 节点执行失败: {error.error}"


def sanitize_error(exc: BaseException) -> str:
    """Return a display-safe error string without exposing implementation detail."""
    return str(exc) or exc.__class__.__name__


def route_to_normal_chat(state: CausalChatState, error: NodeError) -> Command:
    """Agent 路由失败后的保守恢复：进入普通问答兜底分支。"""
    return Command(
        update={
            "messages": [
                AIMessage(
                    content=f"决策：普通问答。路由节点降级原因：{_error_message(error)}",
                    name=error.node,
                )
            ]
        },
        goto="normal_chat",
    )


def recover_to_agent(state: CausalChatState, error: NodeError) -> Command:
    """中间节点失败后的恢复：记录失败消息并回到 agent 重新决策。"""
    return Command(
        update={
            "messages": [
                AIMessage(
                    content=f"决策：节点失败，返回 agent 重新判断。{_error_message(error)}",
                    name=error.node,
                )
            ],
            "tool_call_request": False,
        },
        goto="agent",
    )


def recover_tools_to_agent(state: CausalChatState, error: NodeError) -> Command:
    """工具节点失败后的恢复：保留结构化失败结果并回到 agent。"""
    message = _error_message(error)
    return Command(
        update={
            "messages": [
                AIMessage(content=f"决策：工具执行失败：{message}", name=error.node)
            ],
            "causal_analysis_result": {"success": False, "message": message},
            "knowledge_base_result": {
                "success": False,
                "summary": message,
                "questions": [],
                "evidence_count": 0,
                "error": message,
            },
            "tool_call_request": False,
        },
        goto="agent",
    )


def recover_mcp_tool_failure(state: CausalChatState, error: NodeError) -> dict:
    """MCP ToolNode 失败后的恢复：写入因果分析失败结构，由父图决定后续路由。"""
    message = sanitize_error(error.error)
    return {
        "messages": [AIMessage(content=f"决策：MCP 工具执行失败：{message}", name=error.node)],
        "causal_analysis_result": {
            "success": False,
            "error": message,
            "error_type": type(error.error).__name__,
        },
        "tool_call_request": False,
    }


def degrade_rag_tool_result(state: CausalChatState, error: NodeError) -> dict:
    """RAG ToolNode 失败后的降级：保留稳定结构，让报告继续生成。"""
    return {
        "knowledge_base_result": {
            "success": False,
            "summary": "知识库增强暂不可用，报告将仅基于因果分析结果生成。",
            "questions": [],
            "evidence_count": 0,
            "error": sanitize_error(error.error),
        }
    }


def recover_postprocess_to_report(state: CausalChatState, error: NodeError) -> Command:
    """后处理失败后的恢复：使用原始分析结果继续报告生成。"""
    message = f"{_error_message(error)}；将使用原始分析结果继续生成报告。"
    return Command(
        update={
            "messages": [AIMessage(content=message, name=error.node)],
            "postprocess_result": {"error": message},
        },
        goto="report",
    )


def recover_terminal_message(state: CausalChatState, error: NodeError) -> dict:
    """终态回答节点失败后的恢复：返回可展示的失败消息，让 graph 正常结束。"""
    return {
        "messages": [
            AIMessage(
                content=f"抱歉，本次生成回答时发生错误：{_error_message(error)}",
                name=error.node,
            )
        ]
    }


def recover_report(state: CausalChatState, error: NodeError) -> dict:
    """报告节点失败后的恢复：生成简短兜底报告，让 worker 能走 final_result。"""
    message = f"报告生成失败：{_error_message(error)}"
    return {
        "messages": [AIMessage(content="决策：因果分析报告生成失败。", name=error.node)],
        "final_report": message,
        "visualization_mapping": {},
    }


NodeErrorHandler = Callable[[CausalChatState, NodeError], Command | dict]
