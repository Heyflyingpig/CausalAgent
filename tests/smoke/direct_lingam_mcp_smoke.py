"""在锁定 Python 3.11 环境中验证 DirectLiNGAM MCP wrapper 到真实 runner 的链路。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import sys
import types

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from direct_lingam_smoke import build_six_variable_sem


def install_fastmcp_stub() -> None:
    """在轻量 smoke 镜像缺少 MCP 包时提供只保留 tool 装饰器的 stub。"""

    class FastMCP:
        """记录被注册的工具函数，并保持装饰器返回原函数。"""

        def __init__(self, name):
            self.name = name
            self.registered_tools = []

        def tool(self):
            def decorator(function):
                self.registered_tools.append(function.__name__)
                return function

            return decorator

        def run(self, *args, **kwargs):
            raise RuntimeError("FastMCP stub is only for import-time smoke tests.")

    fake_mcp_module = types.ModuleType("mcp")
    fake_server_module = types.ModuleType("mcp.server")
    fake_fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fake_fastmcp_module.FastMCP = FastMCP
    sys.modules.setdefault("mcp", fake_mcp_module)
    sys.modules.setdefault("mcp.server", fake_server_module)
    sys.modules.setdefault("mcp.server.fastmcp", fake_fastmcp_module)


def disable_mcp_log_file() -> None:
    """避免导入 mcp_server 时向工作区写入 smoke 日志。"""

    class NullFileHandler(logging.NullHandler):
        """兼容 logging.FileHandler 构造参数的空 handler。"""

        def __init__(self, *args, **kwargs):
            super().__init__()

    logging.FileHandler = NullFileHandler


def run_mcp_smoke() -> None:
    """执行 MCP wrapper 到 DirectLiNGAM runner 的最小真实算法链路验证。"""
    install_fastmcp_stub()
    disable_mcp_log_file()

    from Agent.CausalAgentMCP import mcp_server

    node_names = ["x0", "x1", "x2", "x3", "x4", "x5"]
    csv_data = pd.DataFrame(
        build_six_variable_sem(),
        columns=node_names,
    ).to_csv(index=False)

    mcp_server._load_csv = lambda user_id, job_id, input_user_file_id, input_object_id: csv_data
    result = asyncio.run(mcp_server.causal_direct_lingam(1, "smoke-job", 2, 3))

    assert "causal_direct_lingam" in mcp_server.mcp.registered_tools
    assert result["success"] is True, result
    assert result["algorithm"] == "direct_lingam"
    assert result["matrix_convention"] == "target_to_source"
    assert result["raw_results"]["causal_order_names"] == [
        node_names[index] for index in result["raw_results"]["causal_order"]
    ]
    assert len(result["data"]["edges"]) == 7
    assert all("weight" in edge for edge in result["data"]["edges"])

    print(
        "DirectLiNGAM MCP smoke passed: "
        f"tool=causal_direct_lingam, edge_count={len(result['data']['edges'])}"
    )


if __name__ == "__main__":
    run_mcp_smoke()
