"""
RAG embedding provider 解析层。

该模块只读取环境变量和本地路径，不加载模型、不调用 API，用于保证
知识库构建、正式查询和前端状态展示使用同一套 embedding provider 规则。
"""
import os
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LOCAL_EMBEDDING_MODEL_PATH = BASE_DIR / "models" / "bge-small-zh-v1.5"

PROVIDER_ENV = "RAG_EMBEDDING_PROVIDER"
LOCAL_MODEL_PATH_ENV = "RAG_LOCAL_EMBEDDING_MODEL_PATH"
API_KEY_ENV = "MEDICAL_EMBEDDING_API_KEY"
API_BASE_URL_ENV = "MEDICAL_EMBEDDING_BASE_URL"
API_MODEL_ENV = "MEDICAL_EMBEDDING_MODEL"
DEFAULT_API_MODEL = "text-embedding-3-small"

_API_PROVIDER_VALUES = {"api", "openai", "openai_compatible"}
_LOCAL_PROVIDER_VALUES = {"local", "huggingface"}


def resolve_embedding_runtime_config() -> Dict[str, Any]:
    """解析当前 embedding provider 配置，供构建、查询和 UI 状态共用。"""
    raw_provider = os.environ.get(PROVIDER_ENV, "auto").strip().lower() or "auto"
    provider = _resolve_provider(raw_provider)
    if provider == "api":
        return _api_embedding_config(raw_provider)
    return _local_embedding_config(raw_provider)


def _resolve_provider(raw_provider: str) -> str:
    """把环境变量 provider 解析成 api/local，auto 兼容旧行为。"""
    if raw_provider == "auto":
        if os.environ.get("KNOWLEDGE_BUILD_PROFILE") == "medical" or os.environ.get(API_KEY_ENV):
            return "api"
        return "local"
    if raw_provider in _API_PROVIDER_VALUES:
        return "api"
    if raw_provider in _LOCAL_PROVIDER_VALUES:
        return "local"
    raise ValueError(
        f"Unsupported {PROVIDER_ENV}={raw_provider!r}; expected auto, local, or openai_compatible."
    )


def _api_embedding_config(raw_provider: str) -> Dict[str, Any]:
    """返回 OpenAI-compatible embedding 配置摘要，不暴露密钥。"""
    api_key_configured = bool(os.environ.get(API_KEY_ENV))
    base_url = os.environ.get(API_BASE_URL_ENV, "")
    base_url_configured = bool(base_url)
    missing = []
    if not api_key_configured:
        missing.append(API_KEY_ENV)
    if not base_url_configured:
        missing.append(API_BASE_URL_ENV)
    return {
        "status": "ready" if not missing else "missing",
        "mode": "api",
        "provider": "openai_compatible",
        "provider_setting": raw_provider,
        "api_key_env": API_KEY_ENV,
        "base_url_env": API_BASE_URL_ENV,
        "model_env": API_MODEL_ENV,
        "api_key_configured": api_key_configured,
        "base_url_configured": base_url_configured,
        "base_url": base_url,
        "model": os.environ.get(API_MODEL_ENV, DEFAULT_API_MODEL),
        "missing": missing,
        "message": "配置完整" if not missing else "缺少 " + ", ".join(missing),
    }


def _local_embedding_config(raw_provider: str) -> Dict[str, Any]:
    """返回本地 HuggingFace embedding 配置摘要。"""
    model_path = Path(os.environ.get(LOCAL_MODEL_PATH_ENV, str(DEFAULT_LOCAL_EMBEDDING_MODEL_PATH)))
    path_exists = model_path.exists()
    return {
        "status": "ready" if path_exists else "missing",
        "mode": "local",
        "provider": "huggingface",
        "provider_setting": raw_provider,
        "model": model_path.name,
        "path": str(model_path.resolve()),
        "path_exists": path_exists,
        "missing": [] if path_exists else [LOCAL_MODEL_PATH_ENV],
        "message": "本地模型目录存在" if path_exists else "本地 embedding 模型目录不存在",
    }
