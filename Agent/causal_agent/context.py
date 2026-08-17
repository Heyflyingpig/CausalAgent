"""父图与子图共用的 invocation 级运行上下文。"""

from __future__ import annotations

from dataclasses import dataclass

from app.agent.worker.execution_guard import JobExecutionGuard


@dataclass(frozen=True)
class AgentRunContext:
    """不进入 State/checkpoint 的 invocation 级依赖，经 LangGraph runtime.context 传递。"""

    execution_guard: JobExecutionGuard | None
    web_search_enabled: bool = False
