"""多模态解析产物接入 RAG 评测所需的只读契约。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from Agent.knowledge_base.embedding_runtime import EmbeddingConfiguration
from .contracts import canonical_json
from .defaults import DEFAULTS_PATH, ROOT, load_production_defaults
from .index import embedding_fingerprint
from .production import has_frozen_production_identity
from .release import POINTER_SCHEMA_VERSION, compute_manifest_sha256, validate_manifest_artifacts, validate_manifest_contract


MULTIMODAL_EVAL_SCHEMA = "multimodal_retrieval_eval_v1"


def is_multimodal_eval_payload(payload: Any) -> bool:
    """判断 JSON payload 是否为冻结的多模态检索题集。"""
    return isinstance(payload, dict) and payload.get("schema_version") == MULTIMODAL_EVAL_SCHEMA


def load_multimodal_eval_dataset(path: str | Path) -> list[dict[str, Any]]:
    """读取多模态题集并转换成 RAG eval 使用的通用样本结构。"""
    dataset_path = Path(path)
    payload = json.loads(dataset_path.read_text(encoding="utf-8-sig"))
    if not is_multimodal_eval_payload(payload):
        raise ValueError("unsupported multimodal evaluation dataset schema")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not 20 <= len(cases) <= 30:
        raise ValueError("multimodal evaluation dataset must contain 20 to 30 cases")

    samples: list[dict[str, Any]] = []
    for row_index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise ValueError(f"multimodal evaluation case {row_index} must be an object")
        required = {
            "case_id",
            "question",
            "gold_doc_ids",
            "gold_page_numbers",
            "expected_modality",
            "reference_answer",
            "human_reviewed",
        }
        if not required.issubset(case) or not case["human_reviewed"]:
            raise ValueError(f"incomplete multimodal evaluation case: {case.get('case_id', row_index)}")
        key_facts = [str(item).strip() for item in case.get("key_facts", []) if str(item).strip()]
        reference = str(case["reference_answer"]).strip()
        samples.append(
            {
                "sample_id": str(case["case_id"]),
                "question": str(case["question"]).strip(),
                "reference_answer": reference,
                "expected_claims": key_facts or [reference],
                "judge_rubric": {
                    "must_cover": key_facts or [reference],
                    "avoid": ["不得引入检索证据之外的事实"],
                },
                "gold_doc_ids": list(case["gold_doc_ids"]),
                "gold_page_numbers": list(case["gold_page_numbers"]),
                "gold_unit_ids": list(case.get("gold_unit_ids", [])),
                "expected_modality": str(case["expected_modality"]),
                "expected_corpus": "official",
                "expected_sources": list(case["gold_doc_ids"]),
                "question_type": "multimodal_locator",
                "source": {
                    "dataset": MULTIMODAL_EVAL_SCHEMA,
                    "row_index": row_index,
                },
                "evaluation_corpus": "multimodal",
                "evaluation_dataset_schema": MULTIMODAL_EVAL_SCHEMA,
            }
        )
    return samples


def is_multimodal_eval_dataset(path: str | Path) -> bool:
    """在不加载 active index 的情况下识别多模态题集文件。"""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return False
    return is_multimodal_eval_payload(payload)


def read_active_release_identity(*, strict: bool = True) -> dict[str, Any]:
    """只读校验 active pointer、manifest 和运行时 embedding 指纹。"""
    active_path = Path(
        os.getenv(
            "MULTIMODAL_ACTIVE_INDEX_CONFIG",
            ROOT / "Agent" / "knowledge_base" / "multimodal_runtime" / "active_index.json",
        )
    )
    if not active_path.is_file():
        if strict:
            raise FileNotFoundError(f"多模态 active pointer 不存在: {active_path}")
        return {"status": "missing", "active_pointer_path": str(active_path.resolve())}

    active = json.loads(active_path.read_text(encoding="utf-8"))
    index_root = Path(
        os.getenv(
            "MULTIMODAL_INDEX_ROOT",
            ROOT / "Agent" / "knowledge_base" / "multimodal_indexes",
        )
    ).resolve()
    pointer_entry = active.get("active") if isinstance(active.get("active"), dict) else active
    if not isinstance(pointer_entry, dict):
        raise ValueError("多模态 active pointer 缺少 active release")
    if isinstance(active.get("active"), dict) and active.get("schema_version") != POINTER_SCHEMA_VERSION:
        raise ValueError("多模态 active pointer schema 不受支持")
    relative_index_path = Path(str(pointer_entry.get("index_path", "")))
    if not relative_index_path.parts or relative_index_path.is_absolute():
        raise ValueError("多模态 active index_path 必须是相对路径")
    vector_db_dir = (index_root / relative_index_path).resolve()
    try:
        vector_db_dir.relative_to(index_root)
    except ValueError as exc:
        raise ValueError("多模态 active index_path 越界") from exc

    manifest_path = vector_db_dir.parent / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"多模态 manifest 不存在: {manifest_path}")
    manifest_sha256 = compute_manifest_sha256(manifest_path)
    if manifest_sha256 != pointer_entry.get("manifest_sha256"):
        raise ValueError("多模态 active index manifest 哈希不匹配")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("identity_sha256") or manifest.get("schema_version") == 6:
        validate_manifest_contract(manifest)
        validate_manifest_artifacts(manifest, vector_db_dir.parent)
    if strict and os.getenv("MULTIMODAL_ALLOW_NON_PRODUCTION_ACTIVE", "").lower() != "true":
        if not has_frozen_production_identity(manifest):
            raise ValueError("多模态 active index 不是冻结的正式知识源")
        from .production import validate_production_manifest

        policy_failures = validate_production_manifest(manifest)
        if policy_failures:
            raise ValueError("多模态 active release 正式策略不允许: " + ", ".join(policy_failures))

    manifest_embedding_config = manifest.get("embedding_config")
    if not isinstance(manifest_embedding_config, dict) and isinstance(manifest.get("embedding"), dict) and "distance_metric" in manifest["embedding"]:
        manifest_embedding_config = manifest["embedding"]
    if isinstance(manifest_embedding_config, dict):
        config = EmbeddingConfiguration.from_manifest(manifest_embedding_config)
        runtime_embedding = config.fingerprint()
        manifest_embedding = manifest.get("embedding")
        if isinstance(manifest_embedding, dict) and "distance_metric" not in manifest_embedding and manifest_embedding != runtime_embedding:
            raise ValueError("多模态 embedding 指纹不匹配")
        if isinstance(pointer_entry.get("embedding"), dict) and pointer_entry["embedding"] != runtime_embedding:
            raise ValueError("多模态 active embedding 指纹不匹配")
    else:
        runtime_embedding = embedding_fingerprint()
        pointer_embedding = pointer_entry.get("embedding") or active.get("embedding")
        if (pointer_embedding is not None and pointer_embedding != manifest.get("embedding")) or manifest.get("embedding") != runtime_embedding:
            raise ValueError("多模态 embedding 指纹不匹配")

    strategy = {
        "parser": manifest.get("parser"),
        "pdf_parser": manifest.get("build_configuration", {}).get("pdf_parser"),
        "vision": manifest.get("build_configuration", {}).get("vision"),
        "embedding": manifest.get("embedding"),
    }
    return {
        "status": "ready",
        "index_version": pointer_entry.get("release_id") or pointer_entry.get("index_version"),
        "collection_name": pointer_entry.get("collection_name") or manifest.get("collection_name") or manifest.get("retrieval_index", {}).get("collection"),
        "vector_db_dir": str(vector_db_dir),
        "active_pointer_path": str(active_path.resolve()),
        "manifest_sha256": manifest_sha256,
        "embedding": manifest.get("embedding"),
        "embedding_config": manifest.get("embedding_config"),
        "strategy": strategy,
        "strategy_fingerprint": hashlib.sha256(canonical_json(strategy).encode("utf-8")).hexdigest(),
        "source_hashes": [
            {"relative_path": source.get("relative_path"), "content_hash": source.get("content_hash")}
            for source in manifest.get("sources", [])
            if isinstance(source, dict)
        ],
    }


def evaluation_identity(dataset_path: str | Path) -> dict[str, Any]:
    """返回一次 RAG_EVAL 运行需要绑定的题集、索引和解析策略指纹。"""
    path = Path(dataset_path)
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not is_multimodal_eval_payload(payload):
        return {
            "evaluation_corpus": "legacy",
            "dataset_path": str(path.resolve()),
            "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    defaults = load_production_defaults()
    release = read_active_release_identity()
    release_strategy = release.get("strategy", {})
    if release_strategy.get("parser") != defaults.get("parser"):
        raise ValueError("多模态 active index parser 策略与当前生产默认值不匹配")
    if release_strategy.get("pdf_parser") != defaults.get("pdf_parser"):
        raise ValueError("多模态 active index PDF parser 策略与当前生产默认值不匹配")
    release_vision = release_strategy.get("vision") or {}
    expected_vision = defaults.get("vision") or {}
    vision_pairs = (
        ("enabled", "remote_enabled"),
        ("local_ocr_enabled", "local_ocr_enabled"),
    )
    if any(release_vision.get(actual) != expected_vision.get(expected) for actual, expected in vision_pairs):
        raise ValueError("多模态 active index vision 策略与当前生产默认值不匹配")
    return {
        "evaluation_corpus": "multimodal",
        "dataset_schema": MULTIMODAL_EVAL_SCHEMA,
        "dataset_path": str(path.resolve()),
        "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "case_count": len(payload.get("cases", [])),
        "production_defaults_sha256": hashlib.sha256(
            DEFAULTS_PATH.read_bytes()
        ).hexdigest(),
        "production_parser": defaults["parser"],
        "index_version": release["index_version"],
        "collection_name": release["collection_name"],
        "manifest_sha256": release["manifest_sha256"],
        "embedding": release["embedding"],
        "strategy_fingerprint": release["strategy_fingerprint"],
        "source_hashes": release["source_hashes"],
    }


def validate_multimodal_eval_dataset(path: str | Path) -> dict[str, Any]:
    """校验多模态题集结构，不读取向量库或触发模型。"""
    try:
        samples = load_multimodal_eval_dataset(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {"schema_version": MULTIMODAL_EVAL_SCHEMA, "sample_count": 0, "errors": [str(exc)]}
    errors: list[str] = []
    sample_ids = [sample["sample_id"] for sample in samples]
    if len(set(sample_ids)) != len(sample_ids):
        errors.append("multimodal evaluation dataset contains duplicate case_id values")
    for sample in samples:
        if not sample["gold_doc_ids"] or not sample["gold_page_numbers"]:
            errors.append(f"{sample['sample_id']}: gold document and page locators are required")
        if sample["expected_modality"] not in {"text", "image", "table", "equation", "page"}:
            errors.append(f"{sample['sample_id']}: unsupported expected_modality")
    return {
        "schema_version": MULTIMODAL_EVAL_SCHEMA,
        "sample_count": len(samples),
        "with_locator_gold": sum(bool(sample["gold_page_numbers"]) for sample in samples),
        "with_reference_answer": sum(bool(sample["reference_answer"]) for sample in samples),
        "errors": errors,
    }
