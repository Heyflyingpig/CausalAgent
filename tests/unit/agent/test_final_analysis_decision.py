"""P2-U ToolStrategy 终态和 finalization retry 预算测试。"""

import pytest

from Agent.deep_agent.finalization import (
    FinalizationRetryController,
    StructuredResponseError,
    validate_decision_references,
    validate_structured_response,
)


def _decision():
    return {
        "outcome": "algorithm_supported",
        "primary_result_ref": "result-1",
        "result_assessments": [
            {"result_ref": "result-1", "disposition": "primary", "rationale": "valid"}
        ],
        "conflict_status": "none",
        "conflicts": [],
        "revision_proposals": [],
        "selection_rationale": "selected by evidence",
        "confidence": "medium",
        "confidence_basis": ["diagnostics"],
    }


def test_structured_response_and_reference_closure_are_required() -> None:
    decision = validate_structured_response(_decision())
    assert decision.primary_result_ref == "result-1"
    validate_decision_references(decision, algorithm_result_refs={"result-1"})
    with pytest.raises(StructuredResponseError, match="unknown algorithm result"):
        validate_decision_references(decision, algorithm_result_refs=set())


def test_retry_budget_allows_exactly_one_retry() -> None:
    controller = FinalizationRetryController()
    assert controller.can_retry
    assert controller.consume() == 1
    assert not controller.can_retry
    with pytest.raises(StructuredResponseError, match="exhausted"):
        controller.consume()

