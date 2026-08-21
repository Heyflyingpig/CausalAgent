"""第二阶段受管日志事件目录合同测试。"""

from __future__ import annotations

import logging

from observability.event_catalog import EVENT_SPECS, validate_event_details


EXPECTED_CODES = {
    "logging.serialization_failed",
    "logging.contract_invalid",
    "worker.slot.ready",
    "worker.slot.failed",
    "web.request.unhandled",
    "web.request.failed",
    "job.create.accepted",
    "job.create.replayed",
    "job.create.failed",
    "admin.audit.write_failed",
    "security.login.disabled_account",
    "security.authorization.denied",
    "security.csrf.rejected",
    "security.reauthentication.failed",
    "security.session.revoked",
    "db.connection.failed",
    "db.replica.fallback",
    "db.replica.recovered",
    "db.query.slow",
    "worker.job.claimed",
    "worker.job.finished",
    "worker.job.interrupted",
    "worker.job.revoked",
    "worker.job.failed",
    "worker.job.cleanup_failed",
    "worker.lease.refresh_failed",
    "worker.lease.recovered",
    "job.node.timeout",
    "job.node.degraded",
    "job.postprocess.degraded",
    "rag.startup.unavailable",
    "rag.enrichment.degraded",
    "mcp.tool.finished",
    "mcp.tool.failed",
    "mcp.transport.failed",
    "monitor.snapshot.failed",
    "monitor.snapshot.recovered",
    "monitor.config.degraded",
    "monitor.config.recovered",
    "monitor.lock.failed",
    "monitor.lock.recovered",
    "checkpoint.cleanup.succeeded",
    "checkpoint.cleanup.failed",
    "checkpoint.cleanup.runtime.degraded",
    "checkpoint.cleanup.runtime.recovered",
}
EXPECTED_CODES.update(
    f"{service}.startup.{outcome}"
    for service in ("web", "worker", "monitor", "mcp", "maintenance")
    for outcome in ("ready", "failed")
)


def _sample_value(field: str, rule):
    if rule.choices:
        return sorted(rule.choices, key=str)[0]
    if field == "method":
        return "GET"
    if field == "status_code":
        return 500
    if field == "statement_digest":
        return "a" * 64
    if field == "phases":
        return ["writer_abort"]
    if field == "reason_code":
        return "unavailable"
    if field == "violation":
        return "unknown_event"
    if field in {
        "attempt",
        "failure_count",
        "final_attempt",
        "outbox_id",
        "consecutive_failures",
    }:
        return 1
    if field.endswith("_count") or field in {
        "affected_count",
        "duration_ms",
        "downtime_ms",
        "input_bytes",
        "lag_seconds",
        "lease_epoch",
        "max_workers",
        "slot_count",
        "timeout_ms",
        "tool_count",
    }:
        return 0
    return "safe_token"


def test_catalog_has_exact_phase_two_codes_and_fixed_contract_shape():
    assert set(EVENT_SPECS) == EXPECTED_CODES
    for event_code, spec in EVENT_SPECS.items():
        assert spec.event_code == event_code
        assert spec.level in {
            logging.INFO,
            logging.WARNING,
            logging.ERROR,
            logging.CRITICAL,
        }, event_code
        assert spec.category in {"request", "lifecycle", "dependency", "security"}
        assert isinstance(spec.message, str) and spec.message
        assert spec.message.strip() == spec.message
        for rule in spec.details.values():
            if any(value_type in {int, float} for value_type in rule.types):
                assert rule.maximum is not None, event_code


def test_every_declared_detail_rule_accepts_a_safe_value_and_rejects_unknown_keys():
    for event_code, spec in EVENT_SPECS.items():
        details = {
            field: _sample_value(field, rule)
            for field, rule in spec.details.items()
        }
        resolved, safe, violation = validate_event_details(event_code, details)
        assert resolved is spec, event_code
        assert violation is None, (event_code, violation)
        assert safe == details or (not details and safe is None)

        _resolved, _safe, violation = validate_event_details(
            event_code,
            {"not_allowed": "hidden-value"},
        )
        assert violation == "unknown_detail"


def test_catalog_rejects_context_ids_inside_details_and_unknown_events():
    _spec, safe, violation = validate_event_details(
        "worker.job.finished",
        {"job_id": "job-1"},
    )
    assert safe is None
    assert violation == "context_in_details"

    spec, safe, violation = validate_event_details("not.registered", None)
    assert spec is None
    assert safe is None
    assert violation == "unknown_event"
