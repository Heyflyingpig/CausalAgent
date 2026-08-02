from __future__ import annotations

from Agent.causal_agent.state import CausalAgentState


def bind_node(func, **bound_kwargs):
    """将共享资源绑定到异步LangGraph节点，同时不隐藏其协程特性。"""
    async def _node(state: CausalAgentState):
        return await func(state, **bound_kwargs)

    _node.__name__ = getattr(func, "__name__", "bound_node")
    return _node
