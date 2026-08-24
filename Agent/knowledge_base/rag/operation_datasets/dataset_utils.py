import json
import re
from pathlib import Path
from typing import Any, Dict, List

from Agent.knowledge_base.rag.tools.report_utils import build_dataset_validation_markdown_report, write_markdown_file
from Agent.knowledge_base.rag.rag_eval.contracts import (
    EVAL_SCHEMA_VERSION,
    validate_eval_dataset,
)
from Agent.knowledge_base.rag.rag_config import (
    RAG_EVAL_DATASET_NAME,
    RAG_EVAL_DATASET_PATH,
)
from config.rag_eval_paths import RAG_EVAL_MACHINE_OUTPUT_DIR as MACHINE_OUTPUT_DIR
from config.rag_eval_paths import RAG_EVAL_REPORT_OUTPUT_DIR as REPORT_OUTPUT_DIR
ALLOWED_QUESTION_TYPES = {
    "definition",
    "comparison",
    "method",
    "criterion",
    "limitation",
    "example",
    "application",
    "medical_rag",
}
ALLOWED_CORPUS = {"official", "project_note", "mixed", "unknown", "medical"}
ALLOWED_REVIEW_STATUS = {"pending_human_review", "reviewed", "needs_revision"}
CHUNK_ID_PATTERN = re.compile(r"^[a-z0-9_-]+#p\d+#c\d+$")


def infer_dataset_name(path: Path) -> str:
    """根据路径识别评测数据集名称，无法匹配时返回 unknown。"""
    resolved = path.resolve()
    if RAG_EVAL_DATASET_PATH and resolved == RAG_EVAL_DATASET_PATH.resolve():
        return RAG_EVAL_DATASET_NAME
    return "unknown"


def load_dataset_json(path: Path) -> List[Dict[str, Any]]:
    """读取评测数据集 JSON，并确认顶层结构是样本数组。"""
    with path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError(f"{path.name} must be a JSON array.")
    return data


def load_jsonl_file(path: Path) -> List[Dict[str, Any]]:
    """读取 JSONL 文件，并确认每行都是 JSON object。"""
    rows = []
    with path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise ValueError(f"{path.name}:{line_number} must be a JSON object.")
            rows.append(row)
    return rows


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

    if "is_smoke_case" in sample and not isinstance(sample.get("is_smoke_case"), bool):
        errors.append(f"{prefix}: is_smoke_case must be a boolean when present.")

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

    return {
        "sample_count": len(samples),
        "with_gold_chunk_ids": sum(bool(sample.get("gold_chunk_ids")) for sample in samples),
        "with_expected_claims": sum(bool(sample.get("expected_claims")) for sample in samples),
        "question_type_counts": _count_by_key(samples, "question_type"),
        "errors": errors,
    }


def validate_benchmark_v2_dataset(
    samples: List[Dict[str, Any]],
    available_doc_ids: set[str],
    dataset_name: str = "active_benchmark",
) -> Dict[str, Any]:
    """校验通用 benchmark v2 测试集。"""
    errors: List[str] = []
    sample_ids: List[str] = []
    seen_questions = set()
    duplicate_questions = []

    for index, sample in enumerate(samples, start=1):
        prefix = f"{dataset_name}[{index}]"
        sample_id = sample.get("sample_id")
        if not _is_nonempty_string(sample_id):
            errors.append(f"{prefix}: sample_id must be a non-empty string.")
        else:
            sample_ids.append(sample_id)

        if not _is_nonempty_string(sample.get("question")):
            errors.append(f"{prefix}: question must be a non-empty string.")
        if not _is_nonempty_string(sample.get("reference_answer")):
            errors.append(f"{prefix}: reference_answer must be a non-empty string.")
        if not _is_nonempty_string_list(sample.get("expected_claims")):
            errors.append(f"{prefix}: expected_claims must be a non-empty list of strings.")

        gold_doc_ids = sample.get("gold_doc_ids", [])
        if not _is_nonempty_string_list(gold_doc_ids):
            errors.append(f"{prefix}: gold_doc_ids must be a non-empty list of strings.")
        else:
            missing_doc_ids = [doc_id for doc_id in gold_doc_ids if doc_id not in available_doc_ids]
            if missing_doc_ids:
                errors.append(f"{prefix}: gold_doc_ids not found in benchmark corpus: {missing_doc_ids}.")

        rubric = sample.get("judge_rubric")
        if not isinstance(rubric, dict):
            errors.append(f"{prefix}: judge_rubric must be an object.")
        else:
            if not _is_nonempty_string_list(rubric.get("must_cover")):
                errors.append(f"{prefix}: judge_rubric.must_cover must be a non-empty list of strings.")
            if not _is_nonempty_string_list(rubric.get("avoid")):
                errors.append(f"{prefix}: judge_rubric.avoid must be a non-empty list of strings.")

        source = sample.get("source")
        if not isinstance(source, dict):
            errors.append(f"{prefix}: source must be an object.")
        else:
            if not _is_nonempty_string(source.get("dataset")):
                errors.append(f"{prefix}: source.dataset must be a non-empty string.")
            if not isinstance(source.get("row_index"), int):
                errors.append(f"{prefix}: source.row_index must be an integer.")

        removed_fields = [
            "gold_chunk_ids",
            "review_status",
            "is_smoke_case",
            "expected_sources",
            "expected_corpus",
            "question_type",
            "notes",
            "eval_schema_version",
        ]
        present_removed = [field for field in removed_fields if field in sample]
        if present_removed:
            errors.append(f"{prefix}: benchmark v2 sample must not contain removed fields: {present_removed}.")

        question = sample.get("question")
        if question in seen_questions:
            duplicate_questions.append(question)
        seen_questions.add(question)

    duplicate_sample_ids = sorted({sample_id for sample_id in sample_ids if sample_ids.count(sample_id) > 1})
    if duplicate_sample_ids:
        errors.append(f"{dataset_name}: duplicate sample_id values: {duplicate_sample_ids}.")
    if duplicate_questions:
        errors.append(f"{dataset_name}: duplicate questions: {duplicate_questions}.")

    return {
        "schema_version": "benchmark_v2",
        "sample_count": len(samples),
        "with_expected_claims": sum(bool(sample.get("expected_claims")) for sample in samples),
        "with_gold_doc_ids": sum(bool(sample.get("gold_doc_ids")) for sample in samples),
        "sample_id_count": len(set(sample_ids)),
        "benchmark_corpus_doc_count": len(available_doc_ids),
        "errors": errors,
    }


