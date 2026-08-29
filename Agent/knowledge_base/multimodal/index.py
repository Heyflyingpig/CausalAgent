"""多模态暂存 Chroma 索引与 active pointer。"""

from __future__ import annotations

import hashlib
import json
import gc
import time
from pathlib import Path
from collections.abc import Iterable
from typing import Any, Mapping

from langchain_chroma import Chroma
from Agent.knowledge_base.embedding_runtime import (
    EmbeddingConfiguration,
    create_embedding_function,
    resolve_production_embedding_configuration,
)
from .defaults import resolve_production_embedding_config

from .contracts import KnowledgeUnit
from .release import normalize_pointer, pointer_bytes


def replace_with_retry(temporary: Path, target: Path) -> None:
    """原子替换文件，并重试 Windows 短暂文件占用。"""
    for delay in (0.0, 0.05, 0.1, 0.2, 0.4):
        if delay:
            time.sleep(delay)
        try:
            temporary.replace(target)
            return
        except PermissionError:
            if delay == 0.4:
                raise


def embedding_fingerprint(config: Mapping[str, Any] | EmbeddingConfiguration | None = None) -> dict[str, Any]:
    """返回显式 embedding 配置的兼容短指纹。"""
    resolved = (
        EmbeddingConfiguration.from_mapping(resolve_production_embedding_config())
        if config is None
        else EmbeddingConfiguration.from_mapping(config)
    )
    return resolved.fingerprint()


def embedding_configuration_manifest(config: Mapping[str, Any] | EmbeddingConfiguration | None = None) -> dict[str, Any]:
    """返回可写入 release manifest 的完整 embedding 配置。"""
    resolved = (
        resolve_production_embedding_configuration()
        if config is None
        else EmbeddingConfiguration.from_mapping(config)
    )
    return resolved.to_manifest()


def _embeddings(
    config: Mapping[str, Any] | EmbeddingConfiguration | None = None,
    *,
    scope: str = "production",
) -> Any:
    """按显式配置创建 Chroma 所需函数。"""
    resolved = (
        resolve_production_embedding_configuration()
        if config is None
        else EmbeddingConfiguration.from_mapping(config)
    )
    return create_embedding_function(resolved, scope=scope)


class StagedIndex:
    """只向版本专属目录写入的 Chroma 索引。"""

    def __init__(
        self,
        version_dir: Path,
        collection_name: str,
        *,
        directory_name: str = "chroma",
        embedding_config: Mapping[str, Any] | EmbeddingConfiguration | None = None,
        embedding_scope: str = "production",
    ) -> None:
        """绑定唯一版本目录和 collection 名称。"""
        self.version_dir = version_dir
        self.collection_name = collection_name
        self.directory_name = directory_name
        self.embedding_config = embedding_config
        self.embedding_scope = embedding_scope

    def write(self, units: Iterable[KnowledgeUnit], *, batch_size: int = 20) -> int:
        """写入一个此前不存在的版本，拒绝追加到已有 Chroma 数据。"""
        chroma_dir = self.version_dir / self.directory_name
        if chroma_dir.exists() and any(chroma_dir.iterdir()):
            raise ValueError("staged index is immutable and cannot be appended")
        db = Chroma(
            persist_directory=str(chroma_dir),
            collection_name=self.collection_name,
            embedding_function=_embeddings(self.embedding_config, scope=self.embedding_scope),
        )
        try:
            batch: list[KnowledgeUnit] = []
            for unit in units:
                batch.append(unit)
                if len(batch) >= batch_size:
                    self._write_batch(db, batch)
                    batch.clear()
            if batch:
                self._write_batch(db, batch)
            return db._collection.count()
        finally:
            self._close(db)

    @staticmethod
    def _write_batch(db: Any, batch: list[KnowledgeUnit]) -> None:
        """把一批标准化单元写入 Chroma。"""
        db.add_texts(
            [unit.retrieval_text for unit in batch],
            metadatas=[unit.chroma_metadata() for unit in batch],
            ids=[unit.unit_id for unit in batch],
        )

    def count(self) -> int:
        """读取版本 collection 中的向量数量。"""
        db = Chroma(
            persist_directory=str(self.version_dir / self.directory_name),
            collection_name=self.collection_name,
            create_collection_if_not_exists=False,
        )
        try:
            return db._collection.count()
        finally:
            self._close(db)

    @staticmethod
    def _close(db: Any) -> None:
        """在 Windows 重命名索引目录前释放 PersistentClient，避免文件占用。"""
        client = getattr(db, "_client", None)
        close = getattr(client, "close", None)
        if callable(close):
            close()
        del db
        gc.collect()


