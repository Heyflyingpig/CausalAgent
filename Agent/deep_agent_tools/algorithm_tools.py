"""从 AlgorithmSpec/Registry 生成模型可见的本地 function tools。"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from Agent.deep_agent.context import AgentRunContext

from .adapters.base import AdapterInput
from .models import (
    ActionAttempt,
    AlgorithmResult,
    DataProfile,
    InvocationRecord,
    McpInvocationContext,
)
from .identity import build_invocation_id
from .registry import AlgorithmRegistry, RegistryEntry
from .runtime_updates import (
    build_terminal_invocation,
    build_tool_command,
    resolve_runtime_invocation,
    with_tool_runtime_schema,
)


@dataclass(frozen=True)
class AlgorithmTool:
    """轻量工具描述；真实 LangChain Tool 在 graph builder 中惰性包装。"""

    entry: RegistryEntry
    adapter: Any
    runtime_context: "AgentRunContext"
    adapter_input: AdapterInput

    @property
    def name(self) -> str:
        return self.entry.spec.tool_name

    @property
    def description(self) -> str:
        return self.entry.spec.description

    @property
    def args_schema(self) -> type:
        return self.entry.spec.model_input_schema

    def schema(self) -> dict[str, Any]:
        return self.entry.spec.build_tool_schema()

    def _record(
        self,
        *,
        provider_call_id: str,
        response_identity: str,
        response_identity_source: Literal["provider_response_id", "message_execution_id"],
        retry_ordinal: int,
        result: AlgorithmResult | None,
        status: str,
        revision: int,
        result_ref: str | None = None,
    ) -> InvocationRecord:
        invocation_id = build_invocation_id(
            job_id=self.runtime_context.trusted_identity.job_id,
            response_identity=response_identity,
            provider_call_id=provider_call_id,
        )
        safe_error_code = None
        if result is not None:
            safe_error_code = result.diagnostics.safe_error_code
        return InvocationRecord(
            invocation_id=invocation_id,
            response_identity=response_identity,
            response_identity_source=response_identity_source,
            provider_response_id=(
                response_identity if response_identity_source == "provider_response_id" else None
            ),
            provider_call_id=provider_call_id,
            tool_name=self.name,
            final_status=(
                "pending"
                if status in {"queued", "running"}
                else "succeeded"
                if status == "succeeded"
                else "timed_out"
                if status == "timed_out"
                else "not_ready"
                if status == "not_ready"
                else "failed"
            ),
            result_ref=result_ref,
            attempts={
                retry_ordinal: ActionAttempt(
                    retry_ordinal=retry_ordinal,
                    revision=revision,
                    status=status,
                    started_at=datetime.now(timezone.utc) if status == "running" else None,
                    finished_at=(
                        datetime.now(timezone.utc)
                        if status not in {"queued", "running"}
                        else None
                    ),
                    safe_error_code=safe_error_code,
                )
            },
        )

    async def ainvoke(
        self,
        arguments: Mapping[str, Any] | None = None,
        *,
        provider_call_id: str,
        response_identity: str,
        retry_ordinal: int = 0,
        result_index: int = 0,
        runtime_context: "AgentRunContext | None" = None,
    ) -> AlgorithmResult:
        """调用 Adapter；身份参数由 Tool runtime 注入而不是模型 schema。"""

        active_context = runtime_context or self.runtime_context
        await active_context.ensure_active()
        return await self.adapter.run(
            parameters=dict(arguments or {}),
            adapter_input=self.adapter_input,
            trusted_context=active_context.trusted_identity,
            provider_call_id=provider_call_id,
            response_identity=response_identity,
            retry_ordinal=retry_ordinal,
            result_index=result_index,
        )

    async def ainvoke_with_ledger(
        self,
        arguments: Mapping[str, Any] | None = None,
        *,
        provider_call_id: str,
        response_identity: str,
        response_identity_source: Literal["provider_response_id", "message_execution_id"] = "provider_response_id",
        retry_ordinal: int = 0,
        result_index: int = 0,
    ) -> tuple[AlgorithmResult, tuple[InvocationRecord, ...]]:
        """执行一次调用并返回 queued/running/terminal 的完整 Ledger 片段。"""

        queued = self._record(
            provider_call_id=provider_call_id,
            response_identity=response_identity,
            response_identity_source=response_identity_source,
            retry_ordinal=retry_ordinal,
            result=None,
            status="queued",
            revision=0,
        )
        running = queued.model_copy(
            deep=True,
            update={
                "attempts": {
                    retry_ordinal: ActionAttempt(
                        retry_ordinal=retry_ordinal,
                        revision=1,
                        status="running",
                        started_at=datetime.now(timezone.utc),
                    )
                }
            },
        )
        # Adapter 会把可预期执行错误转换为 AlgorithmResult；这里仍会抛出的
        # 是取消、lease/guard 撤销或程序错误，不能在失去写资格后伪造 Ledger。
        result = await self.ainvoke(
            arguments,
            provider_call_id=provider_call_id,
            response_identity=response_identity,
            retry_ordinal=retry_ordinal,
            result_index=result_index,
        )

        terminal_status = {
            "valid": "succeeded",
            "timed_out": "timed_out",
            "not_ready": "not_ready",
            "not_applicable": "failed",
            "invalid_input": "failed",
            "execution_failed": "failed",
        }[result.status]
        terminal = self._record(
            provider_call_id=provider_call_id,
            response_identity=response_identity,
            response_identity_source=response_identity_source,
            retry_ordinal=retry_ordinal,
            result=result,
            status=terminal_status,
            revision=2,
            result_ref=result.result_ref if result.status == "valid" else None,
        )
        return result, (queued, running, terminal)

    def invoke(self, arguments: Mapping[str, Any] | None = None, **kwargs: Any) -> AlgorithmResult:
        """同步测试入口；运行中的 event loop 不会被偷偷嵌套。"""

        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.ainvoke(arguments, **kwargs))
        raise RuntimeError("AlgorithmTool.invoke cannot run inside an active event loop")

    def to_langchain_tool(self) -> Any:
        """包装为使用 ToolRuntime/Command 原子回写结果和 Ledger 的 Tool。"""

        try:
            from langchain.tools import ToolRuntime
            from langchain_core.tools import StructuredTool
        except (ImportError, ModuleNotFoundError) as exc:  # pragma: no cover
            raise RuntimeError("LangChain is not installed") from exc

        async def call(runtime: Any, **kwargs: Any) -> Any:
            identity = resolve_runtime_invocation(
                runtime,
                expected_context=self.runtime_context,
            )
            started_at = datetime.now(timezone.utc)
            result = await self.ainvoke(
                kwargs,
                provider_call_id=identity.provider_call_id,
                response_identity=identity.response_identity,
                runtime_context=identity.runtime_context,
            )
            attempt_status = {
                "valid": "succeeded",
                "timed_out": "timed_out",
                "not_ready": "not_ready",
                "not_applicable": "failed",
                "invalid_input": "failed",
                "execution_failed": "failed",
            }[result.status]
            safe_error_code = result.diagnostics.safe_error_code
            if hasattr(safe_error_code, "value"):
                safe_error_code = safe_error_code.value
            terminal = build_terminal_invocation(
                identity=identity,
                tool_name=self.name,
                attempt_status=attempt_status,
                started_at=started_at,
                result_ref=result.result_ref,
                safe_error_code=safe_error_code,
            )
            return build_tool_command(
                identity=identity,
                tool_name=self.name,
                payload=result.model_dump(mode="json"),
                ledger_record=terminal,
                state_updates={
                    "algorithm_results": {result.result_ref: result},
                },
            )

        # StructuredTool 会把 ToolRuntime 识别为 injected arg；显式 args_schema
        # 仍只暴露 AlgorithmSpec 中的科学参数，不让模型填写内部身份。
        call.__annotations__["runtime"] = ToolRuntime
        runtime_args_schema = with_tool_runtime_schema(
            self.args_schema,
            tool_name=self.name,
            tool_runtime_type=ToolRuntime,
        )
        return StructuredTool.from_function(
            coroutine=call,
            name=self.name,
            description=self.description,
            args_schema=runtime_args_schema,
        )


def build_algorithm_tools(
    registry: AlgorithmRegistry,
    *,
    runtime_context: "AgentRunContext",
    data_profile: DataProfile,
    input_identity: str | None = None,
    dataset_csv: str | None = None,
    missing_values_present: bool = False,
) -> tuple[AlgorithmTool, ...]:
    """按 Registry 静态顺序生成三项领域工具。"""

    identity = input_identity or runtime_context.trusted_identity.input_identity
    adapter_input = AdapterInput(
        data_profile=data_profile,
        input_identity=identity,
        dataset_csv=dataset_csv,
        missing_values_present=missing_values_present,
    )
    tools: list[AlgorithmTool] = []
    for entry in registry.entries:
        tools.append(
            AlgorithmTool(
                entry=entry,
                adapter=entry.adapter,
                runtime_context=runtime_context,
                adapter_input=adapter_input,
            )
        )
    return tuple(tools)


def build_default_algorithm_tools(
    *,
    runtime_context: "AgentRunContext",
    data_profile: DataProfile,
    adapters: Mapping[str, Any],
    **kwargs: Any,
) -> tuple[AlgorithmTool, ...]:
    """显式传入 Adapter 绑定，防止从远端 MCP list_tools 动态注册。"""

    from .registry import build_default_registry

    registry = build_default_registry(adapters)
    return build_algorithm_tools(
        registry,
        runtime_context=runtime_context,
        data_profile=data_profile,
        **kwargs,
    )
