"""会话标题生成规则。"""

MAX_SESSION_TITLE_LENGTH = 500
DEFAULT_SESSION_TITLE = "新会话"


def build_session_title(message: str) -> str:
    """把首条消息转换为单行完整标题，仅在数据库字段上限处截断。"""
    normalized = " ".join(str(message or "").split())
    if not normalized:
        return DEFAULT_SESSION_TITLE
    if len(normalized) <= MAX_SESSION_TITLE_LENGTH:
        return normalized
    return normalized[: MAX_SESSION_TITLE_LENGTH - 1] + "…"
