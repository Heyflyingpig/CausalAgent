"""单次 Job invocation 的合作式执行撤销守卫。"""

from __future__ import annotations

import contextvars
import asyncio
from dataclasses import dataclass

from app.agent import job_service


class JobExecutionRevoked(RuntimeError):
    """表示当前 worker 已失去继续推进 Job 的资格。"""


class ExecutionAuthorityUnknown(JobExecutionRevoked):
    """表示无法从 MySQL 主库确认执行资格，必须停止本次推进。"""


_current_guard: contextvars.ContextVar["JobExecutionGuard | None"] = contextvars.ContextVar(
    "current_job_execution_guard",
    default=None,
)


def current_execution_guard() -> "JobExecutionGuard | None":
    """返回当前 LangGraph invocation 的守卫。"""
    return _current_guard.get()


def raise_if_execution_revoked(exc: BaseException | None = None) -> None:
    """在 retry/error handler 边界重新抛出撤销控制流。"""
    if isinstance(exc, JobExecutionRevoked):
        raise exc
    guard = current_execution_guard()
    if guard is not None and guard.revoked:
        raise JobExecutionRevoked("Job execution revoked")


@dataclass
class JobExecutionGuard:
    """不进入 State/checkpoint 的 invocation 级 worker 执行资格。"""

    job_id: str
    worker_id: str
    attempt_count: int
    lease_epoch: int
    revoked: bool = False
    authority_unknown: bool = False
    last_status: str | None = None
    last_execution_state: str | None = None

    def install(self):
        """把守卫放入当前异步上下文，供子图和错误处理路径读取。"""
        return _current_guard.set(self)

    @staticmethod
    def reset(token: contextvars.Token) -> None:
        """恢复调用前的异步上下文。"""
        _current_guard.reset(token)

    def mark_revoked(
        self,
        *,
        status: str | None = None,
        execution_state: str | None = None,
    ) -> None:
        """标记后续所有节点和持久化均不得继续。"""
        self.revoked = True
        if status is not None:
            self.last_status = str(status)
        if execution_state is not None:
            self.last_execution_state = str(execution_state)

    async def ensure_active(self) -> None:
        """在节点开始前从 MySQL 主库确认当前租约仍有效。"""
        if self.revoked:
            raise JobExecutionRevoked("Job execution revoked")
        try:
            authority = await asyncio.to_thread(
                job_service.get_execution_authority,
                self.job_id,
                self.worker_id,
                self.attempt_count,
                self.lease_epoch,
            )
        except Exception as exc:  # 数据库资格未知时不能默认继续
            self.authority_unknown = True
            self.revoked = True
            raise ExecutionAuthorityUnknown("execution authority unknown") from exc
        self.last_status = str(authority.get("status") or "unknown")
        self.last_execution_state = str(authority.get("execution_state") or "unknown")
        if not authority.get("active"):
            self.revoked = True
            raise JobExecutionRevoked("Job execution revoked")

    async def check_after_call(self) -> None:
        """在 LLM/RAG/MCP/解析等调用返回后再次确认资格。"""
        await self.ensure_active()
