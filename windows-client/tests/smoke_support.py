"""真实 Windows smoke 使用的本地 HTTP stub。只依赖 Python 标准库。"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import shutil
import tempfile
import time
from typing import Iterator
from urllib.parse import urlsplit
from pathlib import Path


class StubHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlsplit(self.path).path
        if path == "/health":
            body = b"ok"
            status = 200
            content_type = "text/plain; charset=utf-8"
        elif path == "/external-link":
            body = b"<html><body>external test page</body></html>"
            status = 200
            content_type = "text/html; charset=utf-8"
        else:
            body = (
                b"<!doctype html><html><body>"
                b"<h1>CausalAgent desktop smoke</h1>"
                b"<a href='/health'>health</a>"
                b"<a href='/external-link'>external</a>"
                b"</body></html>"
            )
            status = 200
            content_type = "text/html; charset=utf-8"

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return None


@contextmanager
def local_stub_server() -> Iterator[ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextmanager
def webview_temp_dir() -> Iterator[Path]:
    """等待 WebView2 子进程释放本次 smoke 的用户数据目录后再清理。"""

    path = Path(tempfile.mkdtemp(prefix="causalagent-desktop-smoke-"))
    try:
        yield path
    finally:
        deadline = time.monotonic() + 10
        while path.exists() and time.monotonic() < deadline:
            try:
                shutil.rmtree(path)
                break
            except OSError:
                time.sleep(0.1)
        if path.exists():
            # 只清理本函数刚创建的临时目录；若 WebView2 仍持有句柄，
            # Windows 会保留目录，避免把正常进程退出变成清理 traceback。
            shutil.rmtree(path, ignore_errors=True)
