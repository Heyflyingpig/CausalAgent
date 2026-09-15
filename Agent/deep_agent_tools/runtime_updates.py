"""LangChain ToolRuntime identity resolution and monotonic State updates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field

from .identity import build_invocation_id
from .models import ActionAttempt, InvocationRecord, canonical_json_bytes


@dataclass(frozen=True)
class RuntimeInvocationIdentity:
    """一次 LangGraph tool call 的可信内部身份。"""

    provider_call_id: str
    response_identity: str
    response_identity_source: Literal[
        "provider_response_id", "message_execution_id"
    ]
    provider_response_id: str | None
    runtime_context: Any


def with_tool_runtime_schema(
    base_schema: type,
    *,
    tool_name: str,
    tool_runtime_type: type,
) -> type:
    """给内部校验 schema 增加 injected runtime，模型可见 schema 会过滤它。"""

    return type(
        f"{tool_name.title().replace('_', '')}RuntimeInput",
        (base_schema,),
        {
            "__annotations__": {"runtime": tool_runtime_type},
            "__module__": base_schema.__module__,
            "model_config": dict(base_schema.model_config)
            | {"arbitrary_types_allowed": True},
            "runtime": Field(exclude=True),
        },
    )


def resolve_runtime_invocation(
    runtime: Any,
    *,
    expected_context: Any | None = None,
) -> RuntimeInvocationIdentity:
    """从 ToolRuntime 提取模型不可伪造的调用、响应和 Job runtime 身份。"""

    provider_call_id = str(getattr(runtime, "tool_call_id", "") or "").strip()
    if not provider_call_id:
        raise RuntimeError("ToolRuntime.tool_call_id is required")

    state = getattr(runtime, "state", None)
    if not isinstance(state, Mapping):
        raise RuntimeError("ToolRuntime.state must be a mapping")

    provider_response_id = str(state.get("provider_response_id") or "").strip() or None
    message_execution_id = str(state.get("message_execution_id") or "").strip() or None
    if provider_response_id is not None:
        response_identity = provider_response_id
        response_identity_source: Literal[
            "provider_response_id", "message_execution_id"
        ] = "provider_response_id"
    elif message_execution_id is not None:
        response_identity = message_execution_id
        response_identity_source = "message_execution_id"
    else:
        raise RuntimeError(
            "graph state must persist provider_response_id or message_execution_id "
            "before executing tools"
        )

    runtime_context = getattr(runtime, "context", None)
    if runtime_context is None:
        raise RuntimeError("ToolRuntime.context is required")
    if expected_context is not None and (
        runtime_context.trusted_identity != expected_context.trusted_identity
    ):
        raise RuntimeError("ToolRuntime context does not match the registered tool context")

    return RuntimeInvocationIdentity(
        provider_call_id=provider_call_id,
        response_identity=response_identity,
        response_identity_source=response_identity_source,
        provider_response_id=provider_response_id,
        runtime_context=runtime_context,
    )


def build_terminal_invocation(
    *,
    identity: RuntimeInvocationIdentity,
    tool_name: str,
    attempt_status: Literal[
        "succeeded", "failed", "timed_out", "not_ready", "canceled", "discarded"
    ],
    started_at: datetime,
    retry_ordinal: int = 0,
    result_ref: str | None = None,
    safe_error_code: str | None = None,
) -> InvocationRecord:
    """生成只写 terminal revision 的单调 Ledger 更新。"""

    invocation_id = build_invocation_id(
        job_id=identity.runtime_context.trusted_identity.job_id,
        response_identity=identity.response_identity,
        provider_call_id=identity.provider_call_id,
    )
    final_status = {
        "succeeded": "succeeded",
        "failed": "failed",
        "timed_out": "timed_out",
        "not_ready": "not_ready",
        "canceled": "canceled",
        "discarded": "discarded",
    }[attempt_status]
    return InvocationRecord(
        invocation_id=invocation_id,
        response_identity=identity.response_identity,
        response_identity_source=identity.response_identity_source,
        provider_response_id=identity.provider_response_id,
        provider_call_id=identity.provider_call_id,
        tool_name=tool_name,
        final_status=final_status,
        result_ref=result_ref,
        attempts={
            retry_ordinal: ActionAttempt(
                retry_ordinal=retry_ordinal,
                revision=2,
                status=attempt_status,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                safe_error_code=safe_error_code,
            )
        },
    )


def build_tool_command(
    *,
    identity: RuntimeInvocationIdentity,
    tool_name: str,
    payload: Any,
    ledger_record: InvocationRecord,
    state_updates: Mapping[str, Any] | None = None,
) -> Any:
    """将受控 Tool 输出、Ledger 和领域结果在同一 graph step 写回 State。"""

    try:
        from langchain_core.messages import ToolMessage
        from langgraph.types import Command
    except (ImportError, ModuleNotFoundError) as exc:  # pragma: no cover
        raise RuntimeError("LangGraph runtime dependencies are not installed") from exc

    update = dict(state_updates or {})
    update["action_ledger"] = {ledger_record.invocation_id: ledger_record}
    update["messages"] = [
        ToolMessage(
            content=canonical_json_bytes(payload).decode("utf-8"),
            tool_call_id=identity.provider_call_id,
            name=tool_name,
        )
    ]
    return Command(update=update)
