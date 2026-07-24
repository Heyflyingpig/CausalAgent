import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
import threading
import time
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import numpy as np
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from Agent.knowledge_base.sparse_retriever import (
    SparseRetriever,
    bm25_score,
    normalize_scores,
    tokenize_text,
)
from Agent.llm_structured_output import with_compatible_structured_output
from config.settings import settings

base_dir = os.path.dirname(os.path.abspath(__file__))
PERSIST_DIRECTORY = os.environ.get("RAG_VECTOR_DB_DIR", os.path.join(base_dir, "db"))
COLLECTION_NAME = os.environ.get("RAG_COLLECTION_NAME", "pubmedqa_clean")
PRODUCTION_RAG_CONFIG_PATH = os.environ.get(
    "RAG_PRODUCTION_CONFIG_PATH",
    os.path.join(base_dir, "rag", "runtime", "production_rag_config.json"),
)

DENSE_FETCH_K = 10
DENSE_MMR_K = 6
SPARSE_FETCH_K = 8
FINAL_TOP_K = 4
DENSE_SCORE_THRESHOLD = 0.45
FINAL_RERANK_THRESHOLD = 0.18
MMR_LAMBDA = 0.7
MAX_EVIDENCE_CHARS = 420


@dataclass(frozen=True)
class RagRetrievalConfig:
    """
    RAG 检索链路调参配置。

    评测脚本只应该通过这个对象覆盖检索参数，避免直接改 query_rag.py
    里的全局默认值。默认值保持线上/业务链路当前行为。
    """

    dense_fetch_k: int = DENSE_FETCH_K
    dense_mmr_k: int = DENSE_MMR_K
    sparse_fetch_k: int = SPARSE_FETCH_K
    final_top_k: int = FINAL_TOP_K
    dense_score_threshold: float = DENSE_SCORE_THRESHOLD
    final_rerank_threshold: float = FINAL_RERANK_THRESHOLD
    mmr_lambda: float = MMR_LAMBDA
    official_only_when_available: bool = True
    max_evidence_chars: int = MAX_EVIDENCE_CHARS

    def to_dict(self) -> Dict[str, Any]:
        """返回可写入评测报告的普通 dict。"""
        return asdict(self)


def get_production_rag_config_status() -> Dict[str, Any]:
    """返回正式 RAG 当前使用的检索配置来源和配置值。"""
    config, source = _load_production_rag_config()
    return {
        "source": source,
        "path": PRODUCTION_RAG_CONFIG_PATH,
        "config": config.to_dict(),
    }


def _load_production_rag_config() -> Tuple[RagRetrievalConfig, str]:
    """加载正式 RAG 检索配置；没有发布配置时保持代码默认值。"""
    return _load_rag_config(PRODUCTION_RAG_CONFIG_PATH)


def _load_rag_config(path: str) -> Tuple[RagRetrievalConfig, str]:
    """从指定路径加载检索配置，供生产 Service 每次问题动态调用。"""
    if not os.path.exists(path):
        return RagRetrievalConfig(), "code_default"
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return RagRetrievalConfig(), "invalid_config_fallback"

    raw_config = payload.get("retrieval_config") if isinstance(payload, dict) else None
    if not isinstance(raw_config, dict):
        return RagRetrievalConfig(), "invalid_config_fallback"
    allowed_fields = set(RagRetrievalConfig.__dataclass_fields__.keys())
    filtered = {key: value for key, value in raw_config.items() if key in allowed_fields}
    try:
        return RagRetrievalConfig(**filtered), "published_config"
    except (TypeError, ValueError):
        return RagRetrievalConfig(), "invalid_config_fallback"


class RagAnswer(BaseModel):
    """RAG生成阶段的结构化输出。"""

    answer: str = Field(..., description="仅基于证据生成的回答。")
    confidence: Literal["high", "medium", "low"] = Field(
        ...,
        description="当前回答对证据支撑强度的主观置信度。",
    )
    citations: List[str] = Field(
        default_factory=list,
        description="回答实际引用的证据ID，例如 ['E1', 'E2']。",
    )
    status: Literal["answered", "insufficient_evidence"] = Field(
        ...,
        description="是否成功基于证据回答问题。",
    )


