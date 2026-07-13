import importlib
from pathlib import Path

import pytest


def _new_settings(monkeypatch, method):
    """构造只依赖测试环境变量的全新配置实例。"""
    for key, value in {
        "SECRET_KEY": "test-secret",
        "API_KEY": "test-api-key",
        "BASE_URL": "https://example.test",
        "MODEL": "test-model",
        "MYSQL_HOST": "mysql",
        "MYSQL_USER": "app",
        "MYSQL_PASSWORD": "password",
        "MYSQL_DATABASE": "causalchat",
    }.items():
        monkeypatch.setenv(key, value)
    if method is None:
        monkeypatch.delenv("LLM_STRUCTURED_OUTPUT_METHOD", raising=False)
    else:
        monkeypatch.setenv("LLM_STRUCTURED_OUTPUT_METHOD", method)
    settings_module = importlib.import_module("config.settings")
    return importlib.reload(settings_module).AppConfig()


def test_structured_output_method_defaults_and_rejects_unknown_value(monkeypatch):
    """结构化输出方式默认使用 json_mode，并拒绝未知值。"""
    settings = _new_settings(monkeypatch, None)
    assert settings.LLM_STRUCTURED_OUTPUT_METHOD == "json_mode"

    with pytest.raises(ValueError, match="LLM_STRUCTURED_OUTPUT_METHOD"):
        _new_settings(monkeypatch, "invalid")


def test_compose_files_forward_only_structured_output_and_legacy_langchain_config():
    """运行 LLM 的服务只新增结构化输出透传，不夹带 LANGSMITH 新变量。"""
    expected_counts = {
        "docker-compose.yml": 2,
        "docker-compose.replica.yml": 2,
        "docker-compose.prod.yml": 1,
    }
    expression = "LLM_STRUCTURED_OUTPUT_METHOD=${LLM_STRUCTURED_OUTPUT_METHOD:-json_mode}"
    forbidden = (
        "LANGSMITH_TRACING=${",
        "LANGSMITH_API_KEY=${",
        "LANGSMITH_PROJECT=${",
        "LANGSMITH_ENDPOINT=${",
    )

    for compose_file, expected_count in expected_counts.items():
        text = Path(compose_file).read_text(encoding="utf-8")
        assert text.count(expression) == expected_count
        assert "LANGCHAIN_API_KEY=${LANGCHAIN_API_KEY:-}" in text
        assert "LANGCHAIN_PROJECT=${LANGCHAIN_PROJECT:-}" in text
        assert not any(item in text for item in forbidden)


def test_readme_does_not_advertise_unimplemented_langsmith_switches():
    """README 不把本次修复无关的 LANGSMITH 变量描述成有效配置。"""
    text = Path("README.md").read_text(encoding="utf-8")

    assert "LLM_STRUCTURED_OUTPUT_METHOD=json_mode" in text
    assert "LANGCHAIN_API_KEY=" in text
    assert "LANGCHAIN_PROJECT=" in text
    for key in (
        "LANGSMITH_TRACING=",
        "LANGSMITH_API_KEY=",
        "LANGSMITH_PROJECT=",
        "LANGSMITH_ENDPOINT=",
    ):
        assert key not in text
