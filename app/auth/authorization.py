"""管理员接口、页面授权与安全回跳工具。"""

from functools import wraps
from html import escape
from urllib.parse import urlencode, urlsplit

from flask import g, jsonify, make_response, redirect, request

from app.auth.session_guard import get_current_session_user
from app.request_context import get_request_id


DEFAULT_ADMIN_PAGE = "/admin/database"
ADMIN_PAGE_PATHS = frozenset({
    "/admin",
    "/admin/overview",
    "/admin/users",
    "/admin/sessions",
    "/admin/jobs",
    "/admin/files",
    "/admin/database",
    "/admin/database/settings",
    "/admin/database/audit",
})


def safe_admin_return_target(raw_target):
    """只保留已知同源管理员页面路径，并丢弃查询参数与片段。"""
    if not isinstance(raw_target, str) or not raw_target:
        return None
    if raw_target.startswith("//") or "\\" in raw_target:
        return None
    if any(ord(character) < 32 for character in raw_target):
        return None
    try:
        parsed = urlsplit(raw_target)
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc:
        return None
    path = "/admin" if parsed.path == "/admin/" else parsed.path
    return path if path in ADMIN_PAGE_PATHS else None


def admin_login_url(raw_target=None):
    """返回统一登录入口，并只携带经过白名单校验的管理员回跳路径。"""
    target = safe_admin_return_target(raw_target)
    if target is None:
        return "/"
    return f"/?{urlencode({'next': target})}"


def _admin_forbidden_page():
    """返回真实 403 拒绝页，再把浏览器送回普通用户首页显示提示。"""
    home_url = "/?notice=admin_required"
    safe_home_url = escape(home_url, quote=True)
    response = make_response(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="0; url={safe_home_url}">
  <title>无管理员权限</title>
</head>
<body>
  <main>
    <h1>无管理员权限</h1>
    <p>当前账号不能访问管理后台，正在返回普通用户首页。</p>
    <p><a href="{safe_home_url}">立即返回首页</a></p>
  </main>
</body>
</html>""",
        403,
    )
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def admin_required(view_func=None, *, page: bool = False):
    """要求当前请求来自有效管理员，并区分页面与 API 未登录响应。"""

    def decorator(func):
        """为目标视图构造实时主库角色校验包装器。"""

        @wraps(func)
        def wrapped_view(*args, **kwargs):
            """在调用管理视图前从主库重新确认用户角色。"""
            current_user = get_current_session_user()
            if current_user is None or not current_user.get("is_active"):
                if page:
                    return redirect(admin_login_url(request.path))
                return jsonify({
                    "success": False,
                    "error": "用户未登录或会话已过期",
                    "code": "auth_required",
                    "request_id": get_request_id(),
                }), 401
            g.current_user = current_user
            if current_user.get("role") != "admin":
                if page:
                    return _admin_forbidden_page()
                return jsonify({
                    "success": False,
                    "error": "需要管理员权限",
                    "code": "admin_required",
                    "request_id": get_request_id(),
                }), 403
            return func(*args, **kwargs)

        return wrapped_view

    if view_func is None:
        return decorator
    return decorator(view_func)
