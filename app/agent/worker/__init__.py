"""analysis job worker package。"""

__all__ = ["OrderedEventWriter", "TEXT_FLUSH_CHARACTER_LIMIT"]


def __getattr__(name: str):
    """保持包级兼容导出，同时避免 worker 入口配置日志前加载数据库配置。"""
    if name in __all__:
        from app.agent.worker import event_writer

        return getattr(event_writer, name)
    raise AttributeError(name)
