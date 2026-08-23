import json
import re
from typing import Any, Dict, List, Optional, Tuple

EdgeRecord = Dict[str, Any]


def _make_edge_record(
    *,
    source: str,
    target: str,
    edge_type: str,
    raw_edge: Any,
    index: int,
    label: Optional[str] = None,
    weight: Optional[float] = None,
) -> EdgeRecord:
    """构造后处理链路内部统一使用的边对象，避免在 prompt 和返回值中混用字符串/dict。"""
    record = {
        "id": f"edge_{index}",
        "source": source,
        "target": target,
        "edge_type": edge_type,
        "label": label or "",
        "raw_edge": raw_edge,
        "original_index": index,
    }
    if weight is not None:
        record["weight"] = weight
    return record


def _parse_edge_string(raw_edge: Any, index: int) -> Optional[EdgeRecord]:
    """把 causal-learn/raw_results 中的边字符串解析为统一边对象。"""
    text = str(raw_edge).strip()
    if not text:
        return None

    edge_match = re.match(
        r"^(.+?)\s*(<->|o->|<-o|-->|<--|o-o|o--|--o|---|--)\s*(.+?)$",
        text,
    )
    if edge_match:
        left = edge_match.group(1).strip()
        connector = edge_match.group(2)
        right = edge_match.group(3).strip()

        if connector == "<--":
            source, target, edge_type = right, left, "directed"
        elif connector == "<-o":
            source, target, edge_type = right, left, "partially_oriented"
        elif connector == "<->":
            source, target, edge_type = left, right, "bidirected"
        elif connector == "o->":
            source, target, edge_type = left, right, "partially_oriented"
        elif connector == "-->":
            source, target, edge_type = left, right, "directed"
        else:
            source, target, edge_type = left, right, "undirected"

        return _make_edge_record(
            source=source,
            target=target,
            edge_type=edge_type,
            raw_edge=raw_edge,
            index=index,
            label=text,
        )

    return _make_edge_record(
        source=text,
        target="",
        edge_type="unknown",
        raw_edge=raw_edge,
        index=index,
        label=text,
    )


def _parse_vis_edge(raw_edge: Dict[str, Any], index: int) -> Optional[EdgeRecord]:
    """把前端 vis-network 格式边对象解析为统一边对象。"""
    from_node = str(raw_edge.get("from", "")).strip()
    to_node = str(raw_edge.get("to", "")).strip()
    if not from_node or not to_node:
        return None

    arrows = str(raw_edge.get("arrows", "") or "")
    if "to" in arrows and "from" in arrows:
        source, target, edge_type = from_node, to_node, "bidirected"
    elif "from" in arrows:
        source, target, edge_type = to_node, from_node, "directed"
    elif "to" in arrows:
        source, target, edge_type = from_node, to_node, "directed"
    else:
        source, target, edge_type = from_node, to_node, "undirected"

    if raw_edge.get("dashes") and edge_type == "directed":
        edge_type = "partially_oriented"

    raw_weight = raw_edge.get("weight")
    weight = (
        float(raw_weight)
        if isinstance(raw_weight, (int, float)) and not isinstance(raw_weight, bool)
        else None
    )

    return _make_edge_record(
        source=source,
        target=target,
        edge_type=edge_type,
        raw_edge=raw_edge,
        index=index,
        label=str(raw_edge.get("label", "") or ""),
        weight=weight,
    )


def _normalize_edges(raw_edges: List[Any]) -> List[EdgeRecord]:
    """把候选边列表规范化，过滤掉无法定位端点的异常边。"""
    normalized_edges: List[EdgeRecord] = []
    for index, raw_edge in enumerate(raw_edges):
        if isinstance(raw_edge, dict):
            edge = _parse_vis_edge(raw_edge, index)
        else:
            edge = _parse_edge_string(raw_edge, index)

        if edge and edge.get("source") and edge.get("target"):
            normalized_edges.append(edge)

    return normalized_edges


def extract_critical_edges(analysis_result: Any) -> Tuple[List[EdgeRecord], Dict[str, Any]]:
    """
    从因果分析结果中提取并规范化需要进入后处理评估的候选边。

    返回值始终是 EdgeRecord 列表，而不是 raw string 或 vis edge dict，避免 LLM prompt、
    结构化输出和后续报告消费方对边格式产生分歧。
    """
    debug_info: Dict[str, Any] = {
        "input_type": type(analysis_result).__name__,
        "algorithm": None,
        "source": None,
        "candidate_edge_count": 0,
        "normalized_edge_count": 0,
        "reason": "",
    }

    if isinstance(analysis_result, str):
        try:
            analysis_result = json.loads(analysis_result)
            debug_info["input_type"] = "str_json"
        except json.JSONDecodeError:
            debug_info["reason"] = "causal_analysis_result 是字符串，但不是有效 JSON"
            return [], debug_info

    if not isinstance(analysis_result, dict):
        debug_info["reason"] = "causal_analysis_result 不是 dict"
        return [], debug_info

    debug_info["algorithm"] = analysis_result.get("algorithm")

    raw_edges = analysis_result.get("data", {}).get("edges")
    if isinstance(raw_edges, list):
        debug_info["source"] = "data.edges"
    else:
        raw_edges = analysis_result.get("raw_results", {}).get("edges")
        if isinstance(raw_edges, list):
            debug_info["source"] = "raw_results.edges"

    if not isinstance(raw_edges, list):
        debug_info["reason"] = "未找到 data.edges 或 raw_results.edges"
        return [], debug_info

    normalized_edges = _normalize_edges(raw_edges)
    debug_info["candidate_edge_count"] = len(raw_edges)
    debug_info["normalized_edge_count"] = len(normalized_edges)
    if raw_edges and not normalized_edges:
        debug_info["reason"] = "候选边存在，但无法规范化为 source/target 格式"

    return normalized_edges, debug_info
