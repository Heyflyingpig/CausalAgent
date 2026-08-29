"""Flask 请求边界的关联、500 去重和 teardown 隔离测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import io
import json
import logging
import sys
import time
from unittest.mock import patch

from flask import jsonify
import pytest

from app import CausalFlask
from app.auth.session_guard import get_current_session_user
from app.request_context import (
    bind_request_log_context,
    log_authorization_denied,
    log_request_failure,
    register_request_context,
)
from observability.logging_runtime import configure_logging, current_log_context, log_event


@contextmanager
def captured_web_logging(monkeypatch: pytest.MonkeyPatch):
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    old_level = root.level
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    try:
        configure_logging("web", "test", logging.INFO)
        yield stream
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            if getattr(handler, "_causalagent_json_handler", False):
                handler.close()
        for handler in old_handlers:
            root.addHandler(handler)
        root.setLevel(old_level)


def _app() -> CausalFlask:
    app = CausalFlask(__name__)
    app.config.update(SECRET_KEY="test", PROPAGATE_EXCEPTIONS=False)
    register_request_context(app)
    logger = logging.getLogger("request-test")

    @app.get("/ok/<session_id>")
    def ok(session_id: str):
        bind_request_log_context(user_id=7, session_id=session_id, job_id=f"job-{session_id}")
        time.sleep(0.005)
        log_event(logger, "job.create.accepted", details={"status": "queued"})
        return jsonify({"success": True})

    @app.get("/boom")
    def boom():
        raise ValueError("password=unhandled-secret")

    @app.get("/caught")
    def caught():
        try:
            raise RuntimeError("caught-secret")
        except RuntimeError as exc:
            log_request_failure(
                logger,
                reason_code="unexpected_error",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
        return jsonify({"success": False}), 500

    @app.get("/bad")
    def bad():
        return jsonify({"success": False}), 400

    @app.get("/plain-forbidden")
    def plain_forbidden():
        return jsonify({"success": False}), 403

    @app.get("/ownership-denied")
    def ownership_denied():
        bind_request_log_context(user_id=7)
        log_authorization_denied(
            logger,
            resource_type="job",
            action="stream_events",
        )
        return jsonify({"success": False}), 404

    return app


def _records(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_concurrent_and_sequential_requests_keep_context_isolated(monkeypatch):
    app = _app()
    with captured_web_logging(monkeypatch) as stream:
        def request_one(index: int):
            with app.test_client() as client:
                response = client.get(
                    f"/ok/session-{index}",
                    headers={"X-Request-ID": f"request-{index}"},
                )
                return response.status_code, response.headers["X-Request-ID"]

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(request_one, (1, 2)))
        with app.test_client() as client:
            client.get("/ok/session-3", headers={"X-Request-ID": "request-3"})

        assert current_log_context() == {}

    assert results == [(200, "request-1"), (200, "request-2")]
    records = _records(stream)
    assert len(records) == 3
    by_request = {record["request_id"]: record for record in records}
    for index in (1, 2, 3):
        record = by_request[f"request-{index}"]
        assert record["user_id"] == "7"
        assert record["session_id"] == f"session-{index}"
        assert record["job_id"] == f"job-session-{index}"


def test_unhandled_and_caught_500_have_one_safe_event_each_while_4xx_is_silent(monkeypatch):
    app = _app()
    with captured_web_logging(monkeypatch) as stream:
        with app.test_client() as client:
            assert client.get("/bad").status_code == 400
            assert client.get("/plain-forbidden").status_code == 403
            assert client.get(
                "/boom",
                headers={"X-Request-ID": "request-boom"},
            ).status_code == 500
            assert client.get(
                "/caught",
                headers={"X-Request-ID": "request-caught"},
            ).status_code == 500
        assert current_log_context() == {}

    raw = stream.getvalue()
    assert "unhandled-secret" not in raw
    assert "caught-secret" not in raw
    records = _records(stream)
    assert [record["event_code"] for record in records] == [
        "web.request.unhandled",
        "web.request.failed",
    ]
    assert records[0]["request_id"] == "request-boom"
    assert records[0]["exception_type"] == "ValueError"
    assert records[1]["request_id"] == "request-caught"
    assert records[1]["exception_type"] == "RuntimeError"


def test_only_confirmed_cross_ownership_uses_security_warning(monkeypatch):
    app = _app()
    with captured_web_logging(monkeypatch) as stream:
        with app.test_client() as client:
            assert client.get("/plain-forbidden").status_code == 403
            assert client.get(
                "/ownership-denied",
                headers={"X-Request-ID": "request-denied"},
            ).status_code == 404

    records = _records(stream)
    assert len(records) == 1
    assert records[0]["event_code"] == "security.authorization.denied"
    assert records[0]["level"] == "warning"
    assert records[0]["user_id"] == "7"
    assert records[0]["details"] == {
        "resource_type": "job",
        "action": "stream_events",
        "reason_code": "ownership_mismatch",
    }


def test_binding_helper_without_registered_lifecycle_cannot_leak_context():
    app = CausalFlask(__name__)

    @app.get("/standalone")
    def standalone():
        bind_request_log_context(user_id=99, session_id="unmanaged-session")
        return jsonify({"success": True})

    with app.test_client() as client:
        assert client.get("/standalone").status_code == 200

    assert current_log_context() == {}


def test_revoked_session_logs_without_binding_unvalidated_user_id(monkeypatch):
    app = CausalFlask(__name__)
    app.config.update(SECRET_KEY="test")
    register_request_context(app)

    @app.get("/session-check")
    def session_check():
        return jsonify({"valid": get_current_session_user() is not None})

    with captured_web_logging(monkeypatch) as stream:
        with app.test_client() as client:
            with client.session_transaction() as flask_session:
                flask_session["user_id"] = 7
                flask_session["auth_version"] = 1
            with patch(
                "app.auth.session_guard.find_user_by_id",
                return_value={
                    "id": 7,
                    "username": "disabled-user",
                    "is_active": False,
                    "auth_version": 1,
                },
            ):
                response = client.get(
                    "/session-check",
                    headers={"X-Request-ID": "request-revoked"},
                )

    assert response.get_json() == {"valid": False}
    records = _records(stream)
    assert len(records) == 1
    assert records[0]["event_code"] == "security.session.revoked"
    assert records[0]["request_id"] == "request-revoked"
    assert "user_id" not in records[0]
