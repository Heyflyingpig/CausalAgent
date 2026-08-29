"""桌面运行时检查和用户可见的启动错误映射。

这里故意不在模块导入阶段加载 pywebview。这样环境检查命令可以在缺少
pythonnet、bottle 或 WebView2 Runtime 时仍然给出可读结果。
"""

from __future__ import annotations

import importlib
import importlib.metadata
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Callable


EXPECTED_PYTHON = (3, 12)
EXPECTED_PYWEBVIEW_VERSION = "5.4"
WEBVIEW2_RUNTIME_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


class EnvironmentIssue(str, Enum):
    UNSUPPORTED_PYTHON = "unsupported_python"
    UNSUPPORTED_PLATFORM = "unsupported_platform"
    PYWEBVIEW_MISSING = "pywebview_missing"
    PYWEBVIEW_VERSION_MISMATCH = "pywebview_version_mismatch"
    PYWEBVIEW_INCOMPLETE = "pywebview_incomplete"
    BOTTLE_MISSING = "bottle_missing"
    PYTHONNET_MISSING = "pythonnet_missing"
    WEBVIEW2_RUNTIME_MISSING = "webview2_runtime_missing"


class EnvironmentCheckError(RuntimeError):
    """环境检查失败；消息本身不包含异常原文。"""

    def __init__(self, report: "EnvironmentReport") -> None:
        self.report = report
        super().__init__("桌面运行环境检查未通过")


class StartupErrorCode(str, Enum):
    WEBVIEW2_RUNTIME = "webview2_runtime"
    DESKTOP_DEPENDENCY = "desktop_dependency"
    STARTUP_FAILED = "startup_failed"


