import json
import sys
from pathlib import Path
from typing import Any, Dict, List

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[4]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from phoenix.otel import OpenInferenceSpanKindValues, SpanAttributes, register


RAG_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = RAG_DIR / "output"
MACHINE_OUTPUT_DIR = OUTPUT_DIR / "machine"
DEFAULT_TRACE_JSONL_PATH = MACHINE_OUTPUT_DIR / "trace.jsonl"

# 本地手动运行时优先改这里。
#phoenix serve
# Phoenix 服务启动后，截图里的 HTTP collector 一般是 http://localhost:6006/v1/traces。
PHOENIX_EXPORT_CONFIG = {
    "trace_jsonl_path": str(DEFAULT_TRACE_JSONL_PATH),
    "endpoint": "http://localhost:6006/v1/traces",
    "project_name": "causal-agent-rag-eval",
    "protocol": "http/protobuf",
    "limit": None,
    "print_full_output": False,
}


def _load_trace_rows(path: Path, limit: int | None) -> List[Dict[str, Any]]:
    """读取本地 trace.jsonl。"""
    rows = []
    with path.open("r", encoding="utf-8-sig") as file:
        for line in file:
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if limit is not None and len(rows) >= limit:
                break
    return rows


def _json_attr(value: Any) -> str:
    """把复杂对象转成 span attribute 可安全保存的 JSON 字符串。"""
    return json.dumps(value, ensure_ascii=False, default=str)


def _set_common_span_attrs(span: Any, trace: Dict[str, Any]) -> None:
    """写入所有 span 都需要的公共属性。"""
    span.set_attribute("rag.trace_id", trace.get("trace_id", ""))
    span.set_attribute("rag.question_index", trace.get("question_index", 0))
    span.set_attribute("rag.question_type", trace.get("question_type", ""))
    span.set_attribute("rag.is_bad_case", bool(trace.get("bad_case", {}).get("is_bad_case", False)))


def _set_score_attrs(span: Any, trace: Dict[str, Any]) -> None:
    """把 Ragas / claim eval 分数写入 span attribute。"""
    ragas_scores = trace.get("ragas_scores", {})
    claim_eval = trace.get("claim_eval", {})
    for metric_name in ["faithfulness", "answer_relevancy", "context_utilization", "context_recall"]:
        value = ragas_scores.get(metric_name)
        if isinstance(value, (int, float)):
            span.set_attribute(f"ragas.{metric_name}", value)
    for metric_name in ["claim_coverage", "evidence_support_rate", "unsupported_answer_claim_count"]:
        value = claim_eval.get(metric_name)
        if isinstance(value, (int, float)):
            span.set_attribute(f"claim_eval.{metric_name}", value)
    span.set_attribute("claim_eval.status", claim_eval.get("claim_eval_status", ""))
    span.set_attribute("claim_eval.judge_failed", bool(claim_eval.get("judge_failed", False)))


