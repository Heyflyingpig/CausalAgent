"""基于 OpenAI Tool Calls 协议的统一 Pydantic 结构化输出入口。"""

from __future__ import annotations

from typing import Any, Mapping, TypeVar

from langchain_openai import ChatOpenAI
from pydantic import BaseModel


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    """封装结构化输出调用或 Pydantic 校验失败，并保留可审计元数据。"""

    def __init__(self, *, node_name: str, schema_name: str, cause: BaseException) -> None:
        self.node_name = node_name
        self.schema_name = schema_name
        self.original_exception_type = type(cause).__name__
        super().__init__(
            f"{node_name} 结构化输出失败: schema={schema_name}, "
            f"cause={self.original_exception_type}"
        )


def _build_structured_runnable(
    *,
    llm: ChatOpenAI,
    schema: type[SchemaT],
    prompt: Any,
    config: Any = None,
):
    """构造关闭 Thinking 且固定使用普通 function calling 的 Runnable。"""
    llm = llm.model_copy(
        update={
            "extra_body": {
                **(llm.extra_body or {}),
                "thinking": {"type": "disabled"},
            }
        }
    )
    runnable = prompt | llm.with_structured_output(
        schema,
        method="function_calling",
    )
    return runnable.with_config(config) if config is not None else runnable


def _validate_result(result: Any, schema: type[SchemaT]) -> SchemaT:
    """确保公共入口只向业务层返回通过校验的 Schema 实例。"""
    if isinstance(result, schema):
        return result
    return schema.model_validate(result)


def invoke_structured(
    *,
    llm: ChatOpenAI,
    schema: type[SchemaT],
    prompt: Any,
    inputs: Mapping[str, Any],
    node_name: str,
    config: Any = None,
) -> SchemaT:
    """同步执行一次结构化调用，失败时统一抛出 StructuredOutputError。"""
    try:
        runnable = _build_structured_runnable(
            llm=llm,
            schema=schema,
            prompt=prompt,
            config=config,
        )
        return _validate_result(runnable.invoke(dict(inputs)), schema)
    except Exception as exc:
        raise StructuredOutputError(
            node_name=node_name,
            schema_name=schema.__name__,
            cause=exc,
        ) from exc


async def ainvoke_structured(
    *,
    llm: ChatOpenAI,
    schema: type[SchemaT],
    prompt: Any,
    inputs: Mapping[str, Any],
    node_name: str,
    config: Any = None,
) -> SchemaT:
    """异步执行一次结构化调用，失败时统一抛出 StructuredOutputError。"""
    try:
        runnable = _build_structured_runnable(
            llm=llm,
            schema=schema,
            prompt=prompt,
            config=config,
        )
        return _validate_result(await runnable.ainvoke(dict(inputs)), schema)
    except Exception as exc:
        raise StructuredOutputError(
            node_name=node_name,
            schema_name=schema.__name__,
            cause=exc,
        ) from exc
