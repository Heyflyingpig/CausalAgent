"""验证 worker runtime 的依赖显式性和 slot 隔离边界。"""

import asyncio
from contextlib import AsyncExitStack
import runpy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.agent.worker.runtime import (
    McpClientResources,
    ProcessRuntime,
    create_process_runtime,
    create_slot_runtime,
)


def test_worker_package_entrypoint_calls_bootstrap_main():
    """包入口应继续把 ``python -m app.agent.worker`` 转交给 bootstrap。"""
    with patch("app.agent.worker.bootstrap.main") as main:
        runpy.run_module("app.agent.worker", run_name="__main__")

    main.assert_called_once_with()


def test_core_facade_does_not_hold_runtime_globals():
    """兼容门面可以转发纯接口，但不能重新成为可变运行时容器。"""
    from app.agent import core

    assert not hasattr(core, "llm")
    assert not hasattr(core, "agent_graph")
    assert not hasattr(core, "mcp_session")


def test_process_runtime_returns_explicit_llm_and_rag_state():
    """进程初始化应返回值对象，而不是写入 core 模块全局变量。"""
    llm = Mock(name="llm")
    with (
        patch("app.agent.worker.runtime.create_llm", return_value=llm),
        patch("app.agent.worker.runtime.check_rag_availability", return_value=False),
    ):
        runtime = create_process_runtime()

    assert runtime.llm is llm
    assert runtime.rag_available is False


def test_slot_runtime_builds_graph_from_explicit_dependencies():
    """slot graph 应由传入 LLM、该 slot tools 与 checkpoint 共同构建。"""
    llm = Mock(name="llm")
    tools = [SimpleNamespace(name="causal_test")]
    graph = Mock(name="graph")
    checkpointer = Mock(name="checkpointer")
    resources = McpClientResources(
        client=Mock(name="client"),
        session=Mock(name="session"),
        tools=tools,
    )
    process_runtime = ProcessRuntime(llm=llm, rag_available=True)

    with (
        patch(
            "app.agent.worker.runtime.open_mcp_client_resources",
            new=AsyncMock(return_value=resources),
        ),
        patch(
            "app.agent.worker.runtime.build_checkpointer",
            return_value=checkpointer,
        ) as build_checkpointer,
        patch(
            "Agent.causal_agent.graph.create_graph_from_tools",
            return_value=graph,
        ) as create_graph,
    ):
        slot_runtime = asyncio.run(
            create_slot_runtime(
                process_runtime,
                AsyncExitStack(),
                Mock(name="checkpoint_pool"),
            )
        )

    build_checkpointer.assert_called_once()
    create_graph.assert_called_once_with(llm, tools, checkpointer)
    assert slot_runtime.llm is llm
    assert slot_runtime.mcp_resources is resources
    assert slot_runtime.mcp_tools is tools
    assert slot_runtime.graph is graph
