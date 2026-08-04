"""
后台 analysis job worker。

启动方式：
    python -m app.agent.worker
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import json
import logging
import socket
import sys
from typing import Any

from Agent.causal_agent.graph import create_graph_from_tools
from Agent.causal_agent.postgres_checkpointer import (
    build_checkpointer,
    open_checkpoint_pool,
    verify_checkpoint_schema,
)
from app.agent import core as agent_core
from app.agent import job_service
from app.db import check_database_readiness
from config.settings import settings


def _parse_sse_payload(event_data: str) -> dict[str, Any]:
    """解析 ai_call_stream 产出的旧 data-only SSE 字符串。"""
    if not event_data.startswith("data: "):
        return {"type": "message", "data": event_data}
    return json.loads(event_data[6:].strip())


async def _heartbeat_until_stopped(
    job_id: str,
    worker_id: str,
    attempt_count: int,
    stop: asyncio.Event,
) -> None:
    """在 job 执行期间定期刷新 heartbeat_at，直到 stop 被设置。"""
    # 持续检查stop是否为true
    while not stop.is_set():
        await asyncio.sleep(settings.JOB_HEARTBEAT_INTERVAL_SECONDS)
        if stop.is_set():
            break
        await asyncio.to_thread(
            job_service.update_heartbeat,
            job_id,
            worker_id,
            attempt_count,
        )
        logging.info("[worker] heartbeat job=%s worker=%s", job_id, worker_id)


async def _complete_terminal_event(
    job: dict[str, Any],
    worker_id: str,
    payload: dict[str, Any],
) -> bool:
    """在一个事务内完成终态事件、聊天保存和 job 成功更新。"""
    event_type = payload.get("type")
    if event_type == "final_result":
        response_data = payload.get("data", {})
    elif event_type == "interrupt":
        response_data = {
            "type": "human_input_required",
            "summary": payload.get("message", ""),
        }
    else:
        return False

    result = payload.get("data") if event_type == "final_result" else payload
    return await asyncio.to_thread(
        job_service.complete_job_with_chat,
        job,
        worker_id,
        event_type,
        payload,
        response_data,
        result,
    )


async def _run_job(job: dict[str, Any], graph, worker_id: str) -> None:
    """执行单个 job，将 Agent 流式事件落库，并处理终态保存。"""
    job_id = job["job_id"]
    stop_heartbeat = asyncio.Event()
    # 心跳检测协程是否正常进行
    heartbeat_task = asyncio.create_task(
        _heartbeat_until_stopped(job_id, worker_id, int(job["attempt_count"]), stop_heartbeat)
    )
    # 标记是否该job是否结束
    terminal_seen = False
    final_result = None

    try:
        ## 执行 AI流式传输
        logging.info("[worker] start job=%s worker=%s session=%s", job_id, worker_id, job["session_id"])
        async for event_data in agent_core.ai_call_stream(
            job["message"],
            job["user_id"],
            f"user-{job['user_id']}",
            job["session_id"],
            job_id=job_id,
            graph=graph,
        ):
            payload = _parse_sse_payload(event_data)
            event_type = payload.get("type", "message")

            if event_type in {"final_result", "interrupt"}:
                await _complete_terminal_event(job, worker_id, payload)
                terminal_seen = True
            elif event_type == "error":
                await asyncio.to_thread(
                    job_service.fail_job,
                    job_id,
                    worker_id,
                    int(job["attempt_count"]),
                    payload.get("message", "任务执行失败"),
                )
                terminal_seen = True
            else:
                await asyncio.to_thread(
                    job_service.write_event,
                    job_id,
                    worker_id,
                    int(job["attempt_count"]),
                    event_type,
                    payload,
                )

        if not terminal_seen:
            await asyncio.to_thread(
                job_service.complete_job,
                job_id,
                worker_id,
                int(job["attempt_count"]),
                final_result or {},
            )
        logging.info("[worker] finish job=%s worker=%s", job_id, worker_id)
    except Exception as exc:
        logging.error("[worker] job failed job=%s worker=%s error=%s", job_id, worker_id, exc, exc_info=True)
        await asyncio.to_thread(
            job_service.fail_job,
            job_id,
            worker_id,
            int(job["attempt_count"]),
            str(exc),
        )
    ## 如果结束，停止心跳
    finally:
        stop_heartbeat.set()
        await heartbeat_task


async def _run_slot(slot_index: int, checkpoint_pool) -> None:
    """启动一个 worker slot，并让它独占一组 MCP session/process 和 graph。"""
    worker_id = f"{socket.gethostname()}:{slot_index}"
    stack = AsyncExitStack()
    try:
        # 独占session和graph
        mcp_resources = await agent_core.open_mcp_client_resources(stack)
        checkpointer = build_checkpointer(checkpoint_pool)
        graph = create_graph_from_tools(
            agent_core.llm,
            mcp_resources.tools,
            checkpointer,
        )
        logging.info(
            "[worker] slot ready worker=%s tools=%s",
            worker_id,
            [tool.name for tool in mcp_resources.tools],
        )
        
        # 死循环领取job
        while True:
            # 线程池
            job = await asyncio.to_thread(job_service.claim_next_job, worker_id)
            if not job:
                # 休止JOB_POLL_INTERVAL_SECONDS秒
                await asyncio.sleep(settings.JOB_POLL_INTERVAL_SECONDS)
                continue
            await _run_job(job, graph, worker_id)
    finally:
        # 安全释放stack
        await stack.aclose()


async def _main_async() -> None:
    """初始化配置、数据库、LLM/RAG，然后启动固定数量的 worker slots。"""
    check_database_readiness()
    async with open_checkpoint_pool() as checkpoint_pool:
        await verify_checkpoint_schema(checkpoint_pool)
        if not agent_core.initialize_llm():
            raise RuntimeError("LLM 初始化失败")
        if not agent_core.initialize_rag_system():
            logging.warning("RAG 系统初始化失败，worker 将以无知识库模式运行。")

        slot_count = max(1, settings.JOB_WORKERS)
        logging.info("[worker] starting slot_count=%s", slot_count)
        # 获取_run_slot所有返回，并解包,单并不结束
        await asyncio.gather(
            *[_run_slot(i + 1, checkpoint_pool) for i in range(slot_count)]
        )


def main() -> None:
    """命令行入口：python -m app.agent.worker。"""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        force=True,
    )
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