class ActiveIndexRegistry:
    """以原子文件替换维护 active/previous pointer，并提供只读保留观测。"""

    def __init__(self, path: Path) -> None:
        """初始化独立于 PubMedQA 的 active pointer 文件位置。"""
        self.path = path

    @property
    def previous_path(self) -> Path:
        """返回与 active pointer 并列的 previous pointer 路径。"""
        return self.path.with_name("previous_index.json")

    def read(self) -> dict[str, Any] | None:
        """读取当前 pointer；不存在时表示尚未发布。"""
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def read_previous(self) -> dict[str, Any] | None:
        """读取上一个 active pointer；首次发布时不存在。"""
        current = self.read()
        if isinstance(current, dict) and isinstance(current.get("fallback"), dict):
            return dict(current["fallback"])
        if not self.previous_path.exists():
            return None
        return json.loads(self.previous_path.read_text(encoding="utf-8"))

    def read_release_pointer(self) -> dict[str, Any]:
        """读取新 pointer，并兼容旧 active/previous 双文件。"""
        previous = None
        if self.previous_path.is_file():
            previous = json.loads(self.previous_path.read_text(encoding="utf-8"))
        return normalize_pointer(self.read(), previous)

    def write_release_pointer(self, pointer: Mapping[str, Any]) -> None:
        """以新 schema 原子写入 active/fallback 单 pointer。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_bytes(pointer_bytes(pointer))
        replace_with_retry(temporary, self.path)

    def publish(self, *, index_root: Path, index_version: str, collection_name: str, manifest_sha256: str, embedding: dict[str, Any]) -> None:
        """兼容旧调用签名，但写入新的 active/fallback 单 pointer。"""
        del index_root, embedding
        current = self.read_release_pointer()
        current_active = current.get("active")
        active = {
            "release_id": index_version,
            "index_version": index_version,
            "index_path": f"{index_version}/chroma",
            "collection_name": collection_name,
            "manifest_sha256": manifest_sha256,
        }
        fallback = current.get("fallback") if current_active and current_active.get("release_id") == index_version else current_active
        self.write_release_pointer({
            "schema_version": "multimodal_release_pointer_v1",
            "generation": int(current.get("generation") or 0) + 1,
            "active": active,
            "fallback": fallback,
        })

    def retention_snapshot(self, index_root: Path) -> dict[str, Any]:
        """返回 active、previous 与候选版本摘要；此方法绝不删除目录。"""
        raw_active = self.read()
        is_new_pointer = isinstance(raw_active, dict) and "active" in raw_active and "fallback" in raw_active
        if is_new_pointer:
            pointer = self.read_release_pointer()
            active = pointer.get("active")
            previous = pointer.get("fallback")
        else:
            active = raw_active
            previous = self.read_previous()
        protected_versions = {
            pointer.get("index_version")
            for pointer in (active, previous)
            if isinstance(pointer, dict) and isinstance(pointer.get("index_version"), str)
        }
        candidates = sorted(
            child.name
            for child in index_root.iterdir()
            if child.is_dir()
            and child.name.startswith("mm_")
            and child.name != ".locks"
            and child.name not in protected_versions
        ) if index_root.is_dir() else []
        return {
            "policy": {
                "active_slots": 1,
                "previous_slots": 1,
                "candidate_slots": 1,
                "automatic_delete": False,
            },
            "active": active,
            "previous": previous,
            "fallback": previous,
            "generation": int(pointer.get("generation") or 0) if is_new_pointer else 0,
            "protected_versions": sorted(protected_versions),
            "candidates": candidates,
            "candidate_overflow": len(candidates) > 1,
        }

    @staticmethod
    def _write_atomic(payload: dict[str, Any], path: Path) -> None:
        """将 pointer 写入临时文件后原子替换目标。"""
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        replace_with_retry(temporary, path)


def file_sha256(path: Path) -> str:
    """计算持久化 manifest 的内容哈希。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()
