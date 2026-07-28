"""多模态暂存 Chroma 索引与 active pointer。"""

from __future__ import annotations

import hashlib
import json
import gc
from pathlib import Path
from collections.abc import Iterable
from typing import Any

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from .defaults import resolve_production_embedding_config

from .contracts import KnowledgeUnit, canonical_json


def embedding_fingerprint() -> dict[str, Any]:
    """从现有 provider resolver 派生且不暴露密钥的嵌入指纹。"""
    config = resolve_production_embedding_config()
    return {
        "provider": config["provider"],
        "model": config["model"],
        "mode": config["mode"],
        "dimension": config.get("dimension"),
        "normalized": config["normalized"],
    }


def _embeddings() -> Any:
    """复用现有项目 embedding 配置创建 Chroma 所需函数。"""
    config = resolve_production_embedding_config()
    if config["status"] != "ready":
        raise RuntimeError(config["message"])
    return HuggingFaceEmbeddings(model_name=config["path"], model_kwargs={"device": "cpu"}, encode_kwargs={"normalize_embeddings": True})


class StagedIndex:
    """只向版本专属目录写入的 Chroma 索引。"""

    def __init__(self, version_dir: Path, collection_name: str, *, directory_name: str = "chroma") -> None:
        """绑定唯一版本目录和 collection 名称。"""
        self.version_dir = version_dir
        self.collection_name = collection_name
        self.directory_name = directory_name

    def write(self, units: Iterable[KnowledgeUnit], *, batch_size: int = 64) -> int:
        """写入一个此前不存在的版本，拒绝追加到已有 Chroma 数据。"""
        chroma_dir = self.version_dir / self.directory_name
        if chroma_dir.exists() and any(chroma_dir.iterdir()):
            raise ValueError("staged index is immutable and cannot be appended")
        db = Chroma(persist_directory=str(chroma_dir), collection_name=self.collection_name, embedding_function=_embeddings())
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
        db = Chroma(persist_directory=str(self.version_dir / self.directory_name), collection_name=self.collection_name)
        try:
            return db._collection.count()
        finally:
            self._close(db)

    @staticmethod
    def _close(db: Any) -> None:
        """Release the PersistentClient before Windows renames its directory."""
        client = getattr(db, "_client", None)
        close = getattr(client, "close", None)
        if callable(close):
            close()
        del db
        gc.collect()


class ActiveIndexRegistry:
    """以原子文件替换维护多模态 active index，不影响现有 RAG 配置。"""

    def __init__(self, path: Path) -> None:
        """初始化独立于 PubMedQA 的 active pointer 文件位置。"""
        self.path = path

    def read(self) -> dict[str, Any] | None:
        """读取当前 pointer；不存在时表示尚未发布。"""
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def publish(self, *, index_root: Path, index_version: str, collection_name: str, manifest_sha256: str, embedding: dict[str, Any]) -> None:
        """原子更新仅含相对路径和验证信息的 active pointer。"""
        payload = {
            "index_version": index_version,
            "index_path": f"{index_version}/chroma",
            "collection_name": collection_name,
            "manifest_sha256": manifest_sha256,
            "embedding": embedding,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)


def file_sha256(path: Path) -> str:
    """计算持久化 manifest 的内容哈希。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()
