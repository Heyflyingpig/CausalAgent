"""
会话用户校验工具。
"""

from flask import session
import logging


def find_user_by_id(user_id):
    """延迟导入认证服务并按 ID 获取当前数据库用户。"""
    from app.auth.service import find_user_by_id as _find_user_by_id

    return _find_user_by_id(user_id)


def get_current_session_user():
    """
    返回当前会话对应的真实用户。

    如果浏览器里还保留着旧 session，但当前数据库中该用户已不存在或
    已被禁用，则主动清空 session，避免继续以失效身份访问受保护接口。
    """
    user_id = session.get("user_id")
    if not user_id:
        return None

    user = find_user_by_id(user_id)
    if not user:
        logging.warning("检测到失效会话，用户 ID %s 在当前数据库中不存在，已清空会话。", user_id)
        session.clear()
        return None

    if not user["is_active"]:
        logging.warning("检测到已禁用用户的会话，用户 ID %s，已清空会话。", user_id)
        session.clear()
        return None

    database_auth_version = int(user.get("auth_version") or 1)
    session_auth_version = session.get("auth_version")
    if session_auth_version is None:
        # 兼容升级前签发的 Cookie：只允许尚未发生安全变更的初始版本补写。
        if database_auth_version != 1:
            logging.warning(
                "检测到认证版本已变化的旧会话，用户 ID %s，已清空会话。",
                user_id,
            )
            session.clear()
            return None
        session["auth_version"] = database_auth_version
    else:
        try:
            matches_version = int(session_auth_version) == database_auth_version
        except (TypeError, ValueError):
            matches_version = False
        if not matches_version:
            logging.warning(
                "检测到认证版本失效的会话，用户 ID %s，已清空会话。",
                user_id,
            )
            session.clear()
            return None

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    return user
