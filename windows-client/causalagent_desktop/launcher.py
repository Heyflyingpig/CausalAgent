"""CausalAgent Windows WebView2 启动器。

pywebview 只在本模块内延迟导入。所有站内/外部/非法导航都在 Edge
WebView2 的原生事件层处理，不依赖网页注入的 JS bridge。
"""

from __future__ import annotations

import html
import importlib
import sys
import threading
import webbrowser
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Sequence

from .config import ConfigError, DesktopConfig, NavigationAction, build_config, is_check_environment_requested
from .runtime import (
    EnvironmentCheckError,
    check_environment,
    ensure_environment,
    environment_error_message,
    show_error_dialog,
    startup_error_message,
)


def render_unavailable_page(url: str) -> str:
    """渲染后端不可达页面；不把异常、Cookie 或查询参数放进页面文本。"""

    from .config import display_url, normalize_url

    normalized = normalize_url(url)
    visible_url = html.escape(display_url(normalized), quote=True)
    target_url = html.escape(normalized, quote=True)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CausalAgent 暂时无法连接</title>
  <style>
    :root {{ color-scheme: light; font-family: "Segoe UI", "Microsoft YaHei", sans-serif; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f7f8fa; color: #1f2937; }}
    main {{ width: min(560px, calc(100% - 48px)); padding: 36px; border: 1px solid #e5e7eb; border-radius: 16px; background: #fff; box-shadow: 0 12px 36px rgb(15 23 42 / 8%); }}
    h1 {{ margin: 0 0 12px; font-size: 24px; }}
    p {{ line-height: 1.6; }}
    code {{ display: block; overflow-wrap: anywhere; padding: 10px 12px; border-radius: 8px; background: #f3f4f6; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 24px; }}
    a {{ display: inline-block; padding: 10px 16px; border-radius: 8px; text-decoration: none; }}
    a.primary {{ color: #fff; background: #2563eb; }}
    a.secondary {{ color: #1d4ed8; background: #eff6ff; }}
  </style>
</head>
<body>
  <main>
    <h1>暂时无法连接 CausalAgent</h1>
    <p>请确认服务器正在运行，或稍后重试。</p>
    <p>当前访问地址：</p>
    <code>{visible_url}</code>
    <nav>
      <a class="primary" href="{target_url}">重新加载</a>
      <a class="secondary" href="{target_url}" target="_blank" rel="noopener">在浏览器中打开</a>
    </nav>
  </main>
</body>
</html>"""


def _event_value(event_args: Any, *names: str) -> Any:
    for name in names:
        try:
            value = getattr(event_args, name)
        except Exception:
            continue
        if callable(value):
            try:
                value = value()
            except TypeError:
                continue
            except Exception:
                continue
        if value is not None:
            return value
    return None


def _event_url(event_args: Any) -> str:
    value = _event_value(event_args, "Uri", "uri", "URL", "url", "get_Uri")
    return str(value) if value is not None else ""


def _set_event_flag(event_args: Any, name: str, value: bool) -> None:
    setter = getattr(event_args, f"set_{name}", None)
    if callable(setter):
        setter(value)
        return
    try:
        setattr(event_args, name, value)
    except Exception:
        pass


class DesktopLauncher:
    """管理一个不暴露 JS API 的 CausalAgent WebView2 窗口。"""

    def __init__(
        self,
        config: DesktopConfig,
        *,
        webview_module: ModuleType | Any | None = None,
        browser_opener: Callable[[str], Any] | None = None,
    ) -> None:
        self.config = config
        self.policy = config.policy
        self._webview = webview_module
        self._browser_opener = browser_opener or webbrowser.open
        self._window: Any | None = None
        self._native_webview: Any | None = None
        self._edge_browser: Any | None = None
        self._error_page_visible = False
        self._loading_error_page = False
        self._smoke_close_scheduled = False
        self.used_renderer: str | None = None
        self.remote_page_loaded = False

    @property
    def window(self) -> Any | None:
        return self._window

    def run(self, *, validate_environment: bool = True) -> int:
        try:
            if validate_environment:
                ensure_environment()
            webview = self._webview or importlib.import_module("webview")
            self._webview = webview
            self.config.storage_path.mkdir(parents=True, exist_ok=True)

            window = webview.create_window(
                self.config.title,
                url=self.config.url,
                width=self.config.width,
                height=self.config.height,
                min_size=(self.config.min_width, self.config.min_height),
                resizable=True,
                background_color=self.config.background_color,
                text_select=True,
                zoomable=False,
            )
            self._window = window
            window.events.before_show += self._install_native_handlers
            window.events.loaded += self._on_loaded

            webview.start(
                gui="edgechromium",
                debug=self.config.debug,
                private_mode=False,
                storage_path=str(self.config.storage_path),
                icon=str(self.config.icon_path) if self.config.icon_path else None,
            )
            return 0
        except EnvironmentCheckError as error:
            show_error_dialog(environment_error_message(error.report))
            return 2
        except Exception as error:
            show_error_dialog(startup_error_message(error))
            return 1

    def _install_native_handlers(self, *_args: Any) -> None:
        """在 pywebview 创建 WinForms 控件后安装原生 Edge 事件。"""

        native = getattr(self._window, "native", None)
        edge_browser = getattr(native, "browser", None)
        native_webview = getattr(edge_browser, "webview", None)
        renderer_name = f"{type(edge_browser).__module__}.{type(edge_browser).__name__}".lower()
        if native_webview is None or "edgechrome" not in renderer_name:
            raise RuntimeError("桌面客户端未使用 Edge Chromium")

        self._edge_browser = edge_browser
        self._native_webview = native_webview
        self.used_renderer = "edgechromium"
        native_webview.NavigationStarting += self._on_navigation_starting
        native_webview.NavigationCompleted += self._on_navigation_completed
        native_webview.CoreWebView2InitializationCompleted += self._on_webview2_initialized

    def _on_webview2_initialized(self, sender: Any, args: Any) -> None:
        if _event_value(args, "IsSuccess", "is_success") is False:
            show_error_dialog("Microsoft Edge WebView2 Runtime 初始化失败，请安装或修复 Evergreen Runtime 后重试。")
            return

        core = _event_value(sender, "CoreWebView2", "core_webview2")
        if core is None:
            core = _event_value(self._native_webview, "CoreWebView2", "core_webview2")
        if core is None:
            return

        # pywebview 5.4 默认会把所有 NewWindowRequested 交给系统浏览器。
        # 移除该默认处理器，改由本客户端按 origin/scheme 策略决定，避免
        # file://、javascript: 和未知协议被系统意外打开。
        default_handler = getattr(self._edge_browser, "on_new_window_request", None)
        if default_handler is not None:
            try:
                core.NewWindowRequested -= default_handler
            except Exception:
                pass
        core.NewWindowRequested += self._on_new_window_requested

    def _on_navigation_starting(self, sender: Any, args: Any | None = None) -> None:
        event_args = args if args is not None else sender
        if self._loading_error_page:
            return

        decision = self.policy.decide(_event_url(event_args))
        if decision.action is NavigationAction.ALLOW_INTERNAL:
            self._error_page_visible = False
            return
        _set_event_flag(event_args, "Cancel", True)
        if decision.action is NavigationAction.OPEN_EXTERNAL and decision.normalized_url:
            self._open_external(decision.normalized_url)

    def _on_new_window_requested(self, sender: Any, args: Any | None = None) -> None:
        event_args = args if args is not None else sender
        url = _event_url(event_args)
        decision = self.policy.decide(url)
        _set_event_flag(event_args, "Handled", True)

        if decision.action is NavigationAction.OPEN_EXTERNAL and decision.normalized_url:
            self._open_external(decision.normalized_url)
            return
        if decision.action is not NavigationAction.ALLOW_INTERNAL or not decision.normalized_url:
            return

        # 错误页的“在浏览器中打开”使用同一个站内 URL，但通过新窗口语义
        # 表示用户明确选择系统浏览器；普通站内 target=_blank 仍留在客户端。
        if self._error_page_visible and decision.normalized_url == self.config.url:
            self._open_external(decision.normalized_url)
            return
        if self._window is not None:
            self._window.load_url(decision.normalized_url)

    def _on_navigation_completed(self, sender: Any, args: Any) -> None:
        if self._loading_error_page:
            if _event_value(args, "IsSuccess", "is_success") is not False:
                self._loading_error_page = False
            return
        if _event_value(args, "IsSuccess", "is_success") is False:
            self._show_unavailable_page(sender)
            return
        self.remote_page_loaded = True

    def _show_unavailable_page(self, sender: Any) -> None:
        self._error_page_visible = True
        self._loading_error_page = True
        page = render_unavailable_page(self.config.url)
        core = _event_value(sender, "CoreWebView2", "core_webview2")
        if core is None:
            core = _event_value(self._native_webview, "CoreWebView2", "core_webview2")
        try:
            if core is not None:
                core.NavigateToString(page)
            elif self._window is not None:
                self._window.load_html(page)
        except Exception:
            self._loading_error_page = False

    def _open_external(self, url: str) -> None:
        try:
            self._browser_opener(url)
        except Exception:
            # 系统浏览器失败时保留当前页面；不输出 URL 或异常原文。
            return

    def _on_loaded(self, *_args: Any) -> None:
        seconds = self.config.test_autoclose_seconds
        if seconds is None or self._smoke_close_scheduled:
            return
        self._smoke_close_scheduled = True
        threading.Timer(seconds, self._close_after_smoke).start()

    def _close_after_smoke(self) -> None:
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                return


def run_environment_check() -> int:
    report = check_environment()
    for line in report.summary_lines():
        print(line)
    if not report.ok:
        print(environment_error_message(report))
        return 2
    print("桌面环境检查通过。")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    if is_check_environment_requested(argv):
        return run_environment_check()

    try:
        config = build_config(sys.argv[1:] if argv is None else argv)
    except ConfigError as error:
        show_error_dialog(f"桌面配置无效：{error}")
        return 2
    return DesktopLauncher(config).run()
