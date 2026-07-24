"""进程级只读 sparse 检索资源。"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Protocol, Tuple


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


def bm25_score(
    query_tokens: List[str],
    entry: Mapping[str, Any],
    doc_freq: Mapping[str, int],
    corpus_size: int,
    avg_length: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    """使用旧查询链参数计算单个文档的 BM25 分数。"""
    if not query_tokens or corpus_size == 0:
        return 0.0

    score = 0.0
    length = entry["length"]
    for token in query_tokens:
        freq = entry["term_freq"].get(token, 0)
        if not freq:
            continue
        df = doc_freq.get(token, 0)
        idf = math.log(1 + (corpus_size - df + 0.5) / (df + 0.5))
        denominator = freq + k1 * (1 - b + b * length / avg_length)
        score += idf * (freq * (k1 + 1) / denominator)
    return score


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
class _SparseEntry:
    """Runtime 内部持有的不可替换语料条目。"""

    page_content: str
    metadata: Mapping[str, Any]
    term_freq: Mapping[str, int]
    length: int


@dataclass(frozen=True)
class InMemoryBm25Retriever:
    """从 Chroma 一次构建、随后只读共享的 BM25 检索器。"""

    entries: Tuple[_SparseEntry, ...]
    doc_freq: Mapping[str, int]
    avg_length: float

    @classmethod
    def from_vector_db(cls, vector_db: Any) -> "InMemoryBm25Retriever":
        """一次读取完整 Chroma collection 并构建 sparse corpus。"""
        from Agent.knowledge_base.query_rag import _normalize_chunk_metadata

        raw = vector_db.get(include=["documents", "metadatas"])
        documents = raw.get("documents", [])
        metadatas = raw.get("metadatas", [])
        ids = raw.get("ids", [])
        entries: List[_SparseEntry] = []
        doc_freq: Counter = Counter()
        total_length = 0

        for index, page_content in enumerate(documents):
            metadata = _normalize_chunk_metadata(
                metadatas[index] if index < len(metadatas) else {},
                page_content,
                fallback_index=index,
            )
            metadata["vector_id"] = ids[index] if index < len(ids) else None
            tokens = tokenize_text(page_content)
            term_freq = Counter(tokens)
            total_length += len(tokens)
            for token in term_freq:
                doc_freq[token] += 1
            entries.append(
                _SparseEntry(
                    page_content=page_content,
                    metadata=MappingProxyType(dict(metadata)),
                    term_freq=MappingProxyType(dict(term_freq)),
                    length=max(len(tokens), 1),
                )
            )

        avg_length = total_length / len(entries) if entries else 1.0
        return cls(
            entries=tuple(entries),
            doc_freq=MappingProxyType(dict(doc_freq)),
            avg_length=avg_length,
        )

    @property
    def size(self) -> int:
        """返回 sparse corpus 条目数量。"""
        return len(self.entries)

    def search(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """检索并返回全新的候选、metadata 和来源集合。"""
        query_tokens = tokenize_text(query)
        if not query_tokens or not self.entries:
            return []

        scored_candidates: List[Dict[str, Any]] = []
        for sparse_entry in self.entries:
            entry = {
                "term_freq": sparse_entry.term_freq,
                "length": sparse_entry.length,
            }
            score = bm25_score(
                query_tokens=query_tokens,
                entry=entry,
                doc_freq=self.doc_freq,
                corpus_size=self.size,
                avg_length=self.avg_length,
            )
            if score <= 0:
                continue
            scored_candidates.append(
                {
                    "page_content": sparse_entry.page_content,
                    "metadata": dict(sparse_entry.metadata),
                    "dense_score": 0.0,
                    "sparse_score": float(score),
                    "retrieval_sources": {"sparse"},
                }
            )

        scored_candidates.sort(key=lambda item: item["sparse_score"], reverse=True)
        selected = scored_candidates[:top_k]
        normalize_scores(selected, "sparse_score", "sparse_score_norm")
        return selected
