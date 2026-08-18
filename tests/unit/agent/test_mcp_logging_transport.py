"""MCP stdio 应用日志边界测试。"""

from __future__ import annotations

import io
import importlib
import json
import logging
import sys
import types


def test_mcp_main_writes_application_logs_to_stderr_only(monkeypatch):
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
    mcp_server = importlib.import_module("Agent.CausalAgentMCP.mcp_server")

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
        for handler in list(root.handlers):
            root.removeHandler(handler)
            if getattr(handler, "_causalagent_json_handler", False):
                handler.close()
        for handler in old_handlers:
            root.addHandler(handler)
        root.setLevel(old_level)

    assert stdout.getvalue() == ""
    records = [json.loads(line) for line in stderr.getvalue().splitlines()]
    assert records[0]["event_code"] == "mcp.startup.ready"
    assert all(record["service"] == "mcp" for record in records)
