"""隔离的多模态公共知识库维护与查询模块。"""

__all__ = ["MultimodalKnowledgeBaseMaintenance"]


def __getattr__(name: str):
    """仅在需要维护管线时加载 embedding 等重型运行时依赖。"""
    if name == "MultimodalKnowledgeBaseMaintenance":
        from .pipeline import MultimodalKnowledgeBaseMaintenance

        return MultimodalKnowledgeBaseMaintenance
    raise AttributeError(name)
