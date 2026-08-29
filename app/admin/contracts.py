"""管理员 3.1 API 的统一响应、分页游标与敏感访问审计契约。"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from functools import wraps
import json
import logging
from typing import Any, Callable, Iterable

from flask import g, jsonify, make_response, request

from app.admin.audit_service import record_admin_audit_event
from app.request_context import get_request_id, log_request_failure


LOGGER = logging.getLogger(__name__)
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 50
MAX_CONTENT_CHUNK = 64 * 1024


@dataclass(slots=True)
class AdminApiError(Exception):
    """表示可安全返回给管理员前端的稳定 API 错误。"""

    code: str
    message: str
    status: int = 400
    fields: dict[str, str] | None = None

    def __str__(self) -> str:
        """返回适合日志记录的简短错误描述。"""
        return self.message


def json_value(value: Any) -> Any:
    """把数据库常见值递归转换为 JSON 可序列化值。"""
    if isinstance(value, datetime):
        return value.isoformat(timespec="milliseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def api_success(data: Any, *, status: int = 200, **extra: Any):
    """构造携带 request ID 的统一成功响应。"""
    payload = {
        "success": True,
        "data": json_value(data),
        "request_id": get_request_id(),
        **extra,
    }
    return jsonify(payload), status


def api_error(error: AdminApiError):
    """构造携带稳定错误码、字段错误和 request ID 的失败响应。"""
    payload: dict[str, Any] = {
        "success": False,
        "error": error.message,
        "code": error.code,
        "request_id": get_request_id(),
    }
    if error.fields:
        payload["fields"] = error.fields
    return jsonify(payload), error.status


def admin_api_endpoint(view_func):
    """把未处理异常收敛为统一管理员 API 错误响应。"""

    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        """执行管理员视图并隐藏内部异常细节。"""
        try:
            return view_func(*args, **kwargs)
        except AdminApiError as exc:
            if exc.status >= 500:
                log_request_failure(
                    LOGGER,
                    status_code=exc.status,
                    reason_code="unavailable",
                )
            return api_error(exc)
        except Exception as exc:
            log_request_failure(
                LOGGER,
                reason_code="unexpected_error",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            return api_error(AdminApiError(
                code="internal_error",
                message="管理员服务暂时不可用",
                status=500,
            ))

    return wrapped_view


def parse_limit(raw_value: str | None) -> int:
    """解析统一列表上限，并拒绝无界或异常值。"""
    if raw_value in (None, ""):
        return DEFAULT_PAGE_LIMIT
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise AdminApiError(
            code="invalid_query",
            message="limit 必须是整数",
            fields={"limit": "必须是整数"},
        ) from exc
    if not 1 <= value <= MAX_PAGE_LIMIT:
        raise AdminApiError(
            code="invalid_query",
            message=f"limit 必须在 1 到 {MAX_PAGE_LIMIT} 之间",
            fields={"limit": f"必须在 1 到 {MAX_PAGE_LIMIT} 之间"},
        )
    return value


def parse_non_negative_int(
    raw_value: str | None,
    *,
    field: str,
    default: int = 0,
    maximum: int | None = None,
) -> int:
    """解析非负整数字段并应用可选上限。"""
    if raw_value in (None, ""):
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise AdminApiError(
            code="invalid_query",
            message=f"{field} 必须是整数",
            fields={field: "必须是整数"},
        ) from exc
    if value < 0 or (maximum is not None and value > maximum):
        suffix = f"且不能超过 {maximum}" if maximum is not None else ""
        raise AdminApiError(
            code="invalid_query",
            message=f"{field} 必须是非负整数{suffix}",
            fields={field: f"必须是非负整数{suffix}"},
        )
    return value


def encode_cursor(values: Iterable[Any]) -> str:
    """把稳定排序键编码为不透明 URL 安全游标。"""
    raw = json.dumps(
        [json_value(value) for value in values],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(raw_value: str | None, *, size: int) -> list[Any] | None:
    """解码并验证不透明游标的元素数量。"""
    if not raw_value:
        return None
    try:
        padding = "=" * (-len(raw_value) % 4)
        decoded = base64.urlsafe_b64decode(raw_value + padding)
        values = json.loads(decoded.decode("utf-8"))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise AdminApiError(
            code="invalid_cursor",
            message="分页游标无效",
            fields={"cursor": "游标无法解析"},
        ) from exc
    if not isinstance(values, list) or len(values) != size:
        raise AdminApiError(
            code="invalid_cursor",
            message="分页游标无效",
            fields={"cursor": "游标结构不正确"},
        )
    return values


def page_result(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    cursor_fields: tuple[str, ...],
) -> dict[str, Any]:
    """截取多取的一行并返回下一页游标。"""
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        next_cursor = encode_cursor(items[-1][field] for field in cursor_fields)
    return {
        "items": [json_value(item) for item in items],
        "limit": limit,
        "has_more": has_more,
        "next_cursor": next_cursor,
    }


def content_chunk_limit(raw_value: str | None) -> int:
    """解析敏感正文单次读取源字节数并限制到 64 KiB。"""
    if raw_value in (None, ""):
        return MAX_CONTENT_CHUNK
    value = parse_non_negative_int(
        raw_value,
        field="limit",
        default=MAX_CONTENT_CHUNK,
        maximum=MAX_CONTENT_CHUNK,
    )
    if value == 0:
        raise AdminApiError(
            code="invalid_query",
            message="limit 必须大于 0",
            fields={"limit": "必须大于 0"},
        )
    return value


AuditValue = str | Callable[[dict[str, Any]], str]


def _resolve_audit_value(value: AuditValue, kwargs: dict[str, Any]) -> str:
    """解析静态或按当前请求生成的审计动作/目标。"""
    return value(kwargs) if callable(value) else value


def audited_access(
    *,
    action: AuditValue,
    target_type: str,
    target_id: AuditValue,
    audit_success: bool = True,
):
    """审计敏感访问；成功审计不可用时拒绝返回敏感数据。"""

    def decorator(view_func):
        """为指定敏感视图构造审计包装器。"""

        @wraps(view_func)
        def wrapped_view(*args, **kwargs):
            """记录成功、拒绝和失败结果且从不保存响应正文。"""
            action_value = _resolve_audit_value(action, kwargs)
            target_value = _resolve_audit_value(target_id, kwargs)
            try:
                response = make_response(view_func(*args, **kwargs))
            except AdminApiError as exc:
                actor = getattr(g, "current_user", None) or {}
                record_admin_audit_event(
                    actor=actor,
                    action=action_value,
                    target_type=target_type,
                    target_id=target_value,
                    old_values=None,
                    new_values=None,
                    result="rejected" if exc.status < 500 else "failed",
                    error_code=exc.code,
                    request_id=get_request_id(),
                )
                raise
            except Exception:
                actor = getattr(g, "current_user", None) or {}
                record_admin_audit_event(
                    actor=actor,
                    action=action_value,
                    target_type=target_type,
                    target_id=target_value,
                    old_values=None,
                    new_values=None,
                    result="failed",
                    error_code="internal_error",
                    request_id=get_request_id(),
                )
                raise

            actor = getattr(g, "current_user", None) or {}
            if 200 <= response.status_code < 300:
                if audit_success and not record_admin_audit_event(
                    actor=actor,
                    action=action_value,
                    target_type=target_type,
                    target_id=target_value,
                    old_values=None,
                    new_values=None,
                    result="success",
                    error_code=None,
                    request_id=get_request_id(),
                ):
                    raise AdminApiError(
                        code="audit_unavailable",
                        message="敏感访问审计暂时不可用",
                        status=503,
                    )
            else:
                result = "rejected" if response.status_code < 500 else "failed"
                record_admin_audit_event(
                    actor=actor,
                    action=action_value,
                    target_type=target_type,
                    target_id=target_value,
                    old_values=None,
                    new_values=None,
                    result=result,
                    error_code=f"http_{response.status_code}",
                    request_id=get_request_id(),
                )
            return response

        return wrapped_view

    return decorator
