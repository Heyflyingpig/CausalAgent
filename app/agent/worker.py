"""
后台 analysis job worker。

启动方式：
    python -m app.agent.worker
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import logging
import socket
import sys
from typing import Any

from Agent.causal_agent.postgres_checkpointer import (
    build_checkpointer,
    open_checkpoint_pool,
    verify_checkpoint_schema,
)
from app.agent import core as agent_core
from app.agent import job_service
from app.db import check_database_readiness
from config.settings import settings


TEXT_FLUSH_INTERVAL_SECONDS = 0.150
TEXT_FLUSH_CHARACTER_LIMIT = 384


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


class OrderedEventWriter:
    """按源事件顺序持久化，并按时间或字符数批量合并文字增量。"""

    def __init__(self, job: dict[str, Any], worker_id: str):
        """为一个 job 创建独占队列和单一消费协程。"""
        self.job = job
        self.worker_id = worker_id
        self.queue: asyncio.Queue = asyncio.Queue()
        self.buffer: dict[str, Any] | None = None
        self.persisted_sequences: dict[str, int] = {}
        self.terminal_seen = False
        self.error: BaseException | None = None
        self.task = asyncio.create_task(self._consume())

    async def submit(self, payload: dict[str, Any]) -> None:
        """把一个结构化事件交给单写协程。"""
        if self.error:
            raise self.error
        accepted = asyncio.get_running_loop().create_future()
        await self.queue.put((payload, accepted))
        await accepted

    async def close(self) -> None:
        """刷新剩余文字并等待所有数据库写入完成。"""
        if self.error:
            raise self.error
        accepted = asyncio.get_running_loop().create_future()
        await self.queue.put((None, accepted))
        await accepted
        await self.task
        if self.error:
            raise self.error

    async def _persist(self, payload: dict[str, Any]) -> None:
        """按事件类型调用 fenced 普通写入或现有事务终态入口。"""
        event_type = payload.get("type", "message")
        attempt_count = int(self.job["attempt_count"])
        if event_type in {"final_result", "interrupt"}:
            await _complete_terminal_event(self.job, self.worker_id, payload)
            self.terminal_seen = True
            return
        if event_type == "error":
            await asyncio.to_thread(
                job_service.fail_job,
                self.job["job_id"],
                self.worker_id,
                attempt_count,
                payload.get("message", "任务执行失败"),
            )
            self.terminal_seen = True
            return
        await asyncio.to_thread(
            job_service.write_event,
            self.job["job_id"],
            self.worker_id,
            attempt_count,
            event_type,
            payload,
        )

    async def _flush_text(self) -> None:
        """把当前文字缓冲合并为一个有序 text_delta。"""
        if not self.buffer:
            return
        stream_id = self.buffer["stream_id"]
        sequence = self.persisted_sequences.get(stream_id, 0) + 1
        self.persisted_sequences[stream_id] = sequence
        payload = {
            key: value
            for key, value in self.buffer.items()
            if key not in {"chunks", "character_count", "started_at"}
        }
        payload.update({
            "type": "text_delta",
            "sequence": sequence,
            "delta": "".join(self.buffer["chunks"]),
        })
        self.buffer = None
        await self._persist(payload)

    async def _accept_text(self, payload: dict[str, Any]) -> None:
        """接收内部 token，并在切流或字符阈值时刷新。"""
        stream_id = payload["stream_id"]
        if self.buffer and self.buffer["stream_id"] != stream_id:
            await self._flush_text()
        if not self.buffer:
            self.buffer = {
                key: value
                for key, value in payload.items()
                if key not in {"type", "sequence", "delta"}
            }
            self.buffer.update({
                "stream_id": stream_id,
                "chunks": [],
                "character_count": 0,
                "started_at": asyncio.get_running_loop().time(),
            })
        self.buffer["chunks"].append(payload["delta"])
        self.buffer["character_count"] += len(payload["delta"])
        if self.buffer["character_count"] >= TEXT_FLUSH_CHARACTER_LIMIT:
            await self._flush_text()

    async def _consume(self) -> None:
        """串行消费队列，并按批次起始时间触发 150ms 刷新。"""
        try:
            while True:
                try:
                    if self.buffer:
                        elapsed = asyncio.get_running_loop().time() - self.buffer["started_at"]
                        payload, accepted = await asyncio.wait_for(
                            self.queue.get(),
                            timeout=max(0.001, TEXT_FLUSH_INTERVAL_SECONDS - elapsed),
                        )
                    else:
                        payload, accepted = await self.queue.get()
                except asyncio.TimeoutError:
                    await self._flush_text()
                    continue

                if payload is None:
                    await self._flush_text()
                    accepted.set_result(None)
                    return
                if payload.get("type") == "text_chunk":
                    await self._accept_text(payload)
                else:
                    await self._flush_text()
                    await self._persist(payload)
                accepted.set_result(None)
        except BaseException as exc:
            self.error = exc
            if "accepted" in locals() and not accepted.done():
                accepted.set_exception(exc)


async def _run_job(job: dict[str, Any], graph, worker_id: str) -> None:
    """执行单个 job，将 Agent 流式事件落库，并处理终态保存。"""
    job_id = job["job_id"]
    stop_heartbeat = asyncio.Event()
    # 心跳检测协程是否正常进行
    heartbeat_task = asyncio.create_task(
        _heartbeat_until_stopped(job_id, worker_id, int(job["attempt_count"]), stop_heartbeat)
    )
    writer = OrderedEventWriter(job, worker_id)

    try:
        ## 执行 AI流式传输
        logging.info("[worker] start job=%s worker=%s session=%s", job_id, worker_id, job["session_id"])
        async for payload in agent_core.ai_call_stream(
            job["message"],
            job["user_id"],
            f"user-{job['user_id']}",
            job["session_id"],
            job_id=job_id,
            job_attempt=int(job["attempt_count"]),
            graph=graph,
        ):
            await writer.submit(payload)
        await writer.close()

        if not writer.terminal_seen:
            await asyncio.to_thread(
                job_service.complete_job,
                job_id,
                worker_id,
                int(job["attempt_count"]),
                {},
            )
        logging.info("[worker] finish job=%s worker=%s", job_id, worker_id)
    except Exception as exc:
        logging.error("[worker] job failed job=%s worker=%s error=%s", job_id, worker_id, exc, exc_info=True)
        safe_message = agent_core.sanitize_public_error(exc)
        await asyncio.to_thread(
            job_service.fail_job,
            job_id,
            worker_id,
            int(job["attempt_count"]),
            safe_message,
        )
    ## 如果结束，停止心跳
    finally:
        stop_heartbeat.set()
        await heartbeat_task


async def _run_slot(slot_index: int, checkpoint_pool) -> None:
    """启动一个 worker slot，并让它独占一组 MCP session/process 和 graph。"""
    from Agent.causal_agent.graph import create_graph_from_tools

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
