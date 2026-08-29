"""不依赖 pytest 的真实 Windows WebView2 smoke 入口。"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path


DESKTOP_ROOT = Path(__file__).resolve().parents[1]
if str(DESKTOP_ROOT) not in sys.path:
    sys.path.insert(0, str(DESKTOP_ROOT))

from causalagent_desktop.config import build_config  # noqa: E402
from causalagent_desktop.launcher import DesktopLauncher  # noqa: E402
from smoke_support import local_stub_server, webview_temp_dir  # noqa: E402


def main() -> int:
    if sys.platform != "win32":
        print("真实 Windows WebView2 smoke 只在 Windows 执行。")
        return 2

    with local_stub_server() as server:
        port = server.server_address[1]
        health_url = f"http://127.0.0.1:{port}/health"
        with urllib.request.urlopen(health_url, timeout=3) as response:
            if response.status != 200 or response.read() != b"ok":
                print("本地 stub health 检查失败。")
                return 1

        with webview_temp_dir() as temp_dir:
            config = build_config(
                ["--url", f"http://127.0.0.1:{port}/"],
                environ={
                    "LOCALAPPDATA": str(temp_dir),
                    "CAUSALAGENT_DESKTOP_TEST_AUTOCLOSE_SECONDS": "1",
                },
            )
            launcher = DesktopLauncher(config)
            result = launcher.run()
            if result != 0 or launcher.used_renderer != "edgechromium" or not launcher.remote_page_loaded:
                print("Windows WebView2 smoke 失败。")
                return result or 1

    print("Windows WebView2 smoke 通过：stub、Edge Chromium、窗口关闭和进程退出均完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
