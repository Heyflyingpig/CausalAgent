"""验证 worker runtime 的依赖显式性和 slot 隔离边界。"""

import asyncio
from contextlib import AsyncExitStack
import runpy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.agent.worker.runtime import (
    McpClientResources,
    ProcessRuntime,
    RagReadiness,
    create_process_runtime,
    create_slot_runtime,
    inspect_rag_readiness,
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
        patch(
            "app.agent.worker.runtime.inspect_rag_readiness",
            return_value=RagReadiness("rag_unavailable", error_code="active_release_missing"),
        ),
    ):
        runtime = create_process_runtime()

    assert runtime.llm is llm
    assert runtime.rag_available is False
    assert runtime.rag_status == "rag_unavailable"
    assert runtime.rag_error_code == "active_release_missing"


def test_rag_readiness_returns_release_identity_without_heavy_runtime_creation():
    """readiness 只解析轻量配置，不创建向量库或 embedding。"""
    config = SimpleNamespace(
        vector_db_dir="/tmp/release/chroma",
        release_id="mm_" + "a" * 20,
        embedding_config={"status": "ready"},
    )
    with (
        patch("app.agent.worker.runtime._load_rag_runtime_config", return_value=config),
        patch("app.agent.worker.runtime.Path.is_dir", return_value=True),
    ):
        readiness = inspect_rag_readiness()

    assert readiness == RagReadiness("available", release_id="mm_" + "a" * 20)


def test_rag_readiness_rejects_unavailable_embedding():
    """embedding resolver 非 ready 时，启动不能误报 RAG 可用。"""
    config = SimpleNamespace(
        vector_db_dir="/tmp/release/chroma",
        release_id="mm_" + "a" * 20,
        embedding_config={"status": "missing"},
    )
    with patch("app.agent.worker.runtime._load_rag_runtime_config", return_value=config):
        readiness = inspect_rag_readiness()

    assert readiness.status == "rag_unavailable"
    assert readiness.error_code == "active_release_invalid"


def test_rag_readiness_rejects_unsafe_release_identity():
    """release id 不符合版本格式时不能进入安全诊断日志。"""
    config = SimpleNamespace(
        vector_db_dir="/tmp/release/chroma",
        release_id="../../private-path",
        embedding_config={"status": "ready"},
    )
    with patch("app.agent.worker.runtime._load_rag_runtime_config", return_value=config):
        readiness = inspect_rag_readiness()

    assert readiness.status == "rag_unavailable"
    assert readiness.error_code == "active_release_invalid"


def test_rag_readiness_hides_invalid_release_details():
    """失败状态只暴露稳定错误码，不泄露异常正文。"""
    with patch(
        "app.agent.worker.runtime._load_rag_runtime_config",
        side_effect=ValueError("/secret/manifest.json contains a private detail"),
    ):
        readiness = inspect_rag_readiness()

    assert readiness.status == "rag_unavailable"
    assert readiness.error_code == "active_release_invalid"
    assert readiness.release_id is None


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
    create_graph.assert_called_once_with(
        llm,
        tools,
        checkpointer,
        rag_available=True,
    )
    assert slot_runtime.llm is llm
    assert slot_runtime.mcp_resources is resources
    assert slot_runtime.mcp_tools is tools
    assert slot_runtime.graph is graph


def test_drain_timeout_cancels_local_slot_without_terminal_job_mutation():
    """超时只取消本地 slot，未完成 Job 留给 stale recovery。"""
    from app.agent.worker.bootstrap import _run_slots_until_shutdown

    async def scenario() -> None:
        """在超时后验证 slot 被取消且没有业务终态写入。"""
        stop_event = asyncio.Event()
        local_job = asyncio.Event()

        async def running_slot() -> None:
            """模拟仍在执行的 slot。"""
            await local_job.wait()

        slot_task = asyncio.create_task(running_slot())
        stop_event.set()
        with patch("config.settings.settings.JOB_DRAIN_TIMEOUT_SECONDS", 0.01):
            await _run_slots_until_shutdown([slot_task], stop_event)

        assert slot_task.done()
        assert not local_job.is_set()

    asyncio.run(scenario())


def test_shutdown_waits_for_slots_before_timeout():
    """停止信号后，仍在运行的 slot 可以在时限内自然完成。"""
    from app.agent.worker.bootstrap import _run_slots_until_shutdown

    async def scenario() -> None:
        """在 drain 时限内验证 slot 可以自然结束。"""
        stop_event = asyncio.Event()
        finished = asyncio.Event()

        async def finishing_slot() -> None:
            """模拟可在 drain 窗口内完成的 slot。"""
            await asyncio.sleep(0.01)
            finished.set()

        slot_task = asyncio.create_task(finishing_slot())
        stop_event.set()
        with patch("config.settings.settings.JOB_DRAIN_TIMEOUT_SECONDS", 1):
            await _run_slots_until_shutdown([slot_task], stop_event)

        assert finished.is_set()

    asyncio.run(scenario())


def test_stop_event_prevents_idle_slot_from_claiming_more_jobs():
    """slot 进入 drain 后不再调用 claim_next_job。"""
    from app.agent.worker import bootstrap

    async def scenario() -> None:
        """在停止事件已设置时验证 slot 不再领取 Job。"""
        stop_event = asyncio.Event()
        stop_event.set()
        slot_runtime = SimpleNamespace(mcp_tools=[])
        process_runtime = ProcessRuntime(llm=Mock(name="llm"), rag_available=True)
        with (
            patch.object(bootstrap, "create_slot_runtime", new=AsyncMock(return_value=slot_runtime)),
            patch.object(bootstrap.job_service, "claim_next_job") as claim_next_job,
        ):
            await bootstrap.run_slot(1, Mock(name="checkpoint_pool"), process_runtime, stop_event)

        claim_next_job.assert_not_called()

    asyncio.run(scenario())
