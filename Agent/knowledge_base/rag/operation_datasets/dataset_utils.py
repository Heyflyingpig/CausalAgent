import json
import re
from pathlib import Path
from typing import Any, Dict, List

from Agent.knowledge_base.rag.tools.report_utils import build_dataset_validation_markdown_report, write_markdown_file


RAG_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = RAG_DIR / "data"
OUTPUT_DIR = RAG_DIR / "output"
MACHINE_OUTPUT_DIR = OUTPUT_DIR / "machine"
REPORT_OUTPUT_DIR = OUTPUT_DIR / "reports"
DATASET_FILES = {
    "smoke": DATA_DIR / "rag_eval_smoke.json",
    "auto": DATA_DIR / "rag_eval_auto.json",
    "regression": DATA_DIR / "rag_eval_regression.json",
}
ALLOWED_QUESTION_TYPES = {
    "definition",
    "comparison",
    "method",
    "criterion",
    "limitation",
    "example",
    "application",
}
ALLOWED_CORPUS = {"official", "project_note", "mixed", "unknown"}
ALLOWED_REVIEW_STATUS = {"pending_human_review", "reviewed", "needs_revision"}
CHUNK_ID_PATTERN = re.compile(r"^[a-z0-9_-]+#p\d+#c\d+$")


def infer_dataset_name(path: Path) -> str:
    """根据路径识别评测数据集名称，无法匹配时返回 unknown。"""
    resolved = path.resolve()
    for dataset_name, dataset_path in DATASET_FILES.items():
        if resolved == dataset_path.resolve():
            return dataset_name
    return "unknown"


def load_dataset_json(path: Path) -> List[Dict[str, Any]]:
    """读取评测数据集 JSON，并确认顶层结构是样本数组。"""
    with path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError(f"{path.name} must be a JSON array.")
    return data


def _is_nonempty_string(value: Any) -> bool:
    """判断字段是否为去空格后非空的字符串。"""
    return isinstance(value, str) and bool(value.strip())


def _is_nonempty_string_list(value: Any) -> bool:
    """判断字段是否为非空字符串列表。"""
    return isinstance(value, list) and all(_is_nonempty_string(item) for item in value) and bool(value)


