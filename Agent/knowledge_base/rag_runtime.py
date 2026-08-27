"""生产 RAG 的进程级显式资源生命周期。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from Agent.knowledge_base.multimodal.defaults import resolve_production_embedding_config as resolve_embedding_runtime_config
from Agent.knowledge_base.multimodal.production import is_production_manifest
from Agent.knowledge_base.sparse_retriever import Bm25sSparseRetriever, SparseRetriever
from observability.logging_runtime import log_event


BASE_DIR = Path(__file__).resolve().parent
LOGGER = logging.getLogger(__name__)
DEFAULT_VECTOR_DB_DIR = BASE_DIR / "db"
DEFAULT_MULTIMODAL_INDEX_ROOT = BASE_DIR / "multimodal_indexes"
DEFAULT_MULTIMODAL_ACTIVE_INDEX_CONFIG = BASE_DIR / "multimodal_runtime" / "active_index.json"
DEFAULT_PRODUCTION_CONFIG_PATH = BASE_DIR / "rag" / "runtime" / "production_rag_config.json"
SAFE_EMBEDDING_CONFIG_KEYS = {
    "status",
    "mode",
    "provider",
    "provider_setting",
    "model",
    "dimension",
    "normalized",
    "path",
    "path_exists",
    "api_key_env",
    "base_url_env",
    "model_env",
    "missing",
    "message",
}
_LOCAL_EMBEDDING_INIT_LOCK = threading.Lock()


@dataclass(frozen=True)
class RagRuntimeConfig:
    """RAG Runtime 的不可变、无密钥配置快照。"""

    vector_db_dir: str
    collection_name: str
    production_config_path: str
    embedding_config: Mapping[str, Any]
    release_id: str = "current"

    def __post_init__(self) -> None:
        """冻结调用方传入的 embedding 配置副本，避免嵌套对象被修改。"""
        safe_config = {
            key: value
            for key, value in self.embedding_config.items()
            if key in SAFE_EMBEDDING_CONFIG_KEYS
        }
        if "missing" in safe_config:
            safe_config["missing"] = tuple(safe_config["missing"])
        object.__setattr__(self, "embedding_config", MappingProxyType(safe_config))

    @classmethod
    def from_environment(cls) -> "RagRuntimeConfig":
        """从已发布的多模态 active index 创建配置，不读取或保存密钥值。"""
        resolved = resolve_embedding_runtime_config()
        safe_embedding_config = {
            key: resolved[key] for key in SAFE_EMBEDDING_CONFIG_KEYS if key in resolved
        }
        if "missing" in safe_embedding_config:
            safe_embedding_config["missing"] = tuple(safe_embedding_config["missing"])
        release = _resolve_multimodal_release(resolved)
        return cls(
            vector_db_dir=str(release["vector_db_dir"]),
            collection_name=str(release["collection_name"]),
            production_config_path=os.environ.get(
                "RAG_PRODUCTION_CONFIG_PATH",
                str(DEFAULT_PRODUCTION_CONFIG_PATH),
            ),
            embedding_config=MappingProxyType(safe_embedding_config),
            release_id=str(release["index_version"]),
        )


def _resolve_multimodal_release(embedding_config: Mapping[str, Any]) -> dict[str, Any]:
    """校验 active pointer、manifest 和 embedding 指纹并解析索引位置。"""
    active_path = Path(
        os.environ.get("MULTIMODAL_ACTIVE_INDEX_CONFIG", str(DEFAULT_MULTIMODAL_ACTIVE_INDEX_CONFIG))
    )
    if not active_path.is_file():
        raise FileNotFoundError(f"多模态 active pointer 不存在: {active_path}")
    active = json.loads(active_path.read_text(encoding="utf-8"))

    index_root = Path(
        os.environ.get("MULTIMODAL_INDEX_ROOT", str(DEFAULT_MULTIMODAL_INDEX_ROOT))
    ).resolve()
    index_path = Path(str(active.get("index_path", "")))
    if not index_path.parts or index_path.is_absolute():
        raise ValueError("多模态 active index_path 必须是相对路径")
    vector_db_dir = (index_root / index_path).resolve()
    try:
        vector_db_dir.relative_to(index_root)
    except ValueError as exc:
        raise ValueError("多模态 active index_path 越界") from exc

    manifest_path = vector_db_dir.parent / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"多模态 manifest 不存在: {manifest_path}")
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if manifest_hash != active.get("manifest_sha256"):
        raise ValueError("多模态 active index manifest 哈希不匹配")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if os.environ.get("MULTIMODAL_ALLOW_NON_PRODUCTION_ACTIVE", "").lower() != "true" and not is_production_manifest(manifest):
        raise ValueError("多模态 active index 不是冻结的正式知识源")
    runtime_fingerprint = {
        "provider": embedding_config.get("provider"),
        "model": embedding_config.get("model"),
        "mode": embedding_config.get("mode"),
        "normalized": embedding_config.get("normalized", embedding_config.get("mode") == "local"),
    }
    if "dimension" in embedding_config:
        runtime_fingerprint["dimension"] = embedding_config["dimension"]
    if active.get("embedding") != manifest.get("embedding") or manifest.get("embedding") != runtime_fingerprint:
        raise ValueError("多模态 embedding 指纹不匹配")
    if manifest.get("index_version") != active.get("index_version"):
        raise ValueError("多模态 index version 不匹配")
    collection_name = str(active.get("collection_name", "")).strip()
    if not collection_name:
        raise ValueError("多模态 active collection_name 为空")
    return {
        "vector_db_dir": vector_db_dir,
        "collection_name": collection_name,
        "index_version": active["index_version"],
    }


@dataclass(frozen=True)
class RagRuntime:
    """持有 worker 进程内共享的全部 RAG 重资源。"""

    config: RagRuntimeConfig
    embedding: Any
    vector_db: Any
    sparse_retriever: SparseRetriever
    answer_llm: Any
    chunk_count: int


class RagRuntimeInitializationError(RuntimeError):
    """标识严格 Runtime 初始化失败及其具体阶段。"""

    def __init__(self, stage: str, cause: BaseException):
        self.stage = stage
        self.cause = cause
        super().__init__(f"RAG Runtime 初始化失败，阶段={stage}: {cause}")


def _validate_vector_db_directory(config: RagRuntimeConfig) -> None:
    """确认向量库目录存在且确实是目录。"""
    path = Path(config.vector_db_dir)
    if not path.exists():
        raise FileNotFoundError(f"知识库持久化目录不存在: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"知识库持久化路径不是目录: {path}")


def _validate_embedding_config(config: RagRuntimeConfig) -> None:
    """在加载模型前验证脱敏后的 embedding 配置状态。"""
    embedding_config = config.embedding_config
    if embedding_config.get("status") != "ready":
        raise ValueError(str(embedding_config.get("message", "embedding 配置不可用")))


def _create_embedding_function(config: RagRuntimeConfig) -> Any:
    """按配置创建唯一的 embedding 实例。"""
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_openai import OpenAIEmbeddings

    embedding_config = config.embedding_config
    if embedding_config["mode"] == "api":
        api_key_env = str(embedding_config["api_key_env"])
        base_url_env = str(embedding_config["base_url_env"])
        return OpenAIEmbeddings(
            api_key=os.environ[api_key_env],
            base_url=os.environ[base_url_env],
            model=str(embedding_config["model"]),
            tiktoken_enabled=False,
            check_embedding_ctx_length=False,
        )
    return HuggingFaceEmbeddings(
        model_name=str(embedding_config["path"]),
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def _create_embedding_function_thread_safe(config: RagRuntimeConfig) -> Any:
    """串行化进程内本地模型构造，规避 Transformers/PyTorch 首次加载竞态。"""
    if config.embedding_config.get("mode") != "local":
        return _create_embedding_function(config)
    with _LOCAL_EMBEDDING_INIT_LOCK:
        return _create_embedding_function(config)


def _open_existing_vector_db(config: RagRuntimeConfig, embedding: Any) -> Any:
    """仅打开已存在的 Chroma collection，禁止缺失时自动创建。"""
    import chromadb
    from langchain_chroma import Chroma

    client = chromadb.PersistentClient(path=config.vector_db_dir)
    client.get_collection(name=config.collection_name)
    return Chroma(
        client=client,
        embedding_function=embedding,
        collection_name=config.collection_name,
        create_collection_if_not_exists=False,
    )


def _count_chunks(vector_db: Any) -> int:
    """读取 collection chunk 数并拒绝空知识库。"""
    chunk_count = int(vector_db._collection.count())
    if chunk_count <= 0:
        raise ValueError("RAG collection 为空")
    return chunk_count


def create_rag_runtime(config: RagRuntimeConfig, answer_llm: Any) -> RagRuntime:
    """按固定顺序严格创建完整 Runtime，失败时不返回半成品。"""
    started = time.perf_counter()
    stages = (
        ("vector_db_directory", lambda: _validate_vector_db_directory(config)),
        ("embedding_config", lambda: _validate_embedding_config(config)),
        ("embedding_instance", lambda: _create_embedding_function_thread_safe(config)),
    )
    embedding = None
    for stage, operation in stages:
        try:
            result = operation()
            if stage == "embedding_instance":
                embedding = result
        except Exception as exc:
            raise RagRuntimeInitializationError(stage, exc) from exc

    try:
        vector_db = _open_existing_vector_db(config, embedding)
    except Exception as exc:
        raise RagRuntimeInitializationError("chroma_collection", exc) from exc
    try:
        chunk_count = _count_chunks(vector_db)
    except Exception as exc:
        raise RagRuntimeInitializationError("chunk_count", exc) from exc
    try:
        sparse_retriever = Bm25sSparseRetriever.from_vector_db(vector_db)
    except Exception as exc:
        raise RagRuntimeInitializationError("sparse_corpus", exc) from exc

    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    embedding_config = config.embedding_config
    log_event(
        LOGGER,
        "rag.runtime.ready",
        details={
            "provider": str(embedding_config.get("provider", "unknown")),
            "model": str(embedding_config.get("model", "unknown")),
            "chunk_count": chunk_count,
            "elapsed_ms": elapsed_ms,
            "release_id": config.release_id,
        },
    )
    return RagRuntime(
        config=config,
        embedding=embedding,
        vector_db=vector_db,
        sparse_retriever=sparse_retriever,
        answer_llm=answer_llm,
        chunk_count=chunk_count,
    )
