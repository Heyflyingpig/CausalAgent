from pathlib import Path


def test_agent_router_uses_the_shared_structured_output_adapter():
    """路由节点与其他后处理调用共享同一个结构化输出配置入口。"""
    text = Path("Agent/causal_agent/nodes.py").read_text(encoding="utf-8")

    assert "with_compatible_structured_output(llm, RouteQuery)" in text
    assert 'response_format={"type": "json_object"}' not in text


def test_shared_adapter_forwards_the_configured_method():
    """兼容层必须把全局选择的方法传给 LangChain。"""
    text = Path("Agent/llm_structured_output.py").read_text(encoding="utf-8")

    assert "llm.with_structured_output(" in text
    assert "method=settings.LLM_STRUCTURED_OUTPUT_METHOD" in text
