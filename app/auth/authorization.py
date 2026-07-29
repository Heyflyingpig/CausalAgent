"""管理员接口与页面授权工具。"""

from functools import wraps

from flask import g, jsonify, redirect

from app.auth.session_guard import get_current_session_user


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
                    return redirect("/")
                return jsonify({"success": False, "error": "用户未登录或会话已过期"}), 401
            if current_user.get("role") != "admin":
                return jsonify({"success": False, "error": "需要管理员权限"}), 403
            g.current_user = current_user
            return func(*args, **kwargs)

        return wrapped_view

    if view_func is None:
        return decorator
    return decorator(view_func)