_COMPATIBILITY_SERVICE = None
_COMPATIBILITY_SERVICE_LOCK = threading.Lock()


def _create_compatibility_service():
    """严格创建供评测、CLI 和遗留调用使用的独立 compatibility Service。"""
    from Agent.knowledge_base.rag_runtime import RagRuntimeConfig, create_rag_runtime
    from Agent.knowledge_base.rag_service import CompatibilityRagService

    def create_runtime():
        """在 compatibility Service 首次需要资源时创建严格 Runtime。"""
        answer_llm = ChatOpenAI(
            api_key=settings.API_KEY,
            base_url=settings.BASE_URL,
            model=settings.MODEL,
        )
        return create_rag_runtime(RagRuntimeConfig.from_environment(), answer_llm)

    return CompatibilityRagService(create_runtime)


def _get_compatibility_service():
    """延迟创建并复用唯一 compatibility Service。"""
    global _COMPATIBILITY_SERVICE
    if _COMPATIBILITY_SERVICE is None:
        with _COMPATIBILITY_SERVICE_LOCK:
            if _COMPATIBILITY_SERVICE is None:
                _COMPATIBILITY_SERVICE = _create_compatibility_service()
    return _COMPATIBILITY_SERVICE


def _get_llm() -> ChatOpenAI:
    """兼容入口：返回 compatibility Runtime 持有的回答 LLM。"""
    return _get_compatibility_service().runtime.answer_llm


def _get_embedding_function() -> Any:
    """兼容入口：返回 compatibility Runtime 持有的 embedding。"""
    return _get_compatibility_service().runtime.embedding


def _get_vector_db() -> Any:
    """兼容入口：返回 compatibility Runtime 持有的 Chroma。"""
    return _get_compatibility_service().runtime.vector_db


def get_vector_db_metadata_summary(limit: int = 10000) -> Dict[str, Any]:
    """兼容入口：通过 compatibility Service 汇总 metadata。"""
    return _get_compatibility_service().get_vector_db_metadata_summary(limit=limit)


def _slugify(value: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff]+", "_", value.strip().lower())
    return value.strip("_") or "unknown_doc"


def _safe_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