@dataclass(frozen=True)
class EnvironmentReport:
    python_version: tuple[int, int, int]
    platform_name: str
    pywebview_version: str | None
    pywebview_importable: bool
    bottle_importable: bool
    pythonnet_importable: bool
    webview2_version: str | None
    issues: tuple[EnvironmentIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def pywebview_complete(self) -> bool:
        return self.pywebview_importable and self.bottle_importable and self.pythonnet_importable

    def summary_lines(self) -> list[str]:
        python_ok = self.python_version[:2] == EXPECTED_PYTHON
        platform_ok = self.platform_name == "win32"
        version_ok = self.pywebview_version == EXPECTED_PYWEBVIEW_VERSION
        return [
            f"Python {'.'.join(str(part) for part in self.python_version)}：{'通过' if python_ok else '不支持'}",
            f"Windows 平台：{'通过' if platform_ok else '不支持'}",
            f"pywebview {self.pywebview_version or '未安装'}：{'通过' if version_ok else '不匹配'}",
            f"pywebview 依赖完整导入：{'通过' if self.pywebview_complete else '失败'}",
            f"WebView2 Runtime {self.webview2_version or '未检测到'}：{'通过' if self.webview2_version else '失败'}",
        ]


def detect_webview2_runtime(platform_name: str | None = None) -> str | None:
    """从 Windows EdgeUpdate 注册表视图寻找 Evergreen WebView2 Runtime。"""

    if (platform_name or sys.platform) != "win32":
        return None

    try:
        import winreg
    except ImportError:
        return None

    key_suffix = rf"Microsoft\EdgeUpdate\Clients\{WEBVIEW2_RUNTIME_CLIENT_ID}"
    paths = (
        rf"SOFTWARE\{key_suffix}",
        rf"SOFTWARE\WOW6432Node\{key_suffix}",
    )
    roots = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
    access_flags = [winreg.KEY_READ]
    for flag_name in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
        flag = getattr(winreg, flag_name, 0)
        if flag and flag not in access_flags:
            access_flags.append(flag | winreg.KEY_READ)

    for root in roots:
        for path in paths:
            for access in access_flags:
                try:
                    with winreg.OpenKey(root, path, 0, access) as key:
                        version, _ = winreg.QueryValueEx(key, "pv")
                    if str(version).strip():
                        return str(version).strip()
                except (OSError, FileNotFoundError, TypeError):
                    continue
    return None


def _package_version(
    webview_module: object | None,
    version_resolver: Callable[[str], str] | None,
) -> str | None:
    resolver = version_resolver or importlib.metadata.version
    try:
        return str(resolver("pywebview"))
    except Exception:
        module_version = getattr(webview_module, "__version__", None)
        return str(module_version) if module_version else None


def check_environment(
    *,
    platform_name: str | None = None,
    python_version: tuple[int, int, int] | None = None,
    module_loader: Callable[[str], object] | None = None,
    version_resolver: Callable[[str], str] | None = None,
    runtime_detector: Callable[[str | None], str | None] | None = None,
) -> EnvironmentReport:
    """检查桌面入口的所有硬前置，不打印或保留异常原文。"""

    effective_platform = platform_name or sys.platform
    effective_python = python_version or tuple(sys.version_info[:3])
    loader = module_loader or importlib.import_module
    loadable: dict[str, object | None] = {}
    for module_name in ("webview", "bottle", "clr"):
        try:
            loadable[module_name] = loader(module_name)
        except Exception:
            loadable[module_name] = None

    webview_module = loadable["webview"]
    pywebview_importable = all(
        callable(getattr(webview_module, attribute, None))
        for attribute in ("create_window", "start")
    )
    bottle_importable = loadable["bottle"] is not None
    pythonnet_importable = loadable["clr"] is not None
    pywebview_version = _package_version(webview_module, version_resolver)

    issues: list[EnvironmentIssue] = []
    if effective_python[:2] != EXPECTED_PYTHON:
        issues.append(EnvironmentIssue.UNSUPPORTED_PYTHON)
    if effective_platform != "win32":
        issues.append(EnvironmentIssue.UNSUPPORTED_PLATFORM)
    if not pywebview_importable:
        issues.append(EnvironmentIssue.PYWEBVIEW_MISSING)
    elif pywebview_version != EXPECTED_PYWEBVIEW_VERSION:
        issues.append(EnvironmentIssue.PYWEBVIEW_VERSION_MISMATCH)
    if not bottle_importable:
        issues.append(EnvironmentIssue.BOTTLE_MISSING)
    if not pythonnet_importable:
        issues.append(EnvironmentIssue.PYTHONNET_MISSING)
    if pywebview_importable and not (bottle_importable and pythonnet_importable):
        issues.append(EnvironmentIssue.PYWEBVIEW_INCOMPLETE)

    detector = runtime_detector or detect_webview2_runtime
    webview2_version = detector(effective_platform) if effective_platform == "win32" else None
    if effective_platform == "win32" and not webview2_version:
        issues.append(EnvironmentIssue.WEBVIEW2_RUNTIME_MISSING)

    # Preserve first-occurrence order while preventing duplicate issue codes.
    unique_issues = tuple(dict.fromkeys(issues))
    return EnvironmentReport(
        python_version=effective_python,
        platform_name=effective_platform,
        pywebview_version=pywebview_version,
        pywebview_importable=pywebview_importable,
        bottle_importable=bottle_importable,
        pythonnet_importable=pythonnet_importable,
        webview2_version=webview2_version,
        issues=unique_issues,
    )


def ensure_environment(report: EnvironmentReport | None = None) -> EnvironmentReport:
    checked = report or check_environment()
    if not checked.ok:
        raise EnvironmentCheckError(checked)
    return checked


def environment_error_message(report: EnvironmentReport) -> str:
    """把检查结果转换为不泄露内部异常的中文提示。"""

    messages: list[str] = []
    issue_set = set(report.issues)
    if EnvironmentIssue.UNSUPPORTED_PLATFORM in issue_set:
        messages.append("CausalAgent 桌面客户端只支持 Windows。")
    if EnvironmentIssue.UNSUPPORTED_PYTHON in issue_set:
        messages.append("请使用受支持的 CPython 3.12 环境。")
    if EnvironmentIssue.PYWEBVIEW_MISSING in issue_set:
        messages.append("未找到 pywebview，请安装 windows-client/requirements-desktop.txt。")
    elif EnvironmentIssue.PYWEBVIEW_VERSION_MISMATCH in issue_set:
        messages.append("pywebview 版本不匹配，请使用固定的 5.4 依赖。")
    if EnvironmentIssue.BOTTLE_MISSING in issue_set or EnvironmentIssue.PYTHONNET_MISSING in issue_set:
        messages.append("桌面依赖未完整安装，请重新安装 windows-client/requirements-desktop.txt。")
    if EnvironmentIssue.WEBVIEW2_RUNTIME_MISSING in issue_set:
        messages.append("未检测到 Microsoft Edge WebView2 Runtime，请安装 Evergreen Runtime 后重试。")
    if not messages:
        messages.append("桌面客户端运行环境检查失败，请运行 --check-environment 查看状态。")
    return "\n".join(messages)


def classify_startup_error(error: BaseException) -> StartupErrorCode:
    if isinstance(error, EnvironmentCheckError):
        if EnvironmentIssue.WEBVIEW2_RUNTIME_MISSING in set(error.report.issues):
            return StartupErrorCode.WEBVIEW2_RUNTIME
        return StartupErrorCode.DESKTOP_DEPENDENCY
    error_type = type(error).__name__.lower()
    if "webview2" in error_type or "edgechromium" in error_type:
        return StartupErrorCode.WEBVIEW2_RUNTIME
    if isinstance(error, (ImportError, ModuleNotFoundError)):
        return StartupErrorCode.DESKTOP_DEPENDENCY
    return StartupErrorCode.STARTUP_FAILED


def startup_error_message(error: BaseException) -> str:
    code = classify_startup_error(error)
    if code is StartupErrorCode.WEBVIEW2_RUNTIME:
        return "Microsoft Edge WebView2 Runtime 不可用，请安装或修复 Evergreen Runtime 后重试。"
    if code is StartupErrorCode.DESKTOP_DEPENDENCY:
        return "桌面依赖未完整安装，请运行 python Run_causal.py --check-environment。"
    return "CausalAgent 桌面客户端启动失败，请运行 python Run_causal.py --check-environment。"


def show_error_dialog(message: str, *, title: str = "CausalAgent") -> None:
    """用中文提示用户；失败时只输出固定提示，不输出 traceback。"""

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
            return
        except Exception:
            pass
    print(message)
