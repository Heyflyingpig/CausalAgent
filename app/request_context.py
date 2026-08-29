"""请求关联 ID 的 Flask 生命周期支持。"""

from __future__ import annotations

import re
from uuid import uuid4
from typing import Any

from flask import current_app, g, request

from observability.logging_runtime import bind_log_context, log_event, reset_log_context


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_DETAIL_TOKEN_PATTERN = re.compile(r"[^a-z0-9_.-]+")
_REQUEST_CONTEXT_EXTENSION = "causalagent_request_context_registered"


def _resolve_request_id() -> str:
    """接纳格式安全的上游 ID，否则生成新的 UUID。"""
    supplied = request.headers.get("X-Request-ID", "").strip()
    if supplied and REQUEST_ID_PATTERN.fullmatch(supplied):
        return supplied
    return str(uuid4())


def get_request_id() -> str:
    """返回当前请求的关联 ID；请求钩子缺失时安全生成。"""
    request_id = getattr(g, "request_id", None)
    if request_id:
        return request_id
    request_id = str(uuid4())
    g.request_id = request_id
    bind_request_log_context(request_id=request_id)
    return request_id


def bind_request_log_context(**fields: Any) -> None:
    """把已验证的请求级身份追加到 teardown 统一清理的上下文栈。"""

    if not current_app.extensions.get(_REQUEST_CONTEXT_EXTENSION):
        # 单元测试或嵌入式蓝图若没有安装生命周期钩子，就不能安全创建
        # 无人负责 reset 的 token；生产 create_app 始终先注册该扩展。
        return

    bound = getattr(g, "_log_context_values", None)
    if not isinstance(bound, dict):
        bound = {}
        g._log_context_values = bound
    changed = {
        field: value
        for field, value in fields.items()
        if value is not None and bound.get(field) != value
    }
    if not changed:
        return
    token = bind_log_context(**changed)
    tokens = getattr(g, "_log_context_tokens", None)
    if not isinstance(tokens, list):
        tokens = []
        g._log_context_tokens = tokens
    tokens.append(token)
    bound.update(changed)


def _stable_endpoint() -> str:
    value = str(request.endpoint or "unknown").lower()
    value = _DETAIL_TOKEN_PATTERN.sub("_", value).strip("_.-")
    if not value or not value[0].isalpha():
        value = f"endpoint_{value or 'unknown'}"
    return value[:128]


def current_request_log_details(*, include_route: bool = False) -> dict[str, Any]:
    """返回不含 URL 参数、查询串或正文的请求元数据。"""
    details: dict[str, Any] = {
        "method": request.method,
        "endpoint": _stable_endpoint(),
    }
    if include_route and request.url_rule is not None:
        details["route"] = request.url_rule.rule
    return details


def log_request_failure(
    logger,
    *,
    status_code: int = 500,
    reason_code: str = "unexpected_error",
    exc_info=None,
) -> None:
    """在捕获型 5xx 的最外层路由记录固定请求结果。"""
    log_event(
        logger,
        "web.request.failed",
        details={
            **current_request_log_details(),
            "status_code": status_code,
            "reason_code": reason_code,
        },
        exc_info=exc_info,
    )


def log_authorization_denied(logger, *, resource_type: str, action: str) -> None:
    """记录已认证用户对确知属于他人的资源访问，不包含资源标识。"""
    log_event(
        logger,
        "security.authorization.denied",
        details={
            "resource_type": resource_type,
            "action": action,
            "reason_code": "ownership_mismatch",
        },
    )


def register_request_context(app) -> None:
    """为 Flask 应用注册 request ID 生成和响应头回传钩子。"""

    if app.extensions.get(_REQUEST_CONTEXT_EXTENSION):
        return
    app.extensions[_REQUEST_CONTEXT_EXTENSION] = True

    @app.before_request
    def assign_request_id() -> None:
        """在业务路由执行前确定本次请求的关联 ID。"""
        g.request_id = _resolve_request_id()
        bind_request_log_context(request_id=g.request_id)

    @app.after_request
    def attach_request_id(response):
        """把关联 ID 添加到所有 HTTP 响应。"""
        response.headers["X-Request-ID"] = get_request_id()
        return response

    @app.teardown_request
    def clear_request_log_context(_error) -> None:
        """异常和正常路径都按逆序清理所有请求级上下文。"""

        tokens = getattr(g, "_log_context_tokens", None)
        if isinstance(tokens, list):
            while tokens:
                reset_log_context(tokens.pop())


__all__ = [
    "REQUEST_ID_PATTERN",
    "bind_request_log_context",
    "current_request_log_details",
    "get_request_id",
    "log_authorization_denied",
    "log_request_failure",
    "register_request_context",
]
