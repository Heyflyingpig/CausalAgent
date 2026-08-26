import json
import os
import re
import sys
import time
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Literal, Optional

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[4]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Windows 上 numpy 与 torch 各自带 libiomp，同时导入会触发 OpenMP 重复初始化。
# 在加载任何可能链接 OpenMP 的库之前设置；setdefault 不覆盖用户显式设置。
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from config.settings import settings
from Agent.knowledge_base.rag.tools.report_utils import (
    build_claim_eval_markdown_report,
    write_markdown_file,
)
from config.rag_eval_paths import RAG_EVAL_MACHINE_OUTPUT_DIR as MACHINE_OUTPUT_DIR
from config.rag_eval_paths import RAG_EVAL_REPORT_OUTPUT_DIR as REPORT_OUTPUT_DIR
DEFAULT_RAGAS_RESULT_PATH = MACHINE_OUTPUT_DIR / "ragas_eval_result.json"
DEFAULT_OUTPUT_PATH = MACHINE_OUTPUT_DIR / "claim_eval_result.json"
DEFAULT_REPORT_PATH = REPORT_OUTPUT_DIR / "claim_eval_report.md"
DEFAULT_BAD_CASES_PATH = MACHINE_OUTPUT_DIR / "claim_eval_bad_cases.json"

# 本地手动运行时优先改这里。
# Phase4 claim eval 消费 Phase3 的 Ragas prepared result，不重新跑 retrieval。
# limit=None 表示评估所有 Ragas 样本；早期调试可设为 3、5 或 10。
CLAIM_EVAL_CONFIG = {
    "ragas_result_path": str(DEFAULT_RAGAS_RESULT_PATH),
    "output_path": str(DEFAULT_OUTPUT_PATH),
    "report_path": str(DEFAULT_REPORT_PATH),
    "bad_cases_path": str(DEFAULT_BAD_CASES_PATH),
    "limit": None,
    "run_llm_judge": True,
    "save_output": True,
    "save_markdown": True,
    "max_context_chars": 700,
    "max_answer_chars": 1200,
    "low_claim_coverage_threshold": 0.7,
    "judge_max_retries": 2,
    "retry_sleep_seconds": 2.0,
}


class ClaimJudgement(BaseModel):
    """单个 expected claim 的覆盖和证据支撑判断。"""

    claim: str = Field(..., description="被评估的 expected claim。")
    answer_covered: bool = Field(..., description="RAG answer 是否覆盖该 claim。")
    evidence_supported: bool = Field(..., description="final evidence 是否足以支撑该 claim。")
    reason: str = Field(default="", description="简短判定理由。")
    evidence_ids: List[str] = Field(default_factory=list, description="支撑该 claim 的证据 ID。")


class ClaimEvalLLMResult(BaseModel):
    """LLM judge 对单题 claim 质量的结构化输出。"""

    status: Literal["pass", "needs_review"] = Field(..., description="该题是否需要人工复查。")
    claim_results: List[ClaimJudgement] = Field(default_factory=list)
    unsupported_answer_claims: List[str] = Field(
        default_factory=list,
        description="answer 中出现但 final evidence 未支撑的重要断言。",
    )
    overall_notes: str = Field(default="", description="整体评估说明。")