def validate_benchmark_corpus(corpus_path: Path) -> Dict[str, Any]:
    """校验 active benchmark corpus，确保 doc_id 唯一且正文不泄漏问答字段。"""
    errors: List[str] = []
    if not corpus_path.exists():
        return {
            "exists": False,
            "doc_count": 0,
            "doc_ids": [],
            "errors": [f"benchmark corpus missing: {corpus_path}."],
        }

    docs = load_jsonl_file(corpus_path)
    doc_ids: List[str] = []
    for index, doc in enumerate(docs, start=1):
        prefix = f"benchmark_corpus[{index}]"
        doc_id = doc.get("doc_id")
        if not _is_nonempty_string(doc_id):
            errors.append(f"{prefix}: doc_id must be a non-empty string.")
        else:
            doc_ids.append(doc_id)
        if not _is_nonempty_string(doc.get("text")):
            errors.append(f"{prefix}: text must be a non-empty string.")

        normalized_keys = {str(key).strip().lower().replace("_", " ") for key in doc}
        if "question" in normalized_keys:
            errors.append(f"{prefix}: corpus doc must not contain Question.")
        if "answer" in normalized_keys:
            errors.append(f"{prefix}: corpus doc must not contain Answer.")
        if "text answer" in normalized_keys:
            errors.append(f"{prefix}: corpus doc must not contain Text Answer.")

    duplicate_doc_ids = sorted({doc_id for doc_id in doc_ids if doc_ids.count(doc_id) > 1})
    if duplicate_doc_ids:
        errors.append(f"benchmark_corpus: duplicate doc_id values: {duplicate_doc_ids}.")

    return {
        "exists": True,
        "doc_count": len(docs),
        "doc_ids": sorted(set(doc_ids)),
        "errors": errors,
    }


def validate_legacy_doc_dataset(samples: List[Dict[str, Any]], available_doc_ids: set[str], dataset_name: str) -> List[str]:
    """校验旧 schema 数据集中 doc-level gold 与 active corpus 的关联。"""
    errors: List[str] = []
    for index, sample in enumerate(samples, start=1):
        prefix = f"{dataset_name}[{index}]"
        gold_doc_ids = sample.get("gold_doc_ids", [])
        if not _is_nonempty_string_list(gold_doc_ids):
            errors.append(f"{prefix}: gold_doc_ids must be a non-empty list of strings.")
        missing_doc_ids = [doc_id for doc_id in gold_doc_ids if doc_id not in available_doc_ids]
        if missing_doc_ids:
            errors.append(f"{prefix}: gold_doc_ids not found in benchmark corpus: {missing_doc_ids}.")
    return errors


