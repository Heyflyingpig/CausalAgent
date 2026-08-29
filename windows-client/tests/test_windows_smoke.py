"""可选的真实 Windows WebView2 smoke。

默认跳过，避免普通 pytest 执行时意外打开窗口。设置
CAUSALAGENT_DESKTOP_RUN_SMOKE=1 后才会启动本地 stub 和真实桌面窗口。
"""

from __future__ import annotations

import os
import sys

import pytest

from causalagent_desktop.config import build_config
from causalagent_desktop.launcher import DesktopLauncher
from smoke_support import local_stub_server, webview_temp_dir


@pytest.mark.skipif(sys.platform != "win32", reason="真实 WebView2 smoke 只在 Windows 执行")
def test_real_edgechromium_window_loads_stub_and_exits_cleanly() -> None:
    if os.environ.get("CAUSALAGENT_DESKTOP_RUN_SMOKE") != "1":
        pytest.skip("设置 CAUSALAGENT_DESKTOP_RUN_SMOKE=1 才执行真实窗口 smoke")

    with local_stub_server() as server:
        with webview_temp_dir() as temp_dir:
            port = server.server_address[1]
            config = build_config(
                ["--url", f"http://127.0.0.1:{port}/"],
                environ={
                    "LOCALAPPDATA": str(temp_dir),
                    "CAUSALAGENT_DESKTOP_TEST_AUTOCLOSE_SECONDS": "1",
                },
            )
            launcher = DesktopLauncher(config)
            assert launcher.run() == 0
            assert launcher.used_renderer == "edgechromium"
            assert launcher.remote_page_loaded is True
