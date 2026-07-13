import pytest

from Agent.Postprocessing.evaluate_edge.edge_utils import (
    _parse_edge_string,
    extract_critical_edges,
)


def test_extract_edges_prefers_vis_network_data_and_keeps_partial_endpoint_names():
    """前端边是首选事实来源，圆端点不能泄漏到节点名。"""
    result = {
        "data": {
            "edges": [
                {"from": "A", "to": "B", "arrows": "to", "dashes": True}
            ]
        },
        "raw_results": {"edges": ["A o-> B"]},
    }

    edges, debug = extract_critical_edges(result)

    assert debug["source"] == "data.edges"
    assert edges[0]["source"] == "A"
    assert edges[0]["target"] == "B"
    assert edges[0]["edge_type"] == "partially_oriented"


@pytest.mark.parametrize(
    ("raw", "source", "target", "edge_type"),
    [
        ("A --> B", "A", "B", "directed"),
        ("A <-- B", "B", "A", "directed"),
        ("A o-> B", "A", "B", "partially_oriented"),
        ("A <-o B", "B", "A", "partially_oriented"),
        ("A <-> B", "A", "B", "bidirected"),
        ("A o-o B", "A", "B", "undirected"),
        ("A --- B", "A", "B", "undirected"),
    ],
)
def test_parse_causallearn_edge_endpoints(raw, source, target, edge_type):
    """完整连接符必须先于宽泛箭头规则解析。"""
    edge = _parse_edge_string(raw, 0)

    assert edge is not None
    assert (edge["source"], edge["target"], edge["edge_type"]) == (
        source,
        target,
        edge_type,
    )


def test_extract_edges_falls_back_to_raw_strings_when_vis_edges_are_missing():
    """只有 data.edges 缺失时才使用 causal-learn 原始字符串。"""
    result = {
        "data": {"nodes": [{"id": "A"}, {"id": "B"}]},
        "raw_results": {"edges": ["A --> B", "malformed"]},
    }

    edges, debug = extract_critical_edges(result)

    assert debug["source"] == "raw_results.edges"
    assert debug["candidate_edge_count"] == 2
    assert debug["normalized_edge_count"] == 1
    assert [(edge["source"], edge["target"]) for edge in edges] == [("A", "B")]


def test_empty_vis_edge_list_remains_the_authoritative_source():
    """显式空的展示边代表无边，不能被旧 raw_results 覆盖。"""
    result = {
        "data": {"edges": []},
        "raw_results": {"edges": ["A --> B"]},
    }

    edges, debug = extract_critical_edges(result)

    assert edges == []
    assert debug["source"] == "data.edges"