def validate_all_datasets() -> Dict[str, Any]:
    """校验显式配置的通用 RAG eval 题集，不读取任何知识库语料。"""
    result: Dict[str, Any] = {
        "schema_version": EVAL_SCHEMA_VERSION,
        "dataset_name": RAG_EVAL_DATASET_NAME,
        "dataset_path": str(RAG_EVAL_DATASET_PATH.resolve()) if RAG_EVAL_DATASET_PATH else "",
        "datasets": {},
        "errors": [],
        "warnings": [],
    }
    if not RAG_EVAL_DATASET_PATH:
        result["errors"].append("RAG_EVAL_DATASET_PATH is not configured.")
    else:
        detail = validate_eval_dataset(RAG_EVAL_DATASET_PATH)
        result["datasets"][RAG_EVAL_DATASET_NAME] = detail
        result["errors"].extend(detail["errors"])

    result["error_count"] = len(result["errors"])
    result["warning_count"] = len(result["warnings"])
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
    """从 reference answer 中切出初版 expected_claims，兼容中英文句子边界。"""
    normalized = re.sub(r"\s+", " ", reference_answer).strip()
    if not normalized:
        return []

    protected = re.sub(r"(?<=\d)\.(?=\d)", "<DOT>", normalized)
    parts = [
        part.replace("<DOT>", ".").strip()
        for part in re.findall(r"[^。；;！？!?.]+[。；;！？!?.]?", protected)
        if part.strip()
    ]
    claims = []
    for part in parts:
        if len(part) < 8:
            continue
        claims.append(part)
        if len(claims) >= max_claims:
            break
    return claims or [normalized]


def _get_generated_field(row: Dict[str, Any], names: List[str], default: Any = "") -> Any:
    """从 Ragas 生成结果中兼容读取不同版本可能使用的字段名。"""
    for name in names:
        if name not in row:
            continue
        value = row[name]
        if value is not None and value != "":
            return value
    return default


DEFAULT_LOCATOR_FIELDS = (
    "document_id",
    "page_number",
    "unit_id",
    "modality",
    "content_kind",
    "asset_uri",
    "chunk_id",
    "doc_id",
    "page",
)


def _context_text(value: Any) -> str:
    """提取 Ragas context 或 source record 中的可比正文。"""
    if isinstance(value, str):
        return re.sub(r"^<\d+-hop>\s*", "", value.strip())
    if not isinstance(value, dict):
        return ""
    for key in ("page_content", "content", "text", "context"):
        text = value.get(key)
        if text is not None and str(text).strip():
            return str(text).strip()
    return ""


def _context_metadata(value: Any) -> Dict[str, Any]:
    """提取 context 自带或 source record 中的 metadata。"""
    if not isinstance(value, dict):
        return {}
    metadata = value.get("metadata")
    if isinstance(metadata, dict):
        return dict(metadata)
    return dict(value)


def _stable_locator(metadata: Dict[str, Any], locator_fields: tuple[str, ...]) -> Dict[str, Any]:
    """只保留 Runtime 可用于严格匹配的稳定 metadata 字段。"""
    return {
        key: metadata[key]
        for key in locator_fields
        if key in metadata and metadata[key] not in (None, "")
    }


def resolve_generated_gold_evidence(
    contexts: Any,
    source_records: List[Dict[str, Any]] | None = None,
    locator_fields: tuple[str, ...] = DEFAULT_LOCATOR_FIELDS,
) -> List[Dict[str, Any]]:
    """把生成 context 映射为稳定 locator；无法唯一映射时保持未评分。"""
    if isinstance(contexts, str):
        contexts = [contexts]
    if not isinstance(contexts, list):
        return []

    records = source_records or []
    resolved: List[Dict[str, Any]] = []
    seen_locators = set()
    for context in contexts:
        locator = _stable_locator(_context_metadata(context), locator_fields)
        if not locator:
            text = _context_text(context)
            matches = [
                record
                for record in records
                if text and _context_text(record) == text
            ]
            if len(matches) == 1:
                locator = _stable_locator(_context_metadata(matches[0]), locator_fields)
        if locator:
            key = json.dumps(locator, ensure_ascii=False, sort_keys=True, default=str)
            if key not in seen_locators:
                resolved.append(locator)
                seen_locators.add(key)
    return resolved


