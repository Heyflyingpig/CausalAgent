"""进程级 JSON 日志运行时。

这个模块只扩展标准库 ``logging``，不引入业务 logger API。业务代码继续使用
``logging.getLogger(__name__)``，受管事件通过标准 ``extra`` 传入：
``event_code``、``category`` 和 ``details``。
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import contextvars
from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
import logging
import math
import os
import re
import sys
import threading
import traceback
from typing import Any


ALLOWED_SERVICES = frozenset({"web", "worker", "monitor", "mcp", "maintenance"})
ALLOWED_CATEGORIES = frozenset({"request", "lifecycle", "dependency", "security"})
ALLOWED_CONTEXT_FIELDS = frozenset(
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

MAX_MESSAGE_BYTES = 2 * 1024
MAX_DETAILS_BYTES = 4 * 1024
MAX_STACK_BYTES = 8 * 1024
MAX_STACK_ITEMS = 20
MAX_LINE_BYTES = 16 * 1024
MAX_CONTEXT_VALUE_BYTES = 256
MAX_ENVIRONMENT_BYTES = 128
MAX_SOURCE_BYTES = 256

_EVENT_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9]+)+$")
_REDACTED = "[REDACTED]"
_HANDLER_MARKER = "_causalagent_json_handler"
_CONFIGURE_LOCK = threading.RLock()
_LOG_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "causalagent_log_context",
    default={},
)

_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?P<label>"
    r"(?:password|passwd|secret|api[_-]?key|authorization|cookie|token|"
    r"connection(?:[_ -]?(?:string|uri|url))?|dsn|密码|口令|令牌|连接串)"
    r"\s*[:=：]\s*)"
    r"(?P<value>[^\s,;]+)",
    re.IGNORECASE,
)
_CONTENT_ASSIGNMENT_PATTERN = re.compile(
    r"(?P<label>"
    r"(?:prompt|file[_ -]?content|file[_ -]?body|csv[_ -]?data|raw[_ -]?sql|"
    r"sql[_ -]?params|user[_ -]?input|request[_ -]?body|tool[_ -]?result|"
    r"提示词|文件正文|用户输入)"
    r"\s*[:=：]\s*)"
    r"(?P<value>[^\n]+)",
    re.IGNORECASE,
)
_BEARER_PATTERN = re.compile(r"\bBearer\s+[^\s,;]+", re.IGNORECASE)
_CONNECTION_URL_PATTERN = re.compile(
    r"\b(?:mysql|mysql\+\w+|postgres(?:ql)?|redis|mongodb(?:\+srv)?)://[^\s]+",
    re.IGNORECASE,
)
_SENSITIVE_KEY_NAMES = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "token",
        "connection",
        "connection_string",
        "connection_uri",
        "connection_url",
        "dsn",
        "prompt",
        "file_content",
        "file_body",
        "csv_data",
        "raw_sql",
        "sql_params",
        "user_input",
        "request_body",
        "tool_result",
        "exception",
        "stack",
    }
)


def current_environment(default: str = "development") -> str:
    """返回不包含凭据的部署环境名。"""

    value = os.getenv("ENVIRONMENT") or os.getenv("FLASK_ENV") or default
    cleaned, _ = _truncate_text(value, MAX_ENVIRONMENT_BYTES)
    return cleaned or default


def _truncate_text(value: Any, limit: int) -> tuple[str, bool]:
    """按 UTF-8 字节截断文本，并保证不会切断 Unicode 字符。"""

    text = _redact_text(str(value))
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    return encoded[:limit].decode("utf-8", errors="ignore"), True


def _redact_text(value: str) -> str:
    """清理常见凭据、连接串和正文标记，且不记录原始匹配值。"""

    text = str(value)
    text = _CONNECTION_URL_PATTERN.sub(_REDACTED, text)
    text = _BEARER_PATTERN.sub(_REDACTED, text)
    text = _SECRET_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group('label')}{_REDACTED}",
        text,
    )
    return _CONTENT_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group('label')}{_REDACTED}",
        text,
    )


def _normalise_key(value: Any) -> str:
    try:
        key = str(value)
    except Exception:
        key = "unserializable_key"
    key, _ = _truncate_text(key, MAX_SOURCE_BYTES)
    return key


def _is_sensitive_key(value: str) -> bool:
    key = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    if key in _SENSITIVE_KEY_NAMES:
        return True
    if key.startswith("prompt_") or key.startswith("file_content_"):
        return True
    if key.endswith("_password") or key.endswith("_passwd"):
        return True
    if key.endswith("_token") or key.endswith("_api_key"):
        return True
    if key.endswith("_cookie") or key.endswith("_secret"):
        return True
    return False


def _sanitize_value(value: Any) -> Any:
    """递归清理 details；未知对象保留到 JSON 阶段触发安全降级。"""

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = _normalise_key(key)
            result[safe_key] = _REDACTED if _is_sensitive_key(safe_key) else _sanitize_value(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _REDACTED
    if isinstance(value, datetime):
        current = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return _REDACTED
    # 不调用 repr/str，避免把未知对象或其内部正文带进日志；json.dumps 会在
    # 这里失败，并由 Formatter 走 logging.serialization_failed 的非递归兜底。
    return value


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _normalise_event_code(value: Any) -> str | None:
    if not isinstance(value, str) or not _EVENT_CODE_PATTERN.fullmatch(value):
        return None
    return value


def _normalise_category(value: Any) -> str | None:
    return value if isinstance(value, str) and value in ALLOWED_CATEGORIES else None


def _level_name(record: logging.LogRecord) -> str:
    if record.levelno <= logging.DEBUG:
        return "debug"
    if record.levelno <= logging.INFO:
        return "info"
    if record.levelno <= logging.WARNING:
        return "warning"
    if record.levelno <= logging.ERROR:
        return "error"
    return "critical"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _context_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise TypeError("日志上下文字段只能使用 JSON 标量")


def _record_context(record: logging.LogRecord) -> tuple[dict[str, Any], bool]:
    values = dict(_LOG_CONTEXT.get())
    for field in ALLOWED_CONTEXT_FIELDS:
        if field in record.__dict__:
            values[field] = record.__dict__[field]

    result: dict[str, Any] = {}
    truncated = False
    for field, value in values.items():
        if value is None:
            continue
        if isinstance(value, str):
            safe, was_truncated = _truncate_text(value, MAX_CONTEXT_VALUE_BYTES)
            result[field] = safe
            truncated = truncated or was_truncated
            continue
        if isinstance(value, bool) or isinstance(value, int):
            result[field] = value
            continue
        if isinstance(value, float) and math.isfinite(value):
            result[field] = value
            continue
        result[field] = _REDACTED
        truncated = True
    return result, truncated


def _record_message(record: logging.LogRecord) -> tuple[str, bool]:
    try:
        message = record.getMessage()
    except Exception:
        return "日志消息格式化失败", True
    return _truncate_text(message, MAX_MESSAGE_BYTES)


def _record_stack(record: logging.LogRecord) -> tuple[list[str] | None, bool]:
    if not record.exc_info:
        return None, False
    try:
        raw_lines = [
            line.rstrip("\r\n")
            for block in traceback.format_exception(*record.exc_info)
            for line in block.splitlines()
            if line.strip()
        ]
    except Exception:
        return ["异常栈清理失败"], True

    truncated = len(raw_lines) > MAX_STACK_ITEMS
    lines = [_truncate_text(_redact_text(line), 1024)[0] for line in raw_lines[:MAX_STACK_ITEMS]]
    while lines and len(_json_bytes(lines)) > MAX_STACK_BYTES:
        truncated = True
        if len(lines) > 1:
            lines.pop()
            continue
        current = lines[0]
        shorter = _truncate_text(current, max(1, len(current.encode("utf-8")) // 2))[0]
        if shorter == current:
            lines.clear()
        else:
            lines[0] = shorter
    return lines or None, truncated


def _details_value(record: logging.LogRecord) -> tuple[dict[str, Any] | None, bool]:
    details = getattr(record, "details", None)
    if details is None:
        return None, False
    if not isinstance(details, Mapping):
        raise TypeError("日志 details 必须是 JSON object")
    sanitized = _sanitize_value(details)
    if not isinstance(sanitized, dict):
        raise TypeError("日志 details 必须是 JSON object")
    if len(_json_bytes(sanitized)) <= MAX_DETAILS_BYTES:
        return sanitized, False
    return {"_truncated": True}, True


def _fit_payload(payload: dict[str, Any], truncated: bool) -> str:
    payload["truncated"] = bool(truncated)
    raw = _json_bytes(payload)
    if len(raw) <= MAX_LINE_BYTES:
        return raw.decode("utf-8")

    payload["truncated"] = True
    payload["details"] = None
    payload["stack"] = None
    payload["message"] = _truncate_text(payload.get("message", ""), 1024)[0]
    for field in ALLOWED_CONTEXT_FIELDS:
        value = payload.get(field)
        if isinstance(value, str):
            payload[field] = _truncate_text(value, 64)[0]
    raw = _json_bytes(payload)
    if len(raw) <= MAX_LINE_BYTES:
        return raw.decode("utf-8")

    payload["logger"] = None
    payload["module"] = None
    payload["message"] = ""
    raw = _json_bytes(payload)
    if len(raw) <= MAX_LINE_BYTES:
        return raw.decode("utf-8")

    # 所有必需字段都已由调用方限制；这里只保留最小合法结构作为最后一道
    # 边界，确保日志系统永远不会向 stderr 写出半截或非法 JSON。
    minimal = {
        "timestamp": payload["timestamp"],
        "level": payload["level"],
        "service": payload["service"],
        "environment": _truncate_text(payload["environment"], MAX_ENVIRONMENT_BYTES)[0],
        "event_code": payload["event_code"],
        "category": payload["category"],
        "message": "",
        "details": None,
        "stack": None,
        "truncated": True,
        "logger": None,
        "module": None,
    }
    for field in ALLOWED_CONTEXT_FIELDS:
        if field in payload:
            value = payload[field]
            minimal[field] = _truncate_text(value, 64)[0] if isinstance(value, str) else value
    return _json_bytes(minimal).decode("utf-8")


def _fallback_line(formatter: "JsonLogFormatter", record: logging.LogRecord) -> str:
    """构造固定、无原始对象的降级事件；此函数绝不调用 logging。"""

    try:
        logger_name, _ = _truncate_text(getattr(record, "name", None), MAX_SOURCE_BYTES)
        module_name, _ = _truncate_text(getattr(record, "module", None), MAX_SOURCE_BYTES)
        payload = {
            "timestamp": _timestamp(),
            "level": _level_name(record),
            "service": formatter.service,
            "environment": formatter.environment,
            "event_code": "logging.serialization_failed",
            "category": "dependency",
            "message": "日志记录序列化失败",
            "details": {"source": "logging_runtime"},
            "stack": None,
            "truncated": False,
            "logger": logger_name or None,
            "module": module_name or None,
        }
        context, context_truncated = _record_context(record)
        payload.update(context)
        return _fit_payload(payload, context_truncated)
    except Exception:
        # 这里仍然不使用 record 中的任何可变内容。
        return json.dumps(
            {
                "timestamp": _timestamp(),
                "level": "error",
                "service": formatter.service,
                "environment": formatter.environment,
                "event_code": "logging.serialization_failed",
                "category": "dependency",
                "message": "日志记录序列化失败",
                "details": None,
                "stack": None,
                "truncated": True,
                "logger": None,
                "module": None,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


class JsonLogFormatter(logging.Formatter):
    """将标准 LogRecord 转成 v1 单行 JSON。"""

    def __init__(self, service: str, environment: str) -> None:
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        try:
            message, message_truncated = _record_message(record)
            details, details_truncated = _details_value(record)
            stack, stack_truncated = _record_stack(record)
            context, context_truncated = _record_context(record)
            logger_name, logger_truncated = _truncate_text(record.name, MAX_SOURCE_BYTES)
            module_name, module_truncated = _truncate_text(record.module, MAX_SOURCE_BYTES)
            payload: dict[str, Any] = {
                "timestamp": _timestamp(),
                "level": _level_name(record),
                "service": self.service,
                "environment": self.environment,
                "event_code": _normalise_event_code(getattr(record, "event_code", None)),
                "category": _normalise_category(getattr(record, "category", None)),
                "message": message,
                "details": details,
                "stack": stack,
                "truncated": False,
                "logger": logger_name or None,
                "module": module_name or None,
            }
            payload.update(context)
            return _fit_payload(
                payload,
                any(
                    (
                        message_truncated,
                        details_truncated,
                        stack_truncated,
                        context_truncated,
                        logger_truncated,
                        module_truncated,
                    )
                ),
            )
        except Exception:
            return _fallback_line(self, record)


def _resolve_level(level: int | str) -> int:
    if isinstance(level, str):
        resolved = logging.getLevelName(level.upper())
        if not isinstance(resolved, int):
            raise ValueError(f"未知日志级别: {level}")
        return resolved
    if isinstance(level, int):
        return level
    raise TypeError("日志级别必须是整数或名称")


def configure_logging(service: str, environment: str, level: int | str = logging.INFO) -> None:
    """幂等配置根 logger，仅保留一个 JSON stderr handler。"""

    if service not in ALLOWED_SERVICES:
        raise ValueError(f"未知日志服务: {service}")
    if not isinstance(environment, str) or not environment.strip():
        raise ValueError("日志环境名不能为空")
    resolved_level = _resolve_level(level)
    safe_environment, _ = _truncate_text(environment, MAX_ENVIRONMENT_BYTES)

    with _CONFIGURE_LOCK:
        root = logging.getLogger()
        owned_handler: logging.Handler | None = None
        for handler in list(root.handlers):
            if getattr(handler, _HANDLER_MARKER, False) and owned_handler is None:
                owned_handler = handler
                continue
            root.removeHandler(handler)
            handler.close()

        if owned_handler is None:
            owned_handler = logging.StreamHandler(sys.stderr)
            setattr(owned_handler, _HANDLER_MARKER, True)
            root.addHandler(owned_handler)
        elif getattr(owned_handler, "stream", None) is not sys.stderr:
            owned_handler.setStream(sys.stderr)

        owned_handler.setLevel(resolved_level)
        owned_handler.setFormatter(JsonLogFormatter(service, safe_environment))
        root.setLevel(resolved_level)
        root.disabled = False


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """在当前 async/task/thread 上下文内临时设置有限的日志关联字段。"""

    unknown = set(fields) - ALLOWED_CONTEXT_FIELDS
    if unknown:
        raise ValueError(f"不允许的日志上下文字段: {sorted(unknown)}")
    values: dict[str, Any] = {}
    for field, value in fields.items():
        if value is None:
            continue
        values[field] = _context_value(value)
    merged = dict(_LOG_CONTEXT.get())
    merged.update(values)
    token = _LOG_CONTEXT.set(merged)
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)


__all__ = [
    "ALLOWED_CATEGORIES",
    "ALLOWED_CONTEXT_FIELDS",
    "ALLOWED_SERVICES",
    "JsonLogFormatter",
    "configure_logging",
    "current_environment",
    "log_context",
]
