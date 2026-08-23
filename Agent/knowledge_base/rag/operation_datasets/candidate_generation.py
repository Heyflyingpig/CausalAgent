"""从完整 staged 多模态索引生成可审阅的 RAG 候选题集。

该模块只读校验 manifest、units、issues、build state 和 Chroma 计数，不会读取或
修改 active pointer，也不会把自动生成结果升级为正式 gold。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from langchain_openai import ChatOpenAI

from Agent.knowledge_base.multimodal.defaults import resolve_production_embedding_config
from Agent.knowledge_base.multimodal.contracts import KnowledgeUnit
from Agent.knowledge_base.multimodal.index import StagedIndex, embedding_fingerprint
from Agent.knowledge_base.rag.operation_datasets.dataset_utils import (
    convert_ragas_generated_row_to_eval_sample,
)
from config.settings import settings


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "tmp" / "rag_eval_candidate_datasets"
MAX_GENERATION_WORKERS = 4
MAX_QUESTIONS_PER_UNIT = 3
DEFAULT_MAX_UNITS = 32
DATASET_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


CandidateGenerator = Callable[[dict[str, Any], int], Iterable[dict[str, Any]]]


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


def _manifest_snapshot(
    index_dir: Path,
    manifest: dict[str, Any],
    state: dict[str, Any],
    unit_count: int,
) -> dict[str, Any]:
    manifest_hash = hashlib.sha256((index_dir / "manifest.json").read_bytes()).hexdigest()
    return {
        "index_version": str(manifest.get("index_version") or index_dir.name),
        "manifest_sha256": manifest_hash,
        "units_sha256": hashlib.sha256((index_dir / "units.jsonl").read_bytes()).hexdigest(),
        "build_state_sha256": hashlib.sha256((index_dir / "build_state.json").read_bytes()).hexdigest(),
        "unit_count": unit_count,
        "vector_count": int(state["vector_count"]),
        "manifest_schema_version": manifest.get("schema_version", ""),
    }


def _validate_staged_index(
    index_dir: Path,
    manifest: dict[str, Any],
    state: dict[str, Any],
    persisted_unit_count: int,
) -> None:
    """只接受完整且与当前 embedding 配置一致的 staged 索引。"""

    if state.get("status") != "staged_complete":
        raise ValueError("staged index is not complete")
    try:
        unit_count = int(state.get("unit_count", -1))
        vector_count = int(state.get("vector_count", -1))
        manifest_unit_count = int(manifest.get("unit_count", -1))
    except (TypeError, ValueError) as exc:
        raise ValueError("staged index counts are invalid") from exc
    if unit_count < 0 or unit_count != vector_count or unit_count != persisted_unit_count:
        raise ValueError("staged index unit/vector count mismatch")
    if manifest_unit_count != unit_count:
        raise ValueError("staged index manifest unit count mismatch")

    manifest_embedding = manifest.get("embedding")
    if not isinstance(manifest_embedding, dict) or manifest_embedding != embedding_fingerprint():
        raise ValueError("staged index embedding fingerprint mismatch")

    chroma_dir = index_dir / "chroma"
    if not chroma_dir.is_dir():
        raise ValueError("staged Chroma directory is missing")
    collection_prefix = os.getenv("MULTIMODAL_COLLECTION_PREFIX", "causal_multimodal")
    try:
        actual_vector_count = StagedIndex(
            index_dir,
            f"{collection_prefix}_{index_dir.name}",
        ).count()
    except Exception as exc:
        raise ValueError("staged Chroma collection is unavailable") from exc
    if actual_vector_count != vector_count:
        raise ValueError("staged Chroma vector count mismatch")


def load_staged_unit_records(index_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """加载 staged 单元并保留足以回读的来源快照。"""

    index_dir = Path(index_dir).resolve()
    manifest_path = index_dir / "manifest.json"
    units_path = index_dir / "units.jsonl"
    state_path = index_dir / "build_state.json"
    issues_path = index_dir / "issues.jsonl"
    if any(not path.is_file() for path in (manifest_path, units_path, state_path, issues_path)):
        raise FileNotFoundError(
            "staged index must contain manifest.json, units.jsonl, issues.jsonl, and build_state.json"
        )

    manifest = _read_json(manifest_path)
    state = _read_json(state_path)
    if manifest.get("index_version") != index_dir.name:
        raise ValueError("staged index version does not match manifest")

    records: list[dict[str, Any]] = []
    unit_lines = [line for line in units_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    _validate_staged_index(index_dir, manifest, state, len(unit_lines))
    for line_number, line in enumerate(unit_lines, start=1):
        try:
            unit = KnowledgeUnit.model_validate_json(line)
        except ValueError as exc:
            raise ValueError(f"invalid staged unit at line {line_number}") from exc
        if not unit.retrieval_text.strip():
            continue
        records.append(
            {
                "unit_id": unit.unit_id,
                "content": unit.retrieval_text,
                "metadata": unit.chroma_metadata(),
                "modality": unit.modality,
                "content_kind": unit.content_kind,
            }
        )
    if not records:
        raise ValueError("staged index contains no non-empty retrieval units")
    return records, _manifest_snapshot(index_dir, manifest, state, int(state["unit_count"]))


def _select_unit_records(records: list[dict[str, Any]], max_units: int) -> list[dict[str, Any]]:
    """按模态轮询取样，避免候选题只覆盖最前面的文本单元。"""

    if max_units < 1:
        raise ValueError("max_units must be positive")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record.get("modality") or "unknown")].append(record)

    selected: list[dict[str, Any]] = []
    positions = {key: 0 for key in groups}
    while len(selected) < min(max_units, len(records)):
        progressed = False
        for modality in sorted(groups):
            position = positions[modality]
            if position >= len(groups[modality]):
                continue
            selected.append(groups[modality][position])
            positions[modality] = position + 1
            progressed = True
            if len(selected) >= max_units:
                break
        if not progressed:
            break
    return selected


def _default_generator_llm() -> ChatOpenAI:
    if settings is None:
        raise RuntimeError("应用配置不可用，无法生成候选题")
    return ChatOpenAI(
        api_key=settings.API_KEY,
        base_url=settings.BASE_URL,
        model=settings.MODEL,
        temperature=0,
    )


def _embeddings() -> Any:
    """使用与 staged index 相同的冻结本地 embedding。"""
    config = resolve_production_embedding_config()
    if config.get("status") != "ready":
        raise RuntimeError(str(config.get("message") or "embedding model is unavailable"))
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=str(config["path"]),
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def _generate_ragas_rows(
    records: list[dict[str, Any]],
    testset_size: int,
    *,
    llm: ChatOpenAI | None,
    max_workers: int,
) -> list[dict[str, Any]]:
    """用 Ragas 0.4.3 的预分块入口生成单跳、多证据和多跳候选。"""

    try:
        ragas_version = importlib.metadata.version("ragas")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError("ragas==0.4.3 is required for candidate generation") from exc
    if ragas_version != "0.4.3":
        raise RuntimeError(f"candidate generation requires ragas==0.4.3, found {ragas_version}")

    # Ragas 0.4.3 仍会导入 langchain-community 0.4.x 已移除的 VertexAI 聊天模块；
    # 导入 TestsetGenerator 前复用评测路径中的兼容 shim。
    from Agent.knowledge_base.rag.rag_eval.ragas_eval import (
        _install_ragas_vertexai_import_shim,
        _langsmith_tracing_disabled,
    )

    _install_ragas_vertexai_import_shim()
    from langchain_core.documents import Document
    from ragas.run_config import RunConfig
    from ragas.testset import TestsetGenerator

    chunks = [
        Document(page_content=str(record["content"]), metadata=dict(record.get("metadata") or {}))
        for record in records
        if str(record.get("content") or "").strip()
    ]
    if not chunks:
        return []
    generator = TestsetGenerator.from_langchain(llm or _default_generator_llm(), _embeddings())
    run_config = RunConfig(
        timeout=120,
        max_retries=2,
        max_wait=5,
        max_workers=max(1, min(int(max_workers), MAX_GENERATION_WORKERS)),
    )
    with _langsmith_tracing_disabled():
        testset = generator.generate_with_chunks(
            chunks=chunks,
            testset_size=testset_size,
            run_config=run_config,
            raise_exceptions=True,
        )
    return [dict(row) for row in testset.to_list()]


def _normalized_question(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _validate_dataset_id(value: Any) -> str:
    dataset_id = str(value or "").strip()
    if not DATASET_ID_PATTERN.fullmatch(dataset_id):
        raise ValueError("dataset_id must be 1-64 ASCII letters, digits, dot, underscore, or hyphen")
    return dataset_id


def _screen_candidate_rows(
    rows: Iterable[dict[str, Any]],
    *,
    source_snapshot: dict[str, Any],
    source_records: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_questions: set[str] = set()
    for row_index, row in enumerate(rows, start=1):
        question = str(row.get("question") or row.get("user_input") or row.get("query") or "").strip()
        reference_answer = str(row.get("reference_answer") or row.get("reference") or row.get("ground_truth") or "").strip()
        normalized = _normalized_question(question)
        if len(question) < 4:
            rejected.append({"row": row_index, "reason": "question_too_short"})
            continue
        if normalized in seen_questions:
            rejected.append({"row": row_index, "reason": "duplicate_question", "question": question})
            continue
        if len(reference_answer) < 8:
            rejected.append({"row": row_index, "reason": "reference_answer_too_short", "question": question})
            continue
        try:
            sample = convert_ragas_generated_row_to_eval_sample(
                row,
                source_records=source_records,
                source_snapshot=source_snapshot,
                row_index=row_index,
            )
        except (TypeError, ValueError) as exc:
            rejected.append({"row": row_index, "reason": "invalid_candidate", "error": str(exc)})
            continue
        if not sample["expected_claims"]:
            rejected.append({"row": row_index, "reason": "missing_expected_claims", "question": question})
            continue
        if not sample["gold_evidence"]:
            rejected.append({"row": row_index, "reason": "unresolved_gold_evidence", "question": question})
            continue
        seen_questions.add(normalized)
        accepted.append(sample)
    return accepted, rejected


def _build_coverage_summary(
    accepted: list[dict[str, Any]],
    selected_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """汇总候选题对本次 staged unit 的可追溯覆盖，不把它当成质量结论。"""

    def increment(counts: dict[str, int], value: Any) -> None:
        key = str(value or "unknown")
        counts[key] = counts.get(key, 0) + 1

    def locator_matches(locator: dict[str, Any], record: dict[str, Any]) -> bool:
        metadata = dict(record.get("metadata") or {})
        aliases = {
            "doc_id": "document_id",
            "page": "page_number",
        }
        comparable = {
            key: metadata.get(aliases.get(key, key))
            for key in locator
            if aliases.get(key, key) in metadata
        }
        return bool(comparable) and all(comparable[key] == value for key, value in locator.items() if key in comparable)

    selected_modality_counts: dict[str, int] = {}
    selected_content_kind_counts: dict[str, int] = {}
    for record in selected_records:
        increment(selected_modality_counts, record.get("modality"))
        increment(selected_content_kind_counts, record.get("content_kind"))

    covered_unit_ids: set[str] = set()
    evidence_modality_counts: dict[str, int] = {}
    evidence_content_kind_counts: dict[str, int] = {}
    evidence_locator_count = 0
    samples_with_evidence = 0
    multi_evidence_sample_count = 0
    for sample in accepted:
        evidence = sample.get("gold_evidence") or []
        if evidence:
            samples_with_evidence += 1
        if len(evidence) >= 2:
            multi_evidence_sample_count += 1
        for locator in evidence:
            if not isinstance(locator, dict):
                continue
            evidence_locator_count += 1
            matches = [record for record in selected_records if locator_matches(locator, record)]
            for record in matches:
                covered_unit_ids.add(str(record.get("unit_id") or ""))
                increment(evidence_modality_counts, record.get("modality"))
                increment(evidence_content_kind_counts, record.get("content_kind"))

    selected_unit_count = len(selected_records)
    covered_unit_count = len({unit_id for unit_id in covered_unit_ids if unit_id})
    return {
        "schema_version": "rag_candidate_coverage_v1",
        "selected_unit_count": selected_unit_count,
        "covered_unit_count": covered_unit_count,
        "coverage_ratio": round(covered_unit_count / selected_unit_count, 4) if selected_unit_count else 0.0,
        "accepted_count": len(accepted),
        "samples_with_evidence": samples_with_evidence,
        "multi_evidence_sample_count": multi_evidence_sample_count,
        "evidence_locator_count": evidence_locator_count,
        "selected_modality_counts": selected_modality_counts,
        "selected_content_kind_counts": selected_content_kind_counts,
        "evidence_modality_counts": evidence_modality_counts,
        "evidence_content_kind_counts": evidence_content_kind_counts,
    }


def _write_dataset(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.link(temporary, path)
    except FileExistsError as exc:
        raise FileExistsError(f"candidate dataset already exists; choose a new revision path: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def expand_candidate_dataset(
    index_dir: Path,
    *,
    output_path: Path | None = None,
    dataset_id: str | None = None,
    max_units: int = DEFAULT_MAX_UNITS,
    selected_records: list[dict[str, Any]] | None = None,
    questions_per_unit: int = 1,
    max_workers: int = 1,
    llm: ChatOpenAI | None = None,
    generator: CandidateGenerator | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    cancel_checker: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """从 staged index 生成一个独立版本的 generated_candidate 题集。

    ``selected_records`` 仅供具备自有检查点的调用方传入已完成模态轮询的分批单元；
    普通调用保持按 ``max_units`` 从完整 staged index 取样的既有行为。
    """

    if questions_per_unit < 1 or questions_per_unit > MAX_QUESTIONS_PER_UNIT:
        raise ValueError(f"questions_per_unit must be 1 to {MAX_QUESTIONS_PER_UNIT}")
    records, source_snapshot = load_staged_unit_records(Path(index_dir))
    selected = [dict(record) for record in selected_records] if selected_records is not None else _select_unit_records(records, max_units)
    if not selected:
        raise ValueError("selected_records must contain at least one staged unit")
    if cancel_checker and cancel_checker():
        raise InterruptedError("candidate generation was cancelled")
    if progress_callback:
        progress_callback({"stage": "generation", "selected_unit_count": len(selected)})
    dataset_id = _validate_dataset_id(dataset_id or f"generated_{source_snapshot['index_version']}")
    revision = (
        f"{source_snapshot['manifest_sha256'][:12]}_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_"
        f"{uuid.uuid4().hex[:8]}"
    )
    target = Path(output_path) if output_path else DEFAULT_OUTPUT_ROOT / f"{dataset_id}_{revision}.json"
    audit_path = target.with_name(f"{target.name}.audit.json")
    if target.exists():
        raise FileExistsError(f"candidate dataset already exists; choose a new revision path: {target}")
    if audit_path.exists():
        raise FileExistsError(f"candidate audit already exists; choose a new revision path: {audit_path}")
    worker_count = min(max(int(max_workers), 1), MAX_GENERATION_WORKERS, len(selected))

    generation_errors: list[dict[str, Any]] = []
    raw_candidates: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    generation_name = "ragas_0.4.3_generate_with_chunks"
    if generator is None:
        try:
            generated = _generate_ragas_rows(
                selected,
                max(1, len(selected) * questions_per_unit),
                llm=llm,
                max_workers=worker_count,
            )
            raw_candidates.extend((dict(candidate), None) for candidate in generated)
            if progress_callback:
                progress_callback({"stage": "generation", "generated_candidate_count": len(generated)})
        except Exception as exc:
            generation_errors.append({
                "scope": "ragas_generate_with_chunks",
                "error": f"{type(exc).__name__}: {exc}",
            })
    else:
        generation_name = "custom_test_generator"
        generated_by_position: dict[int, list[dict[str, Any]]] = {}

        def run_one(position: int, record: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
            values = [dict(value) for value in generator(record, questions_per_unit)]
            return position, values[:questions_per_unit]

        if worker_count == 1:
            for position, record in enumerate(selected):
                if cancel_checker and cancel_checker():
                    raise InterruptedError("candidate generation was cancelled")
                try:
                    generated_by_position[position] = run_one(position, record)[1]
                except Exception as exc:
                    generation_errors.append({"unit_id": record["unit_id"], "error": f"{type(exc).__name__}: {exc}"})
        else:
            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="rag_candidate") as pool:
                futures = {
                    pool.submit(run_one, position, record): position
                    for position, record in enumerate(selected)
                }
                for future in as_completed(futures):
                    if cancel_checker and cancel_checker():
                        raise InterruptedError("candidate generation was cancelled")
                    position = futures[future]
                    try:
                        position, values = future.result()
                        generated_by_position[position] = values
                    except Exception as exc:
                        generation_errors.append({"unit_id": selected[position]["unit_id"], "error": f"{type(exc).__name__}: {exc}"})
        for position, record in enumerate(selected):
            raw_candidates.extend((candidate, record) for candidate in generated_by_position.get(position, []))

    if cancel_checker and cancel_checker():
        raise InterruptedError("candidate generation was cancelled")

    rows: list[dict[str, Any]] = []
    for candidate_index, (candidate, record) in enumerate(raw_candidates, start=1):
        source = dict(candidate.get("source") or {})
        source.update(
            {
                "generator": generation_name,
                "review_status": "candidate",
                "synthesizer_name": candidate.get("synthesizer_name", ""),
                "source_snapshot": dict(source_snapshot),
            }
        )
        if record is not None:
            source.update(
                {
                    "unit_id": record["unit_id"],
                    "modality": record.get("modality", ""),
                    "content_kind": record.get("content_kind", ""),
                }
            )
            reference_contexts = [{"page_content": record["content"], "metadata": record["metadata"]}]
        else:
            reference_contexts = candidate.get("reference_contexts", [])
        rows.append(
            {
                **candidate,
                "sample_id": str(candidate.get("sample_id") or f"generated-{revision[-12:]}-{candidate_index:04d}"),
                "reference_contexts": reference_contexts,
                "source": source,
            }
        )

    accepted, rejected = _screen_candidate_rows(
        rows,
        source_snapshot=source_snapshot,
        source_records=selected,
    )
    coverage = _build_coverage_summary(accepted, selected)
    if progress_callback:
        progress_callback({
            "stage": "screening",
            "generated_candidate_count": len(rows),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
        })
    audit = {
        "schema_version": "rag_candidate_generation_audit_v1",
        "dataset_id": dataset_id,
        "dataset_revision": revision,
        "source_snapshot": source_snapshot,
        "generation": {
            "generator": generation_name,
            "requested_count": max(1, len(selected) * questions_per_unit),
            "worker_count": worker_count,
        },
        "generated_candidate_count": len(rows),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "rejections": rejected,
        "generation_errors": generation_errors,
        "coverage": coverage,
    }
    if not accepted:
        _write_dataset(audit_path, audit)
        raise ValueError(
            "no candidates passed quality screening "
            f"(generated={len(rows)}, rejected={len(rejected)}, generation_errors={len(generation_errors)}); "
            f"audit={audit_path}"
        )
    payload = {
        "schema_version": "rag_eval_v1",
        "dataset_id": dataset_id,
        "dataset_kind": "generated_candidate",
        "dataset_revision": revision,
        "source_snapshot": source_snapshot,
        "generation": audit["generation"],
        "screening": {
            "schema_version": "rag_candidate_screening_v1",
            "generated_candidate_count": len(rows),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "rejections": rejected,
            "generation_errors": generation_errors,
            "coverage": coverage,
        },
        "samples": accepted,
    }
    _write_dataset(target, payload)
    _write_dataset(audit_path, audit)
    if progress_callback:
        progress_callback({"stage": "completed", "accepted_count": len(accepted), "dataset_revision": revision})
    return {
        "dataset_path": str(target.resolve()),
        "dataset_id": dataset_id,
        "dataset_revision": revision,
        "source_snapshot": source_snapshot,
        "selected_unit_count": len(selected),
        "generated_candidate_count": len(rows),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "rejections": rejected,
        "generation_errors": generation_errors,
        "coverage": coverage,
        "worker_count": worker_count,
        "generation": audit["generation"],
        "audit_path": str(audit_path.resolve()),
        "candidate_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="从 staged index 生成 generated_candidate RAG 题集")
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--dataset-id", default=None)
    parser.add_argument("--max-units", type=int, default=DEFAULT_MAX_UNITS)
    parser.add_argument("--questions-per-unit", type=int, default=1)
    parser.add_argument("--max-workers", type=int, default=1)
    args = parser.parse_args()
    result = expand_candidate_dataset(
        args.index_dir,
        output_path=args.output,
        dataset_id=args.dataset_id,
        max_units=args.max_units,
        questions_per_unit=args.questions_per_unit,
        max_workers=args.max_workers,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