def _ensure_parent_dir(path: Path) -> None:
    """确保输出文件所在目录存在。"""
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_json_file(path: Path, data: Dict[str, Any]) -> None:
    """写入机器可读 JSON。"""
    _ensure_parent_dir(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json_file(path: Path) -> Dict[str, Any]:
    """读取 JSON 文件。"""
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def _truncate_text(text: str, max_chars: Optional[int]) -> str:
    """限制送入 claim judge 的 answer/context 长度。"""
    if max_chars is None or max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _extract_json_object(text: str) -> Dict[str, Any]:
    """从 LLM 普通文本输出中提取 JSON 对象。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _build_claim_eval_prompt() -> ChatPromptTemplate:
    """构造 claim eval 的 LLM judge prompt。"""
    return ChatPromptTemplate.from_template(
        """
你是一个严谨的 RAG 评测 judge。你的任务是评估 RAG answer 是否覆盖 expected claims，
以及这些 claims 是否被 final evidence 支撑。不要评价写作风格，只评价证据忠实性和 claim 覆盖。

# Question
{question}

# Reference answer
{reference_answer}

# Expected claims
{expected_claims}

# RAG answer
{answer}

# Final evidence
{evidence_blocks}

# Judge rubric
{judge_rubric}

# 输出要求
只输出 JSON，不要输出额外解释。JSON schema:
{{
  "status": "pass 或 needs_review",
  "claim_results": [
    {{
      "claim": "原始 expected claim",
      "answer_covered": true,
      "evidence_supported": true,
      "reason": "一句话理由",
      "evidence_ids": ["C1"]
    }}
  ],
  "unsupported_answer_claims": ["answer 中缺少 evidence 支撑的重要断言"],
  "overall_notes": "整体说明"
}}
"""
    )


def _build_judge_llm() -> ChatOpenAI:
    """构造 claim eval 使用的 OpenAI-compatible judge LLM。"""
    return ChatOpenAI(
        api_key=settings.API_KEY,
        base_url=settings.BASE_URL,
        model_name=settings.MODEL,
        temperature=0,
    )


def _format_evidence_blocks(contexts: List[str], evidence_ids: List[str], max_context_chars: int) -> str:
    """把 Ragas retrieved contexts 转成 judge prompt 中的证据块。"""
    blocks = []
    for index, context in enumerate(contexts, start=1):
        evidence_id = evidence_ids[index - 1] if index - 1 < len(evidence_ids) else f"E{index}"
        blocks.append(
            f"[E{index}]\n"
            f"evidence_id: {evidence_id}\n"
            f"content: {_truncate_text(context, max_context_chars)}"
        )
    return "\n\n".join(blocks) if blocks else "No final evidence."


def _parse_claim_eval_result(text: str) -> ClaimEvalLLMResult:
    """把 LLM 输出解析为 ClaimEvalLLMResult。"""
    data = _extract_json_object(text)
    return ClaimEvalLLMResult.model_validate(data)


def _run_claim_judge(
    question: str,
    answer: str,
    contexts: List[str],
    evidence_ids: List[str],
    expected_claims: List[str],
    reference_answer: str,
    judge_rubric: Dict[str, Any],
    max_context_chars: int,
) -> ClaimEvalLLMResult:
    """调用 LLM judge 评估单题 claim 覆盖和证据支撑。"""
    prompt = _build_claim_eval_prompt()
    response = (prompt | _build_judge_llm()).invoke(
        {
            "question": question,
            "reference_answer": reference_answer,
            "expected_claims": json.dumps(expected_claims, ensure_ascii=False, indent=2),
            "answer": answer,
            "evidence_blocks": _format_evidence_blocks(contexts, evidence_ids, max_context_chars),
            "judge_rubric": json.dumps(judge_rubric, ensure_ascii=False, indent=2),
        }
    )
    return _parse_claim_eval_result(str(response.content))


def _run_claim_judge_with_retries(
    question: str,
    answer: str,
    contexts: List[str],
    evidence_ids: List[str],
    expected_claims: List[str],
    reference_answer: str,
    judge_rubric: Dict[str, Any],
    max_context_chars: int,
    max_retries: int,
    retry_sleep_seconds: float,
) -> tuple[ClaimEvalLLMResult, Optional[Exception]]:
    """调用 claim judge，并对临时 API / 网络失败做有限重试。"""
    last_error: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            return (
                _run_claim_judge(
                    question=question,
                    answer=answer,
                    contexts=contexts,
                    evidence_ids=evidence_ids,
                    expected_claims=expected_claims,
                    reference_answer=reference_answer,
                    judge_rubric=judge_rubric,
                    max_context_chars=max_context_chars,
                ),
                None,
            )
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(retry_sleep_seconds)
    return _fallback_failed_result(expected_claims, last_error or RuntimeError("unknown judge error")), last_error


def _fallback_failed_result(expected_claims: List[str], error: Exception) -> ClaimEvalLLMResult:
    """当 LLM judge 失败时，构造需要复查的保守结果。"""
    return ClaimEvalLLMResult(
        status="needs_review",
        claim_results=[
            ClaimJudgement(
                claim=claim,
                answer_covered=False,
                evidence_supported=False,
                reason=f"claim judge failed: {error!r}",
                evidence_ids=[],
            )
            for claim in expected_claims
        ],
        unsupported_answer_claims=[],
        overall_notes=f"claim judge failed: {error!r}",
    )


def _score_claim_result(judge_result: ClaimEvalLLMResult) -> Dict[str, Any]:
    """计算单题 claim coverage、evidence support 和 unsupported claims 指标。"""
    claim_results = judge_result.claim_results
    total_claims = len(claim_results)
    covered_count = sum(1 for claim in claim_results if claim.answer_covered)
    supported_count = sum(1 for claim in claim_results if claim.evidence_supported)
    missing_claims = [claim.claim for claim in claim_results if not claim.answer_covered]
    unsupported_expected_claims = [
        claim.claim
        for claim in claim_results
        if claim.answer_covered and not claim.evidence_supported
    ]
    return {
        "total_claims": total_claims,
        "covered_count": covered_count,
        "supported_count": supported_count,
        "claim_coverage": round(covered_count / total_claims, 4) if total_claims else 0.0,
        "evidence_support_rate": round(supported_count / total_claims, 4) if total_claims else 0.0,
        "missing_claims": missing_claims,
        "unsupported_expected_claims": unsupported_expected_claims,
        "unsupported_answer_claim_count": len(judge_result.unsupported_answer_claims),
    }


def _build_bad_cases(details: List[Dict[str, Any]], low_threshold: float) -> List[Dict[str, Any]]:
    """抽取低覆盖或存在 unsupported answer claims 的题目，供人工复查。"""
    bad_cases = []
    for detail in details:
        if detail.get("judge_failed"):
            continue
        reasons = []
        if detail["claim_coverage"] < low_threshold:
            reasons.append("low_claim_coverage")
        if detail["evidence_support_rate"] < low_threshold:
            reasons.append("low_evidence_support")
        if detail["unsupported_answer_claims"]:
            reasons.append("unsupported_answer_claims")
        if not reasons:
            continue
        bad_cases.append(
            {
                "question_index": detail["question_index"],
                "question": detail["question"],
                "question_type": detail["question_type"],
                "reasons": reasons,
                "claim_coverage": detail["claim_coverage"],
                "evidence_support_rate": detail["evidence_support_rate"],
                "missing_claims": detail["missing_claims"],
                "unsupported_expected_claims": detail["unsupported_expected_claims"],
                "unsupported_answer_claims": detail["unsupported_answer_claims"],
            }
        )
    return bad_cases


def _build_eval_rows(ragas_result: Dict[str, Any], limit: Optional[int]) -> List[Dict[str, Any]]:
    """从 Ragas result 中抽取 claim eval 所需的逐题输入。"""
    rows = []
    metadata_rows = ragas_result.get("metadata", [])
    ragas_rows = ragas_result.get("ragas_rows", [])
    max_count = min(len(metadata_rows), len(ragas_rows))
    if limit is not None:
        max_count = min(max_count, limit)

    for index in range(max_count):
        metadata = metadata_rows[index]
        ragas_row = ragas_rows[index]
        rows.append(
            {
                "question_index": index + 1,
                "question": metadata.get("question", ragas_row.get("user_input", "")),
                "question_type": metadata.get("question_type", ""),
                "expected_claims": metadata.get("expected_claims", []),
                "reference_answer": metadata.get("reference_answer", ragas_row.get("reference", "")),
                "judge_rubric": metadata.get("judge_rubric", {}),
                "answer": ragas_row.get("response", ""),
                "retrieved_contexts": ragas_row.get("retrieved_contexts", []),
                "evidence_ids": [
                    evidence.get("evidence_id", f"E{evidence_index}")
                    for evidence_index, evidence in enumerate(
                        metadata.get("final_evidence_payload", []), start=1
                    )
                    if isinstance(evidence, dict)
                ],
                "answer_status": metadata.get("answer_status", ""),
                "answer_confidence": metadata.get("answer_confidence", ""),
            }
        )
    return rows


def run_claim_eval_from_code_config() -> Dict[str, Any]:
    """根据 CLAIM_EVAL_CONFIG 运行 claim eval，并写入 JSON / Markdown 输出。"""
    ragas_result = _load_json_file(Path(CLAIM_EVAL_CONFIG["ragas_result_path"]))
    eval_rows = _build_eval_rows(ragas_result, CLAIM_EVAL_CONFIG.get("limit"))
    started_at = time.perf_counter()
    details: List[Dict[str, Any]] = []

    for row in eval_rows:
        expected_claims = row.get("expected_claims", [])
        judge_failed = False
        if not CLAIM_EVAL_CONFIG.get("run_llm_judge"):
            judge_result = ClaimEvalLLMResult(
                status="needs_review",
                claim_results=[
                    ClaimJudgement(
                        claim=claim,
                        answer_covered=False,
                        evidence_supported=False,
                        reason="LLM judge disabled.",
                    )
                    for claim in expected_claims
                ],
                overall_notes="LLM judge disabled.",
            )
        else:
            answer = _truncate_text(row.get("answer", ""), CLAIM_EVAL_CONFIG.get("max_answer_chars"))
            judge_result, judge_error = _run_claim_judge_with_retries(
                question=row.get("question", ""),
                answer=answer,
                contexts=row.get("retrieved_contexts", []),
                evidence_ids=row.get("evidence_ids", []),
                expected_claims=expected_claims,
                reference_answer=row.get("reference_answer", ""),
                judge_rubric=row.get("judge_rubric", {}),
                max_context_chars=int(CLAIM_EVAL_CONFIG["max_context_chars"]),
                max_retries=int(CLAIM_EVAL_CONFIG["judge_max_retries"]),
                retry_sleep_seconds=float(CLAIM_EVAL_CONFIG["retry_sleep_seconds"]),
            )
            judge_failed = judge_error is not None

        score = _score_claim_result(judge_result)
        details.append(
            {
                **row,
                "claim_eval_status": judge_result.status,
                "judge_failed": judge_failed,
                "claim_results": [claim.model_dump() for claim in judge_result.claim_results],
                "unsupported_answer_claims": judge_result.unsupported_answer_claims,
                "overall_notes": judge_result.overall_notes,
                **score,
            }
        )

    valid_details = [detail for detail in details if not detail.get("judge_failed")]
    judge_failed_cases = [
        {
            "question_index": detail["question_index"],
            "question": detail["question"],
            "overall_notes": detail.get("overall_notes", ""),
        }
        for detail in details
        if detail.get("judge_failed")
    ]
    claim_coverages = [detail["claim_coverage"] for detail in valid_details]
    support_rates = [detail["evidence_support_rate"] for detail in valid_details]
    unsupported_counts = [detail["unsupported_answer_claim_count"] for detail in valid_details]
    low_threshold = float(CLAIM_EVAL_CONFIG["low_claim_coverage_threshold"])
    bad_cases = _build_bad_cases(details, low_threshold)
    low_coverage_cases = [case for case in bad_cases if "low_claim_coverage" in case["reasons"]]

    result = {
        "status": "pass" if details else "empty",
        "ragas_result_path": str(Path(CLAIM_EVAL_CONFIG["ragas_result_path"]).resolve()),
        "judge_model": settings.MODEL,
        "judge_base_url": settings.BASE_URL,
        "sample_count": len(details),
        "valid_sample_count": len(valid_details),
        "judge_failed_count": len(judge_failed_cases),
        "limit": CLAIM_EVAL_CONFIG.get("limit"),
        "run_llm_judge": CLAIM_EVAL_CONFIG.get("run_llm_judge"),
        "eval_seconds": round(time.perf_counter() - started_at, 3),
        "score_summary": {
            "claim_coverage": round(mean(claim_coverages), 4) if claim_coverages else 0.0,
            "evidence_support_rate": round(mean(support_rates), 4) if support_rates else 0.0,
            "unsupported_answer_claim_count": round(mean(unsupported_counts), 4) if unsupported_counts else 0.0,
        },
        "low_claim_coverage_threshold": low_threshold,
        "judge_failed_cases": judge_failed_cases,
        "low_coverage_cases": low_coverage_cases,
        "bad_cases": bad_cases,
        "details": details,
    }

    if CLAIM_EVAL_CONFIG.get("save_output"):
        _write_json_file(Path(CLAIM_EVAL_CONFIG["output_path"]), result)
        _write_json_file(
            Path(CLAIM_EVAL_CONFIG["bad_cases_path"]),
            {
                "judge_model": result["judge_model"],
                "sample_count": result["sample_count"],
                "valid_sample_count": result["valid_sample_count"],
                "judge_failed_count": result["judge_failed_count"],
                "low_claim_coverage_threshold": low_threshold,
                "bad_case_count": len(bad_cases),
                "bad_cases": bad_cases,
            },
        )
    if CLAIM_EVAL_CONFIG.get("save_markdown"):
        write_markdown_file(Path(CLAIM_EVAL_CONFIG["report_path"]), build_claim_eval_markdown_report(result))
    return result
