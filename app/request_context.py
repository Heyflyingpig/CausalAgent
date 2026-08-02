"""请求关联 ID 的 Flask 生命周期支持。"""

from __future__ import annotations

import re
from uuid import uuid4

from flask import g, request


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


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
    return request_id


def register_request_context(app) -> None:
    """为 Flask 应用注册 request ID 生成和响应头回传钩子。"""

    @app.before_request
    def assign_request_id() -> None:
        """在业务路由执行前确定本次请求的关联 ID。"""
        g.request_id = _resolve_request_id()

    @app.after_request
    def attach_request_id(response):
        """把关联 ID 添加到所有 HTTP 响应。"""
        response.headers["X-Request-ID"] = get_request_id()
        return response