## 截取证据文本，减少污染
def _truncate_text(text: str, max_chars: int = MAX_EVIDENCE_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


## 保证知识库matedata完整
def _normalize_chunk_metadata(
    metadata: Optional[Dict[str, Any]],
    page_content: str,
    fallback_index: int = 0,
) -> Dict[str, Any]:
    normalized = dict(metadata or {})
    source = normalized.get("source") or normalized.get("file_path") or "unknown_source"
    source_name = os.path.basename(source) if os.path.isabs(source) else source
    title = normalized.get("title") or os.path.splitext(source_name)[0]
    page = _safe_int(normalized.get("page"))
    chunk_index = _safe_int(normalized.get("chunk_index"))
    if chunk_index is None:
        chunk_index = fallback_index

    doc_type = normalized.get("doc_type")
    if not doc_type:
        if source_name.lower().endswith(".pdf"):
            doc_type = "reference_pdf"
        elif source_name.lower().endswith(".txt"):
            doc_type = "note"
        else:
            doc_type = "text"

    corpus = normalized.get("corpus")
    if not corpus:
        corpus = "test" if "test" in source_name.lower() else "official"

    doc_id = normalized.get("doc_id") or _slugify(title or source_name)
    chunk_hash = hashlib.md5(page_content.encode("utf-8")).hexdigest()[:8]
    page_fragment = page if page is not None else "na"
    chunk_id = normalized.get("chunk_id") or f"{doc_id}#p{page_fragment}#c{chunk_index}_{chunk_hash}"

    normalized.update(
        {
            "source": source,
            "source_name": source_name,
            "title": title,
            "page": page,
            "doc_id": doc_id,
            "chunk_index": chunk_index,
            "chunk_id": chunk_id,
            "doc_type": doc_type,
            "corpus": corpus,
            "section": normalized.get("section", ""),
        }
    )
    return normalized


def _tokenize_text(text: str) -> List[str]:
    """兼容入口：使用独立 sparse 模块中的原 tokenizer。"""
    return tokenize_text(text)


def _get_sparse_corpus() -> Dict[str, Any]:
    """兼容入口：返回 Runtime sparse corpus 的隔离快照。"""
    retriever = _get_compatibility_service().runtime.sparse_retriever
    entries = [
        {
            "page_content": entry.page_content,
            "metadata": dict(entry.metadata),
            "term_freq": Counter(entry.term_freq),
            "length": entry.length,
        }
        for entry in getattr(retriever, "entries", ())
    ]
    return {
        "entries": entries,
        "doc_freq": Counter(getattr(retriever, "doc_freq", {})),
        "avg_length": getattr(retriever, "avg_length", 1.0),
        "size": getattr(retriever, "size", len(entries)),
    }


def _bm25_score(
    query_tokens: List[str],
    entry: Dict[str, Any],
    doc_freq: Counter,
    corpus_size: int,
    avg_length: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    """兼容入口：使用独立 sparse 模块中的原 BM25 公式。"""
    return bm25_score(query_tokens, entry, doc_freq, corpus_size, avg_length, k1=k1, b=b)


def _normalize_scores(candidates: List[Dict[str, Any]], score_key: str, normalized_key: str) -> None:
    """兼容入口：按旧规则归一化候选分数。"""
    normalize_scores(candidates, score_key, normalized_key)


def _dense_retrieve(
    question: str,
    fetch_k: int = DENSE_FETCH_K,
    score_threshold: float = DENSE_SCORE_THRESHOLD,
    *,
    vector_db: Any = None,
) -> List[Dict[str, Any]]:
    active_vector_db = vector_db if vector_db is not None else _get_vector_db()
    dense_results = active_vector_db.similarity_search_with_relevance_scores(question, k=fetch_k)
    candidates: List[Dict[str, Any]] = []

    for index, (doc, score) in enumerate(dense_results):
        if float(score) < score_threshold:
            continue
        metadata = _normalize_chunk_metadata(doc.metadata, doc.page_content, fallback_index=index)
        candidates.append(
            {
                "page_content": doc.page_content,
                "metadata": metadata,
                "dense_score": float(score),
                "sparse_score": 0.0,
                "retrieval_sources": {"dense"},
            }
        )

    _normalize_scores(candidates, "dense_score", "dense_score_norm")
    return candidates


def _select_mmr_candidates(
    question: str,
    candidates: List[Dict[str, Any]],
    top_k: int = DENSE_MMR_K,
    mmr_lambda: float = MMR_LAMBDA,
    embedding_function: Any = None,
    ) -> List[Dict[str, Any]]:
    
    if len(candidates) <= top_k:
        return candidates

    active_embedding = embedding_function if embedding_function is not None else _get_embedding_function()
    query_embedding = np.array(active_embedding.embed_query(question), dtype=np.float32)
    doc_embeddings = np.array(
        active_embedding.embed_documents([candidate["page_content"] for candidate in candidates]),
        dtype=np.float32,
    )

    query_scores = np.dot(doc_embeddings, query_embedding)
    selected_indices: List[int] = [int(np.argmax(query_scores))]
    remaining_indices = set(range(len(candidates))) - set(selected_indices)

    while remaining_indices and len(selected_indices) < top_k:
        best_index = None
        best_score = -float("inf")
        for candidate_index in remaining_indices:
            similarity_to_query = float(query_scores[candidate_index])
            similarity_to_selected = max(
                float(np.dot(doc_embeddings[candidate_index], doc_embeddings[selected_index]))
                for selected_index in selected_indices
            )
            mmr_score = mmr_lambda * similarity_to_query - (1 - mmr_lambda) * similarity_to_selected
            if mmr_score > best_score:
                best_score = mmr_score
                best_index = candidate_index

        if best_index is None:
            break
        selected_indices.append(best_index)
        remaining_indices.remove(best_index)

    return [candidates[index] for index in selected_indices]


def _sparse_retrieve(
    question: str,
    fetch_k: int = SPARSE_FETCH_K,
    *,
    sparse_retriever: Optional[SparseRetriever] = None,
) -> List[Dict[str, Any]]:
    """通过显式或 compatibility Runtime 的只读 sparse 检索器查询。"""
    active_retriever = (
        sparse_retriever
        if sparse_retriever is not None
        else _get_compatibility_service().runtime.sparse_retriever
    )
    return active_retriever.search(question, fetch_k)


def _merge_candidates(
    dense_candidates: List[Dict[str, Any]],
    sparse_candidates: List[Dict[str, Any]],
    final_top_k: int = FINAL_TOP_K,
    final_rerank_threshold: float = FINAL_RERANK_THRESHOLD,
    official_only_when_available: bool = True,
    return_before_final: bool = False,
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for candidate in dense_candidates + sparse_candidates:
        key = candidate["metadata"]["chunk_id"]
        if key not in merged:
            merged[key] = {
                "page_content": candidate["page_content"],
                "metadata": candidate["metadata"],
                "dense_score": float(candidate.get("dense_score", 0.0)),
                "dense_score_norm": float(candidate.get("dense_score_norm", 0.0)),
                "sparse_score": float(candidate.get("sparse_score", 0.0)),
                "sparse_score_norm": float(candidate.get("sparse_score_norm", 0.0)),
                "retrieval_sources": set(candidate.get("retrieval_sources", set())),
            }
            continue

        merged_candidate = merged[key]
        merged_candidate["dense_score"] = max(merged_candidate["dense_score"], float(candidate.get("dense_score", 0.0)))
        merged_candidate["dense_score_norm"] = max(
            merged_candidate["dense_score_norm"],
            float(candidate.get("dense_score_norm", 0.0)),
        )
        merged_candidate["sparse_score"] = max(merged_candidate["sparse_score"], float(candidate.get("sparse_score", 0.0)))
        merged_candidate["sparse_score_norm"] = max(
            merged_candidate["sparse_score_norm"],
            float(candidate.get("sparse_score_norm", 0.0)),
        )
        merged_candidate["retrieval_sources"].update(candidate.get("retrieval_sources", set()))

    merged_candidates = list(merged.values())
    official_candidates = [
        candidate for candidate in merged_candidates if candidate["metadata"].get("corpus") == "official"
    ]
    if official_candidates and official_only_when_available:
        merged_candidates = official_candidates

    for candidate in merged_candidates:
        metadata_bonus = 1.0 if candidate["metadata"].get("corpus") == "official" else 0.0
        hybrid_bonus = 0.1 if len(candidate["retrieval_sources"]) > 1 else 0.0
        candidate["rerank_score"] = (
            0.55 * candidate["dense_score_norm"]
            + 0.25 * candidate["sparse_score_norm"]
            + 0.1 * metadata_bonus
            + hybrid_bonus
        )
        candidate["retrieval_source"] = "+".join(sorted(candidate["retrieval_sources"]))

    merged_candidates.sort(key=lambda item: item["rerank_score"], reverse=True)
    if return_before_final:
        return merged_candidates

    filtered = [candidate for candidate in merged_candidates if candidate["rerank_score"] >= final_rerank_threshold]
    if filtered:
        return filtered[:final_top_k]
    return merged_candidates[: min(final_top_k, len(merged_candidates))]


def _build_evidence_payloads(
    candidates: List[Dict[str, Any]],
    max_chars: int = MAX_EVIDENCE_CHARS,
) -> List[Dict[str, Any]]:
    evidence_payloads: List[Dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        metadata = candidate["metadata"]
        evidence_payloads.append(
            {
                "evidence_id": f"E{index}",
                "chunk_id": metadata["chunk_id"],
                "doc_id": metadata["doc_id"],
                "source": metadata["source_name"],
                "title": metadata.get("title", ""),
                "page": metadata.get("page"),
                "section": metadata.get("section", ""),
                "doc_type": metadata.get("doc_type", ""),
                "corpus": metadata.get("corpus", ""),
                "dense_score": round(float(candidate.get("dense_score", 0.0)), 4),
                "sparse_score": round(float(candidate.get("sparse_score", 0.0)), 4),
                "rerank_score": round(float(candidate.get("rerank_score", 0.0)), 4),
                "retrieval_source": candidate.get("retrieval_source", ""),
                "content": _truncate_text(candidate["page_content"], max_chars=max_chars),
            }
        )
    return evidence_payloads


def _format_evidence_blocks(evidence_payloads: List[Dict[str, Any]]) -> str:
    if not evidence_payloads:
        return "无可用证据。"

    blocks = []
    for evidence in evidence_payloads:
        block = (
            f"[{evidence['evidence_id']}]\n"
            f"source: {evidence['source']}\n"
            f"title: {evidence['title']}\n"
            f"page: {evidence['page']}\n"
            f"doc_type: {evidence['doc_type']}\n"
            f"corpus: {evidence['corpus']}\n"
            f"retrieval_source: {evidence['retrieval_source']}\n"
            f"rerank_score: {evidence['rerank_score']}\n"
            f"content: {evidence['content']}"
        )
        blocks.append(block)
    return "\n\n".join(blocks)


def _build_answer_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_template(
        """
        你是一位严谨的 RAG 知识库问答助手。你的任务不是自由发挥，而是严格依据检索到的证据回答问题。

        # 问题
        {question}

        # 问题意图
        {intent}

        # 为什么这个问题重要
        {why_needed}

        # 可用证据
        {evidence_blocks}

        # 回答规则
        1. 只能依据提供的证据回答，不要引入证据中不存在的结论。
        2. 如果证据不足，请明确给出“根据当前检索到的证据，无法可靠回答该问题”。
        3. `citations` 只能填写你真正使用到的证据ID，例如 E1、E2。
        4. `status` 只能是 `answered` 或 `insufficient_evidence`。
        5. 输出必须是结构化结果，不要附加额外说明。
        6. 只返回一个 JSON 对象，不要输出 Markdown、代码块或额外解释。
        """
    )


def _extract_json_object(text: str) -> Dict[str, Any]:
    """从普通 LLM 文本输出中提取 JSON object。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _invoke_answer_llm_fallback(
    question_payload: Dict[str, Any],
    evidence_blocks: str,
    answer_prompt: Optional[ChatPromptTemplate] = None,
    answer_llm: Any = None,
) -> RagAnswer:
    """兼容不支持 response_format 的 OpenAI-compatible 模型。"""
    prompt = answer_prompt or _build_answer_prompt()
    active_llm = answer_llm or _get_llm()
    response = (prompt | active_llm).invoke(
        {
            "question": question_payload.get("question", ""),
            "intent": question_payload.get("intent", ""),
            "why_needed": question_payload.get("why_needed", ""),
            "evidence_blocks": evidence_blocks
            + "\n\n请只输出 JSON object，字段为 answer、confidence、citations、status。",
        }
    )
    data = _extract_json_object(str(response.content))
    confidence = data.get("confidence", "low")
    if isinstance(confidence, (int, float)):
        if confidence >= 0.75:
            data["confidence"] = "high"
        elif confidence >= 0.45:
            data["confidence"] = "medium"
        else:
            data["confidence"] = "low"
    elif isinstance(confidence, str):
        confidence_map = {
            "高": "high",
            "高置信": "high",
            "高置信度": "high",
            "中": "medium",
            "中等": "medium",
            "中置信": "medium",
            "中置信度": "medium",
            "moderate": "medium",
            "低": "low",
            "低置信": "low",
            "低置信度": "low",
        }
        normalized_confidence = confidence.strip().lower()
        data["confidence"] = confidence_map.get(
            confidence.strip(),
            confidence_map.get(normalized_confidence, normalized_confidence),
        )

    status = data.get("status", "insufficient_evidence")
    if isinstance(status, str):
        status_map = {
            "已回答": "answered",
            "可回答": "answered",
            "回答": "answered",
            "证据不足": "insufficient_evidence",
            "证据不充分": "insufficient_evidence",
            "无法回答": "insufficient_evidence",
        }
        normalized_status = status.strip().lower()
        data["status"] = status_map.get(status.strip(), normalized_status)

    citations = data.get("citations", [])
    if isinstance(citations, str):
        data["citations"] = [item.strip() for item in re.split(r"[,，;；\s]+", citations) if item.strip()]
    return RagAnswer.model_validate(data)


def _answer_question(
    question_payload: Dict[str, Any],
    evidence_payloads: List[Dict[str, Any]],
    answer_prompt: Optional[ChatPromptTemplate] = None,
) -> Dict[str, Any]:
    """基于检索证据回答问题；可选 prompt 仅用于评测等特殊链路，默认业务行为不变。"""
    answer_llm = _get_llm() if evidence_payloads else None
    return _answer_question_with_llm(
        question_payload,
        evidence_payloads,
        answer_llm=answer_llm,
        answer_prompt=answer_prompt,
    )


def _answer_question_with_llm(
    question_payload: Dict[str, Any],
    evidence_payloads: List[Dict[str, Any]],
    answer_llm: Any,
    answer_prompt: Optional[ChatPromptTemplate] = None,
) -> Dict[str, Any]:
    """使用显式回答 LLM 基于检索证据生成兼容回答结构。"""
    question_text = question_payload.get("question", "")
    if not evidence_payloads:
        return {
            "question": question_text,
            "intent": question_payload.get("intent", ""),
            "priority": question_payload.get("priority", "medium"),
            "why_needed": question_payload.get("why_needed", ""),
            "status": "insufficient_evidence",
            "answer": "根据当前检索到的证据，无法可靠回答该问题。",
            "confidence": "low",
            "citations": [],
            "retrieved_docs": [],
        }

    evidence_blocks = _format_evidence_blocks(evidence_payloads)
    prompt = answer_prompt or _build_answer_prompt()
    active_llm = answer_llm
    try:
        runnable = prompt | with_compatible_structured_output(active_llm, RagAnswer)
        answer = runnable.invoke(
            {
                "question": question_text,
                "intent": question_payload.get("intent", ""),
                "why_needed": question_payload.get("why_needed", ""),
                "evidence_blocks": evidence_blocks,
            }
        )
    except Exception as exc:
        try:
            answer = _invoke_answer_llm_fallback(
                question_payload,
                evidence_blocks,
                answer_prompt=prompt,
                answer_llm=active_llm,
            )
        except Exception as fallback_exc:
            return {
                "question": question_text,
                "intent": question_payload.get("intent", ""),
                "priority": question_payload.get("priority", "medium"),
                "why_needed": question_payload.get("why_needed", ""),
                "status": "insufficient_evidence",
                "answer": f"证据已检索，但回答生成失败：{exc}; fallback_failed={fallback_exc}",
                "confidence": "low",
                "citations": [],
                "retrieved_docs": evidence_payloads,
            }

    valid_citations = {evidence["evidence_id"] for evidence in evidence_payloads}
    citations = [citation for citation in answer.citations if citation in valid_citations]
    status = answer.status
    confidence = answer.confidence
    answer_text = answer.answer
    if status == "answered" and not citations:
        status = "insufficient_evidence"
        confidence = "low"
        answer_text = "根据当前检索到的证据，无法可靠回答该问题。"

    return {
        "question": question_text,
        "intent": question_payload.get("intent", ""),
        "priority": question_payload.get("priority", "medium"),
        "why_needed": question_payload.get("why_needed", ""),
        "status": status,
        "answer": answer_text,
        "confidence": confidence,
        "citations": citations,
        "retrieved_docs": evidence_payloads,
    }
## 统一问题对象格式
def _normalize_question_payload(question: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(question, str):
        return {
            "question": question,
            "intent": "补充报告所需的领域知识",
            "priority": "medium",
            "why_needed": "当前问题由系统自动生成，需要知识库补充背景理论。",
        }

    return {
        "question": question.get("question", ""),
        "intent": question.get("intent", "补充报告所需的领域知识"),
        "priority": question.get("priority", "medium"),
        "why_needed": question.get("why_needed", "用于增强报告中的理论解释与风险说明。"),
    }

## 回答摘要构建，无证据索引
def _build_question_summary(result: Dict[str, Any]) -> str:
    citations = ", ".join(result.get("citations", [])) or "无"
    return (
        f"问题：{result.get('question', '')}\n"
        f"意图：{result.get('intent', '')}\n"
        f"回答：{result.get('answer', '')}\n"
        f"置信度：{result.get('confidence', 'low')}\n"
        f"引用：{citations}"
    )

## 限制查询prompt长度，压缩
def format_rag_summary_for_prompt(
    rag_result: Union[str, Dict[str, Any], None],
    max_questions: int = 3,
    include_evidence: bool = False,
) -> str:
    if not rag_result:
        return "无可用领域知识。"

    if isinstance(rag_result, str):
        return rag_result

    if not rag_result.get("success", False):
        return f"知识库查询失败：{rag_result.get('summary', rag_result.get('error', '未知错误'))}"

    question_results = rag_result.get("questions", [])[:max_questions]
    if not question_results:
        return "知识库查询成功，但没有获得有效结果。"

    summaries = []
    for index, question_result in enumerate(question_results, start=1):
        block = [f"知识库查询 {index}", _build_question_summary(question_result)]
        if include_evidence and question_result.get("retrieved_docs"):
            evidence_lines = []
            for evidence in question_result["retrieved_docs"][:2]:
                evidence_lines.append(
                    f"- {evidence['evidence_id']} | {evidence['source']} | page={evidence['page']} | score={evidence['rerank_score']}"
                )
            block.append("证据摘要：\n" + "\n".join(evidence_lines))
        summaries.append("\n".join(block))
    return "\n\n".join(summaries)

## 后处理模块适配
def get_rag_excerpt(rag_result: Union[str, Dict[str, Any], None], max_chars: int = 800) -> str:
    summary = format_rag_summary_for_prompt(rag_result, max_questions=2, include_evidence=True)
    return _truncate_text(summary, max_chars=max_chars)


def _copy_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """复制候选列表，避免 trace 阶段之间共享 set 等可变对象。"""
    copied: List[Dict[str, Any]] = []
    for candidate in candidates:
        item = dict(candidate)
        retrieval_sources = item.get("retrieval_sources")
        if isinstance(retrieval_sources, set):
            item["retrieval_sources"] = set(retrieval_sources)
        item["metadata"] = dict(item.get("metadata", {}))
        copied.append(item)
    return copied


def _with_stage_rank(candidates: List[Dict[str, Any]], stage: str) -> List[Dict[str, Any]]:
    """为 trace 输出补充阶段名和阶段排名。"""
    ranked = _copy_candidates(candidates)
    for rank, candidate in enumerate(ranked, start=1):
        candidate["stage"] = stage
        candidate["rank"] = rank
        stage_scores = dict(candidate.get("stage_scores", {}))
        stage_scores.update(
            {
                "rank": rank,
                "dense_score": round(float(candidate.get("dense_score", 0.0)), 4),
                "sparse_score": round(float(candidate.get("sparse_score", 0.0)), 4),
                "rerank_score": round(float(candidate.get("rerank_score", 0.0)), 4),
            }
        )
        candidate["stage_scores"] = stage_scores
    return ranked


def _select_final_candidates(candidates: List[Dict[str, Any]], config: RagRetrievalConfig) -> List[Dict[str, Any]]:
    """应用 final rerank threshold 和 final_top_k 截断。"""
    filtered = [
        candidate
        for candidate in candidates
        if float(candidate.get("rerank_score", 0.0)) >= config.final_rerank_threshold
    ]
    if filtered:
        return filtered[: config.final_top_k]
    return candidates[: min(config.final_top_k, len(candidates))]


def build_retrieval_trace(
    question_text: str,
    config: Optional[RagRetrievalConfig] = None,
) -> Dict[str, Any]:
    """兼容入口：通过唯一 compatibility Service 执行检索 trace。"""
    return _get_compatibility_service().build_retrieval_trace(question_text, config=config)


def _build_retrieval_trace_with_resources(
    question_text: str,
    config: RagRetrievalConfig,
    *,
    vector_db: Any,
    embedding_function: Any,
    sparse_retriever: SparseRetriever,
) -> Dict[str, Any]:
    """
    执行完整 RAG 检索链路并返回分阶段 trace。

    这是 RAG 测评模块调参的稳定入口，包含：
    dense_raw -> dense_thresholded -> dense_mmr -> sparse ->
    merged_before_rerank -> reranked -> final。
    """
    active_config = config
    timings_ms: Dict[str, float] = {}
    total_start = time.perf_counter()

    started = time.perf_counter()
    dense_raw = _dense_retrieve(
        question_text,
        fetch_k=active_config.dense_fetch_k,
        score_threshold=0.0,
        vector_db=vector_db,
    )
    timings_ms["dense_raw"] = round((time.perf_counter() - started) * 1000, 3)

    started = time.perf_counter()
    dense_thresholded = [
        candidate
        for candidate in dense_raw
        if float(candidate.get("dense_score", 0.0)) >= active_config.dense_score_threshold
    ]
    timings_ms["dense_thresholded"] = round((time.perf_counter() - started) * 1000, 3)

    started = time.perf_counter()
    dense_mmr = _select_mmr_candidates(
        question_text,
        dense_thresholded,
        top_k=active_config.dense_mmr_k,
        mmr_lambda=active_config.mmr_lambda,
        embedding_function=embedding_function,
    )
    timings_ms["dense_mmr"] = round((time.perf_counter() - started) * 1000, 3)

    started = time.perf_counter()
    sparse = _sparse_retrieve(
        question_text,
        fetch_k=active_config.sparse_fetch_k,
        sparse_retriever=sparse_retriever,
    )
    timings_ms["sparse"] = round((time.perf_counter() - started) * 1000, 3)

    started = time.perf_counter()
    reranked = _merge_candidates(
        dense_mmr,
        sparse,
        final_top_k=active_config.final_top_k,
        final_rerank_threshold=active_config.final_rerank_threshold,
        official_only_when_available=active_config.official_only_when_available,
        return_before_final=True,
    )
    timings_ms["merge_rerank"] = round((time.perf_counter() - started) * 1000, 3)

    started = time.perf_counter()
    final_candidates = _select_final_candidates(reranked, active_config)
    evidence_payloads = _build_evidence_payloads(
        final_candidates,
        max_chars=active_config.max_evidence_chars,
    )
    timings_ms["final_select"] = round((time.perf_counter() - started) * 1000, 3)
    timings_ms["total"] = round((time.perf_counter() - total_start) * 1000, 3)

    return {
        "question": question_text,
        "config": active_config.to_dict(),
        "timings_ms": timings_ms,
        "stages": {
            "dense_raw": _with_stage_rank(dense_raw, "dense_raw"),
            "dense_thresholded": _with_stage_rank(dense_thresholded, "dense_thresholded"),
            "dense_mmr": _with_stage_rank(dense_mmr, "dense_mmr"),
            "sparse": _with_stage_rank(sparse, "sparse"),
            "merged_before_rerank": _with_stage_rank(reranked, "merged_before_rerank"),
            "reranked": _with_stage_rank(reranked, "reranked"),
            "final": _with_stage_rank(final_candidates, "final"),
        },
        "evidence_payload": evidence_payloads,
    }


## 检索整体封装
def _retrieve_candidates(
    question_text: str,
    config: Optional[RagRetrievalConfig] = None,
) -> List[Dict[str, Any]]:
    active_config = config or _load_production_rag_config()[0]
    trace = build_retrieval_trace(question_text, config=active_config)
    return trace["stages"]["final"]

## 查询主入口
def get_rag_response(questions: List[Union[str, Dict[str, Any]]]) -> Dict[str, Any]:
    """
    接收一个问题列表，对每个问题执行混合检索、证据重排和结构化回答。
    返回结构化的RAG结果，供报告与后处理模块使用。
    """
    return _get_compatibility_service().get_response(
        questions,
        retrieve_candidates=_retrieve_candidates,
        answer_question=_answer_question,
        summary_formatter=format_rag_summary_for_prompt,
        config_loader=_load_production_rag_config,
    )


def query(question: str) -> None:
    """本地调试时使用。"""
    print(f"\n用户问题: {question}")
    print("--- RAG响应 ---")
    response = get_rag_response([question])
    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    query("因果推断是什么？它和相关性有什么区别？")
    query("什么是因果推断定律？")
    query("Judea Pearl是谁？")
