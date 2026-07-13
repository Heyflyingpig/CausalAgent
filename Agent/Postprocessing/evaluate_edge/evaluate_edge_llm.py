import json
import logging
from typing import Any, Dict, List, Literal, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from Agent.llm_structured_output import with_compatible_structured_output
from Agent.causal_agent.state import CausalChatState
from Agent.knowledge_base.query_rag import get_rag_excerpt

from Agent.causal_agent.back_prompt import evaluate_edge_prompt

EdgeAction = Literal["keep", "reverse", "remove", "uncertain"]
EdgeConfidence = Literal["high", "medium", "low"]
VALID_EDGE_ACTIONS = {"keep", "reverse", "remove", "uncertain"}
VALID_EDGE_CONFIDENCES = {"high", "medium", "low"}


class EdgeDecision(BaseModel):
    """LLM 对单条候选边给出的结构化修正决策。"""

    source: str = Field(..., description="候选边的起点变量名，必须来自输入候选边")
    target: str = Field(..., description="候选边的终点变量名，必须来自输入候选边")
    action: EdgeAction = Field(
        ...,
        description="keep=保留，reverse=反转方向，remove=删除，uncertain=证据不足时保守保留",
    )
    revised_source: Optional[str] = Field(
        default=None,
        description="action=reverse 时的新起点；其他 action 可为空",
    )
    revised_target: Optional[str] = Field(
        default=None,
        description="action=reverse 时的新终点；其他 action 可为空",
    )
    reason: str = Field(..., description="该边决策的因果学理由")
    confidence: EdgeConfidence = Field(..., description="该单边决策的置信度")


class EdgeEvaluationResult(BaseModel):
    """LLM 对候选边集合的结构化评估结果。"""

    decisions: List[EdgeDecision] = Field(
        ...,
        description="每条候选边一条决策；不得新增候选边中不存在的变量",
    )
    summary: str = Field(..., description="整体修正摘要")
    confidence: EdgeConfidence = Field(
        ...,
        description="整体评估置信度",
    )


def _format_edge(edge: Dict[str, Any]) -> str:
    """把规范化边对象转换成人类可读的边描述。"""
    separator = "--" if edge.get("edge_type") == "undirected" else "-->"
    return f"{edge.get('source', '')} {separator} {edge.get('target', '')}".strip()


def _decision_key(source: str, target: str) -> str:
    """生成用于匹配 LLM 决策和候选边的稳定键。"""
    return f"{source.strip()}|||{target.strip()}"


def _serialize_edge_for_prompt(edge: Dict[str, Any]) -> Dict[str, Any]:
    """仅向 prompt 暴露必要字段，减少模型被原始对象噪声干扰的概率。"""
    return {
        "id": edge.get("id"),
        "source": edge.get("source"),
        "target": edge.get("target"),
        "edge_type": edge.get("edge_type"),
        "label": edge.get("label", ""),
    }


def _coerce_edge_action(value: Any) -> EdgeAction:
    """把模型返回的 action 归一到 EdgeAction 枚举。"""
    action = str(value or "uncertain").strip().lower()
    return action if action in VALID_EDGE_ACTIONS else "uncertain"


def _coerce_edge_confidence(value: Any) -> EdgeConfidence:
    """把模型返回的 confidence 归一到 EdgeConfidence 枚举。"""
    confidence = str(value or "low").strip().lower()
    return confidence if confidence in VALID_EDGE_CONFIDENCES else "low"


def _aggregate_confidence(decisions: List[Dict[str, Any]]) -> EdgeConfidence:
    """从单边置信度推导整体置信度，缺失或混合时偏保守。"""
    confidences = [_coerce_edge_confidence(decision.get("confidence")) for decision in decisions]
    if not confidences or "low" in confidences:
        return "low"
    if "medium" in confidences:
        return "medium"
    return "high"


