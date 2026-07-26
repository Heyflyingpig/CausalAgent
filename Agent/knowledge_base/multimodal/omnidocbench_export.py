"""把固定 OmniDocBench 页面导出为官方 end-to-end 评测输入。"""

from __future__ import annotations

import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .benchmark import FIXED_SAMPLES, OMNIDOCBENCH_REVISION, _sha256, audit_omnidocbench_subset


def export_omnidocbench_official_inputs(root: Path, output_dir: Path, converter: Callable[[Path], str] | None = None, selection_manifest: Path | None = None) -> dict[str, object]:
    """生成选定页面的 GT、同名页面 Markdown 和内容哈希 manifest。"""
    specifications, source_root, selection_audit = _selected_pages(root, selection_manifest)
    converter = converter or _docling_image_converter()
    all_records = json.loads((root / "OmniDocBench.json").read_text(encoding="utf-8"))
    records = {Path(item["page_info"]["image_path"]).name: item for item in all_records}
    output_dir.mkdir(parents=True, exist_ok=True)
    prediction_dir = output_dir / "predictions"
    prediction_dir.mkdir(exist_ok=True)
    selected_records = []
    pages: list[dict[str, str]] = []
    for specification in specifications:
        relative_path = specification["relative_path"]
        source = source_root / relative_path
        record = records[Path(relative_path).name]
        try:
            markdown = converter(source).strip()
        except FileNotFoundError as exc:
            if "docling-layout" in str(exc):
                raise RuntimeError("Docling layout model cache is incomplete; prepare docling-layout-heron before exporting official predictions") from exc
            raise
        if not markdown:
            raise ValueError(f"Docling produced empty markdown for {relative_path}")
        prediction_path = prediction_dir / Path(relative_path).name
        prediction_path = prediction_path.with_suffix(".md")
        prediction_path.write_text(markdown + "\n", encoding="utf-8")
        selected_records.append(record)
        pages.append({"sample_id": specification["sample_id"], "source_relative_path": relative_path, "source_sha256": _sha256(source), "prediction_filename": prediction_path.name, "prediction_sha256": _sha256(prediction_path)})
    ground_truth_path = output_dir / "OmniDocBench_subset.json"
    ground_truth_path.write_text(json.dumps(selected_records, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {"dataset": "opendatalab/OmniDocBench", "revision": OMNIDOCBENCH_REVISION, "exported_at": datetime.now(timezone.utc).isoformat(), "ground_truth_filename": ground_truth_path.name, "ground_truth_sha256": _sha256(ground_truth_path), "selection_audit": selection_audit, "pages": pages}
    if selection_manifest is not None:
        manifest["selection_manifest_filename"] = selection_manifest.name
        manifest["selection_manifest_sha256"] = _sha256(selection_manifest)
    manifest_path = output_dir / "official_export_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "exported", "ground_truth_path": str(ground_truth_path), "prediction_dir": str(prediction_dir), "manifest_path": str(manifest_path), "page_count": len(pages)}


def _selected_pages(root: Path, selection_manifest: Path | None) -> tuple[list[dict[str, Any]], Path, dict[str, object]]:
    """读取固定子集或生产清单，并在写出前验证页面、哈希和官方标注。"""
    if selection_manifest is None:
        audit = audit_omnidocbench_subset(root)
        if not audit["passed"]:
            raise ValueError("OmniDocBench fixed subset audit must pass before export")
        return list(FIXED_SAMPLES), root, audit
    payload = json.loads(selection_manifest.read_text(encoding="utf-8"))
    if payload.get("dataset") != "opendatalab/OmniDocBench" or payload.get("revision") != OMNIDOCBENCH_REVISION:
        raise ValueError("selection manifest dataset or revision does not match OmniDocBench")
    specifications = payload.get("samples")
    if not isinstance(specifications, list) or not specifications:
        raise ValueError("selection manifest must contain samples")
    records = {Path(item["page_info"]["image_path"]).name: item for item in json.loads((root / "OmniDocBench.json").read_text(encoding="utf-8"))}
    filenames: set[str] = set()
    failures: list[str] = []
    for specification in specifications:
        sample_id = str(specification.get("sample_id", ""))
        relative_path = str(specification.get("relative_path", ""))
        source = selection_manifest.parent / relative_path
        filename = Path(relative_path).name
        record = records.get(filename)
        if not sample_id or not relative_path or not source.is_file():
            failures.append(f"{sample_id or relative_path}:image_missing")
            continue
        if filename in filenames:
            failures.append(f"{sample_id}:duplicate_prediction_filename")
        filenames.add(filename)
        if specification.get("sha256") != _sha256(source):
            failures.append(f"{sample_id}:image_hash_mismatch")
        if record is None:
            failures.append(f"{sample_id}:annotation_missing")
            continue
        if record["page_info"].get("page_attribute", {}) != specification.get("page_attribute", {}):
            failures.append(f"{sample_id}:annotation_attribute_mismatch")
        categories = {str(item.get("category_type", "")) for item in record.get("layout_dets", [])}
        if not set(specification.get("required_categories", [])).issubset(categories):
            failures.append(f"{sample_id}:annotation_category_mismatch")
    if failures:
        raise ValueError("selection manifest audit failed: " + ", ".join(failures))
    return specifications, selection_manifest.parent, {"manifest": selection_manifest.name, "manifest_sha256": _sha256(selection_manifest), "sample_count": len(specifications), "passed": True}


def _docling_image_converter() -> Callable[[Path], str]:
    """创建一个复用 Docling 模型的单页 Markdown 转换器。"""
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    return lambda source: converter.convert(source).document.export_to_markdown()


def main() -> int:
    """提供不加载多模态索引依赖的官方页面评测导出命令。"""
    parser = argparse.ArgumentParser(prog="omnidocbench-export-official")
    parser.add_argument("--root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--selection-manifest")
    args = parser.parse_args()
    print(json.dumps(export_omnidocbench_official_inputs(Path(args.root), Path(args.output_dir), selection_manifest=Path(args.selection_manifest) if args.selection_manifest else None), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
