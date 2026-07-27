"""已发布多模态索引的只读检索与父级证据输出。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma

from .assets import AssetStore
from .index import ActiveIndexRegistry, _embeddings, embedding_fingerprint, file_sha256
from .production import is_production_manifest


def multimodal_rag_search(questions: list[Any], max_results: int = 5) -> dict[str, Any]:
    """仅查询多模态 active pointer，绝不回退或混入 PubMedQA 索引。"""
    base = Path(__file__).resolve().parents[1]
    root = Path(__import__("os").getenv("MULTIMODAL_INDEX_ROOT", base / "multimodal_indexes"))
    registry = ActiveIndexRegistry(Path(__import__("os").getenv("MULTIMODAL_ACTIVE_INDEX_CONFIG", base / "multimodal_runtime" / "active_index.json")))
    active = registry.read()
    if not active:
        return {"success": False, "summary": "多模态知识库尚未发布", "questions": [], "evidence_count": 0, "evidence": []}
    version_dir = root / active["index_version"]
    manifest_path = version_dir / "manifest.json"
    if not manifest_path.exists() or file_sha256(manifest_path) != active.get("manifest_sha256"):
        return {"success": False, "summary": "多模态 active index 完整性校验失败", "questions": [], "evidence_count": 0, "evidence": []}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if __import__("os").getenv("MULTIMODAL_ALLOW_NON_PRODUCTION_ACTIVE", "").lower() != "true" and not is_production_manifest(manifest):
        return {"success": False, "summary": "多模态 active index 不是冻结的正式知识源", "error_code": "production_source_mismatch", "questions": [], "evidence_count": 0, "evidence": []}
    runtime_embedding = embedding_fingerprint()
    if active.get("embedding") != manifest.get("embedding") or manifest.get("embedding") != runtime_embedding:
        return {"success": False, "summary": "多模态 embedding 指纹不匹配，索引不可用", "error_code": "embedding_fingerprint_mismatch", "questions": [], "evidence_count": 0, "evidence": []}
    unit_list = [json.loads(line) for line in (version_dir / "units.jsonl").read_text(encoding="utf-8").splitlines() if line]
    units = {unit["unit_id"]: unit for unit in unit_list}
    db = Chroma(persist_directory=str(version_dir / "chroma"), collection_name=active["collection_name"], embedding_function=_embeddings())
    evidence: list[dict[str, Any]] = []
    for query in questions[:max_results]:
        question = query if isinstance(query, str) else str(query.get("question", query.get("content", "")))
        for document, score in db.similarity_search_with_relevance_scores(question, k=max_results * 4):
            unit = units.get(document.metadata.get("unit_id"))
            if not unit:
                continue
            if unit.get("modality") == "image" and not unit.get("vision_model") and not unit.get("raw_text", "").strip():
                continue
            asset_uri = unit.get("asset_uri")
            asset_available = not asset_uri or AssetStore(Path(__import__("os").getenv("MULTIMODAL_ASSET_DIR", base / "multimodal_assets"))).exists(asset_uri)
            evidence.append({"evidence_id": f"M{len(evidence) + 1}", "unit_id": unit["unit_id"], "document_id": unit["document_id"], "title": document.metadata.get("source_name", "多模态资料"), "page_number": unit.get("page_number"), "modality": unit["modality"], "content_kind": unit["content_kind"], "content": document.page_content, "asset_uri": asset_uri, "asset_available": asset_available, "parent_context": _parent_context(unit, unit_list), "score": float(score)})
            if len(evidence) >= max_results:
                break
    return {"success": True, "summary": f"已从多模态索引返回 {len(evidence)} 条证据", "questions": questions[:max_results], "evidence_count": len(evidence), "evidence": evidence}


def _parent_context(unit: dict[str, Any], all_units: list[dict[str, Any]]) -> str:
    """回取同一页面的正文单元，为图片、表格和公式提供邻近上下文。"""
    page_number = unit.get("page_number")
    if page_number is None:
        return unit.get("raw_text", "")
    nearby = [
        candidate.get("raw_text", "")
        for candidate in all_units
        if candidate.get("document_id") == unit.get("document_id")
        and candidate.get("page_number") == page_number
        and candidate.get("modality") == "text"
        and candidate.get("raw_text")
    ]
    return "\n".join(nearby[:3])