def _count_by_key(samples: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    """统计样本中某个字段的取值分布。"""
    counts: Dict[str, int] = {}
    for sample in samples:
        value = sample.get(key, "")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def validate_common_sample(sample: Dict[str, Any], dataset_name: str, index: int) -> List[str]:
    """校验单条样本的通用 schema 字段，并返回错误列表。"""
    errors: List[str] = []
    prefix = f"{dataset_name}[{index}]"

    if not _is_nonempty_string(sample.get("question")):
        errors.append(f"{prefix}: question must be a non-empty string.")

    if sample.get("eval_schema_version") != "phase1_v1":
        errors.append(f"{prefix}: eval_schema_version must be 'phase1_v1'.")

    review_status = sample.get("review_status")
    if review_status not in ALLOWED_REVIEW_STATUS:
        errors.append(
            f"{prefix}: review_status must be one of {sorted(ALLOWED_REVIEW_STATUS)}, got {review_status!r}."
        )

    if not isinstance(sample.get("is_smoke_case"), bool):
        errors.append(f"{prefix}: is_smoke_case must be a boolean.")

    question_type = sample.get("question_type")
    if question_type not in ALLOWED_QUESTION_TYPES:
        errors.append(
            f"{prefix}: question_type must be one of {sorted(ALLOWED_QUESTION_TYPES)}, got {question_type!r}."
        )

    expected_corpus = sample.get("expected_corpus")
    if expected_corpus not in ALLOWED_CORPUS:
        errors.append(f"{prefix}: expected_corpus must be one of {sorted(ALLOWED_CORPUS)}, got {expected_corpus!r}.")

    if not _is_nonempty_string_list(sample.get("expected_sources")):
        errors.append(f"{prefix}: expected_sources must be a non-empty list of strings.")

    if not _is_nonempty_string_list(sample.get("expected_claims")):
        errors.append(f"{prefix}: expected_claims must be a non-empty list of strings.")

    if not _is_nonempty_string(sample.get("reference_answer")):
        errors.append(f"{prefix}: reference_answer must be a non-empty string.")

    rubric = sample.get("judge_rubric")
    if not isinstance(rubric, dict):
        errors.append(f"{prefix}: judge_rubric must be an object.")
    else:
        if not _is_nonempty_string_list(rubric.get("must_cover")):
            errors.append(f"{prefix}: judge_rubric.must_cover must be a non-empty list of strings.")
        if not _is_nonempty_string_list(rubric.get("avoid")):
            errors.append(f"{prefix}: judge_rubric.avoid must be a non-empty list of strings.")

    gold_chunk_ids = sample.get("gold_chunk_ids", [])
    if not isinstance(gold_chunk_ids, list):
        errors.append(f"{prefix}: gold_chunk_ids must be a list.")
    else:
        bad_ids = [chunk_id for chunk_id in gold_chunk_ids if not isinstance(chunk_id, str)]
        if bad_ids:
            errors.append(f"{prefix}: gold_chunk_ids must contain only strings.")
        malformed = [
            chunk_id
            for chunk_id in gold_chunk_ids
            if isinstance(chunk_id, str) and not CHUNK_ID_PATTERN.match(chunk_id)
        ]
        if malformed:
            errors.append(f"{prefix}: malformed gold_chunk_ids: {malformed}.")

    gold_doc_ids = sample.get("gold_doc_ids", [])
    if not isinstance(gold_doc_ids, list):
        errors.append(f"{prefix}: gold_doc_ids must be a list.")

    has_gold = isinstance(gold_chunk_ids, list) and bool(gold_chunk_ids)
    if sample.get("is_smoke_case") != has_gold:
        errors.append(f"{prefix}: is_smoke_case must match whether gold_chunk_ids is non-empty.")

    if not _is_nonempty_string(sample.get("notes")):
        errors.append(f"{prefix}: notes must be a non-empty string.")

    return errors


def validate_dataset(dataset_name: str, samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """校验一个数据集文件，并汇总样本数量、字段覆盖和错误。"""
    errors: List[str] = []
    seen_questions = set()
    duplicate_questions = []

    for index, sample in enumerate(samples, start=1):
        errors.extend(validate_common_sample(sample, dataset_name, index))
        question = sample.get("question")
        if question in seen_questions:
            duplicate_questions.append(question)
        seen_questions.add(question)

    if duplicate_questions:
        errors.append(f"{dataset_name}: duplicate questions: {duplicate_questions}.")

    if dataset_name == "smoke":
        missing_gold = [
            sample.get("question", f"index {index}")
            for index, sample in enumerate(samples, start=1)
            if not sample.get("gold_chunk_ids")
        ]
        if missing_gold:
            errors.append(f"smoke: every sample must have gold_chunk_ids, missing: {missing_gold}.")

    return {
        "sample_count": len(samples),
        "with_gold_chunk_ids": sum(bool(sample.get("gold_chunk_ids")) for sample in samples),
        "with_expected_claims": sum(bool(sample.get("expected_claims")) for sample in samples),
        "question_type_counts": _count_by_key(samples, "question_type"),
        "errors": errors,
    }


def validate_all_datasets() -> Dict[str, Any]:
    """校验 smoke、auto、regression 三个评测集并返回总结果。"""
    result: Dict[str, Any] = {"datasets": {}, "errors": []}
    loaded: Dict[str, List[Dict[str, Any]]] = {}

    for dataset_name, path in DATASET_FILES.items():
        if not path.exists():
            result["errors"].append(f"{dataset_name}: missing dataset file {path}.")
            continue
        samples = load_dataset_json(path)
        loaded[dataset_name] = samples
        detail = validate_dataset(dataset_name, samples)
        result["datasets"][dataset_name] = detail
        result["errors"].extend(detail["errors"])

    if "auto" in loaded and "smoke" in loaded:
        auto_questions = {sample["question"] for sample in loaded["auto"]}
        smoke_questions = {sample["question"] for sample in loaded["smoke"]}
        missing_in_auto = sorted(smoke_questions - auto_questions)
        if missing_in_auto:
            result["errors"].append(f"smoke questions missing from auto dataset: {missing_in_auto}.")

    result["error_count"] = len(result["errors"])
    result["status"] = "pass" if result["error_count"] == 0 else "fail"
    return result


def write_dataset_validation_outputs(result: Dict[str, Any]) -> None:
    """把数据集校验结果同时写成机器 JSON 和人工 Markdown。"""
    MACHINE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = MACHINE_OUTPUT_DIR / "dataset_validation_result.json"
    md_path = REPORT_OUTPUT_DIR / "dataset_validation_report.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown_file(md_path, build_dataset_validation_markdown_report(result))


def infer_question_type(question: str) -> str:
    """根据问题文本粗略推断 question_type，用于自动生成样本的初始标注。"""
    if "区别" in question or "不同" in question or "对比" in question:
        return "comparison"
    if "准则" in question or "条件" in question:
        return "criterion"
    if "为什么" in question or "限制" in question or "不能" in question or "不足" in question:
        return "limitation"
    if "例子" in question or "举例" in question:
        return "example"
    if "如何" in question or "怎样" in question or "怎么" in question:
        return "method"
    if question.startswith("什么是") or question.startswith("何为"):
        return "definition"
    return "application"


def extract_claims_from_reference(reference_answer: str, max_claims: int = 3) -> List[str]:
    """从 reference answer 中切出初版 expected_claims。"""
    parts = [
        part.strip()
        for part in re.split(r"[。；;！？!?]\s*", reference_answer)
        if part.strip()
    ]
    claims = []
    for part in parts:
        if len(part) < 8:
            continue
        claims.append(part + "。")
        if len(claims) >= max_claims:
            break
    return claims or [reference_answer.strip()]


def _get_generated_field(row: Dict[str, Any], names: List[str], default: Any = "") -> Any:
    """从 Ragas 生成结果中兼容读取不同版本可能使用的字段名。"""
    for name in names:
        if name not in row:
            continue
        value = row[name]
        if value is not None and value != "":
            return value
    return default


def convert_ragas_generated_row_to_eval_sample(row: Dict[str, Any]) -> Dict[str, Any]:
    """把 Ragas 生成的一行样本转换为当前 RAG eval schema。"""
    question = str(_get_generated_field(row, ["user_input", "question", "query"], "")).strip()
    reference_answer = str(
        _get_generated_field(row, ["reference", "reference_answer", "ground_truth", "answer"], "")
    ).strip()
    if not question or not reference_answer:
        raise ValueError(f"generated row missing question/reference: {row}")

    contexts = _get_generated_field(row, ["reference_contexts", "contexts", "retrieved_contexts"], [])
    if isinstance(contexts, str):
        contexts = [contexts]

    question_type = infer_question_type(question)
    return {
        "question": question,
        "question_type": question_type,
        "expected_corpus": "official",
        "expected_sources": [
            "pearl_2009_causality-mono_1",
            "pearl_mackenzie_2018_the_book_of_why-mono_1",
        ],
        "expected_claims": extract_claims_from_reference(reference_answer),
        "reference_answer": reference_answer,
        "gold_chunk_ids": [],
        "gold_doc_ids": [
            "pearl_2009_causality-mono_1",
            "pearl_mackenzie_2018_the_book_of_why-mono_1",
        ],
        "judge_rubric": {
            "must_cover": extract_claims_from_reference(reference_answer),
            "avoid": [
                "脱离证据编造因果结论",
                "把相关性直接等同于因果关系",
                "忽略题目中的限制条件或识别假设",
            ],
        },
        "notes": (
            "Generated by Ragas testset generation; pending human review. "
            f"source_context_count={len(contexts)}"
        ),
        "eval_schema_version": "phase1_v1",
        "review_status": "pending_human_review",
        "is_smoke_case": False,
    }


def append_samples_to_auto_dataset(samples: List[Dict[str, Any]], auto_path: Path | None = None) -> Dict[str, Any]:
    """把新样本去重后追加到 rag_eval_auto.json。"""
    target_path = auto_path or DATASET_FILES["auto"]
    existing = load_dataset_json(target_path)
    existing_questions = {sample["question"] for sample in existing}
    appended = []
    skipped_duplicates = []

    for sample in samples:
        question = sample["question"]
        if question in existing_questions:
            skipped_duplicates.append(question)
            continue
        existing.append(sample)
        existing_questions.add(question)
        appended.append(question)

    target_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "auto_path": str(target_path.resolve()),
        "input_count": len(samples),
        "appended_count": len(appended),
        "skipped_duplicate_count": len(skipped_duplicates),
        "appended_questions": appended,
        "skipped_duplicate_questions": skipped_duplicates,
        "final_count": len(existing),
    }