def _message_content_to_text(content: Any) -> str:
    """将 LangChain 消息内容转换为可解析 JSON 的文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", item.get("content", ""))))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def _parse_json_payload(raw_payload: Any) -> Dict[str, Any]:
    """从 dict、字符串或 BaseMessage 中提取 JSON 对象。"""
    if isinstance(raw_payload, dict):
        return raw_payload

    content = getattr(raw_payload, "content", raw_payload)
    text = _message_content_to_text(content).strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()

    return json.loads(text)


def _normalize_edge_evaluation_payload(raw_payload: Any) -> EdgeEvaluationResult:
    """将模型输出的标准或近似 JSON 统一校验为 EdgeEvaluationResult。"""
    if isinstance(raw_payload, EdgeEvaluationResult):
        return raw_payload

    payload = _parse_json_payload(raw_payload)
    if "decisions" in payload:
        return EdgeEvaluationResult.model_validate(payload)

    raw_edges = payload.get("edges")
    if not isinstance(raw_edges, list):
        return EdgeEvaluationResult.model_validate(payload)

    decisions = []
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            continue

        revised_edges = raw_edge.get("revised_edges")
        revised_edge = revised_edges[0] if isinstance(revised_edges, list) and revised_edges else {}
        decisions.append(
            {
                "source": raw_edge.get("source", ""),
                "target": raw_edge.get("target", ""),
                "action": _coerce_edge_action(raw_edge.get("action")),
                "revised_source": raw_edge.get("revised_source", revised_edge.get("source")),
                "revised_target": raw_edge.get("revised_target", revised_edge.get("target")),
                "reason": raw_edge.get("reason", "模型返回 edges 近似结构，已规范化为标准决策。"),
                "confidence": _coerce_edge_confidence(raw_edge.get("confidence")),
            }
        )

    summary_items = [
        f"{decision['source']}->{decision['target']}: {decision['action']}"
        for decision in decisions
    ]
    normalized_payload = {
        "decisions": decisions,
        "summary": "模型返回 edges 近似结构，已规范化为 EdgeEvaluationResult。"
        + (" " + "；".join(summary_items) if summary_items else ""),
        "confidence": _aggregate_confidence(decisions),
    }
    return EdgeEvaluationResult.model_validate(normalized_payload)


def _parse_structured_evaluation_output(raw_output: Any) -> EdgeEvaluationResult:
    """解析 include_raw=True 的结构化输出，必要时从 raw 内容做兼容规范化。"""
    if isinstance(raw_output, EdgeEvaluationResult):
        return raw_output

    if isinstance(raw_output, dict):
        parsed = raw_output.get("parsed")
        if isinstance(parsed, EdgeEvaluationResult):
            return parsed

        raw_message = raw_output.get("raw")
        if raw_message is not None:
            return _normalize_edge_evaluation_payload(raw_message)

    return _normalize_edge_evaluation_payload(raw_output)


def _build_fallback_evaluation(
    normalized_edges: List[Dict[str, Any]],
    *,
    reason: str = "",
) -> Dict[str, Any]:
    """LLM 失败或没有候选边时保守保留原边，并返回完整兼容字段。"""
    kept_edges = [_serialize_edge_for_prompt(edge) for edge in normalized_edges]
    readable_edges = [_format_edge(edge) for edge in kept_edges]
    return {
        "schema_version": "edge_evaluation_v2",
        "decisions": [
            {
                "source": edge.get("source"),
                "target": edge.get("target"),
                "action": "keep",
                "revised_source": edge.get("source"),
                "revised_target": edge.get("target"),
                "reason": reason or "未执行 LLM 评估，保守保留原边。",
                "confidence": "low",
            }
            for edge in normalized_edges
        ],
        "revised_edges": kept_edges,
        "revision_summary": reason or "未执行 LLM 评估，保守保留原边。",
        "confidence": "low",
        "decision": readable_edges,
        "reason": reason or "未执行 LLM 评估，保守保留原边。",
    }


def _apply_edge_decisions(
    normalized_edges: List[Dict[str, Any]],
    evaluation: EdgeEvaluationResult,
) -> Dict[str, Any]:
    """校验并应用 LLM 决策，生成新结构和旧字段兼容输出。"""
    decisions_by_edge = {
        _decision_key(decision.source, decision.target): decision
        for decision in evaluation.decisions
    }
    revised_edges: List[Dict[str, Any]] = []
    applied_decisions: List[Dict[str, Any]] = []

    for edge in normalized_edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        decision = decisions_by_edge.get(_decision_key(source, target))

        if decision is None:
            decision = EdgeDecision(
                source=source,
                target=target,
                action="keep",
                revised_source=source,
                revised_target=target,
                reason="LLM 未返回该边的决策，保守保留原边。",
                confidence="low",
            )

        applied = decision.model_dump()
        if decision.action == "remove":
            applied_decisions.append(applied)
            continue

        revised_edge = _serialize_edge_for_prompt(edge)
        if decision.action == "reverse":
            # 反转端点只能由原始候选边确定，不能信任模型自报的新节点名。
            revised_source = target
            revised_target = source
            revised_edge["source"] = revised_source
            revised_edge["target"] = revised_target
            revised_edge["edge_type"] = "directed"
            revised_edge["label"] = ""
            applied["revised_source"] = revised_source
            applied["revised_target"] = revised_target
        else:
            applied["revised_source"] = source
            applied["revised_target"] = target

        revised_edges.append(revised_edge)
        applied_decisions.append(applied)

    readable_edges = [_format_edge(edge) for edge in revised_edges]
    return {
        "schema_version": "edge_evaluation_v2",
        "decisions": applied_decisions,
        "revised_edges": revised_edges,
        "revision_summary": evaluation.summary,
        "confidence": evaluation.confidence,
        "decision": readable_edges,
        "reason": evaluation.summary,
    }


def evaluate_edges_with_llm(
        critical_edges: List[Dict[str, Any]],
        state: CausalChatState,
        llm: ChatOpenAI
    ) -> Dict[str, Any]:
    """
    使用 LLM 评估候选边的合理性，并返回规范化后的修正结果。
    
    Args:
        critical_edges: 已由 edge_utils 规范化的候选边列表
        state: 当前状态
        llm: LangChain 的 ChatOpenAI 实例
        
    Returns:
        包含 schema_version、decisions、revised_edges、revision_summary 的字典；
        同时保留 decision/reason 旧字段，兼容已有报告 prompt。
    """
    if not critical_edges:
        logging.info("没有关键边需要评估")
        return _build_fallback_evaluation([], reason="没有关键边需要评估。")
    
    analysis_parameters = state.get("analysis_parameters", "无可用数据摘要")
    knowledge_base_result = state.get("knowledge_base_result", {})
    knowledge_excerpt = get_rag_excerpt(knowledge_base_result, max_chars=500)

    logging.info(f"开始LLM评估 {len(critical_edges)} 条关键边...")
    try:
        edge_evaluation_prompt = ChatPromptTemplate.from_messages([
            ("system", """{causal_reviewer_role}

