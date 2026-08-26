"""Gold v2 审核冻结和 Baseline v2 绑定契约。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Agent.knowledge_base.rag.operation_datasets.candidate_generation import _write_dataset
from Agent.knowledge_base.rag.rag_config import RETRIEVAL_PROFILES
from Agent.knowledge_base.rag.rag_eval.contracts import evaluation_identity, load_eval_dataset_bundle
from config.rag_eval_paths import RAG_EVAL_BASELINE_ROOT
from observability.cli import write_cli_output


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PEARL_GOLD_V1 = PROJECT_ROOT / "Agent" / "knowledge_base" / "rag" / "data" / "eval" / "pearl_gold_v1.json"
DEFAULT_GOLD_V2_OUTPUT = PROJECT_ROOT / "Agent" / "knowledge_base" / "rag" / "data" / "eval" / "pearl_gold_v2.json"
DEFAULT_ACTIVE_POINTER = PROJECT_ROOT / "Agent" / "knowledge_base" / "multimodal_runtime" / "active_index.json"
DEFAULT_INDEX_ROOT = PROJECT_ROOT / "Agent" / "knowledge_base" / "multimodal_indexes"
DEFAULT_BASELINE_ROOT = RAG_EVAL_BASELINE_ROOT
GOLD_V2_ID = "pearl_gold_v2"
BASELINE_V2_SCHEMA = "rag_baseline_v2"
REVIEW_SCHEMA = "rag_candidate_review_v1"
INDEX_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
LOW_QUALITY_TYPO_PATTERN = re.compile(r"\b(?:wat|wht|teh|causl|relashun|zhow|btwn|woud|scietists|whats|whts)\b", re.IGNORECASE)
DOCUMENT_NAVIGATION_PATTERN = re.compile(r"\b(?:bibliography|section\s+\d|chapter|contents?|page(?:s)?\b)", re.IGNORECASE)
BARE_SYMBOL_REFERENCE_PATTERN = re.compile(
    r"\b(?:what|which)\s+(?:is|does|the)?\s*(?:[xyz]\d*|slippery)\b.*\b(?:diagram|picture|figure|table)\b",
    re.IGNORECASE,
)
PEARL_V1_COUNT = 24
EXPANDED_REVIEWED_COUNT = 48
LOCATOR_AUDIT_FIELDS = {
    "bound_index_version",
    "rebound_from_unit_id",
    "locator_rebind_algorithm",
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_versioned(path: Path, payload: dict[str, Any], *, replace_existing: bool = False) -> str | None:
    archived_path: Path | None = None
    if path.exists():
        if not replace_existing:
            raise FileExistsError(f"versioned artifact already exists; choose a new path: {path}")
        archive_dir = path.parent / "history"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archived_path = archive_dir / (
            f"{path.stem}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_"
            f"{_sha256(path)[:12]}{path.suffix}"
        )
        shutil.copy2(path, archived_path)
        path.unlink()
    _write_dataset(path, payload)
    return str(archived_path.resolve()) if archived_path else None


def _require_count(name: str, actual: int, expected: int) -> None:
    if actual != expected:
        raise ValueError(f"{name} must contain exactly {expected} samples, found {actual}")


def _load_index_units(index_dir: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    index_dir = Path(index_dir).resolve()
    manifest_path = index_dir / "manifest.json"
    state_path = index_dir / "build_state.json"
    units_path = index_dir / "units.jsonl"
    if any(not path.is_file() for path in (manifest_path, state_path, units_path)):
        raise FileNotFoundError("target staged index is missing manifest, build state, or units")
    manifest = _read_json(manifest_path)
    state = _read_json(state_path)
    if manifest.get("index_version") != index_dir.name:
        raise ValueError("target staged index version does not match manifest")
    if state.get("status") != "staged_complete":
        raise ValueError("target staged index is not complete")
    lines = [line for line in units_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if int(state.get("unit_count") or -1) != len(lines) or int(manifest.get("unit_count") or -1) != len(lines):
        raise ValueError("target staged index unit count is inconsistent")
    records = []
    for line_number, line in enumerate(lines, start=1):
        try:
            unit = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"target staged index unit {line_number} is invalid") from exc
        if not isinstance(unit, dict):
            raise ValueError(f"target staged index unit {line_number} is invalid")
        records.append({
            "unit_id": unit.get("unit_id"),
            "modality": unit.get("modality"),
            "content_kind": unit.get("content_kind"),
            "metadata": {
                "document_id": unit.get("document_id"),
                "page_number": unit.get("page_number"),
            },
        })
    snapshot = {
        "index_version": manifest.get("index_version"),
        "manifest_sha256": _sha256(manifest_path),
        "units_sha256": _sha256(units_path),
        "build_state_sha256": _sha256(state_path),
        "unit_count": len(records),
        "vector_count": int(state.get("vector_count") or 0),
        "manifest_schema_version": manifest.get("schema_version", ""),
    }
    index_version = str(snapshot.get("index_version") or "")
    if not INDEX_VERSION_PATTERN.fullmatch(index_version):
        raise ValueError("target staged index version is invalid")
    by_unit_id = {str(record.get("unit_id") or ""): record for record in records}
    if not by_unit_id or "" in by_unit_id:
        raise ValueError("target staged index contains an invalid unit_id")
    return by_unit_id, snapshot


def _runtime_locator(record: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(record.get("metadata") or {})
    locator = {
        key: (record.get(key) if key in {"unit_id", "modality", "content_kind"} else metadata.get(key))
        for key in ("unit_id", "document_id", "page_number", "modality", "content_kind")
        if (record.get(key) if key in {"unit_id", "modality", "content_kind"} else metadata.get(key)) not in (None, "")
    }
    if not locator.get("unit_id") or not locator.get("document_id"):
        raise ValueError("target staged index unit lacks a stable locator")
    return locator


def _question_quality_flags(question: str) -> list[str]:
    normalized = " ".join(str(question or "").split())
    flags = []
    if len(normalized) < 35:
        flags.append("question_too_short_or_underspecified")
    if len(normalized) > 420:
        flags.append("question_overly_compound")
    if LOW_QUALITY_TYPO_PATTERN.search(normalized):
        flags.append("obvious_typo_or_informal_wording")
    lowered = normalized.lower()
    if any(marker in lowered for marker in ("this here pdf", "provided context", "what is y in the diagram", "what z2 do", "what the ", "so like")) or BARE_SYMBOL_REFERENCE_PATTERN.search(normalized):
        flags.append("ambiguous_reference")
    if DOCUMENT_NAVIGATION_PATTERN.search(normalized):
        flags.append("document_navigation_or_structure_question")
    if len(re.findall(r"\b(?:figure|table|diagram|picture)\b", lowered)) >= 2:
        flags.append("multi_figure_or_table_comparison")
    if "pearl_2009" in lowered and "pearl_mackenzie" in lowered:
        flags.append("cross_document_question")
    return flags


def _validate_locator(locator: dict[str, Any], *, record: dict[str, Any], index_version: str, sample_id: str) -> None:
    if str(locator.get("bound_index_version") or "") != index_version:
        raise ValueError(f"{sample_id}: gold locator bound_index_version must equal {index_version}")
    if str(locator.get("unit_id") or "") != str(record.get("unit_id") or ""):
        raise ValueError(f"{sample_id}: gold locator unit_id is unavailable in target index")
    metadata = dict(record.get("metadata") or {})
    for field in ("document_id", "page_number", "modality", "content_kind"):
        value = locator.get(field)
        actual = record.get(field) if field in {"modality", "content_kind"} else metadata.get(field)
        if value not in (None, "") and value != actual:
            raise ValueError(f"{sample_id}: gold locator {field} does not match target index")


def validate_candidate_gold_binding(candidate: dict[str, Any], *, index_dir: Path) -> dict[str, Any]:
    """验证候选题 evidence 已精确绑定到本次评测 staged index。"""
    return validate_frozen_gold_bundle(candidate, index_dir=index_dir, require_generated_candidate=True)


def validate_frozen_gold_bundle(
    dataset: dict[str, Any], *, index_dir: Path, expected_snapshot: dict[str, Any] | None = None,
    require_generated_candidate: bool = False, require_fixed_binding: bool = False,
) -> dict[str, Any]:
    """以 units.jsonl 为真相校验候选题和冻结 Gold 的 locator。"""
    by_unit_id, snapshot = _load_index_units(index_dir)
    index_version = str(snapshot["index_version"])
    expected_snapshot = dict(expected_snapshot or {})
    if require_generated_candidate:
        source_snapshot = dict(dataset.get("source_snapshot") or {})
        if source_snapshot.get("index_version") != index_version:
            raise ValueError("candidate source_snapshot index_version does not match target staged index")
        if expected_snapshot.get("manifest_sha256") and source_snapshot.get("manifest_sha256") != expected_snapshot["manifest_sha256"]:
            raise ValueError("candidate source_snapshot manifest_sha256 does not match target staged index")
    checked = 0
    checked_samples = 0
    checked_fixed_samples = 0
    checked_generated_samples = 0
    for sample in dataset.get("samples") or []:
        sample_id = str(sample.get("sample_id") or "candidate")
        source = dict(sample.get("source") or {})
        generated = require_generated_candidate or bool(source.get("generator"))
        if not generated:
            if not require_fixed_binding:
                continue
            checked_fixed_samples += 1
        else:
            checked_generated_samples += 1
            binding = dict(source.get("index_binding") or {})
            if not require_generated_candidate and not str(binding.get("index_version") or "").strip():
                raise ValueError(f"{sample_id}: frozen candidate Gold index_binding.index_version is required")
            for field, expected in (("index_version", index_version), ("manifest_sha256", expected_snapshot.get("manifest_sha256"))):
                actual = binding.get(field)
                if expected not in (None, "") and actual not in (None, "") and actual != expected:
                    raise ValueError(f"{sample_id}: frozen candidate Gold {field} does not match evaluation index")
        evidence = sample.get("gold_evidence") or []
        if not evidence:
            raise ValueError(f"{sample_id}: gold_evidence is required")
        for locator in evidence:
            if not isinstance(locator, dict):
                raise ValueError(f"{sample_id}: gold_evidence locator is invalid")
            if not generated and require_fixed_binding:
                missing_fields = [
                    field for field in ("unit_id", "document_id", "page_number", "modality", "content_kind", "bound_index_version")
                    if locator.get(field) in (None, "")
                ]
                if missing_fields:
                    raise ValueError(f"{sample_id}: fixed Gold locator is missing {', '.join(missing_fields)}")
            unit_id = str(locator.get("unit_id") or "")
            record = by_unit_id.get(unit_id)
            if record is None:
                raise ValueError(f"{sample_id}: gold locator unit_id is unavailable in target index")
            if require_generated_candidate or (not generated and require_fixed_binding):
                _validate_locator(locator, record=record, index_version=index_version, sample_id=sample_id)
            else:
                metadata = dict(record.get("metadata") or {})
                for field in ("document_id", "page_number", "modality", "content_kind"):
                    actual = record.get(field) if field in {"modality", "content_kind"} else metadata.get(field)
                    if locator.get(field) not in (None, "") and locator.get(field) != actual:
                        raise ValueError(f"{sample_id}: frozen Gold locator {field} does not match evaluation index")
            checked += 1
        checked_samples += 1
    return {
        "index_version": index_version,
        "checked_locator_count": checked,
        "checked_sample_count": checked_samples,
        "checked_fixed_sample_count": checked_fixed_samples,
        "checked_generated_sample_count": checked_generated_samples,
        "checked_candidate_sample_count": checked_generated_samples,
    }


def rebind_candidate_dataset_to_index(
    *,
    candidate_path: Path,
    index_dir: Path,
    output_path: Path,
) -> dict[str, Any]:
    """将候选题 locator 重绑到目标索引，并把它们送回人工复审。"""
    candidate = load_eval_dataset_bundle(candidate_path)
    if candidate["dataset_kind"] != "generated_candidate":
        raise ValueError("candidate input must be generated_candidate")
    by_unit_id, snapshot = _load_index_units(index_dir)
    rebound_samples: list[dict[str, Any]] = []
    for raw_sample in candidate["samples"]:
        sample = dict(raw_sample)
        rebound_evidence = []
        for raw_locator in sample.get("gold_evidence") or []:
            locator = dict(raw_locator)
            target_unit_id = str(locator.get("rebound_from_unit_id") or locator.get("unit_id") or "")
            record = by_unit_id.get(target_unit_id)
            if record is None:
                raise ValueError(f"{sample.get('sample_id')}: cannot rebind locator to target staged index")
            rebound = _runtime_locator(record)
            rebound["bound_index_version"] = snapshot["index_version"]
            rebound_evidence.append(rebound)
        if not rebound_evidence:
            raise ValueError(f"{sample.get('sample_id')}: gold_evidence is required for rebind")
        sample["gold_evidence"] = rebound_evidence
        source = dict(sample.get("source") or {})
        source["rebound_from_source_snapshot"] = dict(source.get("source_snapshot") or candidate.get("source_snapshot") or {})
        source["source_snapshot"] = dict(snapshot)
        source["index_binding"] = dict(snapshot)
        source["review_status"] = "needs_revision"
        source["rebind_status"] = "requires_reapproval"
        source["review_flags"] = _question_quality_flags(str(sample.get("question") or ""))
        sample["source"] = source
        rebound_samples.append(sample)
    rebound = dict(candidate)
    rebound["dataset_revision"] = f"{candidate.get('dataset_revision', 'unversioned')}_rebound_{snapshot['index_version']}"
    rebound["source_snapshot"] = dict(snapshot)
    rebound["samples"] = rebound_samples
    rebound["rebind"] = {
        "target_index_version": snapshot["index_version"],
        "status": "requires_reapproval",
        "sample_count": len(rebound_samples),
    }
    _write_dataset(output_path, rebound)
    return {
        "candidate_dataset_path": str(Path(output_path).resolve()),
        "candidate_dataset_revision": rebound["dataset_revision"],
        "index_version": snapshot["index_version"],
        "sample_count": len(rebound_samples),
        "review_status": "requires_reapproval",
    }


def write_reapproval_manifest(*, candidate_path: Path, output_path: Path) -> dict[str, Any]:
    """为重绑候选集生成待复审清单；不自动恢复任何批准决定。"""
    candidate = load_eval_dataset_bundle(candidate_path)
    decisions = []
    flagged = 0
    for sample in candidate["samples"]:
        flags = list(dict(sample.get("source") or {}).get("review_flags") or [])
        if flags:
            flagged += 1
        note = "Gold locator 已重绑到当前索引，需重新审核。"
        if flags:
            note += " 自动复审提示：" + "、".join(flags)
        decisions.append({"sample_id": sample["sample_id"], "decision": "needs_revision", "note": note})
    payload = {
        "schema_version": REVIEW_SCHEMA,
        "reviewer": "rebind-pending-review",
        "candidate_dataset_id": candidate["dataset_id"],
        "candidate_dataset_revision": candidate.get("dataset_revision", ""),
        "candidate_sha256": _sha256(candidate_path),
        "decisions": decisions,
        "review_status": "requires_reapproval",
    }
    _write_dataset(output_path, payload)
    return {"review_manifest_path": str(Path(output_path).resolve()), "decision_count": len(decisions), "flagged_sample_count": flagged}


def validate_frozen_gold_binding(dataset_path: Path, *, index_dir: Path) -> dict[str, Any]:
    """拒绝在非绑定索引上运行含候选题的冻结 Gold，避免产生伪低分。"""
    return validate_frozen_gold_bundle(
        load_eval_dataset_bundle(dataset_path),
        index_dir=index_dir,
        require_fixed_binding=True,
    )


def _load_review_manifest(path: Path, candidate: dict[str, Any], candidate_path: Path) -> tuple[str, set[str]]:
    review = _read_json(path)
    if not isinstance(review, dict) or review.get("schema_version") != REVIEW_SCHEMA:
        raise ValueError(f"review manifest must use {REVIEW_SCHEMA}")
    reviewer = str(review.get("reviewer") or "").strip()
    if not reviewer:
        raise ValueError("reviewer is required")
    if review.get("candidate_dataset_id") != candidate["dataset_id"]:
        raise ValueError("review manifest candidate_dataset_id does not match candidate dataset")
    if review.get("candidate_dataset_revision") != candidate.get("dataset_revision", ""):
        raise ValueError("review manifest candidate_dataset_revision does not match candidate dataset")
    expected_sha = str(review.get("candidate_sha256") or "").strip()
    if not expected_sha or expected_sha != _sha256(candidate_path):
        raise ValueError("review manifest candidate_sha256 does not match candidate dataset")
    decisions = review.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("review manifest decisions must be a list")
    decision_by_id: dict[str, str] = {}
    for decision in decisions:
        if not isinstance(decision, dict):
            raise ValueError("review decision must be an object")
        sample_id = str(decision.get("sample_id") or "").strip()
        state = str(decision.get("decision") or "").strip()
        if not sample_id or state not in {"approved", "rejected", "needs_revision"}:
            raise ValueError("review decision requires sample_id and a supported decision")
        if sample_id in decision_by_id:
            raise ValueError(f"duplicate review decision: {sample_id}")
        decision_by_id[sample_id] = state
    candidate_ids = {str(sample["sample_id"]) for sample in candidate["samples"]}
    if not set(decision_by_id).issubset(candidate_ids):
        raise ValueError("review manifest contains an unknown candidate sample_id")
    approved = {sample_id for sample_id, state in decision_by_id.items() if state == "approved"}
    return reviewer, approved


def freeze_pearl_gold_v2(
    *,
    candidate_path: Path,
    review_manifest_path: Path,
    index_dir: Path,
    pearl_path: Path = DEFAULT_PEARL_GOLD_V1,
    output_path: Path = DEFAULT_GOLD_V2_OUTPUT,
    replace_existing: bool = False,
) -> dict[str, Any]:
    """只接受显式审核清单，把 24+48 题冻结为新的 Gold v2。"""

    pearl = load_eval_dataset_bundle(pearl_path)
    candidate = load_eval_dataset_bundle(candidate_path)
    _require_count("Pearl gold v1", len(pearl["samples"]), PEARL_V1_COUNT)
    if pearl["dataset_id"] != "pearl_gold_v1" or pearl["dataset_kind"] != "gold_regression":
        raise ValueError("pearl input must be pearl_gold_v1 gold_regression")
    if candidate["dataset_kind"] != "generated_candidate":
        raise ValueError("candidate input must be generated_candidate")

    binding = validate_candidate_gold_binding(candidate, index_dir=index_dir)
    reviewer, approved_ids = _load_review_manifest(review_manifest_path, candidate, candidate_path)
    reviewed_samples = [sample for sample in candidate["samples"] if str(sample["sample_id"]) in approved_ids]
    _require_count("candidate approved set", len(reviewed_samples), EXPANDED_REVIEWED_COUNT)
    if any(not sample.get("gold_evidence") for sample in reviewed_samples):
        raise ValueError("every reviewed candidate must have gold_evidence before freezing")

    freeze_revision = (
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_"
        f"{uuid.uuid4().hex[:8]}"
    )
    freeze_id = hashlib.sha256(
        json.dumps(
            {
                "pearl_sha256": _sha256(pearl_path),
                "candidate_sha256": _sha256(candidate_path),
                "review_sha256": _sha256(review_manifest_path),
                "revision": freeze_revision,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    frozen_samples = []
    for sample in pearl["samples"]:
        frozen = dict(sample)
        frozen["source"] = {
            **dict(sample.get("source") or {}),
            "review_status": "frozen",
            "reviewer": reviewer,
            "freeze_id": freeze_id,
            "freeze_revision": freeze_revision,
        }
        frozen_samples.append(frozen)
    for sample in reviewed_samples:
        frozen = dict(sample)
        frozen["gold_evidence"] = [
            {key: value for key, value in dict(locator).items() if key not in LOCATOR_AUDIT_FIELDS}
            for locator in sample["gold_evidence"]
        ]
        frozen["source"] = {
            **dict(sample.get("source") or {}),
            "review_status": "frozen",
            "reviewer": reviewer,
            "freeze_id": freeze_id,
            "freeze_revision": freeze_revision,
            "index_binding": binding,
        }
        frozen_samples.append(frozen)

    payload = {
        "schema_version": "rag_eval_v1",
        "dataset_id": GOLD_V2_ID,
        "dataset_kind": "gold_regression",
        "dataset_revision": freeze_revision,
        "source_snapshot": {
            "pearl_gold_v1": {
                "dataset_id": pearl["dataset_id"],
                "dataset_revision": pearl.get("dataset_revision", ""),
                "sha256": _sha256(pearl_path),
                "sample_count": len(pearl["samples"]),
            },
            "candidate_review": {
                "dataset_id": candidate["dataset_id"],
                "dataset_revision": candidate.get("dataset_revision", ""),
                "sha256": _sha256(candidate_path),
                "review_manifest_sha256": _sha256(review_manifest_path),
                "sample_count": len(candidate["samples"]),
                "index_binding": binding,
            },
        },
        "review": {
            "schema_version": REVIEW_SCHEMA,
            "status": "frozen",
            "reviewer": reviewer,
            "freeze_id": freeze_id,
            "reviewed_counts": {"pearl": PEARL_V1_COUNT, "expanded": EXPANDED_REVIEWED_COUNT},
        },
        "samples": frozen_samples,
    }
    archived_dataset_path = _write_versioned(output_path, payload, replace_existing=replace_existing)
    return {
        "dataset_path": str(output_path.resolve()),
        "dataset_id": GOLD_V2_ID,
        "dataset_revision": freeze_revision,
        "sample_count": len(frozen_samples),
        "review_status": "frozen",
        "freeze_id": freeze_id,
        "archived_dataset_path": archived_dataset_path,
    }


def _resolve_active_index(pointer_path: Path) -> dict[str, Any]:
    pointer = _read_json(pointer_path)
    if not isinstance(pointer, dict):
        raise ValueError("active pointer must be a JSON object")
    index_version = str(pointer.get("index_version") or "").strip()
    if not INDEX_VERSION_PATTERN.fullmatch(index_version):
        raise ValueError("active pointer index_version is invalid")
    index_root = Path(os.getenv("MULTIMODAL_INDEX_ROOT", str(DEFAULT_INDEX_ROOT))).resolve()
    index_dir = (index_root / index_version).resolve()
    if index_dir.parent != index_root or not index_dir.is_dir():
        raise ValueError("active pointer index directory is unavailable")
    manifest_path = index_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("active pointer index manifest is unavailable")
    manifest_sha = _sha256(manifest_path)
    if manifest_sha != str(pointer.get("manifest_sha256") or ""):
        raise ValueError("active pointer manifest hash mismatch")
    manifest = _read_json(manifest_path)
    if manifest.get("index_version") != index_version:
        raise ValueError("active pointer index version does not match manifest")
    return {
        "pointer_path": str(pointer_path.resolve()),
        "pointer_sha256": _sha256(pointer_path),
        "index_version": index_version,
        "index_dir": str(index_dir),
        "manifest_sha256": manifest_sha,
        "embedding": pointer.get("embedding", {}),
    }


def bind_baseline_v2(
    *,
    dataset_path: Path,
    active_pointer_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """生成绑定固定 Gold v2、active index 和 active_current 的 Baseline v2 清单。"""

    dataset = load_eval_dataset_bundle(dataset_path)
    if dataset["dataset_id"] != GOLD_V2_ID or dataset["dataset_kind"] != "gold_regression":
        raise ValueError("Baseline v2 requires pearl_gold_v2 gold_regression")
    _require_count("Gold v2", len(dataset["samples"]), PEARL_V1_COUNT + EXPANDED_REVIEWED_COUNT)
    pointer_path = Path(active_pointer_path or os.getenv("MULTIMODAL_ACTIVE_INDEX_CONFIG", str(DEFAULT_ACTIVE_POINTER)))
    index_binding = _resolve_active_index(pointer_path)
    validate_frozen_gold_binding(dataset_path, index_dir=Path(index_binding["index_dir"]))
    revision = f"{dataset.get('dataset_revision', 'unversioned')}_{index_binding['index_version']}"
    target = output_path or DEFAULT_BASELINE_ROOT / f"baseline_v2_{revision}.json"
    payload = {
        "schema_version": BASELINE_V2_SCHEMA,
        "baseline_id": "pearl_baseline_v2",
        "dataset_identity": evaluation_identity(dataset_path),
        "index_binding": index_binding,
        "retrieval_binding": {
            "profile": "active_current",
            "config": dict(RETRIEVAL_PROFILES["active_current"]),
        },
        "release_policy": {
            "active_pointer_mutation": False,
            "profile_publication": False,
            "requires_real_retrieval_and_ragas_evidence": True,
        },
    }
    _write_versioned(target, payload)
    return {
        "baseline_path": str(target.resolve()),
        "baseline_id": payload["baseline_id"],
        "dataset_identity": payload["dataset_identity"],
        "index_binding": index_binding,
        "retrieval_profile": "active_current",
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze-gold")
    freeze.add_argument("--candidate", type=Path, required=True)
    freeze.add_argument("--review-manifest", type=Path, required=True)
    freeze.add_argument("--index-dir", type=Path, required=True)
    freeze.add_argument("--pearl", type=Path, default=DEFAULT_PEARL_GOLD_V1)
    freeze.add_argument("--output", type=Path, default=DEFAULT_GOLD_V2_OUTPUT)
    baseline = subparsers.add_parser("bind-baseline")
    baseline.add_argument("--dataset", type=Path, required=True)
    baseline.add_argument("--active-pointer", type=Path, default=None)
    baseline.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.command == "freeze-gold":
        result = freeze_pearl_gold_v2(
            candidate_path=args.candidate,
            review_manifest_path=args.review_manifest,
            index_dir=args.index_dir,
            pearl_path=args.pearl,
            output_path=args.output,
        )
    else:
        result = bind_baseline_v2(
            dataset_path=args.dataset,
            active_pointer_path=args.active_pointer,
            output_path=args.output,
        )
    write_cli_output(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
