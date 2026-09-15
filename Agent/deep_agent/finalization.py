"""结构化终态的静态校验和一次性修正预算。"""

from __future__ import annotations

from collections.abc import Mapping, Set
from dataclasses import dataclass
from typing import Any

from Agent.deep_agent_tools.models import FinalAnalysisDecision


class StructuredResponseError(ValueError):
    """模型没有提交可验证的 ``structured_response``。"""


def validate_structured_response(value: Any) -> FinalAnalysisDecision:
    """只接受 ToolStrategy 产出的对象或等价 JSON mapping。"""

    if isinstance(value, FinalAnalysisDecision):
        return value.model_copy(deep=True)
    if isinstance(value, Mapping):
        try:
            return FinalAnalysisDecision.model_validate(value)
        except Exception as exc:  # Pydantic 的细节不能透传到公共输出
            raise StructuredResponseError("structured_response schema validation failed") from exc
    raise StructuredResponseError("structured_response is required")


def validate_decision_references(
    decision: FinalAnalysisDecision,
    *,
    algorithm_result_refs: Set[str],
    evidence_refs: Set[str] = frozenset(),
) -> FinalAnalysisDecision:
    """验证静态 schema 之外的引用闭包，不做科学判断。"""

    result_refs = set(algorithm_result_refs)
    assessment_refs = {item.result_ref for item in decision.result_assessments}
    if not assessment_refs.issubset(result_refs):
        raise StructuredResponseError("decision references an unknown algorithm result")
    if decision.primary_result_ref and decision.primary_result_ref not in result_refs:
        raise StructuredResponseError("primary_result_ref is not an available result")
    for proposal in decision.revision_proposals:
        if proposal.result_ref not in result_refs:
            raise StructuredResponseError("revision proposal references an unknown result")
        if not set(proposal.evidence_refs).issubset(evidence_refs):
            raise StructuredResponseError("revision proposal references unknown evidence")
    for conflict in decision.conflicts:
        if not set(conflict.result_refs).issubset(result_refs):
            raise StructuredResponseError("conflict references an unknown result")
    return decision.model_copy(deep=True)


@dataclass
class FinalizationRetryController:
    """Gate 动态不一致后最多把修正机会交还 Deep Agent 一次。"""

    retry_limit: int = 1
    retries_used: int = 0

    def __post_init__(self) -> None:
        if self.retry_limit < 0:
            raise ValueError("retry_limit must be non-negative")
        if self.retries_used < 0 or self.retries_used > self.retry_limit:
            raise ValueError("retries_used is outside retry_limit")

    @property
    def can_retry(self) -> bool:
        return self.retries_used < self.retry_limit

    def consume(self) -> int:
        if not self.can_retry:
            raise StructuredResponseError("finalization retry budget exhausted")
        self.retries_used += 1
        return self.retries_used

