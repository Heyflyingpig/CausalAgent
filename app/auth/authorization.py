"""管理员接口授权工具。"""

from functools import wraps

from flask import jsonify

from app.auth.session_guard import get_current_session_user


def admin_required(view_func):
    """要求当前请求来自仍然有效的管理员账号。"""

    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        """在调用管理接口前从主库重新确认用户角色。"""
        current_user = get_current_session_user()
        if current_user is None:
            return jsonify({"success": False, "error": "用户未登录或会话已过期"}), 401
        if not current_user.get("is_active"):
            return jsonify({"success": False, "error": "用户未登录或会话已过期"}), 401
        if current_user.get("role") != "admin":
            return jsonify({"success": False, "error": "需要管理员权限"}), 403
        return view_func(*args, **kwargs)

    return wrapped_view
