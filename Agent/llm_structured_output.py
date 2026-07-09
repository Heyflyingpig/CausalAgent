"""LLM 结构化输出兼容层。"""

from typing import Any

from langchain_openai import ChatOpenAI

from config.settings import settings


def with_compatible_structured_output(llm: ChatOpenAI, schema: Any, **kwargs: Any):
    """使用项目配置选择 LangChain 结构化输出方式，并保持 Pydantic 返回类型。"""
    return llm.with_structured_output(
        schema,
        method=settings.LLM_STRUCTURED_OUTPUT_METHOD,
        **kwargs,
    )
