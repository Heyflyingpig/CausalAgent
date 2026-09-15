"""RAG evidence-only 原子 Tool。"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .models import EvidenceResult
from .runtime_updates import (
    build_terminal_invocation,
    build_tool_command,
    resolve_runtime_invocation,
    with_tool_runtime_schema,
)


class EvidenceRetriever(Protocol):
    def get_evidence(self, query: str, *, max_contexts: int | None = None) -> Mapping[str, Any]:
        ...


class _RagEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    max_contexts: int | None = Field(default=None, gt=0)


@dataclass(frozen=True)
class RagEvidenceQuery:
    query: str
    max_contexts: int | None = None

    def __post_init__(self) -> None:
        if not self.query or not self.query.strip():
            raise ValueError("query must be non-blank")
        if self.max_contexts is not None and self.max_contexts <= 0:
            raise ValueError("max_contexts must be positive")


def _coerce_evidence(item: Mapping[str, Any], *, release_id: str | None) -> EvidenceResult:
    evidence_id = str(item.get("evidence_id") or "") or None
    evidence_ref = str(item.get("evidence_ref") or evidence_id or "")
    snippet = str(item.get("snippet") or item.get("content") or "").strip()
    if not evidence_ref or not snippet:
        raise ValueError("RAG evidence item is missing reference or snippet")
    return EvidenceResult(
        evidence_ref=evidence_ref,
        evidence_id=evidence_id,
        snippet=snippet,
        source_title=item.get("source_title") or item.get("title"),
        source_url=item.get("source_url") or item.get("url"),
        locator=item.get("locator"),
        modality=item.get("modality"),
        score=item.get("score") if item.get("score") is not None else item.get("rerank_score"),
        dense_score=item.get("dense_score"),
        sparse_score=item.get("sparse_score"),
        rerank_score=item.get("rerank_score"),
        sufficiency=item.get("sufficiency"),
        release_id=item.get("release_id") or release_id,
        degradation_flags=tuple(str(flag) for flag in item.get("degradation_flags", ())),
    )


@dataclass
class RagEvidenceTool:
    """只调用 retriever.get_evidence，不调用 answer_question。"""

    retriever: EvidenceRetriever

    name: str = "rag_evidence_search"
    description: str = (
        "检索当前 active release 的知识库证据。只返回可引用片段和来源元数据，"
        "不生成回答，不替代因果算法。"
    )

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "max_contexts": {"type": ["integer", "null"], "minimum": 1},
                },
                "required": ["query"],
            },
        }

    async def get_evidence(self, query: str, *, max_contexts: int | None = None) -> dict[str, Any]:
        request = RagEvidenceQuery(query=query, max_contexts=max_contexts)
        try:
            raw = self.retriever.get_evidence(
                request.query,
                max_contexts=request.max_contexts,
            )
            if inspect.isawaitable(raw):
                raw = await raw
        except Exception:
            return {
                "status": "unavailable",
                "query": request.query,
                "release_id": None,
                "evidence": [],
                "evidence_by_ref": {},
                "sufficiency": "unavailable",
                "diagnostics": {"reason_code": "retrieval_unavailable"},
            }
        if not isinstance(raw, Mapping):
            return {
                "status": "protocol_error",
                "query": request.query,
                "release_id": None,
                "evidence": [],
                "diagnostics": {"reason_code": "invalid_retriever_payload"},
            }
        status = str(raw.get("status") or "protocol_error")
        if status not in {
            "available",
            "no_relevant_evidence",
            "unavailable",
            "protocol_error",
        }:
            status = "protocol_error"
        release_id = raw.get("release_id")
        try:
            evidence = [
                _coerce_evidence(item, release_id=release_id)
                for item in raw.get("evidence", [])
                if isinstance(item, Mapping)
            ]
        except (TypeError, ValueError):
            return {
                "status": "protocol_error",
                "query": request.query,
                "release_id": release_id,
                "evidence": [],
                "diagnostics": {"reason_code": "invalid_evidence_item"},
            }
        return {
            "status": status,
            "query": request.query,
            "release_id": release_id,
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "evidence_by_ref": {
                item.evidence_ref: item.model_dump(mode="json") for item in evidence
            },
            "sufficiency": raw.get(
                "sufficiency",
                "sufficient" if status == "available" and evidence else "insufficient",
            ),
            "diagnostics": dict(raw.get("diagnostics") or {}),
        }

    async def ainvoke(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        return await self.get_evidence(
            str(arguments.get("query") or ""),
            max_contexts=arguments.get("max_contexts"),
        )

    def to_langchain_tool(self) -> Any:
        """包装为把 evidence 与 terminal Ledger 同步写回 State 的 Tool。"""

        try:
            from langchain.tools import ToolRuntime
            from langchain_core.tools import StructuredTool
        except (ImportError, ModuleNotFoundError) as exc:  # pragma: no cover
            raise RuntimeError("LangChain is not installed") from exc

        async def call(
            query: str,
            runtime: Any,
            max_contexts: int | None = None,
        ) -> Any:
            identity = resolve_runtime_invocation(runtime)
            await identity.runtime_context.ensure_active()
            started_at = datetime.now(timezone.utc)
            payload = await self.get_evidence(query, max_contexts=max_contexts)
            status = str(payload.get("status") or "protocol_error")
            attempt_status = (
                "succeeded"
                if status in {"available", "no_relevant_evidence"}
                else "failed"
            )
            safe_error_code = {
                "unavailable": "RAG_RETRIEVAL_UNAVAILABLE",
                "protocol_error": "RAG_PROTOCOL_ERROR",
            }.get(status)
            evidence_by_ref = {
                str(ref): EvidenceResult.model_validate(value)
                for ref, value in dict(payload.get("evidence_by_ref") or {}).items()
            }
            terminal = build_terminal_invocation(
                identity=identity,
                tool_name=self.name,
                attempt_status=attempt_status,
                started_at=started_at,
                safe_error_code=safe_error_code,
            )
            return build_tool_command(
                identity=identity,
                tool_name=self.name,
                payload=payload,
                ledger_record=terminal,
                state_updates={"rag_evidence": evidence_by_ref},
            )

        call.__annotations__["runtime"] = ToolRuntime
        runtime_args_schema = with_tool_runtime_schema(
            _RagEvidenceInput,
            tool_name=self.name,
            tool_runtime_type=ToolRuntime,
        )
        return StructuredTool.from_function(
            coroutine=call,
            name=self.name,
            description=self.description,
            args_schema=runtime_args_schema,
        )


def build_default_rag_evidence_tool(*, service: EvidenceRetriever | None = None) -> RagEvidenceTool:
    """惰性绑定当前 RagService；不会在模块 import 时初始化索引或模型。"""

    if service is None:
        from Agent.knowledge_base.rag_service import UnavailableRagService
        from Agent.knowledge_base.query_rag import _get_rag_service

        try:
            service = _get_rag_service()
        except Exception:
            service = UnavailableRagService()
    return RagEvidenceTool(service)