def convert_ragas_generated_row_to_eval_sample(
    row: Dict[str, Any],
    source_records: List[Dict[str, Any]] | None = None,
    *,
    locator_fields: tuple[str, ...] = DEFAULT_LOCATOR_FIELDS,
    source_snapshot: Dict[str, Any] | None = None,
    row_index: int | None = None,
) -> Dict[str, Any]:
    """把 Ragas 生成的一行样本转换为候选 rag_eval_v1 样本。"""
    question = str(_get_generated_field(row, ["user_input", "question", "query"], "")).strip()
    reference_answer = str(
        _get_generated_field(row, ["reference", "reference_answer", "ground_truth", "answer"], "")
    ).strip()
    if not question or not reference_answer:
        raise ValueError(f"generated row missing question/reference: {row}")

    contexts = _get_generated_field(row, ["reference_contexts", "contexts", "retrieved_contexts"], [])
    if isinstance(contexts, str):
        contexts = [contexts]
    claims = row.get("expected_claims") or extract_claims_from_reference(reference_answer)
    if not isinstance(claims, list):
        claims = extract_claims_from_reference(reference_answer)
    claims = [str(claim).strip() for claim in claims if str(claim).strip()]
    gold_evidence = row.get("gold_evidence") or resolve_generated_gold_evidence(
        contexts,
        source_records=source_records,
        locator_fields=locator_fields,
    )
    source = dict(row.get("source") or {})
    source.update(
        {
            "generator": source.get("generator", "ragas"),
            "review_status": source.get("review_status", "candidate"),
            "context_count": len(contexts),
        }
    )
    if source_snapshot:
        index_binding = dict(source_snapshot)
        source["source_snapshot"] = index_binding
        source["index_binding"] = index_binding
        index_version = str(index_binding.get("index_version") or "").strip()
        if index_version:
            gold_evidence = [
                {**locator, "bound_index_version": index_version}
                if isinstance(locator, dict) else locator
                for locator in gold_evidence
            ]
    if row_index is not None:
        source["row_index"] = row_index

    return {
        "sample_id": str(row.get("sample_id") or f"generated-{row_index or 0:04d}"),
        "question": question,
        "expected_claims": claims,
        "reference_answer": reference_answer,
        "gold_evidence": gold_evidence,
        "judge_rubric": {
            "must_cover": claims,
            "avoid": [
                "脱离证据编造因果结论",
                "把相关性直接等同于因果关系",
                "忽略题目中的限制条件或识别假设",
            ],
        },
        "source": source,
    }


def build_generated_eval_dataset(
    rows: List[Dict[str, Any]],
    source_records: List[Dict[str, Any]] | None = None,
    *,
    dataset_id: str = "generated_candidate",
    dataset_revision: str = "",
    source_snapshot: Dict[str, Any] | None = None,
    locator_fields: tuple[str, ...] = DEFAULT_LOCATOR_FIELDS,
) -> Dict[str, Any]:
    """构造冻结前的 generated_candidate 题集文档。"""
    samples = [
        convert_ragas_generated_row_to_eval_sample(
            row,
            source_records=source_records,
            locator_fields=locator_fields,
            source_snapshot=source_snapshot,
            row_index=index,
        )
        for index, row in enumerate(rows, start=1)
    ]
    return {
        "schema_version": EVAL_SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "dataset_kind": "generated_candidate",
        "dataset_revision": dataset_revision,
        "source_snapshot": dict(source_snapshot or {}),
        "samples": samples,
    }


def write_generated_eval_dataset(
    samples: List[Dict[str, Any]],
    dataset_path: Path | None = None,
    merge_existing: bool = True,
    *,
    dataset_id: str = "generated_candidate",
    dataset_revision: str = "",
    dataset_kind: str = "generated_candidate",
    source_snapshot: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """写入带 provenance 的统一 eval dataset，可按 question 去重合并。"""
    target_path = dataset_path or RAG_EVAL_DATASET_PATH
    if target_path is None:
        raise ValueError("RAG_EVAL_DATASET_PATH is not configured.")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    existing: List[Dict[str, Any]] = []
    if merge_existing and target_path.exists():
        payload = json.loads(target_path.read_text(encoding="utf-8-sig"))
        existing = payload.get("samples", []) if isinstance(payload, dict) else payload
        if not isinstance(existing, list):
            raise ValueError(f"{target_path} must contain a samples list")
        existing_kind = payload.get("dataset_kind", "untyped") if isinstance(payload, dict) else "untyped"
        existing_id = payload.get("dataset_id", target_path.stem) if isinstance(payload, dict) else target_path.stem
        if existing_kind != dataset_kind or existing_id != dataset_id:
            raise ValueError(
                f"refusing to merge {dataset_kind}/{dataset_id} into "
                f"{existing_kind}/{existing_id}; use a separate dataset path"
            )
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

    target_path.write_text(
        json.dumps(
            {
                "schema_version": EVAL_SCHEMA_VERSION,
                "dataset_id": dataset_id,
                "dataset_kind": dataset_kind,
                "dataset_revision": dataset_revision,
                "source_snapshot": dict(source_snapshot or {}),
                "samples": existing,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "dataset_path": str(target_path.resolve()),
        "input_count": len(samples),
        "appended_count": len(appended),
        "skipped_duplicate_count": len(skipped_duplicates),
        "appended_questions": appended,
        "skipped_duplicate_questions": skipped_duplicates,
        "final_count": len(existing),
        "with_gold_evidence": sum(bool(sample.get("gold_evidence")) for sample in existing),
        "unscored_retrieval_count": sum(not bool(sample.get("gold_evidence")) for sample in existing),
    }

