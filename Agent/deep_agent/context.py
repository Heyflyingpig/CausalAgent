"""Deep Agent invocation 级运行上下文。

State 会进入 checkpoint，而本模块中的对象只在一次 graph invocation 内存活。
因此 execution guard、executor、backend 和服务连接只能通过这里注入，不能被
模型参数构造，也不能写进 ``ProjectDeepAgentState``。
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from Agent.deep_agent_tools.models import McpInvocationContext


def _canonical_uuid(value: str | UUID, *, field_name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{field_name} must be a canonical UUID value") from exc


@dataclass(frozen=True)
class TrustedJobIdentity:
    """由 worker claim/lease 绑定的可信 Job 身份。

    ``input_identity`` 是冻结输入快照的摘要，不是文件正文。它可以进入内部
    command/provenance，但不会出现在模型可见的参数 schema 中。
    """

    job_id: str | UUID
    session_id: str | UUID
    user_id: int
    attempt_count: int
    lease_epoch: int
    worker_id: str
    input_identity: str
    input_snapshot_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", _canonical_uuid(self.job_id, field_name="job_id"))
        object.__setattr__(
            self,
            "session_id",
            _canonical_uuid(self.session_id, field_name="session_id"),
        )
        if self.user_id <= 0:
            raise ValueError("user_id must be positive")
        if self.attempt_count < 0 or self.lease_epoch < 0:
            raise ValueError("attempt_count and lease_epoch must be non-negative")
        for name in ("worker_id", "input_identity"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{name} must be a non-blank string")
        if self.input_snapshot_digest is not None and (
            not self.input_snapshot_digest
            or self.input_snapshot_digest != self.input_snapshot_digest.strip()
        ):
            raise ValueError("input_snapshot_digest must be blank or a trimmed string")

    def to_mcp_context(
        self,
        *,
        invocation_id: str,
        key_id: str = "deep-agent-runtime",
        ttl_seconds: int = 900,
        now: datetime | None = None,
    ) -> McpInvocationContext:
        """把可信身份投影为内部 MCP executor 使用的短时上下文。"""

        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        issued_at = now or datetime.now(timezone.utc)
        if issued_at.tzinfo is None or issued_at.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        digest = self.input_snapshot_digest or self.input_identity
        return McpInvocationContext(
            invocation_id=invocation_id,
            job_id=self.job_id,
            session_id=self.session_id,
            user_id=self.user_id,
            attempt_count=self.attempt_count,
            lease_epoch=self.lease_epoch,
            worker_id=self.worker_id,
            input_snapshot_digest=digest,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(seconds=ttl_seconds),
            key_id=key_id,
        )


@dataclass(frozen=True)
class AgentRunContext:
    """一次 Deep Agent 调用的只读依赖集合。

    这些字段故意使用协议/对象类型而不使用可序列化 State 类型。调用方应在
    worker claim 后创建它，并在 graph invocation 结束时释放连接与 semaphore。
    """

    execution_guard: Any | None
    trusted_identity: TrustedJobIdentity
    algorithm_executor: Any
    rag_executor: Any | None = None
    web_executor: Any | None = None
    filesystem_backend: Any | None = None
    web_search_enabled: bool = False

    async def ensure_active(self) -> None:
        """在跨边界调用前复用已有 JobExecutionGuard 的资格检查。"""

        guard = self.execution_guard
        if guard is None:
            return
        ensure_active = getattr(guard, "ensure_active", None)
        if ensure_active is None:
            return
        result = ensure_active()
        if inspect.isawaitable(result):
            await result

    def assert_state_safe(self, state: object) -> None:
        """拒绝把本 runtime context 直接放入 State。"""

        if state is self or state is self.algorithm_executor:
            raise TypeError("runtime context objects must not enter graph state")
        if isinstance(state, dict):
            forbidden = {
                "execution_guard",
                "algorithm_executor",
                "rag_executor",
                "web_executor",
                "filesystem_backend",
                "trusted_identity",
            }
            leaked = forbidden.intersection(state)
            if leaked:
                raise TypeError(
                    "runtime-only fields must not enter graph state: "
                    + ", ".join(sorted(leaked))
                )

