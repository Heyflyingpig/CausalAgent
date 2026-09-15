"""P2-U Deep Agent State 与父图投影的协议测试。"""

from __future__ import annotations

import pytest

from Agent.deep_agent.state import (
    assert_checkpoint_state_safe,
    from_deep_agent_output,
    initial_deep_agent_state,
    to_deep_agent_input,
)
from Agent.deep_agent_tools.models import DataProfile


def test_state_always_has_empty_ledger_and_independent_reducers() -> None:
    state = initial_deep_agent_state(
        data_profile=DataProfile(row_count=10, column_count=2, column_names=("x", "y")),
        analysis_question="compare methods",
    )
    assert state["action_ledger"] == {}
    assert state["algorithm_results"] == {}
    assert state["rag_evidence"] == {}
    assert state["web_evidence"] == {}
    assert state["finalization_retry_count"] == 0


def test_parent_projection_does_not_copy_job_or_runtime_fields() -> None:
    parent = {
        "messages": ["message"],
        "analysis_question": "question",
        "analysis_parameters": {"target": "y"},
        "file_summary": {"rows": 10, "columns": ["x", "y"]},
        "job_id": "job-secret-to-parent-only",
        "execution_guard": object(),
    }
    projected = to_deep_agent_input(parent)
    assert projected["analysis_question"] == "question"
    assert projected["data_profile"].column_names == ("x", "y")
    assert "job_id" not in projected
    assert "execution_guard" not in projected

    update = from_deep_agent_output(projected)
    assert set(update) == {
        "deep_agent_algorithm_results",
        "deep_agent_action_ledger",
        "deep_agent_rag_evidence",
        "deep_agent_web_evidence",
        "deep_agent_decision",
        "deep_agent_structured_response",
    }


def test_runtime_only_state_keys_are_rejected() -> None:
    with pytest.raises(TypeError, match="runtime-only"):
        assert_checkpoint_state_safe({"algorithm_executor": object()})

