from pathlib import Path



def test_compose_files_keep_legacy_langchain_config_without_mode_switch():
    """Compose 保留既有 LangChain 观测配置，但不再透传结构化模式。"""
    forbidden = (
        "LANGSMITH_TRACING=${",
        "LANGSMITH_API_KEY=${",
        "LANGSMITH_PROJECT=${",
        "LANGSMITH_ENDPOINT=${",
    )

    for compose_file in (
        "docker-compose.yml",
        "docker-compose.replica.yml",
        "docker-compose.prod.yml",
    ):
        text = Path(compose_file).read_text(encoding="utf-8")
        assert "LANGCHAIN_API_KEY=${LANGCHAIN_API_KEY:-}" in text
        assert "LANGCHAIN_PROJECT=${LANGCHAIN_PROJECT:-}" in text
        assert not any(item in text for item in forbidden)


def test_readme_does_not_advertise_unimplemented_langsmith_switches():
    """README 不把本次修复无关的 LANGSMITH 变量描述成有效配置。"""
    text = Path("README.md").read_text(encoding="utf-8")

    assert "DeepSeek/OpenAI 兼容的普通 Tool Calls" in text
    assert "Pydantic 结构化输出" in text
    assert "MCP" in text
    assert "LANGCHAIN_API_KEY=" in text
    assert "LANGCHAIN_PROJECT=" in text
    for key in (
        "LANGSMITH_TRACING=",
        "LANGSMITH_API_KEY=",
        "LANGSMITH_PROJECT=",
        "LANGSMITH_ENDPOINT=",
    ):
        assert key not in text