你现在只负责“因果图候选边后处理评估”，必须基于候选边集合逐条给出结构化决策。

# 候选边 JSON
{candidate_edges_json}

# 数据特征摘要 JSON
{data_profile_json}

# 相关领域知识
{domain_knowledge_excerpt}

# 决策约束
1. 必须为每条候选边返回一条 decision，不要遗漏。
2. 不得发明候选边以外的变量名。
3. 除非方向明显违背时间顺序、领域知识或因果图理论，否则 action 使用 keep。
4. 如果证据不足，action 使用 uncertain，并在 revised_edges 中保守保留原边。
5. 只有在明确不合理时才使用 reverse 或 remove，并写清楚理论依据。
6. 输出必须严格遵循 EdgeEvaluationResult 结构。
7. 只返回一个 JSON 对象，不要输出 Markdown、代码块或额外解释。

# 唯一允许的顶层 JSON 结构
{{
  "decisions": [
    {{
      "source": "候选边的原始起点",
      "target": "候选边的原始终点",
      "action": "keep | reverse | remove | uncertain",
      "revised_source": "reverse 时的新起点；其他情况可等于 source",
      "revised_target": "reverse 时的新终点；其他情况可等于 target",
      "reason": "该边决策的因果学理由",
      "confidence": "high | medium | low"
    }}
  ],
  "summary": "整体修正摘要",
  "confidence": "high | medium | low"
}}

禁止把顶层字段写成 edges、revised_edges、result 或 data。"""),
            ("human", "请评估候选边并返回结构化结果。"),
        ])

        runnable = (
            edge_evaluation_prompt
            | with_compatible_structured_output(llm, EdgeEvaluationResult, include_raw=True)
        ).with_config({
            "run_name": "postprocess_edge_evaluation",
            "tags": ["postprocess", "edge-evaluation"],
            "metadata": {
                "algorithm": state.get("causal_analysis_result", {}).get("algorithm"),
                "critical_edge_count": len(critical_edges),
            },
        })
        
        raw_evaluation = runnable.invoke({
            "candidate_edges_json": json.dumps(
                [_serialize_edge_for_prompt(edge) for edge in critical_edges],
                ensure_ascii=False,
                indent=2,
            ),
            "data_profile_json": json.dumps(analysis_parameters, ensure_ascii=False, indent=2),
            "domain_knowledge_excerpt": knowledge_excerpt,
            "causal_reviewer_role": evaluate_edge_prompt(),
        })
        evaluation = _parse_structured_evaluation_output(raw_evaluation)
        
        result = _apply_edge_decisions(critical_edges, evaluation)
        logging.info(
            "边评估完成: revised_edges=%s, summary=%s",
            result["decision"],
            result["revision_summary"][:80],
        )
        return result
        
    except Exception as e:
        logging.error(f"评估边 {critical_edges} 时发生错误: {e}", exc_info=True)
        return _build_fallback_evaluation(
            critical_edges,
            reason=f"LLM 边评估失败，已保守保留原边：{e}",
        )
