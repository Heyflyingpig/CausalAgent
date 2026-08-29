from __future__ import annotations

import json
import re
from typing import Any, Type, TypeVar

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import BasePromptTemplate
from pydantic import BaseModel


SchemaT = TypeVar("SchemaT", bound=BaseModel)


def supports_structured_output(base_url: str | None = None) -> bool:
    """判断当前模型后端是否适合优先使用 LangChain with_structured_output。"""
    normalized_base_url = (base_url or "").lower()
    unsupported_hosts = ("api.deepseek.com",)
    return not any(host in normalized_base_url for host in unsupported_hosts)


def is_response_format_unavailable_error(exc: Exception) -> bool:
    """判断异常是否来自 response_format 或 structured output 不可用。"""
    message = str(exc).lower()
    return (
        "response_format" in message
        and (
            "unavailable" in message
            or "invalid_request_error" in message
            or "unsupported" in message
            or "not support" in message
        )
    )


def bind_json_response_format(llm: Any) -> Any:
    """为 OpenAI-compatible JSON mode 绑定 JSON object 输出约束。"""
    return llm.bind(response_format={"type": "json_object"})


def _content_blocks_to_text(content: list[Any]) -> str:
    """把多模态或兼容接口返回的 content blocks 合并为文本。"""
    parts: list[str] = []
    for part in content:
        if isinstance(part, dict):
            parts.append(str(part.get("text") or part.get("content") or ""))
            continue
        text = getattr(part, "text", None)
        parts.append(str(text if text is not None else part))
    return "".join(parts)


def parse_json_payload(payload: Any) -> Any:
    """把消息对象、字符串、dict 或 list 统一解析为 Python JSON payload。"""
    if isinstance(payload, (dict, list)):
        return payload

    content = getattr(payload, "content", payload)
    if isinstance(content, list):
        content = _content_blocks_to_text(content)

    if not isinstance(content, str):
        raise TypeError(f"Unsupported JSON payload type: {type(payload)!r}")

    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON payload content must be valid JSON: {exc}") from exc


async def ainvoke_json_output(
    prompt: BasePromptTemplate,
    llm: Any,
    payload: dict[str, Any],
) -> Any:
    """优先用 JSON mode 调用 LLM；不支持 response_format 时降级为普通 JSON parser。"""
    try:
        runnable = prompt | bind_json_response_format(llm) | JsonOutputParser()
        return await runnable.ainvoke(payload)
    except Exception as exc:
        if not is_response_format_unavailable_error(exc):
            raise
        runnable = prompt | llm | JsonOutputParser()
        return await runnable.ainvoke(payload)


async def ainvoke_structured_or_json(
    prompt: BasePromptTemplate,
    llm: Any,
    payload: dict[str, Any],
    schema: Type[SchemaT],
    *,
    base_url: str | None = None,
) -> SchemaT:
    """优先使用 with_structured_output；不可用时降级到 JSON mode 并校验 schema。"""
    if supports_structured_output(base_url):
        try:
            runnable = prompt | llm.with_structured_output(schema)
            return await runnable.ainvoke(payload)
        except Exception as exc:
            if not is_response_format_unavailable_error(exc):
                raise

    json_payload = await ainvoke_json_output(prompt, llm, payload)
    return schema.model_validate(parse_json_payload(json_payload))
