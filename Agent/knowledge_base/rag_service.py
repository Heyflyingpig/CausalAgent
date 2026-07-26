"""RAG Runtime 之上的查询服务与可选能力降级。"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Protocol, Union

from Agent.knowledge_base.rag_runtime import RagRuntime


UNAVAILABLE_RAG_RESULT = {
    "success": False,
    "status": "unavailable",
    "summary": "知识库暂不可用，当前结果未使用知识库增强。",
    "questions": [],
    "evidence_count": 0,
}


class RagQueryService(Protocol):
    """生产 RAG Tool 唯一依赖的最小接口。"""

    def get_response(self, questions: List[Union[str, Dict[str, Any]]]) -> Dict[str, Any]:
        """对标准化前的问题列表执行知识库查询。"""


class RagService:
    """使用同一 Runtime 执行检索、回答和元数据查询。"""

    def __init__(self, runtime: RagRuntime):
        """绑定已完整初始化的 Runtime。"""
        self._runtime = runtime

    @property
    def runtime(self) -> RagRuntime:
        """返回已绑定的 Runtime。"""
        return self._runtime

    def _load_retrieval_config(self) -> Any:
        """每次问题执行前读取当前发布的生产检索配置。"""
        from Agent.knowledge_base import query_rag

        return query_rag._load_rag_config(self.runtime.config.production_config_path)[0]

    def build_retrieval_trace(self, question_text: str, config: Any = None) -> Dict[str, Any]:
        """使用 Runtime 资源执行完整检索 trace。"""
        from Agent.knowledge_base import query_rag

        active_config = config or query_rag.RagRetrievalConfig()
        return query_rag._build_retrieval_trace_with_resources(
            question_text,
            active_config,
            vector_db=self.runtime.vector_db,
            embedding_function=self.runtime.embedding,
            sparse_retriever=self.runtime.sparse_retriever,
        )

    def get_vector_db_metadata_summary(self, limit: int = 10000) -> Dict[str, Any]:
        """汇总 Runtime 已打开 collection 的 metadata。"""
        from collections import Counter

        raw = self.runtime.vector_db.get(include=["metadatas"], limit=limit)
        metadatas = raw.get("metadatas") or []
        doc_ids = [
            str(metadata.get("doc_id") or metadata.get("document_id") or "")
            for metadata in metadatas
        ]
        datasets = [str(metadata.get("dataset", "")) for metadata in metadatas]
        prefixes = [doc_id.split("_", 1)[0] for doc_id in doc_ids if doc_id]
        return {
            "exists": True,
            "persist_directory": self.runtime.config.vector_db_dir,
            "collection_name": self.runtime.config.collection_name,
            "vector_count": len(raw.get("ids") or []),
            "dataset_counts": dict(Counter(datasets)),
            "doc_id_prefix_counts": dict(Counter(prefixes)),
            "sample_doc_ids": doc_ids[:5],
        }

    def answer_question(
        self,
        question_payload: Dict[str, Any],
        evidence_payloads: List[Dict[str, Any]],
        answer_prompt: Any = None,
    ) -> Dict[str, Any]:
        """使用 Runtime 显式持有的回答 LLM 生成兼容回答。"""
        from Agent.knowledge_base import query_rag

        return query_rag._answer_question_with_llm(
            question_payload,
            evidence_payloads,
            answer_llm=self.runtime.answer_llm,
            answer_prompt=answer_prompt,
        )

    def get_response(
        self,
        questions: List[Union[str, Dict[str, Any]]],
        *,
        retrieve_candidates: Callable[..., List[Dict[str, Any]]] | None = None,
        answer_question: Callable[..., Dict[str, Any]] | None = None,
        summary_formatter: Callable[..., str] | None = None,
        config_loader: Callable[[], Any] | None = None,
    ) -> Dict[str, Any]:
        """逐问题热加载检索配置，并保持原有响应结构。"""
        from Agent.knowledge_base import query_rag

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
            question_payload = query_rag._normalize_question_payload(question)
            question_text = question_payload["question"].strip()
            if not question_text:
                continue

            production_config = (
                config_loader()[0] if config_loader is not None else self._load_retrieval_config()
            )
            if retrieve_candidates is None:
                trace = self.build_retrieval_trace(question_text, config=production_config)
                candidates = trace["stages"]["final"]
            else:
                candidates = retrieve_candidates(question_text, config=production_config)
            evidence_payloads = query_rag._build_evidence_payloads(
                candidates,
                max_chars=production_config.max_evidence_chars,
            )
            total_evidence_count += len(evidence_payloads)
            if answer_question is None:
                answer_result = self.answer_question(question_payload, evidence_payloads)
            else:
                answer_result = answer_question(question_payload, evidence_payloads)
            question_results.append(answer_result)

        formatter = summary_formatter or query_rag.format_rag_summary_for_prompt
        summary = formatter(
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


class UnavailableRagService:
    """Runtime 初始化失败后绑定的稳定、无敏感信息降级服务。"""

    def get_response(self, questions: List[Union[str, Dict[str, Any]]]) -> Dict[str, Any]:
        """忽略输入并返回新的稳定降级对象。"""
        return dict(UNAVAILABLE_RAG_RESULT)


class CompatibilityRagService(RagService):
    """仅为遗留调用延迟创建严格 Runtime 的单一 Service。"""

    def __init__(self, runtime_factory: Callable[[], RagRuntime]):
        """保存 Runtime 工厂，但不在模块导入或纯 mock 调用时加载资源。"""
        self._runtime_factory = runtime_factory
        self._runtime = None
        self._runtime_lock = threading.Lock()

    @property
    def runtime(self) -> RagRuntime:
        """首次访问时严格创建完整 Runtime，失败直接向调用方抛出。"""
        if self._runtime is None:
            with self._runtime_lock:
                if self._runtime is None:
                    self._runtime = self._runtime_factory()
        return self._runtime
