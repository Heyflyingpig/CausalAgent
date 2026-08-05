from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from Agent.causal_agent.state import CausalAgentState


def bind_node(func, *, event_node_name: str | None = None, **bound_kwargs):
    """绑定节点依赖，并通过 custom 流暴露真实的节点执行尝试。"""
    node_name = event_node_name or getattr(func, "__name__", "bound_node").removesuffix("_node")

    async def _node(state: CausalAgentState, runtime: Runtime):
        """执行函数节点，并把 attempt 边界写入 custom 流。"""
        execution_info = runtime.execution_info
        task_id = execution_info.task_id if execution_info else None
        node_attempt = execution_info.node_attempt if execution_info else 0
        runtime.stream_writer({
            "type": "node_attempt_start",
            "node_name": node_name,
            "task_id": task_id,
            "node_attempt": node_attempt,
        })
        try:
            return await func(state, **bound_kwargs)
        except Exception as exc:
            runtime.stream_writer({
                "type": "node_attempt_failed",
                "node_name": node_name,
                "task_id": task_id,
                "node_attempt": node_attempt,
                "error_kind": type(exc).__name__,
            })
            raise

    _node.__name__ = getattr(func, "__name__", "bound_node")
    return _node


def bind_runnable_node(runnable, *, event_node_name: str):
    """包装 ToolNode 等 Runnable，同时保留其执行 config 和 retry attempt 事件。"""
    async def _node(
        state: CausalAgentState,
        runtime: Runtime,
        config: RunnableConfig,
    ):
        """执行 Runnable 节点，并保留 LangGraph 传入的运行配置。"""
        execution_info = runtime.execution_info
        task_id = execution_info.task_id if execution_info else None
        node_attempt = execution_info.node_attempt if execution_info else 0
        runtime.stream_writer({
            "type": "node_attempt_start",
            "node_name": event_node_name,
            "task_id": task_id,
            "node_attempt": node_attempt,
        })
        try:
            return await runnable.ainvoke(state, config)
        except Exception as exc:
            runtime.stream_writer({
                "type": "node_attempt_failed",
                "node_name": event_node_name,
                "task_id": task_id,
                "node_attempt": node_attempt,
                "error_kind": type(exc).__name__,
            })
            raise

    _node.__name__ = event_node_name
    return _node
