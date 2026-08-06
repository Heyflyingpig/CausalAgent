"""按 LangGraph 源事件顺序持久化 worker 事件。"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agent import job_service


TEXT_FLUSH_INTERVAL_SECONDS = 0.150
TEXT_FLUSH_CHARACTER_LIMIT = 384


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
        payload.update(
            {
                "type": "text_delta",
                "sequence": sequence,
                "delta": "".join(self.buffer["chunks"]),
            }
        )
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
            self.buffer.update(
                {
                    "stream_id": stream_id,
                    "chunks": [],
                    "character_count": 0,
                    "started_at": asyncio.get_running_loop().time(),
                }
            )
        self.buffer["chunks"].append(payload["delta"])
        self.buffer["character_count"] += len(payload["delta"])
        if self.buffer["character_count"] >= TEXT_FLUSH_CHARACTER_LIMIT:
            await self._flush_text()

    async def _consume(self) -> None:
        """串行消费队列，并按批次起始时间触发定时刷新。"""
        try:
            while True:
                try:
                    if self.buffer:
                        elapsed = (
                            asyncio.get_running_loop().time()
                            - self.buffer["started_at"]
                        )
                        payload, accepted = await asyncio.wait_for(
                            self.queue.get(),
                            timeout=max(
                                0.001,
                                TEXT_FLUSH_INTERVAL_SECONDS - elapsed,
                            ),
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
