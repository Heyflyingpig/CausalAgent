import hashlib
import json
import math
import os
import re
from collections import Counter
from functools import lru_cache
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import numpy as np
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from config.settings import settings

base_dir = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(base_dir, "models", "bge-small-zh-v1.5")
PERSIST_DIRECTORY = os.path.join(base_dir, "db")

DENSE_FETCH_K = 10
DENSE_MMR_K = 6
SPARSE_FETCH_K = 8
FINAL_TOP_K = 4
DENSE_SCORE_THRESHOLD = 0.45
FINAL_RERANK_THRESHOLD = 0.18
MMR_LAMBDA = 0.7
MAX_EVIDENCE_CHARS = 420


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


@lru_cache(maxsize=1)
def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        api_key=settings.API_KEY,
        base_url=settings.BASE_URL,
        model=settings.MODEL,
    )


@lru_cache(maxsize=1)
def _get_embedding_function() -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(
        model_name=MODEL_PATH,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


@lru_cache(maxsize=1)
def _get_vector_db() -> Chroma:
    if not os.path.exists(PERSIST_DIRECTORY):
        raise FileNotFoundError(
            f"知识库持久化目录不存在: {PERSIST_DIRECTORY}。请先运行 Agent/knowledge_base/build_knowledge.py 构建知识库。"
        )

    return Chroma(
        persist_directory=PERSIST_DIRECTORY,
        embedding_function=_get_embedding_function(),
    )


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
    text = text.lower()
    segments = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9_]+", text)
    tokens: List[str] = []
    for segment in segments:
        if re.fullmatch(r"[\u4e00-\u9fff]+", segment):
            tokens.extend(list(segment))
            if len(segment) >= 2:
                tokens.extend(segment[i : i + 2] for i in range(len(segment) - 1))
        else:
            tokens.extend(part for part in segment.split("_") if part)
    return tokens[:512]

### 注意这里用了iru
# 第一次 sparse 检索时，会把当前向量库内容读出来并构造成 BM25 语料缓存
# 之后都会复用这份缓存
# 如果重建了知识库，这个 sparse 语料缓存不会自动刷新

