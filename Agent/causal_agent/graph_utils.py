from __future__ import annotations

import inspect

from langchain_core.runnables import RunnableConfig
from langgraph.errors import NodeError
from langgraph.runtime import Runtime

from app.agent.worker.execution_guard import (
    JobExecutionRevoked,
    current_execution_guard,
)


def _runtime_guard(runtime: Runtime):
    """读取 LangGraph runtime context；测试/旧直接调用退回当前异步上下文。"""
    context = getattr(runtime, "context", None)
    return context if hasattr(context, "ensure_active") else current_execution_guard()


def bind_node(func, *, event_node_name: str | None = None, **bound_kwargs):
    """绑定节点依赖，并通过 custom 流暴露真实的节点执行尝试。"""
    node_name = event_node_name or getattr(func, "__name__", "bound_node").removesuffix("_node")

    async def _node(state, runtime: Runtime):
        """执行函数节点，并把 attempt 边界写入 custom 流。"""
        guard = _runtime_guard(runtime)
        if guard is not None:
            await guard.ensure_active()
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
            result = await func(state, **bound_kwargs)
            if guard is not None:
                await guard.check_after_call()
            return result
        except JobExecutionRevoked:
            raise
        except Exception as exc:
            if guard is not None:
                await guard.check_after_call()
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
        state,
        runtime: Runtime,
        config: RunnableConfig,
    ):
        """执行 Runnable 节点，并保留 LangGraph 传入的运行配置。"""
        guard = _runtime_guard(runtime)
        if guard is not None:
            await guard.ensure_active()
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
            result = await runnable.ainvoke(state, config)
            if guard is not None:
                await guard.check_after_call()
            return result
        except JobExecutionRevoked:
            raise
        except Exception as exc:
            if guard is not None:
                await guard.check_after_call()
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


def bind_subgraph_node(func, *, event_node_name: str, **bound_kwargs):
    """绑定需要显式透传 ``config`` 和 runtime context 的子图适配节点。"""

    async def _node(
        state,
        runtime: Runtime,
        config: RunnableConfig,
    ):
        """执行父子 State 映射，并保留父图的 Guard 与 attempt 边界。"""
        guard = _runtime_guard(runtime)
        if guard is not None:
            await guard.ensure_active()
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
            result = await func(
                state,
                runtime=runtime,
                config=config,
                **bound_kwargs,
            )
            if guard is not None:
                await guard.check_after_call()
            return result
        except JobExecutionRevoked:
            raise
        except Exception as exc:
            if guard is not None:
                await guard.check_after_call()
            runtime.stream_writer({
                "type": "node_attempt_failed",
                "node_name": event_node_name,
                "task_id": task_id,
                "node_attempt": node_attempt,
                "error_kind": type(exc).__name__,
            })
            raise

    _node.__name__ = getattr(func, "__name__", event_node_name)
    return _node


def guarded_router(func):
    """在 conditional edge 读取 State 前后检查 invocation 执行资格。"""

    async def _router(state, runtime: Runtime):
        guard = _runtime_guard(runtime)
        if guard is not None:
            await guard.ensure_active()
        result = func(state)
        if inspect.isawaitable(result):
            result = await result
        if guard is not None:
            await guard.check_after_call()
        return result

    _router.__name__ = getattr(func, "__name__", "guarded_router")
    return _router


def guarded_error_handler(func):
    """阻断撤销后的 fallback State/Command 生成，并保留 LangGraph 参数注入。"""

    async def _handler(
        state,
        error: NodeError,
        runtime: Runtime,
    ):
        guard = _runtime_guard(runtime)
        if guard is not None:
            await guard.ensure_active()
        try:
            result = func(state, error)
            if inspect.isawaitable(result):
                result = await result
            if guard is not None:
                await guard.check_after_call()
            return result
        except JobExecutionRevoked:
            raise
        except Exception:
            if guard is not None:
                await guard.check_after_call()
            raise

    _handler.__name__ = getattr(func, "__name__", "guarded_error_handler")
    return _handler
