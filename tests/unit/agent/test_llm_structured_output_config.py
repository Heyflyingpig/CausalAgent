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
        "docker-compose.prod.yml",
    ):
        text = Path(compose_file).read_text(encoding="utf-8")
        assert "LANGCHAIN_API_KEY=${LANGCHAIN_API_KEY:-}" in text
        assert "LANGCHAIN_PROJECT=${LANGCHAIN_PROJECT:-}" in text
        assert not any(item in text for item in forbidden)
