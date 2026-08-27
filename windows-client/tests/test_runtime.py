from __future__ import annotations

import logging

import pytest

from causalagent_desktop.runtime import (
    EnvironmentCheckError,
    EnvironmentIssue,
    StartupErrorCode,
    check_environment,
    classify_startup_error,
    environment_error_message,
    startup_error_message,
)


class FakeWebview:
    @staticmethod
    def create_window(*_args, **_kwargs):
        return object()

    @staticmethod
    def start(*_args, **_kwargs):
        return None


def _loader(modules: dict[str, object]):
    def load(name: str) -> object:
        value = modules.get(name)
        if isinstance(value, BaseException):
            raise value
        if value is None:
            raise ModuleNotFoundError(name)
        return value

    return load


def test_environment_check_accepts_complete_python312_windows_runtime() -> None:
    report = check_environment(
        platform_name="win32",
        python_version=(3, 12, 3),
        module_loader=_loader(
            {
                "webview": FakeWebview,
                "bottle": object(),
                "clr": object(),
            }
        ),
        version_resolver=lambda _name: "5.4",
        runtime_detector=lambda _platform: "151.0.4129.107",
    )

    assert report.ok
    assert report.pywebview_complete
    assert report.webview2_version == "151.0.4129.107"


def test_environment_check_reports_half_installed_webview_without_echoing_error() -> None:
    secret_error = RuntimeError("Cookie=secret-token query=private user text")
    report = check_environment(
        platform_name="win32",
        python_version=(3, 12, 3),
        module_loader=_loader(
            {
                "webview": FakeWebview,
                "bottle": secret_error,
                "clr": object(),
            }
        ),
        version_resolver=lambda _name: "5.4",
        runtime_detector=lambda _platform: "151.0.4129.107",
    )

    assert EnvironmentIssue.BOTTLE_MISSING in report.issues
    assert EnvironmentIssue.PYWEBVIEW_INCOMPLETE in report.issues
    message = environment_error_message(report)
    assert "secret-token" not in message
    assert "private user text" not in message


def test_missing_webview2_maps_to_a_chinese_runtime_message() -> None:
    report = check_environment(
        platform_name="win32",
        python_version=(3, 12, 3),
        module_loader=_loader(
            {
                "webview": FakeWebview,
                "bottle": object(),
                "clr": object(),
            }
        ),
        version_resolver=lambda _name: "5.4",
        runtime_detector=lambda _platform: None,
    )
    error = EnvironmentCheckError(report)

    assert classify_startup_error(error) is StartupErrorCode.WEBVIEW2_RUNTIME
    message = startup_error_message(error)
    assert "WebView2 Runtime" in message
    assert "secret-token" not in message
    assert "private" not in message


def test_unsupported_python_and_platform_are_reported() -> None:
    report = check_environment(
        platform_name="linux",
        python_version=(3, 11, 9),
        module_loader=_loader({}),
        version_resolver=lambda _name: "5.4",
        runtime_detector=lambda _platform: None,
    )

    assert EnvironmentIssue.UNSUPPORTED_PYTHON in report.issues
    assert EnvironmentIssue.UNSUPPORTED_PLATFORM in report.issues
    assert "CPython 3.12" in environment_error_message(report)


def test_startup_messages_do_not_echo_full_exception_or_sensitive_payload(caplog: pytest.LogCaptureFixture) -> None:
    secret_error = RuntimeError("Cookie=secret-token Token=abc123 query=private question")
    with caplog.at_level(logging.INFO, logger="causalagent_desktop"):
        message = startup_error_message(secret_error)

    assert "secret-token" not in message
    assert "abc123" not in message
    assert "private question" not in message
    assert all("secret-token" not in record.getMessage() for record in caplog.records)
