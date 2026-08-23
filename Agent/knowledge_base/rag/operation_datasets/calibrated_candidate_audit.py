"""基于校准标签的候选题语义审核；输出清单，不直接写 Gold。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from Agent.knowledge_base.rag.operation_datasets.candidate_generation import load_staged_unit_records
from Agent.knowledge_base.rag.operation_datasets.benchmark_v2 import _question_quality_flags
from Agent.knowledge_base.rag.rag_eval.contracts import load_eval_dataset_bundle


AUDIT_SCHEMA = "rag_calibrated_candidate_audit_v1"
REVIEW_SCHEMA = "rag_candidate_review_v1"
MIN_APPROVAL_CONFIDENCE = 0.85
MAX_REMOTE_AUDIT_WORKERS = 4
Reviewer = Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]]
Rewriter = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _normalized_question(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _candidate_is_in_scope(sample: dict[str, Any], *, governance_only: bool) -> bool:
    source = sample.get("source") if isinstance(sample.get("source"), dict) else {}
    if not source.get("generator"):
        return False
    return not governance_only or source.get("origin") == "governance_replacement"


def _evidence_for_sample(sample: dict[str, Any], records_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for locator in sample.get("gold_evidence") or []:
        if not isinstance(locator, dict):
            continue
        record = records_by_id.get(str(locator.get("unit_id") or ""))
        if record is None:
            continue
        evidence.append({
            "unit_id": record.get("unit_id"),
            "content": str(record.get("content") or "")[:6000],
        })
    return evidence


def _bound_locator(record: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any] | None:
    metadata = dict(record.get("metadata") or {})
    locator = {
        "unit_id": record.get("unit_id"),
        "document_id": metadata.get("document_id"),
        "page_number": metadata.get("page_number"),
        "modality": record.get("modality"),
        "content_kind": record.get("content_kind"),
        "bound_index_version": snapshot.get("index_version"),
    }
    if not locator["unit_id"] or not locator["document_id"] or not locator["bound_index_version"]:
        return None
    return {key: value for key, value in locator.items() if value not in (None, "")}


def _hard_fail_flags(sample: dict[str, Any]) -> list[str]:
    """拦截不依赖模型推理即可确定的题目-证据违约。"""
    question = str(sample.get("question") or "")
    answer = str(sample.get("reference_answer") or "")
    source = sample.get("source") if isinstance(sample.get("source"), dict) else {}
    evidence_count = len(sample.get("gold_evidence") or [])
    normalized = " ".join(question.split()).casefold()
    flags = [
        flag for flag in _question_quality_flags(question)
        if flag != "multi_figure_or_table_comparison"
    ]
    if re.search(r"\btype of (?:the )?document\b|\bis of type\b", normalized):
        flags.append("parser_metadata_as_domain_knowledge")
    if re.search(r"\bwhat the heck\b", normalized):
        flags.append("unprofessional_question_wording")
    if re.search(r"\bhow many\b", normalized) and "%" in answer:
        flags.append("question_answer_unit_mismatch")
    if evidence_count > 1 and re.search(
        r"\b(relate|support|illustrate|suggest|mechanism|infer|implication|why)\b",
        f"{question} {answer}".casefold(),
    ):
        flags.append("cross_evidence_inference_requires_rewrite")
    if source.get("origin") == "evidence_seed":
        flags.append("evidence_seed_requires_rewrite")
    return sorted(set(flags))


def _decision_from_review(review: dict[str, Any], evidence: list[dict[str, Any]]) -> tuple[str, list[str]]:
    required = {
        "verdict",
        "direct_entailment",
        "unsupported_inference",
        "cross_evidence_relation",
        "question_quality",
        "answer_scope",
        "metric_contract",
        "confidence",
        "reason",
        "supporting_quotes",
    }
    missing = sorted(required - set(review))
    if missing:
        return "needs_revision", ["invalid_reviewer_response:" + ",".join(missing)]
    try:
        confidence = float(review["confidence"])
    except (TypeError, ValueError):
        return "needs_revision", ["invalid_reviewer_confidence"]
    failures = []
    if review.get("verdict") != "retain":
        failures.append("reviewer_verdict_not_retain")
    if review.get("direct_entailment") != "pass":
        failures.append("direct_entailment_failed")
    if review.get("unsupported_inference") is not False:
        failures.append("unsupported_inference")
    if review.get("cross_evidence_relation") not in {"not_applicable", "explicit"}:
        failures.append("cross_evidence_relation_missing")
    if review.get("question_quality") != "pass":
        failures.append("question_quality_not_pass")
    if review.get("answer_scope") != "evidence_only":
        failures.append("answer_scope_overclaim")
    if review.get("metric_contract") != "aligned":
        failures.append("metric_contract_mismatched")
    if not 0.0 <= confidence <= 1.0 or confidence < MIN_APPROVAL_CONFIDENCE:
        failures.append("reviewer_confidence_too_low")
    quotes = review.get("supporting_quotes")
    if not isinstance(quotes, list) or not quotes or not all(isinstance(quote, str) and len(quote.strip()) >= 8 for quote in quotes):
        failures.append("missing_verbatim_evidence_quote")
    else:
        def normalize(value: str) -> str:
            return re.sub(r"\s+", "", value).casefold()

        evidence_text = normalize("\n".join(str(item.get("content") or "") for item in evidence))
        if any(normalize(quote) not in evidence_text for quote in quotes):
            failures.append("evidence_quote_not_verbatim")
    return ("approved", []) if not failures else ("needs_revision", failures)


def default_calibrated_reviewer(sample: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """调用远程结构化审核器；异常由调用方转换为 fail-closed 决定。"""
    # 审核证据不应被额外发送到 LangSmith 等追踪服务。
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["LANGSMITH_TRACING"] = "false"
    from typing import Literal

    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI
    from pydantic import BaseModel, Field

    from Agent.llm_structured_output import invoke_structured
    from config.settings import settings

    class ProsecutorReview(BaseModel):
        has_defect: bool
        defect_types: list[Literal[
            "metadata_as_knowledge", "unsupported_inference", "cross_evidence_inference",
            "question_answer_mismatch", "wording", "other",
        ]]
        reason: str = Field(min_length=1, max_length=1000)

    class CalibratedReview(BaseModel):
        verdict: Literal["retain", "rewrite", "reject"]
        direct_entailment: Literal["pass", "fail"]
        unsupported_inference: bool
        cross_evidence_relation: Literal["not_applicable", "explicit", "missing"]
        question_quality: Literal["pass", "rewrite", "reject"]
        answer_scope: Literal["evidence_only", "overclaim"]
        metric_contract: Literal["aligned", "mismatched"]
        confidence: float = Field(ge=0.0, le=1.0)
        reason: str = Field(min_length=1, max_length=1000)
        supporting_quotes: list[str] = Field(min_length=1, max_length=12)

    llm = ChatOpenAI(
        api_key=settings.API_KEY,
        base_url=settings.BASE_URL,
        model=settings.MODEL,
        temperature=0,
    )
    prosecutor_prompt = ChatPromptTemplate.from_messages([
        ("system", "你是 RAG 评测题的反证审核员。任务是找出题干、参考答案或 expected_claims 不被给定 evidence 直接支持的地方。unit_id 只是定位符；不要把文件类型、页码、模态、解析结构当作知识。不同 evidence 同时出现不构成它们之间的因果、机制或解释关系。题目问人数而答案给比例、语气不专业、需要补充含义时，必须认定有缺陷。无法验证时按有缺陷处理。"),
        ("human", "sample={sample}\nevidence={evidence}"),
    ])
    inputs = {
        "sample": json.dumps(sample, ensure_ascii=False, sort_keys=True),
        "evidence": json.dumps(evidence, ensure_ascii=False, sort_keys=True),
    }
    prosecutor = invoke_structured(
        llm=llm,
        schema=ProsecutorReview,
        prompt=prosecutor_prompt,
        inputs=inputs,
        node_name="rag_calibrated_candidate_prosecutor",
    )
    verifier_prompt = ChatPromptTemplate.from_messages([
        ("system", "你是 RAG 候选评测题的严格核验员。只有当所有题干、答案和 expected_claims 都被 evidence 逐字或近乎逐字直接支持，且反证审核员未发现缺陷，才能 retain。必须给出 evidence 中的原文短引 supporting_quotes；若需要推断、解释元数据、跨 evidence 拼接关系、或题目与答案单位不一致，必须 rewrite 或 reject。宁可错拒也不可错放。"),
        ("human", "sample={sample}\nevidence={evidence}\nprosecutor={prosecutor}"),
    ])
    result = invoke_structured(
        llm=llm,
        schema=CalibratedReview,
        prompt=verifier_prompt,
        inputs={**inputs, "prosecutor": json.dumps(prosecutor.model_dump(), ensure_ascii=False, sort_keys=True)},
        node_name="rag_calibrated_candidate_verifier",
    ).model_dump()
    if prosecutor.has_defect:
        result["verdict"] = "rewrite"
        result["question_quality"] = "rewrite"
        result["reason"] = f"prosecutor: {prosecutor.reason}; verifier: {result['reason']}"
    return result


def _is_low_quality_anchor_sentence(sentence: str) -> bool:
    """识别不适合作为答案锚点的句子：公式/LaTeX 碎片与出版版本页套话。"""
    stripped = sentence.strip()
    if re.search(r"\\begin|\\frac|\\left|\\mathrm", stripped):
        return True
    symbols = len(re.findall(r"[\\|{}$&^~=<>]", stripped))
    if stripped and symbols / max(len(stripped), 1) > 0.12:
        return True
    if re.search(r"\b(?:edition|isbn|copyright|published by|press)\b|[©®™]", stripped, flags=re.IGNORECASE):
        return True
    letters = [char for char in stripped if char.isalpha()]
    if len(letters) >= 6 and all(not char.islower() for char in letters):
        return True
    usable = sum(
        1 for char in stripped
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    )
    if stripped and usable / len(stripped) < 0.5:
        return True
    return False


def _fixed_reference_answer(sample: dict[str, Any], evidence: dict[str, Any]) -> str:
    """优先复用原答案；否则截取一条证据中的完整句子。"""
    def is_parser_metadata(value: str) -> bool:
        return bool(re.match(
            r"^(?:类型|标题|文件名|页码|source|content_kind|modality)\s*[：:]",
            value.strip(),
            flags=re.IGNORECASE,
        ))

    content = str(evidence.get("content") or "").strip()
    normalized_content = re.sub(r"\s+", "", content).casefold()
    original = str(sample.get("reference_answer") or "").strip()
    if (
        len(original) >= 8
        and not is_parser_metadata(original)
        and re.sub(r"\s+", "", original).casefold() in normalized_content
    ):
        return original
    for sentence in re.split(r"(?<=[。！？.!?])\s*|\n+", content):
        sentence = sentence.strip()
        if (
            8 <= len(sentence) <= 800
            and not is_parser_metadata(sentence)
            and not _is_low_quality_anchor_sentence(sentence)
        ):
            return sentence
    return ""


def build_evidence_seed_dataset(
    *,
    index_dir: Path,
    output_path: Path,
    max_units: int,
    offset: int = 0,
) -> dict[str, Any]:
    """从文本证据构造待重写种子；种子不是可评测题集。"""
    records, snapshot = load_staged_unit_records(Path(index_dir))
    if max_units < 1 or offset < 0:
        raise ValueError("max_units must be positive and offset cannot be negative")
    samples: list[dict[str, Any]] = []
    eligible_seen = 0
    for record in records:
        if str(record.get("modality") or "") != "text":
            continue
        unit_id = str(record.get("unit_id") or "")
        answer = _fixed_reference_answer({}, {"content": record.get("content")})
        locator = _bound_locator(record, snapshot)
        if not unit_id or locator is None or len(answer) < 24:
            continue
        if eligible_seen < offset:
            eligible_seen += 1
            continue
        eligible_seen += 1
        samples.append({
            "sample_id": f"seed-{hashlib.sha256(unit_id.encode('utf-8')).hexdigest()[:12]}",
            "question": "待重写的证据事实种子，不能直接用于评测或发布。",
            "reference_answer": answer,
            "expected_claims": [answer],
            "gold_evidence": [locator],
            "source": {
                "generator": "calibrated_evidence_seed_v1",
                "origin": "evidence_seed",
                "review_status": "seed",
                "source_snapshot": snapshot,
            },
        })
        if len(samples) >= max_units:
            break
    payload = {
        "schema_version": "rag_eval_v1",
        "dataset_id": f"evidence_seed_{snapshot['index_version']}",
        "dataset_kind": "generated_candidate",
        "candidate_stage": "seed",
        "dataset_revision": f"seed_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}",
        "source_snapshot": snapshot,
        "samples": samples,
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"seed_path": str(output_path.resolve()), "seed_count": len(samples), "offset": offset, "source_snapshot": snapshot}


def default_evidence_rewriter(sample: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    """从一条已绑定证据生成单事实候选；输出仍需重新审核。"""
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI
    from pydantic import BaseModel, Field

    from Agent.llm_structured_output import invoke_structured
    from config.settings import settings

    class EvidenceRewrite(BaseModel):
        question: str = Field(min_length=35, max_length=420)

    answer = _fixed_reference_answer(sample, evidence)
    if len(answer) < 8:
        raise ValueError("evidence_has_no_usable_answer")

    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["LANGSMITH_TRACING"] = "false"
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你重写被拒的 RAG 评测题。只根据 fixed_reference_answer 生成专业、单义、单事实的问题。问题的直接答案必须是该原文；不得加入其中没有出现的文档名、表号、作者、变量、数值或其他细节，不推断因果、概率或机制。只输出问题。"),
        ("human", "fixed_reference_answer={answer}"),
    ])
    result = invoke_structured(
        llm=ChatOpenAI(api_key=settings.API_KEY, base_url=settings.BASE_URL, model=settings.MODEL, temperature=0),
        schema=EvidenceRewrite,
        prompt=prompt,
        inputs={"answer": answer},
        node_name="rag_calibrated_candidate_rewriter",
    )
    return {"question": result.question, "reference_answer": answer, "expected_claim": answer}


def rewrite_rejected_candidates(
    dataset_path: Path,
    audit_report: dict[str, Any],
    *,
    index_dir: Path,
    output_path: Path,
    rewriter: Rewriter = default_evidence_rewriter,
) -> dict[str, Any]:
    """把拒绝项重写成候选集；不冻结、不发布 Gold。"""
    dataset_path = Path(dataset_path)
    dataset = load_eval_dataset_bundle(dataset_path)
    if audit_report.get("schema_version") != AUDIT_SCHEMA or audit_report.get("dataset_sha256") != _sha256(dataset_path):
        raise ValueError("audit report must bind exactly to the source candidate dataset")
    records, snapshot = load_staged_unit_records(Path(index_dir))
    records_by_id = {str(record["unit_id"]): record for record in records}
    rejected_ids = {
        str(item.get("sample_id") or "")
        for item in audit_report.get("items") or []
        if isinstance(item, dict) and item.get("decision") == "needs_revision"
    }
    rewritten_samples: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    pending: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for original in dataset.get("samples") or []:
        sample_id = str(original.get("sample_id") or "")
        if sample_id not in rejected_ids:
            continue
        # 收集全部可解析证据锚点；单一 locator 失败时回退其余证据。
        evidence_items: list[dict[str, Any]] = []
        seen_units: set[str] = set()
        for locator in original.get("gold_evidence") or []:
            if not isinstance(locator, dict):
                continue
            for item in _evidence_for_sample({"gold_evidence": [locator]}, records_by_id):
                unit_id = str(item.get("unit_id") or "")
                if unit_id in seen_units:
                    continue
                seen_units.add(unit_id)
                evidence_items.append(item)
        if not evidence_items:
            errors.append({"sample_id": sample_id, "error": "evidence_unavailable"})
            continue
        pending.append((original, evidence_items))

    def _validated_rewrite(sample_input: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
        rewrite = rewriter(sample_input, evidence)
        question = str(rewrite.get("question") or "").strip()
        answer = str(rewrite.get("reference_answer") or "").strip()
        claim = str(rewrite.get("expected_claim") or "").strip()
        normalized_evidence = re.sub(r"\s+", "", str(evidence.get("content") or "")).casefold()
        if not question or not answer or not claim:
            raise ValueError("incomplete_rewrite")
        if claim != answer or re.sub(r"\s+", "", answer).casefold() not in normalized_evidence:
            raise ValueError("rewrite_answer_not_verbatim_evidence")
        return {"question": question, "reference_answer": answer, "expected_claim": claim}

    def rewrite_one(original: dict[str, Any], evidence_list: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        """逐个证据锚点尝试改写并校验；每个锚点最多重试两次。"""
        sample_input = {
            "sample_id": original.get("sample_id"),
            "question": original.get("question"),
            "reference_answer": original.get("reference_answer"),
            "expected_claims": original.get("expected_claims") or [],
        }
        last_error: Exception | None = None
        for evidence in evidence_list:
            for _ in range(2):
                try:
                    return _validated_rewrite(sample_input, evidence), evidence
                except Exception as exc:
                    last_error = exc
        assert last_error is not None
        raise last_error

    with ThreadPoolExecutor(max_workers=min(MAX_REMOTE_AUDIT_WORKERS, max(1, len(pending)))) as pool:
        futures = {
            pool.submit(rewrite_one, original, evidence_list): (original, evidence_list)
            for original, evidence_list in pending
        }
        for future in as_completed(futures):
            original, _evidence_list = futures[future]
            sample_id = str(original.get("sample_id") or "")
            try:
                rewrite, anchor = future.result()
            except Exception as exc:
                errors.append({
                    "sample_id": sample_id,
                    "error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                    "error_type": type(exc).__name__,
                })
                continue
            anchor_unit = str(anchor.get("unit_id") or "")
            all_locators = [item for item in original.get("gold_evidence") or [] if isinstance(item, dict)]
            locator = next(
                (item for item in all_locators if str(item.get("unit_id") or "") == anchor_unit),
                all_locators[0] if all_locators else None,
            )
            if locator is None:
                errors.append({"sample_id": sample_id, "error": "evidence_locator_missing"})
                continue
            question = rewrite["question"]
            answer = rewrite["reference_answer"]
            claim = rewrite["expected_claim"]
            source = dict(original.get("source") or {})
            source.update({
                "generator": "calibrated_evidence_rewriter_v1",
                "origin": "calibrated_rewrite_candidate",
                "review_status": "candidate",
                "rewritten_from_sample_id": sample_id,
                "source_snapshot": snapshot,
            })
            rewritten_samples.append({
                **dict(original),
                "sample_id": f"rewrite-{uuid.uuid4().hex[:12]}",
                "question": question,
                "reference_answer": answer,
                "expected_claims": [claim],
                "gold_evidence": [dict(locator)],
                "source": source,
            })
    payload = {
        "schema_version": "rag_eval_v1",
        "dataset_id": f"{dataset.get('dataset_id', 'candidate')}_rewrites",
        "dataset_kind": "generated_candidate",
        "dataset_revision": f"{dataset.get('dataset_revision', 'unversioned')}_rewrite_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}",
        "source_snapshot": snapshot,
        "samples": rewritten_samples,
        "generation_summary": {
            "requested": len(rejected_ids),
            "eligible": len(pending),
            "rewritten": len(rewritten_samples),
            "errors": errors,
        },
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"candidate_path": str(output_path.resolve()), "rewritten_count": len(rewritten_samples), "errors": errors}


def audit_candidate_dataset(
    dataset_path: Path,
    *,
    index_dir: Path,
    reviewer: Reviewer = default_calibrated_reviewer,
    governance_only: bool = False,
    sample_ids: set[str] | None = None,
) -> dict[str, Any]:
    """审核候选题并生成可冻结的 fail-closed 决策，绝不修改输入数据集。"""
    dataset_path = Path(dataset_path)
    dataset = load_eval_dataset_bundle(dataset_path)
    records, snapshot = load_staged_unit_records(Path(index_dir))
    records_by_id = {str(record["unit_id"]): record for record in records}
    items: list[dict[str, Any] | None] = []
    pending: list[tuple[int, dict[str, Any], list[dict[str, Any]]]] = []

    for sample in dataset.get("samples") or []:
        if not isinstance(sample, dict) or not _candidate_is_in_scope(sample, governance_only=governance_only):
            continue
        position = len(items)
        sample_id = str(sample.get("sample_id") or "").strip()
        if sample_ids is not None and sample_id not in sample_ids:
            continue
        evidence = _evidence_for_sample(sample, records_by_id)
        if not sample_id or not evidence:
            items.append({"sample_id": sample_id, "decision": "needs_revision", "reasons": ["evidence_unavailable"], "review": {}})
            continue
        hard_flags = _hard_fail_flags(sample)
        if hard_flags:
            items.append({
                "sample_id": sample_id,
                "decision": "needs_revision",
                "reasons": hard_flags,
                "review": {},
            })
            continue
        audit_sample = {
            "sample_id": sample_id,
            "question": sample.get("question"),
            "reference_answer": sample.get("reference_answer"),
            "expected_claims": sample.get("expected_claims") or [],
            "gold_evidence": sample.get("gold_evidence") or [],
        }
        items.append(None)
        pending.append((position, audit_sample, evidence))

    def review_one(audit_sample: dict[str, Any], evidence: list[dict[str, Any]]) -> tuple[str, list[str], dict[str, Any], bool]:
        last_error: Exception | None = None
        for _ in range(2):
            try:
                review = reviewer(audit_sample, evidence)
                if not isinstance(review, dict):
                    raise TypeError("reviewer must return an object")
                decision, reasons = _decision_from_review(review, evidence)
                return decision, reasons, review, False
            except Exception as exc:
                last_error = exc
        return "needs_revision", [f"reviewer_error:{type(last_error).__name__}"], {}, True

    with ThreadPoolExecutor(max_workers=min(MAX_REMOTE_AUDIT_WORKERS, max(1, len(pending)))) as pool:
        futures = {
            pool.submit(review_one, sample, evidence): (position, sample["sample_id"])
            for position, sample, evidence in pending
        }
        for future in as_completed(futures):
            decision, reasons, review, review_error = future.result()
            position, sample_id = futures[future]
            items[position] = {
                "sample_id": sample_id,
                "decision": decision,
                "reasons": reasons,
                "review": review,
                "review_error": review_error,
            }

    final_items = [item for item in items if item is not None]
    counts = {
        "approved": sum(item["decision"] == "approved" for item in final_items),
        "needs_revision": sum(item["decision"] == "needs_revision" for item in final_items),
        "review_errors": sum(bool(item.get("review_error")) for item in final_items),
    }

    return {
        "schema_version": AUDIT_SCHEMA,
        "reviewer": "calibrated_remote_structured_v1" if reviewer is default_calibrated_reviewer else "injected_test_reviewer",
        "dataset_id": dataset.get("dataset_id", ""),
        "dataset_revision": dataset.get("dataset_revision", ""),
        "dataset_sha256": _sha256(dataset_path),
        "index_binding": snapshot,
        "scope": "governance_replacements" if governance_only else "generated_candidates",
        "summary": {"candidate_count": len(final_items), **counts, "minimum_approval_confidence": MIN_APPROVAL_CONFIDENCE},
        "items": final_items,
    }


def build_review_manifest(report: dict[str, Any]) -> dict[str, Any]:
    """把审核报告转为冻结接口已识别的审核清单；未通过项保持 needs_revision。"""
    if report.get("schema_version") != AUDIT_SCHEMA:
        raise ValueError(f"audit report must use {AUDIT_SCHEMA}")
    return {
        "schema_version": REVIEW_SCHEMA,
        "reviewer": str(report.get("reviewer") or "calibrated_remote_structured_v1"),
        "candidate_dataset_id": report.get("dataset_id", ""),
        "candidate_dataset_revision": report.get("dataset_revision", ""),
        "candidate_sha256": report.get("dataset_sha256", ""),
        "decisions": [
            {"sample_id": item.get("sample_id", ""), "decision": item.get("decision", "needs_revision"), "note": "; ".join(item.get("reasons") or [])}
            for item in report.get("items") or []
        ],
        "review_status": "ready_for_freeze" if all(item.get("decision") == "approved" for item in report.get("items") or []) else "requires_revision",
    }


def merge_audit_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """合并同一候选集的不重叠批次审核，保留 fail-closed 决策。"""
    if not reports or any(report.get("schema_version") != AUDIT_SCHEMA for report in reports):
        raise ValueError("reports must be non-empty calibrated audit reports")
    identity = (reports[0].get("dataset_id"), reports[0].get("dataset_revision"), reports[0].get("dataset_sha256"))
    if any((report.get("dataset_id"), report.get("dataset_revision"), report.get("dataset_sha256")) != identity for report in reports):
        raise ValueError("all audit reports must bind to the same candidate dataset")
    items = [item for report in reports for item in report.get("items") or []]
    item_ids = [str(item.get("sample_id") or "") for item in items]
    if len(item_ids) != len(set(item_ids)):
        raise ValueError("audit reports contain duplicate sample decisions")
    return {
        **dict(reports[0]),
        "summary": {
            "candidate_count": len(items),
            "approved": sum(item.get("decision") == "approved" for item in items),
            "needs_revision": sum(item.get("decision") == "needs_revision" for item in items),
            "review_errors": sum(bool(item.get("review_error")) for item in items),
            "minimum_approval_confidence": MIN_APPROVAL_CONFIDENCE,
        },
        "items": items,
    }


def assemble_approved_candidate_dataset(
    batches: list[tuple[Path, Path]],
    *,
    output_path: Path,
    review_manifest_path: Path,
    target_count: int = 48,
    offset: int = 0,
) -> dict[str, Any]:
    """汇集跨批已批准候选，按题干与证据单元去重；不冻结 Gold。"""
    if target_count < 1 or offset < 0 or not batches:
        raise ValueError("target_count and batches must be non-empty")
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    binding: dict[str, Any] | None = None
    sources: list[dict[str, str]] = []
    for candidate_path, report_path in batches:
        candidate_path, report_path = Path(candidate_path), Path(report_path)
        candidate = load_eval_dataset_bundle(candidate_path)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("schema_version") != AUDIT_SCHEMA or report.get("dataset_sha256") != _sha256(candidate_path):
            raise ValueError("approved batch audit must bind exactly to its candidate dataset")
        batch_binding = dict(report.get("index_binding") or {})
        if binding is None:
            binding = batch_binding
        elif batch_binding != binding:
            raise ValueError("approved batches must bind to the same index")
        approved_ids = {str(item.get("sample_id") or "") for item in report.get("items") or [] if item.get("decision") == "approved"}
        for sample in candidate.get("samples") or []:
            if str(sample.get("sample_id") or "") not in approved_ids:
                continue
            locator_ids = tuple(sorted(str(locator.get("unit_id") or "") for locator in sample.get("gold_evidence") or [] if isinstance(locator, dict)))
            key = (_normalized_question(sample.get("question")), locator_ids)
            if not key[0] or not locator_ids or key in seen:
                continue
            seen.add(key)
            selected.append(dict(sample))
        sources.append({"candidate_path": str(candidate_path.resolve()), "audit_path": str(report_path.resolve())})
    if len(selected) < offset + target_count:
        raise ValueError(f"approved candidates are insufficient after deduplication: {len(selected)} < {offset + target_count}")
    selected = selected[offset:offset + target_count]
    payload = {
        "schema_version": "rag_eval_v1",
        "dataset_id": "pearl_gold_v2_calibrated_candidates",
        "dataset_kind": "generated_candidate",
        "dataset_revision": f"calibrated_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}",
        "source_snapshot": binding,
        "assembly": {"target_count": target_count, "offset": offset, "source_batches": sources},
        "samples": selected,
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "schema_version": AUDIT_SCHEMA,
        "reviewer": "calibrated_remote_structured_v1",
        "dataset_id": payload["dataset_id"],
        "dataset_revision": payload["dataset_revision"],
        "dataset_sha256": _sha256(output_path),
        "index_binding": binding,
        "summary": {"candidate_count": target_count, "approved": target_count, "needs_revision": 0, "review_errors": 0, "minimum_approval_confidence": MIN_APPROVAL_CONFIDENCE},
        "items": [{"sample_id": sample["sample_id"], "decision": "approved", "reasons": [], "review_error": False} for sample in selected],
    }
    review_manifest_path = Path(review_manifest_path)
    review_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    review_manifest_path.write_text(json.dumps(build_review_manifest(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"candidate_path": str(output_path.resolve()), "review_manifest_path": str(review_manifest_path.resolve()), "approved_count": target_count}


def main() -> None:
    parser = argparse.ArgumentParser(description="校准审核生成候选题；仅输出报告和审核清单，不写 Gold")
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--index-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed-max-units", type=int)
    parser.add_argument("--seed-offset", type=int, default=0)
    parser.add_argument("--approved-candidate", type=Path, action="append", default=[])
    parser.add_argument("--approved-audit", type=Path, action="append", default=[])
    parser.add_argument("--approved-limit", type=int, default=48)
    parser.add_argument("--approved-offset", type=int, default=0)
    parser.add_argument("--approved-manifest-output", type=Path)
    parser.add_argument("--review-manifest-output", type=Path)
    parser.add_argument("--rewrite-output", type=Path)
    parser.add_argument("--input-audit-report", type=Path)
    parser.add_argument("--merge-audit-report", type=Path, action="append", default=[])
    parser.add_argument("--sample-id", action="append", default=[])
    parser.add_argument("--governance-only", action="store_true")
    args = parser.parse_args()
    if args.approved_candidate or args.approved_audit:
        if len(args.approved_candidate) != len(args.approved_audit) or not args.approved_manifest_output:
            parser.error("approved assembly requires matching --approved-candidate/--approved-audit and --approved-manifest-output")
        print(json.dumps(assemble_approved_candidate_dataset(
            list(zip(args.approved_candidate, args.approved_audit)),
            output_path=args.output,
            review_manifest_path=args.approved_manifest_output,
            target_count=args.approved_limit,
            offset=args.approved_offset,
        ), ensure_ascii=False, indent=2))
        return
    if args.seed_max_units is not None:
        if args.rewrite_output or args.review_manifest_output or args.input_audit_report or args.merge_audit_report:
            parser.error("seed generation cannot be combined with audit or rewrite options")
        print(json.dumps(build_evidence_seed_dataset(
            index_dir=args.index_dir,
            output_path=args.output,
            max_units=args.seed_max_units,
            offset=args.seed_offset,
        ), ensure_ascii=False, indent=2))
        return
    if args.dataset is None:
        parser.error("--dataset is required unless --seed-max-units is used")
    report = (
        merge_audit_reports([json.loads(path.read_text(encoding="utf-8")) for path in args.merge_audit_report])
        if args.merge_audit_report
        else json.loads(args.input_audit_report.read_text(encoding="utf-8"))
        if args.input_audit_report
        else audit_candidate_dataset(
            args.dataset,
            index_dir=args.index_dir,
            governance_only=args.governance_only,
            sample_ids=set(args.sample_id) if args.sample_id else None,
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.review_manifest_output:
        args.review_manifest_output.parent.mkdir(parents=True, exist_ok=True)
        args.review_manifest_output.write_text(json.dumps(build_review_manifest(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.rewrite_output:
        rewrite_rejected_candidates(
            args.dataset,
            report,
            index_dir=args.index_dir,
            output_path=args.rewrite_output,
        )


if __name__ == "__main__":
    main()
