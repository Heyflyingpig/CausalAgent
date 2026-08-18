"""共享 JSON 日志运行时的安全边界和并发隔离测试。"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import io
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Iterator

import pytest

from observability.logging_runtime import (
    MAX_DETAILS_BYTES,
    MAX_LINE_BYTES,
    MAX_MESSAGE_BYTES,
    MAX_STACK_BYTES,
    MAX_STACK_ITEMS,
    configure_logging,
    log_context,
)


@contextmanager
def captured_logging(monkeypatch: pytest.MonkeyPatch) -> Iterator[io.StringIO]:
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    old_level = root.level
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    try:
        configure_logging("worker", "test", logging.INFO)
        yield stream
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            if getattr(handler, "_causalagent_json_handler", False):
                handler.close()
        for handler in old_handlers:
            root.addHandler(handler)
        root.setLevel(old_level)


def _lines(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_legacy_record_is_single_line_json_with_utc_and_null_classification(monkeypatch):
    with captured_logging(monkeypatch) as stream:
        logging.getLogger("legacy").info("中文日志")

    records = _lines(stream)
    assert len(records) == 1
    record = records[0]
    assert record["event_code"] is None
    assert record["category"] is None
    assert record["message"] == "中文日志"
    timestamp = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
    assert timestamp.tzinfo == timezone.utc
    assert len(stream.getvalue().splitlines()) == 1


def test_context_is_nested_and_does_not_leak_between_async_tasks_or_threads(monkeypatch):
    async def emit_async(logger: logging.Logger, request_id: str) -> None:
        with log_context(request_id=request_id):
            await asyncio.sleep(0)
            logger.info("async")

    async def emit_all(logger: logging.Logger) -> None:
        await asyncio.gather(
            emit_async(logger, "request-a"),
            emit_async(logger, "request-b"),
        )

    with captured_logging(monkeypatch) as stream:
        logger = logging.getLogger("context")
        with log_context(session_id="session-outer"):
            logger.info("outer")
            asyncio.run(emit_all(logger))
            logger.info("after-tasks")

        def emit_thread(request_id: str) -> None:
            with log_context(request_id=request_id):
                logger.info("thread")

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(emit_thread, ["thread-a", "thread-b"]))

    records = _lines(stream)
    assert records[0]["session_id"] == "session-outer"
    assert records[0].get("request_id") is None
    async_ids = {record["request_id"] for record in records if record["message"] == "async"}
    assert async_ids == {"request-a", "request-b"}
    assert records[3]["session_id"] == "session-outer"
    thread_ids = {record["request_id"] for record in records if record["message"] == "thread"}
    assert thread_ids == {"thread-a", "thread-b"}


def test_recursive_redaction_removes_sensitive_values_but_keeps_safe_counts(monkeypatch):
    with captured_logging(monkeypatch) as stream:
        logging.getLogger("redaction").info(
            "request password=top-secret Bearer bearer-secret",
            extra={
                "event_code": "request.accepted",
                "category": "request",
                "details": {
                    "count": 3,
                    "nested": [
                        {"token": "nested-secret"},
                        {"safe_id": "id-1", "file_content": "CSV正文"},
                    ],
                },
            },
        )

    raw = stream.getvalue()
    assert "top-secret" not in raw
    assert "bearer-secret" not in raw
    assert "nested-secret" not in raw
    assert "CSV正文" not in raw
    record = _lines(stream)[0]
    assert record["details"]["count"] == 3
    assert record["details"]["nested"][0]["token"] == "[REDACTED]"


def test_message_details_stack_and_complete_line_have_byte_limits(monkeypatch):
    with captured_logging(monkeypatch) as stream:
        logger = logging.getLogger("limits")
        try:
            raise ValueError("password=stack-secret " + ("异常" * 5000))
        except ValueError:
            logger.exception(
                "消息" * 3000,
                extra={
                    "event_code": "worker.job.failed",
                    "category": "lifecycle",
                    "details": {"large": "详情" * 5000},
                },
            )

    raw_line = stream.getvalue().splitlines()[0]
    record = json.loads(raw_line)
    assert len(record["message"].encode("utf-8")) <= MAX_MESSAGE_BYTES
    assert len(json.dumps(record["details"], ensure_ascii=False).encode("utf-8")) <= MAX_DETAILS_BYTES
    assert record["stack"] is not None
    assert len(record["stack"]) <= MAX_STACK_ITEMS
    assert len(json.dumps(record["stack"], ensure_ascii=False).encode("utf-8")) <= MAX_STACK_BYTES
    assert len(raw_line.encode("utf-8")) <= MAX_LINE_BYTES
    assert record["truncated"] is True
    assert "stack-secret" not in raw_line


def test_serialization_failure_uses_non_recursive_fallback_event(monkeypatch):
    with captured_logging(monkeypatch) as stream:
        logging.getLogger("serialization").info(
            "safe message",
            extra={"details": {"unsupported": object()}},
        )

    records = _lines(stream)
    assert len(records) == 1
    assert records[0]["event_code"] == "logging.serialization_failed"
    assert records[0]["category"] == "dependency"
    assert "object at" not in stream.getvalue()


def test_repeated_configuration_keeps_one_json_handler_and_rejects_unknown_context(monkeypatch):
    with captured_logging(monkeypatch) as stream:
        configure_logging("worker", "test", logging.INFO)
        configure_logging("worker", "test", logging.INFO)
        assert len(logging.getLogger().handlers) == 1
        with pytest.raises(ValueError):
            with log_context(arbitrary="not-allowed"):
                pass
        logging.getLogger("repeat").info("once")

    assert len(_lines(stream)) == 1