def _export_single_trace(tracer: Any, trace: Dict[str, Any]) -> None:
    """把单条本地 RAG trace 导出成 Phoenix/OpenInference spans。"""
    generation = trace.get("generation", {})
    retrieval_eval = trace.get("retrieval_eval", {})
    ragas_scores = trace.get("ragas_scores", {})
    claim_eval = trace.get("claim_eval", {})
    bad_case = trace.get("bad_case", {})

    with tracer.start_as_current_span(f"rag.eval.{trace.get('trace_id', '')}") as root_span:
        root_span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND, OpenInferenceSpanKindValues.CHAIN.value)
        root_span.set_attribute(SpanAttributes.INPUT_VALUE, trace.get("question", ""))
        root_span.set_attribute(SpanAttributes.OUTPUT_VALUE, generation.get("answer", ""))
        _set_common_span_attrs(root_span, trace)
        _set_score_attrs(root_span, trace)
        root_span.set_attribute("rag.expected_claims", _json_attr(trace.get("expected_claims", [])))
        root_span.set_attribute("rag.reference_answer", trace.get("reference_answer", ""))
        root_span.set_attribute("rag.bad_case.sources", _json_attr([case.get("source", "") for case in bad_case.get("cases", [])]))
        root_span.set_attribute("rag.bad_case.details", _json_attr(bad_case.get("cases", [])))

        with tracer.start_as_current_span("retrieval.eval") as retrieval_span:
            retrieval_span.set_attribute(
                SpanAttributes.OPENINFERENCE_SPAN_KIND,
                OpenInferenceSpanKindValues.RETRIEVER.value,
            )
            retrieval_span.set_attribute(SpanAttributes.INPUT_VALUE, trace.get("question", ""))
            retrieval_span.set_attribute(SpanAttributes.OUTPUT_VALUE, _json_attr(generation.get("retrieved_context_ids", [])))
            _set_common_span_attrs(retrieval_span, trace)
            retrieval_span.set_attribute("retrieval.has_gold_eval", bool(retrieval_eval.get("has_retrieval_eval", False)))
            for metric_name in ["recall", "reciprocal_rank"]:
                value = retrieval_eval.get(metric_name)
                if isinstance(value, (int, float)):
                    retrieval_span.set_attribute(f"retrieval.{metric_name}", value)
            retrieval_span.set_attribute("retrieval.loss_reasons", _json_attr(retrieval_eval.get("loss_reasons", [])))
            retrieval_span.set_attribute("retrieval.stage_results", _json_attr(retrieval_eval.get("stage_results", [])))
            retrieval_span.set_attribute("retrieval.final_context_ids", _json_attr(generation.get("retrieved_context_ids", [])))
            retrieval_span.set_attribute("retrieval.context_previews", _json_attr(generation.get("context_previews", [])))

        with tracer.start_as_current_span("generation.answer") as generation_span:
            generation_span.set_attribute(
                SpanAttributes.OPENINFERENCE_SPAN_KIND,
                OpenInferenceSpanKindValues.LLM.value,
            )
            generation_span.set_attribute(SpanAttributes.INPUT_VALUE, trace.get("question", ""))
            generation_span.set_attribute(SpanAttributes.OUTPUT_VALUE, generation.get("answer", ""))
            _set_common_span_attrs(generation_span, trace)
            generation_span.set_attribute("generation.answer_status", generation.get("answer_status", ""))
            generation_span.set_attribute("generation.answer_confidence", generation.get("answer_confidence", ""))
            generation_span.set_attribute("generation.citations", _json_attr(generation.get("citations", [])))
            generation_span.set_attribute("generation.final_evidence_payload", _json_attr(generation.get("final_evidence_payload", [])))

        with tracer.start_as_current_span("ragas.eval") as ragas_span:
            ragas_span.set_attribute(
                SpanAttributes.OPENINFERENCE_SPAN_KIND,
                OpenInferenceSpanKindValues.EVALUATOR.value,
            )
            ragas_span.set_attribute(SpanAttributes.INPUT_VALUE, trace.get("question", ""))
            ragas_span.set_attribute(SpanAttributes.OUTPUT_VALUE, _json_attr(ragas_scores))
            _set_common_span_attrs(ragas_span, trace)
            _set_score_attrs(ragas_span, trace)
            ragas_span.set_attribute("ragas.metric_run_values", _json_attr(ragas_scores.get("metric_run_values", {})))

        with tracer.start_as_current_span("claim.eval") as claim_span:
            claim_span.set_attribute(
                SpanAttributes.OPENINFERENCE_SPAN_KIND,
                OpenInferenceSpanKindValues.EVALUATOR.value,
            )
            claim_span.set_attribute(SpanAttributes.INPUT_VALUE, trace.get("question", ""))
            claim_span.set_attribute(SpanAttributes.OUTPUT_VALUE, _json_attr(claim_eval))
            _set_common_span_attrs(claim_span, trace)
            _set_score_attrs(claim_span, trace)
            claim_span.set_attribute("claim_eval.missing_claims", _json_attr(claim_eval.get("missing_claims", [])))
            claim_span.set_attribute(
                "claim_eval.unsupported_answer_claims",
                _json_attr(claim_eval.get("unsupported_answer_claims", [])),
            )
            claim_span.set_attribute("claim_eval.claim_results", _json_attr(claim_eval.get("claim_results", [])))


def export_traces_to_phoenix_from_code_config() -> Dict[str, Any]:
    """读取本地 trace.jsonl 并导出到正在运行的 Phoenix 服务。"""
    trace_path = Path(PHOENIX_EXPORT_CONFIG["trace_jsonl_path"])
    trace_rows = _load_trace_rows(trace_path, PHOENIX_EXPORT_CONFIG.get("limit"))
    tracer_provider = register(
        endpoint=PHOENIX_EXPORT_CONFIG["endpoint"],
        project_name=PHOENIX_EXPORT_CONFIG["project_name"],
        protocol=PHOENIX_EXPORT_CONFIG["protocol"],
        batch=False,
        auto_instrument=False,
        verbose=False,
    )
    tracer = tracer_provider.get_tracer(__name__)

    for trace in trace_rows:
        _export_single_trace(tracer, trace)

    return {
        "status": "pass",
        "project_name": PHOENIX_EXPORT_CONFIG["project_name"],
        "endpoint": PHOENIX_EXPORT_CONFIG["endpoint"],
        "trace_count": len(trace_rows),
        "trace_jsonl_path": str(trace_path.resolve()),
    }


if __name__ == "__main__":
    output = export_traces_to_phoenix_from_code_config()
    print(json.dumps(output, ensure_ascii=False, indent=2))