@lru_cache(maxsize=1)
def _get_sparse_corpus() -> Dict[str, Any]:
    raw = _get_vector_db().get(include=["documents", "metadatas"])
    documents = raw.get("documents", [])
    metadatas = raw.get("metadatas", [])
    ids = raw.get("ids", [])

    entries: List[Dict[str, Any]] = []
    doc_freq: Counter = Counter()
    total_length = 0

    for index, page_content in enumerate(documents):
        metadata = _normalize_chunk_metadata(
            metadatas[index] if index < len(metadatas) else {},
            page_content,
            fallback_index=index,
        )
        metadata["vector_id"] = ids[index] if index < len(ids) else None

        tokens = _tokenize_text(page_content)
        term_freq = Counter(tokens)
        total_length += len(tokens)

        for token in term_freq:
            doc_freq[token] += 1

        entries.append(
            {
                "page_content": page_content,
                "metadata": metadata,
                "term_freq": term_freq,
                "length": max(len(tokens), 1),
            }
        )

    avg_length = total_length / len(entries) if entries else 1.0
    return {
        "entries": entries,
        "doc_freq": doc_freq,
        "avg_length": avg_length,
        "size": len(entries),
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


def _normalize_scores(candidates: List[Dict[str, Any]], score_key: str, normalized_key: str) -> None:
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
        candidate[normalized_key] = (float(candidate.get(score_key, 0.0)) - min_score) / (max_score - min_score)


def _dense_retrieve(question: str, fetch_k: int = DENSE_FETCH_K) -> List[Dict[str, Any]]:
    dense_results = _get_vector_db().similarity_search_with_relevance_scores(question, k=fetch_k)
    candidates: List[Dict[str, Any]] = []

    for index, (doc, score) in enumerate(dense_results):
        if float(score) < DENSE_SCORE_THRESHOLD:
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
    ) -> List[Dict[str, Any]]:
    
    if len(candidates) <= top_k:
        return candidates

    embedding_function = _get_embedding_function()
    query_embedding = np.array(embedding_function.embed_query(question), dtype=np.float32)
    doc_embeddings = np.array(
        embedding_function.embed_documents([candidate["page_content"] for candidate in candidates]),
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
            mmr_score = MMR_LAMBDA * similarity_to_query - (1 - MMR_LAMBDA) * similarity_to_selected
            if mmr_score > best_score:
                best_score = mmr_score
                best_index = candidate_index

        if best_index is None:
            break
        selected_indices.append(best_index)
        remaining_indices.remove(best_index)

    return [candidates[index] for index in selected_indices]


def _sparse_retrieve(question: str, fetch_k: int = SPARSE_FETCH_K) -> List[Dict[str, Any]]:
    query_tokens = _tokenize_text(question)
    corpus = _get_sparse_corpus()
    if not query_tokens or not corpus["entries"]:
        return []

    scored_candidates: List[Dict[str, Any]] = []
    for entry in corpus["entries"]:
        score = _bm25_score(
            query_tokens=query_tokens,
            entry=entry,
            doc_freq=corpus["doc_freq"],
            corpus_size=corpus["size"],
            avg_length=corpus["avg_length"],
        )
        if score <= 0:
            continue
        scored_candidates.append(
            {
                "page_content": entry["page_content"],
                "metadata": entry["metadata"],
                "dense_score": 0.0,
                "sparse_score": float(score),
                "retrieval_sources": {"sparse"},
            }
        )

    scored_candidates.sort(key=lambda item: item["sparse_score"], reverse=True)
    scored_candidates = scored_candidates[:fetch_k]
    _normalize_scores(scored_candidates, "sparse_score", "sparse_score_norm")
    return scored_candidates


def _merge_candidates(
    dense_candidates: List[Dict[str, Any]],
    sparse_candidates: List[Dict[str, Any]],
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
    if official_candidates:
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
    filtered = [candidate for candidate in merged_candidates if candidate["rerank_score"] >= FINAL_RERANK_THRESHOLD]
    if filtered:
        return filtered[:FINAL_TOP_K]
    return merged_candidates[: min(FINAL_TOP_K, len(merged_candidates))]


def _build_evidence_payloads(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
                "content": _truncate_text(candidate["page_content"]),
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
        你是一位严谨的因果推断知识库问答助手。你的任务不是自由发挥，而是严格依据检索到的证据回答问题。

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
        """
    )


def _answer_question(question_payload: Dict[str, Any], evidence_payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
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
    try:
        runnable = _build_answer_prompt() | _get_llm().with_structured_output(RagAnswer)
        answer = runnable.invoke(
            {
                "question": question_text,
                "intent": question_payload.get("intent", ""),
                "why_needed": question_payload.get("why_needed", ""),
                "evidence_blocks": evidence_blocks,
            }
        )
    except Exception as exc:
        return {
            "question": question_text,
            "intent": question_payload.get("intent", ""),
            "priority": question_payload.get("priority", "medium"),
            "why_needed": question_payload.get("why_needed", ""),
            "status": "insufficient_evidence",
            "answer": f"证据已检索，但回答生成失败：{exc}",
            "confidence": "low",
            "citations": [],
            "retrieved_docs": evidence_payloads,
        }

    valid_citations = {evidence["evidence_id"] for evidence in evidence_payloads}
    citations = [citation for citation in answer.citations if citation in valid_citations]

    return {
        "question": question_text,
        "intent": question_payload.get("intent", ""),
        "priority": question_payload.get("priority", "medium"),
        "why_needed": question_payload.get("why_needed", ""),
        "status": answer.status,
        "answer": answer.answer,
        "confidence": answer.confidence,
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


## 检索整体封装
def _retrieve_candidates(question_text: str) -> List[Dict[str, Any]]:
    dense_candidates = _select_mmr_candidates(question_text, _dense_retrieve(question_text))
    sparse_candidates = _sparse_retrieve(question_text)
    return _merge_candidates(dense_candidates, sparse_candidates)

## 查询主入口
def get_rag_response(questions: List[Union[str, Dict[str, Any]]]) -> Dict[str, Any]:
    """
    接收一个问题列表，对每个问题执行混合检索、证据重排和结构化回答。
    返回结构化的RAG结果，供报告与后处理模块使用。
    """
    if not questions:
        return {
            "success": True,
            "summary": "没有生成任何需要查询知识库的问题。",
            "questions": [],
            "evidence_count": 0,
        }

    question_results: List[Dict[str, Any]] = []
    total_evidence_count = 0

    for question in questions:
        question_payload = _normalize_question_payload(question)
        question_text = question_payload["question"].strip()
        if not question_text:
            continue

        candidates = _retrieve_candidates(question_text)
        evidence_payloads = _build_evidence_payloads(candidates)
        total_evidence_count += len(evidence_payloads)

        answer_result = _answer_question(question_payload, evidence_payloads)
        question_results.append(answer_result)

    summary = format_rag_summary_for_prompt(
        {"success": True, "questions": question_results},
        max_questions=len(question_results),
        include_evidence=True,
    )

    return {
        "success": True,
        "summary": summary,
        "questions": question_results,
        "evidence_count": total_evidence_count,
    }


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
