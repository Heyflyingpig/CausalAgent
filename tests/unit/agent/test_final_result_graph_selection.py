import json
import os

import pytest


for key, value in {
    "SECRET_KEY": "test-secret",
    "API_KEY": "test-api-key",
    "BASE_URL": "https://example.test",
    "MODEL": "test-model",
    "MYSQL_HOST": "mysql",
    "MYSQL_USER": "app",
    "MYSQL_PASSWORD": "password",
    "MYSQL_DATABASE": "causalagent",
}.items():
    os.environ.setdefault(key, value)


from langchain_core.messages import AIMessage

from app.agent.worker.result_presenter import process_final_result
from app.chat.response_storage import prepare_ai_response_for_storage


ORIGINAL_GRAPH = {
    "nodes": [{"id": "A"}, {"id": "B"}],
    "edges": [{"from": "A", "to": "B", "arrows": "to"}],
}
REVISED_GRAPH = {
    "nodes": [{"id": "A"}, {"id": "B"}],
    "edges": [{"from": "B", "to": "A", "arrows": "to"}],
}


def _final_state(postprocess_result):
    """构造报告完成时 process_final_result 所需的最小状态。"""
    return {
        "messages": [AIMessage(content="report ready", name="report")],
        "final_report": "report body",
        "causal_analysis_result": {
            "success": True,
            "data": ORIGINAL_GRAPH,
        },
        "postprocess_result": postprocess_result,
    }


def test_final_result_uses_valid_revised_graph_and_history_persists_same_data():
    """最终 SSE 与历史附件必须保存同一份修订图。"""
    result = process_final_result(
        _final_state(
            {
                "revised_graph": REVISED_GRAPH,
                "revision_summary": "reversed A to B",
            }
        )
    )

    assert result["type"] == "causal_graph"
    assert result["data"] == REVISED_GRAPH
    assert result["graph_source"] == "postprocessed"
    assert result["revision_summary"] == "reversed A to B"

    _content, attachments = prepare_ai_response_for_storage(result)
    persisted = json.loads(attachments[0]["content"])
    assert persisted["data"] == REVISED_GRAPH
    assert persisted["graph_source"] == "postprocessed"


@pytest.mark.parametrize(
    "postprocess_result",
    [
        None,
        {},
        {"revised_graph": []},
        {"revised_graph": {"nodes": [], "edges": "invalid"}},
        {"revised_graph": REVISED_GRAPH, "error": "postprocess failed"},
    ],
)
def test_final_result_falls_back_to_original_graph_when_revision_is_invalid(
    postprocess_result,
):
    """缺失、结构错误或带 error 的修订结果都必须安全回退原图。"""
    result = process_final_result(_final_state(postprocess_result))

    assert result["data"] == ORIGINAL_GRAPH
    assert result["graph_source"] == "original"
