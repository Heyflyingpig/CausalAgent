from pathlib import Path

def test_legacy_structured_output_switch_is_absent_from_config_docs_and_tests():
    """旧结构化模式开关不再构成配置、部署、文档或测试契约。"""
    legacy_key = "LLM_" + "STRUCTURED_OUTPUT_" + "METHOD"
    files = [
        Path("config/settings.py"),
        Path("docker-compose.yml"),
        Path("docker-compose.replica.yml"),
        Path("docker-compose.prod.yml"),
        Path("README.md"),
        *Path("README").glob("*.md"),
        *Path("tests").glob("test_*.py"),
    ]

    for path in files:
        assert legacy_key not in path.read_text(encoding="utf-8"), path


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
