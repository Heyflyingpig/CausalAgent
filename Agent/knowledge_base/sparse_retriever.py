"""进程级只读 sparse 检索资源。"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Protocol, Tuple

LOGGER = logging.getLogger(__name__)
BM25_K1 = 1.5
BM25_B = 0.75
LEGACY_RAW_SCORE_SCALE = BM25_K1 + 1.0


class SparseRetriever(Protocol):
    """RAG Runtime 使用的最小 sparse 检索接口。"""

    def search(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """返回按 BM25 分数降序排列的新候选对象。"""


def tokenize_text(text: str) -> List[str]:
    """按旧查询链规则切分中英文 token，并最多保留 512 个 token。"""
    text = text.lower()
    segments = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9_]+", text)
    tokens: List[str] = []
    for segment in segments:
        if re.fullmatch(r"[\u4e00-\u9fff]+", segment):
            tokens.extend(list(segment))
            if len(segment) >= 2:
                tokens.extend(segment[index : index + 2] for index in range(len(segment) - 1))
        else:
            tokens.extend(part for part in segment.split("_") if part)
    return tokens[:512]


def normalize_scores(
    candidates: List[Dict[str, Any]],
    score_key: str,
    normalized_key: str,
) -> None:
    """原地写入 min-max 归一化分数，保持旧检索链行为。"""
    scores = [float(candidate.get(score_key, 0.0)) for candidate in candidates]
    if not scores:
        return

    min_score = min(scores)
    max_score = max(scores)
    if max_score == min_score:
        default_value = 1.0 if max_score > 0 else 0.0
        for candidate in candidates:
            candidate[normalized_key] = default_value
        return

    for candidate in candidates:
        candidate[normalized_key] = (
            float(candidate.get(score_key, 0.0)) - min_score
        ) / (max_score - min_score)


@dataclass(frozen=True)
class _SparseDocument:
    """Runtime 内部持有的不可替换文档与 metadata。"""

    page_content: str
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class Bm25sSparseRetriever:
    """从 Chroma 一次构建、随后只读共享的 BM25s 检索器。"""

    entries: Tuple[_SparseDocument, ...]
    _index: Any

    @classmethod
    def from_vector_db(cls, vector_db: Any) -> "Bm25sSparseRetriever":
        """一次读取完整 Chroma collection 并构建 BM25s 内存索引。"""
        import bm25s

        from Agent.knowledge_base.query_rag import _normalize_chunk_metadata

        started = time.perf_counter()
        raw = vector_db.get(include=["documents", "metadatas"])
        documents = raw.get("documents", [])
        metadatas = raw.get("metadatas", [])
        ids = raw.get("ids", [])
        entries: List[_SparseDocument] = []
        corpus_tokens: List[List[str]] = []

        for index, page_content in enumerate(documents):
            metadata = _normalize_chunk_metadata(
                metadatas[index] if index < len(metadatas) else {},
                page_content,
                fallback_index=index,
            )
            metadata["vector_id"] = ids[index] if index < len(ids) else None
            corpus_tokens.append(tokenize_text(page_content))
            entries.append(
                _SparseDocument(
                    page_content=page_content,
                    metadata=MappingProxyType(dict(metadata)),
                )
            )

        bm25_index = bm25s.BM25(
            k1=BM25_K1,
            b=BM25_B,
            method="lucene",
            dtype="float64",
            backend="numpy",
            csc_backend="numpy",
        )
        bm25_index.index(
            corpus_tokens,
            create_empty_token=True,
            show_progress=False,
            leave_progress=False,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        LOGGER.info(
            "BM25s 索引构建完成 version=%s documents=%s vocabulary=%s backend=%s elapsed_ms=%s",
            bm25s.__version__,
            len(entries),
            len(bm25_index.vocab_dict),
            bm25_index.backend,
            elapsed_ms,
        )
        return cls(entries=tuple(entries), _index=bm25_index)

    @property
    def size(self) -> int:
        """返回 BM25s 索引对应的文档数量。"""
        return len(self.entries)

    def search(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """查询 BM25s 索引并返回全新的候选、metadata 和来源集合。"""
        query_tokens = tokenize_text(query)
        if not query_tokens or not self.entries or top_k <= 0:
            return []

        document_indices, scores = self._index.retrieve(
            [query_tokens],
            k=min(top_k, self.size),
            sorted=True,
            show_progress=False,
            leave_progress=False,
            n_threads=0,
            backend_selection="numpy",
        )
        scored_candidates: List[Dict[str, Any]] = []
        for document_index, raw_score in zip(document_indices[0], scores[0]):
            # BM25s Lucene 省略不影响排序的 (k1 + 1)，这里恢复旧接口的原始分数尺度。
            score = float(raw_score) * LEGACY_RAW_SCORE_SCALE
            if score <= 0:
                continue
            sparse_document = self.entries[int(document_index)]
            scored_candidates.append(
                {
                    "page_content": sparse_document.page_content,
                    "metadata": dict(sparse_document.metadata),
                    "dense_score": 0.0,
                    "sparse_score": score,
                    "retrieval_sources": {"sparse"},
                }
            )

        normalize_scores(scored_candidates, "sparse_score", "sparse_score_norm")
        return scored_candidates
