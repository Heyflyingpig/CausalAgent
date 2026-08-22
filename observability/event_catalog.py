"""受管运行日志事件目录。

事件目录是运行日志级别、分类、固定消息和 ``details`` 白名单的唯一来源。
调用方不得在事件码之外自行决定这些属性。
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import math
import re
from types import MappingProxyType
from typing import Any, Mapping


_STABLE_TOKEN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_CONTEXT_FIELDS = frozenset(
    {
        "request_id",
        "user_id",
        "session_id",
        "job_id",
        "worker_slot",
        "node",
        "tool",
        "instance",
    }
)

CONTRACT_VIOLATIONS = frozenset(
    {
        "unknown_event",
        "details_not_mapping",
        "unknown_detail",
        "context_in_details",
        "invalid_detail_type",
        "invalid_detail_value",
        "detail_too_large",
        "invalid_context_field",
        "invalid_context_value",
        "context_reset_failed",
    }
)

REASON_CODES = frozenset(
    {
        "account_disabled",
        "account_missing",
        "audit_write_failed",
        "auth_failed",
        "auth_version_changed",
        "canceled",
        "checkpoint_unavailable",
        "claim_failed",
        "cleanup_failed",
        "collection_failed",
        "config_read_failed",
        "connection_unavailable",
        "csrf_invalid",
        "csrf_missing",
        "database_missing",
        "database_unavailable",
        "fenced",
        "heartbeat_failed",
        "initialization_failed",
        "internal_error",
        "invalid_result",
        "invalid_runtime_context",
        "knowledge_base_missing",
        "lock_operation_failed",
        "lock_release_failed",
        "node_error",
        "node_timeout",
        "ownership_mismatch",
        "persist_failed",
        "pool_capacity_below_snapshot_count",
        "pool_exhausted",
        "postprocess_failed",
        "protocol_error",
        "query_timeout",
        "reauthentication_failed",
        "readiness_failed",
        "replica_lag",
        "replica_status_unavailable",
        "replica_unhealthy",
        "retry_exhausted",
        "runtime_failed",
        "snapshot_publish_failed",
        "tool_error",
        "transport_error",
        "unexpected_error",
        "unavailable",
        "waiting_input",
        "worker_shutdown",
    }
)


@dataclass(frozen=True)
class DetailRule:
    """一个受管详情字段的值约束。"""

    types: tuple[type, ...]
    choices: frozenset[Any] | None = None
    pattern: re.Pattern[str] | None = None
    max_bytes: int = 256
    minimum: float | None = None
    maximum: float | None = None
    max_items: int = 16


@dataclass(frozen=True)
class EventSpec:
    """稳定事件合同。"""

    event_code: str
    level: int
    category: str
    message: str
    details: Mapping[str, DetailRule]


TOKEN = DetailRule((str,), pattern=_STABLE_TOKEN, max_bytes=128)
TEXT = DetailRule((str,), max_bytes=256)
MAX_SAFE_NUMBER = 9_223_372_036_854_775_807
COUNT = DetailRule((int,), minimum=0, maximum=MAX_SAFE_NUMBER)
POSITIVE_COUNT = DetailRule((int,), minimum=1, maximum=MAX_SAFE_NUMBER)
DURATION = DetailRule((int, float), minimum=0, maximum=MAX_SAFE_NUMBER)
BOOLEAN = DetailRule((bool,))
REASON = DetailRule((str,), choices=REASON_CODES, max_bytes=64)
METHOD = DetailRule(
    (str,),
    choices=frozenset({"DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"}),
    max_bytes=16,
)
STATUS_CODE = DetailRule((int,), minimum=100, maximum=599)
PHASES = DetailRule((list, tuple), max_items=16, max_bytes=1024)
SHA256 = DetailRule((str,), pattern=re.compile(r"^[a-f0-9]{64}$"), max_bytes=64)
JOB_STATUS = DetailRule(
    (str,),
    choices=frozenset({
        "queued",
        "running",
        "waiting_input",
        "succeeded",
        "failed",
        "canceled",
        "missing",
        "unknown",
    }),
    max_bytes=32,
)
EXECUTION_STATE = DetailRule(
    (str,),
    choices=frozenset({"leased", "draining", "unknown"}),
    max_bytes=32,
)
CLAIM_KIND = DetailRule(
    (str,),
    choices=frozenset({"initial", "user_resume", "stale_recovery"}),
    max_bytes=32,
)
JOB_OUTCOME = DetailRule(
    (str,),
    choices=frozenset({"final_result", "implicit_completion"}),
    max_bytes=32,
)
RAG_STATUS = DetailRule(
    (str,),
    choices=frozenset({"unavailable", "protocol_error"}),
    max_bytes=32,
)
RESULT_KIND = DetailRule(
    (str,),
    choices=frozenset({"structured_result", "other_result"}),
    max_bytes=32,
)


def _details(**rules: DetailRule) -> Mapping[str, DetailRule]:
    return MappingProxyType(dict(rules))


def _spec(
    level: int,
    category: str,
    message: str,
    **rules: DetailRule,
) -> EventSpec:
    # event_code 在目录冻结时由映射键回填，避免调用处重复写两份易漂移的值。
    return EventSpec("", level, category, message, _details(**rules))


_events: dict[str, EventSpec] = {
    "logging.serialization_failed": _spec(
        logging.ERROR,
        "dependency",
        "日志记录序列化失败",
    ),
    "logging.contract_invalid": _spec(
        logging.ERROR,
        "dependency",
        "日志事件合同无效",
        violation=DetailRule((str,), choices=CONTRACT_VIOLATIONS, max_bytes=64),
    ),
    "worker.slot.ready": _spec(
        logging.INFO,
        "lifecycle",
        "Worker slot 已就绪",
        tool_count=COUNT,
    ),
    "worker.slot.failed": _spec(
        logging.CRITICAL,
        "dependency",
        "Worker slot 初始化或运行失败",
        phase=TOKEN,
        reason_code=REASON,
    ),
    "web.request.unhandled": _spec(
        logging.ERROR,
        "request",
        "请求发生未处理异常",
        method=METHOD,
        endpoint=TOKEN,
        route=TEXT,
    ),
    "web.request.failed": _spec(
        logging.ERROR,
        "request",
        "请求在受控边界失败",
        method=METHOD,
        endpoint=TOKEN,
        status_code=STATUS_CODE,
        reason_code=REASON,
    ),
    "job.create.accepted": _spec(
        logging.INFO,
        "request",
        "分析任务已创建",
        status=JOB_STATUS,
    ),
    "job.create.replayed": _spec(
        logging.INFO,
        "request",
        "分析任务幂等重放已接受",
        status=JOB_STATUS,
    ),
    "job.create.failed": _spec(
        logging.ERROR,
        "request",
        "分析任务创建失败",
        reason_code=REASON,
    ),
    "admin.audit.write_failed": _spec(
        logging.ERROR,
        "dependency",
        "管理员审计事件写入失败",
        action=TOKEN,
        reason_code=REASON,
    ),
    "security.login.disabled_account": _spec(
        logging.WARNING,
        "security",
        "禁用账号尝试登录",
    ),
    "auth.login.last_login_update_failed": _spec(
        logging.WARNING,
        "dependency",
        "登录后的最后登录时间记录失败",
        reason_code=REASON,
    ),
    "security.authorization.denied": _spec(
        logging.WARNING,
        "security",
        "已验证用户尝试跨归属访问资源",
        resource_type=TOKEN,
        action=TOKEN,
        reason_code=REASON,
    ),
    "security.csrf.rejected": _spec(
        logging.WARNING,
        "security",
        "CSRF 校验拒绝请求",
        method=METHOD,
        endpoint=TOKEN,
        reason_code=REASON,
    ),
    "security.reauthentication.failed": _spec(
        logging.WARNING,
        "security",
        "高风险管理员操作重新认证失败",
        action=TOKEN,
        reason_code=REASON,
    ),
    "security.session.revoked": _spec(
        logging.WARNING,
        "security",
        "失效安全会话已撤销",
        reason_code=REASON,
    ),
    "db.connection.failed": _spec(
        logging.ERROR,
        "dependency",
        "数据库连接失败",
        source_alias=TOKEN,
        operation=TOKEN,
        reason_code=REASON,
        suppressed_count=COUNT,
    ),
    "db.replica.fallback": _spec(
        logging.WARNING,
        "dependency",
        "数据库读取已回退主库",
        source_alias=TOKEN,
        reason_code=REASON,
        lag_seconds=DURATION,
        suppressed_count=COUNT,
    ),
    "db.replica.recovered": _spec(
        logging.INFO,
        "dependency",
        "数据库副本读取已恢复",
        source_alias=TOKEN,
        downtime_ms=DURATION,
        failure_count=POSITIVE_COUNT,
    ),
    "db.query.slow": _spec(
        logging.WARNING,
        "dependency",
        "数据库查询超过慢查询阈值",
        operation=TOKEN,
        duration_ms=DURATION,
        statement_digest=SHA256,
        suppressed_count=COUNT,
    ),
    "worker.job.claimed": _spec(
        logging.INFO,
        "lifecycle",
        "Worker 已领取分析任务",
        claim_kind=CLAIM_KIND,
        attempt=POSITIVE_COUNT,
        lease_epoch=COUNT,
    ),
    "worker.job.finished": _spec(
        logging.INFO,
        "lifecycle",
        "分析任务执行完成",
        attempt=POSITIVE_COUNT,
        duration_ms=DURATION,
        outcome=JOB_OUTCOME,
    ),
    "worker.job.interrupted": _spec(
        logging.INFO,
        "lifecycle",
        "分析任务已暂停并等待输入",
        attempt=POSITIVE_COUNT,
        duration_ms=DURATION,
        reason_code=REASON,
    ),
    "worker.job.revoked": _spec(
        logging.INFO,
        "lifecycle",
        "分析任务执行资格已撤销",
        reason_code=REASON,
        status=JOB_STATUS,
        execution_state=EXECUTION_STATE,
    ),
    "worker.job.failed": _spec(
        logging.ERROR,
        "lifecycle",
        "分析任务执行失败",
        failure_phase=TOKEN,
        reason_code=REASON,
        attempt=POSITIVE_COUNT,
        duration_ms=DURATION,
    ),
    "worker.job.cleanup_failed": _spec(
        logging.ERROR,
        "dependency",
        "分析任务执行资源清理失败",
        failure_count=POSITIVE_COUNT,
        phases=PHASES,
    ),
    "worker.lease.refresh_failed": _spec(
        logging.WARNING,
        "dependency",
        "Worker lease 刷新失败",
        consecutive_failures=POSITIVE_COUNT,
        suppressed_count=COUNT,
    ),
    "worker.lease.recovered": _spec(
        logging.INFO,
        "dependency",
        "Worker lease 刷新已恢复",
        failure_count=POSITIVE_COUNT,
        downtime_ms=DURATION,
    ),
    "job.node.timeout": _spec(
        logging.WARNING,
        "lifecycle",
        "Agent 节点最终超时并进入降级路径",
        final_attempt=POSITIVE_COUNT,
        timeout_ms=DURATION,
        fallback=TOKEN,
    ),
    "job.node.degraded": _spec(
        logging.WARNING,
        "lifecycle",
        "Agent 节点最终失败并进入降级路径",
        failure_kind=TOKEN,
        final_attempt=POSITIVE_COUNT,
        fallback=TOKEN,
    ),
    "job.postprocess.degraded": _spec(
        logging.WARNING,
        "lifecycle",
        "因果分析后处理已降级",
        reason_code=REASON,
        affected_count=COUNT,
    ),
    "rag.startup.unavailable": _spec(
        logging.WARNING,
        "dependency",
        "RAG 知识库启动检查不可用",
        reason_code=REASON,
    ),
    "rag.enrichment.degraded": _spec(
        logging.WARNING,
        "dependency",
        "RAG 增强结果已降级",
        status=RAG_STATUS,
        reason_code=REASON,
        question_count=COUNT,
        evidence_count=COUNT,
    ),
    "mcp.tool.finished": _spec(
        logging.INFO,
        "dependency",
        "MCP 工具调用完成",
        duration_ms=DURATION,
        input_bytes=COUNT,
        result_kind=RESULT_KIND,
    ),
    "mcp.tool.failed": _spec(
        logging.ERROR,
        "dependency",
        "MCP 工具调用失败",
        duration_ms=DURATION,
        input_bytes=COUNT,
        reason_code=REASON,
    ),
    "mcp.transport.failed": _spec(
        logging.WARNING,
        "dependency",
        "MCP transport 最终调用失败",
        reason_code=REASON,
        final_attempt=POSITIVE_COUNT,
        duration_ms=DURATION,
    ),
    "monitor.snapshot.failed": _spec(
        logging.ERROR,
        "dependency",
        "数据库监控快照采集失败",
        snapshot_key=TOKEN,
        reason_code=REASON,
        duration_ms=DURATION,
        suppressed_count=COUNT,
    ),
    "monitor.snapshot.recovered": _spec(
        logging.INFO,
        "dependency",
        "数据库监控快照采集已恢复",
        snapshot_key=TOKEN,
        downtime_ms=DURATION,
        failure_count=POSITIVE_COUNT,
    ),
    "monitor.config.degraded": _spec(
        logging.WARNING,
        "dependency",
        "数据库监控配置已降级",
        reason_code=REASON,
        suppressed_count=COUNT,
    ),
    "monitor.config.recovered": _spec(
        logging.INFO,
        "dependency",
        "数据库监控配置已恢复",
        downtime_ms=DURATION,
        failure_count=POSITIVE_COUNT,
    ),
    "monitor.lock.failed": _spec(
        logging.WARNING,
        "dependency",
        "数据库监控命名锁操作失败",
        snapshot_key=TOKEN,
        reason_code=REASON,
        suppressed_count=COUNT,
    ),
    "monitor.lock.recovered": _spec(
        logging.INFO,
        "dependency",
        "数据库监控命名锁操作已恢复",
        snapshot_key=TOKEN,
        downtime_ms=DURATION,
        failure_count=POSITIVE_COUNT,
    ),
    "checkpoint.cleanup.succeeded": _spec(
        logging.INFO,
        "lifecycle",
        "Checkpoint cleanup 已完成",
        outbox_id=POSITIVE_COUNT,
        attempt=POSITIVE_COUNT,
        duration_ms=DURATION,
    ),
    "checkpoint.cleanup.failed": _spec(
        logging.ERROR,
        "dependency",
        "Checkpoint cleanup 执行失败",
        outbox_id=POSITIVE_COUNT,
        attempt=POSITIVE_COUNT,
        duration_ms=DURATION,
        reason_code=REASON,
    ),
    "checkpoint.cleanup.runtime.degraded": _spec(
        logging.WARNING,
        "dependency",
        "Checkpoint cleanup 运行循环已降级",
        reason_code=REASON,
        suppressed_count=COUNT,
    ),
    "checkpoint.cleanup.runtime.recovered": _spec(
        logging.INFO,
        "dependency",
        "Checkpoint cleanup 运行循环已恢复",
        downtime_ms=DURATION,
        failure_count=POSITIVE_COUNT,
    ),
}

for _service in ("web", "worker", "monitor", "mcp", "maintenance"):
    _events[f"{_service}.startup.ready"] = _spec(
        logging.INFO,
        "lifecycle",
        f"{_service} 进程启动检查完成",
    )
    _events[f"{_service}.startup.failed"] = _spec(
        logging.CRITICAL,
        "dependency",
        f"{_service} 进程启动失败",
        phase=TOKEN,
        dependency=TOKEN,
        reason_code=REASON,
    )

EVENT_SPECS: Mapping[str, EventSpec] = MappingProxyType(
    {
        event_code: EventSpec(
            event_code,
            spec.level,
            spec.category,
            spec.message,
            spec.details,
        )
        for event_code, spec in _events.items()
    }
)


def _is_expected_type(value: Any, rule: DetailRule) -> bool:
    if isinstance(value, bool) and bool not in rule.types:
        return False
    return isinstance(value, rule.types)


def _validate_value(value: Any, rule: DetailRule) -> str | None:
    if not _is_expected_type(value, rule):
        return "invalid_detail_type"
    if isinstance(value, float) and not math.isfinite(value):
        return "invalid_detail_value"
    if rule.choices is not None and value not in rule.choices:
        return "invalid_detail_value"
    if isinstance(value, str):
        if rule.pattern is not None and rule.pattern.fullmatch(value) is None:
            return "invalid_detail_value"
        if len(value.encode("utf-8")) > rule.max_bytes:
            return "detail_too_large"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if rule.minimum is not None and value < rule.minimum:
            return "invalid_detail_value"
        if rule.maximum is not None and value > rule.maximum:
            return "invalid_detail_value"
    if isinstance(value, (list, tuple)):
        if len(value) > rule.max_items:
            return "detail_too_large"
        if not all(isinstance(item, str) and _STABLE_TOKEN.fullmatch(item) for item in value):
            return "invalid_detail_value"
        if len("|".join(value).encode("utf-8")) > rule.max_bytes:
            return "detail_too_large"
    return None


def validate_event_details(
    event_code: str,
    details: Mapping[str, Any] | None,
) -> tuple[EventSpec | None, dict[str, Any] | None, str | None]:
    """返回事件合同、安全详情和可空违规码，不回显违规内容。"""

    spec = EVENT_SPECS.get(event_code)
    if spec is None:
        return None, None, "unknown_event"
    if details is None:
        return spec, None, None
    if not isinstance(details, Mapping):
        return spec, None, "details_not_mapping"

    safe: dict[str, Any] = {}
    for key, value in details.items():
        if key in _CONTEXT_FIELDS:
            return spec, None, "context_in_details"
        rule = spec.details.get(key)
        if rule is None:
            return spec, None, "unknown_detail"
        if value is None:
            continue
        violation = _validate_value(value, rule)
        if violation is not None:
            return spec, None, violation
        safe[key] = list(value) if isinstance(value, tuple) else value
    return spec, safe or None, None


__all__ = [
    "CONTRACT_VIOLATIONS",
    "DetailRule",
    "EVENT_SPECS",
    "EventSpec",
    "REASON_CODES",
    "validate_event_details",
]
