"""OmniDocBench 固定子集的本地审计、暂存检索评测和坏例报告。"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .assets import AssetStore


OMNIDOCBENCH_REVISION = "aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec"
Chroma: Any | None = None


def _embeddings() -> Any:
    """按需加载本地 embedding，避免纯审计路径导入模型运行时。"""
    from .index import _embeddings as load_embeddings

    return load_embeddings()
FIXED_SAMPLES = (
    {"sample_id": "handwritten_table", "relative_path": "images/notes_1ba14cb325bc448f7201b20502ecf2b5_11.jpg", "coverage": "手写/扫描风格中文表格", "attributes": {"data_source": "note", "language": "simplified_chinese"}, "required_categories": ("table", "text_block")},
    {"sample_id": "complex_table", "relative_path": "images/page-c7792da7-4167-4f5c-a7ca-ec0f8833f83b.png", "coverage": "复杂表格", "attributes": {"subset": "table_hard"}, "required_categories": ("table",)},
    {"sample_id": "color_figure", "relative_path": "images/page-67013be9-58e5-4842-809d-7a3c1fc91fc7.png", "coverage": "彩色教材图文", "attributes": {"data_source": "colorful_textbook"}, "required_categories": ("figure", "text_block")},
    {"sample_id": "three_column", "relative_path": "images/yanbaor2_0071908e787f90267682e19ef093bb18dda6e1c1614534c445ddd62c425b3a94.pdf_44.jpg", "coverage": "英文三栏版式", "attributes": {"layout": "three_column", "language": "english"}, "required_categories": ("figure", "text_block")},
    {"sample_id": "formula_hard", "relative_path": "images/page-d1561665-5359-42fe-920c-d6e3bff81953.png", "coverage": "公式困难页", "attributes": {"subset": "equation_hard"}, "required_categories": ("equation_isolated",)},
    {"sample_id": "mixed_language", "relative_path": "images/page-59ff417b-63b3-40a4-a6ac-8fc2cdf71b5f.png", "coverage": "中英混排及水印", "attributes": {"language": "en_ch_mixed"}, "required_categories": ("text_block",)},
)


def audit_omnidocbench_subset(root: Path) -> dict[str, Any]:
    """验证固定子集与官方标注的版本、路径、属性和文件哈希。"""
    annotation_path = root / "OmniDocBench.json"
    if not annotation_path.is_file():
        raise FileNotFoundError("OmniDocBench.json is required for subset audit")
    records = _annotation_records(annotation_path)
    samples: list[dict[str, Any]] = []
    failures: list[str] = []
    for specification in FIXED_SAMPLES:
        record = records.get(Path(specification["relative_path"]).name)
        source_path = root / specification["relative_path"]
        sample_failures: list[str] = []
        if record is None:
            sample_failures.append("annotation_missing")
            attributes: dict[str, Any] = {}
            categories: set[str] = set()
        else:
            attributes = record["page_info"].get("page_attribute", {})
            categories = {str(item.get("category_type", "")) for item in record.get("layout_dets", [])}
            if any(attributes.get(key) != value for key, value in specification["attributes"].items()):
                sample_failures.append("annotation_attribute_mismatch")
            if not set(specification["required_categories"]).issubset(categories):
                sample_failures.append("annotation_category_mismatch")
        if not source_path.is_file():
            sample_failures.append("image_missing")
        samples.append({
            "sample_id": specification["sample_id"], "relative_path": specification["relative_path"], "coverage": specification["coverage"],
            "sha256": _sha256(source_path) if source_path.is_file() else None, "attributes": attributes,
            "categories": sorted(categories), "failures": sample_failures,
        })
        failures.extend(f"{specification['sample_id']}:{item}" for item in sample_failures)
    return {"dataset": "opendatalab/OmniDocBench", "revision": OMNIDOCBENCH_REVISION, "annotation_sha256": _sha256(annotation_path), "sample_count": len(samples), "passed": not failures, "failures": failures, "samples": samples}


def evaluate_omnidocbench_staged_index(root: Path, index_root: Path, index_version: str, asset_root: Path, output_dir: Path) -> dict[str, Any]:
    """用固定 OCR 片段检查已增强暂存索引的文档可检索性并输出坏例报告。"""
    chroma_class = Chroma
    if chroma_class is None:
        from langchain_chroma import Chroma as chroma_class

    audit = audit_omnidocbench_subset(root)
    version_dir = index_root / index_version
    manifest = json.loads((version_dir / "manifest.json").read_text(encoding="utf-8"))
    units = [json.loads(line) for line in (version_dir / "units.jsonl").read_text(encoding="utf-8").splitlines() if line]
    document_by_path = {document["relative_path"]: document for document in manifest.get("documents", [])}
    store = AssetStore(asset_root)
    cases: list[dict[str, Any]] = []
    collection_name = f"{os.getenv('MULTIMODAL_COLLECTION_PREFIX', 'causal_multimodal')}_{index_version}"
    db = chroma_class(persist_directory=str(version_dir / "chroma"), collection_name=collection_name, embedding_function=_embeddings())
    records = _annotation_records(root / "OmniDocBench.json")
    for specification in FIXED_SAMPLES:
        relative_path = specification["relative_path"]
        document = document_by_path.get(relative_path)
        document_units = [unit for unit in units if document and unit["document_id"] == document["document_id"]]
        asset_ok = bool(document_units) and all(not unit.get("asset_uri") or store.exists(unit["asset_uri"]) for unit in document_units)
        query = _ocr_probe(records.get(Path(relative_path).name, {}))
        case = {"sample_id": specification["sample_id"], "coverage": specification["coverage"], "source_present": document is not None, "unit_count": len(document_units), "asset_available": asset_ok, "query": query, "status": "passed"}
        if not document or not document_units or not asset_ok:
            case["status"] = "failed"; case["failure_type"] = "parse_or_asset_chain"
        elif not any(unit.get("modality") == "image" and unit.get("raw_text", "").strip() for unit in document_units):
            case["status"] = "skipped"; case["failure_type"] = "local_ocr_unavailable"
        elif not query:
            case["status"] = "skipped"; case["failure_type"] = "gold_ocr_probe_unavailable"
        else:
            hits = db.similarity_search(query, k=min(5, len(units)))
            target_unit_ids = {unit["unit_id"] for unit in document_units}
            hit_ids = [hit.metadata.get("unit_id") for hit in hits]
            case["hit_unit_ids"] = hit_ids
            if not target_unit_ids.intersection(hit_ids):
                case["status"] = "failed"; case["failure_type"] = "retrieval_miss"
        cases.append(case)
    failures = [case for case in cases if case["status"] == "failed"]
    result = {"benchmark": "OmniDocBench fixed subset", "index_version": index_version, "evaluated_at": datetime.now(timezone.utc).isoformat(), "audit": audit, "case_count": len(cases), "passed_cases": len([case for case in cases if case["status"] == "passed"]), "skipped_cases": len([case for case in cases if case["status"] == "skipped"]), "failed_cases": len(failures), "cases": cases}
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "omnidocbench_eval.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_bad_case_report(output_dir / "omnidocbench_bad_cases.md", result)
    return result


def _annotation_records(annotation_path: Path) -> dict[str, dict[str, Any]]:
    """以官方图片文件名映射页面标注，避免依赖本机绝对路径。"""
    payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    return {Path(item["page_info"]["image_path"]).name: item for item in payload}


def _ocr_probe(record: dict[str, Any]) -> str:
    """从公开标注取一条最短可用正文片段作为检索 probe，不生成人工 gold。"""
    for item in record.get("layout_dets", []):
        if item.get("category_type") not in {"title", "text_block", "table_caption", "figure_caption"}:
            continue
        text = " ".join(str(item.get("text", "")).split())
        if len(text) >= 8:
            return text[:120]
    return ""


def _write_bad_case_report(path: Path, result: dict[str, Any]) -> None:
    """生成只含样本 ID、类别和状态的 Markdown 报告，不复制原始图片或 OCR 正文。"""
    lines = ["# OmniDocBench 固定子集坏例报告", "", f"- 索引版本：`{result['index_version']}`", f"- 通过：{result['passed_cases']}；跳过：{result['skipped_cases']}；失败：{result['failed_cases']}", "", "| 样本 | 覆盖维度 | 状态 | 分类 |", "| --- | --- | --- | --- |"]
    for case in result["cases"]:
        lines.append(f"| {case['sample_id']} | {case['coverage']} | {case['status']} | {case.get('failure_type', '')} |")
    lines.extend(["", "说明：此报告只评估固定子集的本地解析/资源链和已增强索引的 OCR probe 召回；未运行官方 Docker 全指标评测，因此不包含或声称官方 OCR、TEDS、CDM、布局 mAP 指标。"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    """计算本地固定资料的内容哈希。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()
