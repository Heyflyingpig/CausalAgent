"""MCP stdio 应用日志边界测试。"""

from __future__ import annotations

import asyncio
import io
import importlib
import json
import logging
import sys
import types


def _import_mcp_server(monkeypatch):
    class FakeFastMCP:
        def __init__(self, name):
            self.name = name

        def tool(self):
            def decorator(function):
                return function

            return decorator

        def run(self, **kwargs):
            return None

    fake_mcp_module = types.ModuleType("mcp")
    fake_server_module = types.ModuleType("mcp.server")
    fake_fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fake_fastmcp_module.FastMCP = FakeFastMCP
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_server_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp_module)
    sys.modules.pop("Agent.CausalAgentMCP.mcp_server", None)
    return importlib.import_module("Agent.CausalAgentMCP.mcp_server")


def _restore_logging(root, old_handlers, old_level):
    for handler in list(root.handlers):
        root.removeHandler(handler)
        if getattr(handler, "_causalagent_json_handler", False):
            handler.close()
    for handler in old_handlers:
        root.addHandler(handler)
    root.setLevel(old_level)


def test_mcp_main_writes_application_logs_to_stderr_only(monkeypatch):
    mcp_server = _import_mcp_server(monkeypatch)

    root = logging.getLogger()
    old_handlers = root.handlers[:]
    old_level = root.level
    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(mcp_server.mcp, "run", lambda **_: None)
    try:
        mcp_server.main()
    finally:
        _restore_logging(root, old_handlers, old_level)

    assert stdout.getvalue() == ""
    records = [json.loads(line) for line in stderr.getvalue().splitlines()]
    assert records[0]["event_code"] == "mcp.startup.ready"
    assert all(record["service"] == "mcp" for record in records)


def test_mcp_fatal_runtime_failure_is_logged_and_exits_nonzero(monkeypatch):
    mcp_server = _import_mcp_server(monkeypatch)
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    old_level = root.level
    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(
        mcp_server.mcp,
        "run",
        lambda **_: (_ for _ in ()).throw(RuntimeError("transport-sensitive")),
    )
    try:
        try:
            mcp_server.main()
        except SystemExit as exc:
            assert exc.code == 1
        else:  # pragma: no cover - fatal failure must never look successful
            raise AssertionError("MCP fatal failure did not exit")
    finally:
        _restore_logging(root, old_handlers, old_level)

    assert stdout.getvalue() == ""
    assert "transport-sensitive" not in stderr.getvalue()
    records = [json.loads(line) for line in stderr.getvalue().splitlines()]
    assert [record["event_code"] for record in records] == [
        "mcp.startup.ready",
        "mcp.startup.failed",
    ]
    assert records[-1]["exception_type"] == "RuntimeError"


def test_mcp_tool_events_keep_context_and_never_log_csv_result_or_exception(monkeypatch):
    mcp_server = _import_mcp_server(monkeypatch)
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    old_level = root.level
    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(mcp_server, "_load_csv", lambda *_: "csv-sensitive\n1,2")

    async def scenario():
        success = await mcp_server._execute_tool(
            "causal_pc",
            lambda _csv: {"success": True, "result": "result-sensitive"},
            user_id=7,
            session_id="session-1",
            job_id="job-1",
            input_user_file_id=11,
            input_object_id=22,
            request_id="request-1",
            worker_slot=3,
        )

        def fail(_csv):
            raise ValueError("exception-sensitive")

        failed = await mcp_server._execute_tool(
            "causal_pc",
            fail,
            user_id=7,
            session_id="session-1",
            job_id="job-1",
            input_user_file_id=11,
            input_object_id=22,
            request_id="request-1",
            worker_slot=3,
        )
        return success, failed

    try:
        mcp_server.configure_logging("mcp", "test", logging.INFO)
        success, failed = asyncio.run(scenario())
    finally:
        _restore_logging(root, old_handlers, old_level)

    assert success["result"] == "result-sensitive"
    assert failed["success"] is False
    assert stdout.getvalue() == ""
    raw = stderr.getvalue()
    assert "csv-sensitive" not in raw
    assert "result-sensitive" not in raw
    assert "exception-sensitive" not in raw
    records = [json.loads(line) for line in raw.splitlines()]
    assert [record["event_code"] for record in records] == [
        "mcp.tool.finished",
        "mcp.tool.failed",
    ]
    for record in records:
        assert record["request_id"] == "request-1"
        assert record["user_id"] == "7"
        assert record["session_id"] == "session-1"
        assert record["job_id"] == "job-1"
        assert record["worker_slot"] == "3"
        assert record["node"] == "mcp_tool_node"
        assert record["tool"] == "causal_pc"
