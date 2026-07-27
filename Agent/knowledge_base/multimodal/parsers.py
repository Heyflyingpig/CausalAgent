"""将允许的资料转换为项目内部的标准化解析结果。"""

from __future__ import annotations

import importlib.util
import csv
import json
import os
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from .contracts import IngestionIssue, IssueSeverity

TEXT_SUFFIXES = {".txt", ".md", ".markdown"}
TABLE_SUFFIXES = {".csv", ".xlsx"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
PDF_SUFFIXES = {".pdf"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | TABLE_SUFFIXES | IMAGE_SUFFIXES | PDF_SUFFIXES


@dataclass(frozen=True)
class ParsedItem:
    """解析器输出的单一、仍未嵌入的内容项。"""

    modality: str
    content_kind: str
    raw_text: str = ""
    page_number: int | None = None
    bbox: dict[str, float] | None = None
    asset_bytes: bytes | None = None
    asset_name: str | None = None
    parent_key: str | None = None


@dataclass(frozen=True)
class ParsedDocument:
    """单份资料的解析结果及其可追踪问题。"""

    parser_name: str
    parser_version: str
    items: tuple[ParsedItem, ...] = ()
    issues: tuple[IngestionIssue, ...] = ()
    raw_artifacts: tuple[tuple[str, bytes], ...] = ()


def inspect_source(path: Path) -> IngestionIssue | None:
    """只检查输入文件的格式、存在性和大小，不执行解析或远程调用。"""
    if not path.is_file():
        return IngestionIssue(code="source_missing", message="资料不存在或不是普通文件", severity=IssueSeverity.ERROR, blocking=True, source_path=str(path))
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        return IngestionIssue(code="unsupported_format", message="首期不支持该资料格式", severity=IssueSeverity.ERROR, blocking=False, source_path=str(path))
    if path.stat().st_size == 0:
        return IngestionIssue(code="empty_source", message="资料为空", severity=IssueSeverity.ERROR, blocking=False, source_path=str(path))
    return None


def parse_document(path: Path, preferred_parser: str) -> ParsedDocument:
    """以 MinerU 优先、Docling 回退的策略解析资料，缺依赖时隔离失败。"""
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return _parse_text(path)
    if suffix == ".csv":
        return _parse_csv(path)
    if suffix == ".xlsx":
        return _parse_xlsx(path)
    if suffix in IMAGE_SUFFIXES:
        return ParsedDocument("image", "builtin-1", (ParsedItem("image", "image", asset_bytes=path.read_bytes(), asset_name=path.name),))
    if suffix in PDF_SUFFIXES:
        return _parse_pdf(path, preferred_parser)
    raise ValueError(f"unsupported source suffix: {suffix}")


def _parse_text(path: Path) -> ParsedDocument:
    """使用确定性的 UTF-8 文本解析作为无外部依赖路径。"""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
    return ParsedDocument("text", "builtin-1", (ParsedItem("text", "paragraph", raw_text=text),))


def _parse_csv(path: Path) -> ParsedDocument:
    """把 CSV 的表头和每一行保留为独立、可检索的表格单元。"""
    try:
        content = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        content = path.read_text(encoding="utf-8", errors="replace")
    rows = list(csv.reader(content.splitlines()))
    if not rows:
        return ParsedDocument("csv", "builtin-1", issues=(_empty_table_issue(path),))
    headers = _table_headers(rows[0])
    items = tuple(
        ParsedItem("table", "table_row", raw_text=_render_table_row(headers, row, row_index))
        for row_index, row in enumerate(rows[1:], 2)
        if any(cell.strip() for cell in row)
    )
    return ParsedDocument("csv", "builtin-1", items or (ParsedItem("table", "table", raw_text="表头：" + "、".join(headers)),))


def _parse_xlsx(path: Path) -> ParsedDocument:
    """使用 openpyxl 的只读模式稳定提取每张工作表的行列语义。"""
    try:
        from openpyxl import load_workbook

        workbook = load_workbook(path, read_only=True, data_only=False)
        items: list[ParsedItem] = []
        for sheet in workbook.worksheets:
            rows = [["" if value is None else str(value) for value in row] for row in sheet.iter_rows(values_only=True)]
            if not rows:
                continue
            headers = _table_headers(rows[0])
            for row_index, row in enumerate(rows[1:], 2):
                if any(cell.strip() for cell in row):
                    items.append(ParsedItem("table", "table_row", raw_text=_render_table_row(headers, row, row_index, sheet.title)))
        workbook.close()
    except Exception as exc:
        return ParsedDocument("xlsx", "openpyxl", issues=(IngestionIssue(code="xlsx_parse_failed", message=f"XLSX 解析失败：{type(exc).__name__}", severity=IssueSeverity.ERROR, blocking=False, source_path=str(path)),))
    return ParsedDocument("xlsx", "openpyxl", tuple(items), () if items else (_empty_table_issue(path),))


def _table_headers(row: list[str]) -> list[str]:
    """为缺失表头的列生成稳定名称，避免丢失列语义。"""
    return [cell.strip() or f"列{index}" for index, cell in enumerate(row, 1)]


def _render_table_row(headers: list[str], row: list[str], row_index: int, sheet_name: str | None = None) -> str:
    """按表头、工作表和闭区间行号渲染确定性表格文本。"""
    pairs = [f"{header}：{row[index].strip() if index < len(row) else ''}" for index, header in enumerate(headers)]
    prefix = f"工作表：{sheet_name}\n" if sheet_name else ""
    return prefix + f"行：{row_index}\n" + "\n".join(pairs)


def _empty_table_issue(path: Path) -> IngestionIssue:
    """为无可索引行的表格资料创建可追踪问题。"""
    return IngestionIssue(code="table_empty", message="表格没有可索引的数据行", severity=IssueSeverity.WARNING, blocking=False, source_path=str(path))


def _parse_pdf(path: Path, preferred_parser: str) -> ParsedDocument:
    """选择已安装的指定 PDF adapter；不以 PyMuPDF 作为新链路回退。"""
    if importlib.util.find_spec("docling") is None:
        return ParsedDocument(
            "unavailable", "0",
            issues=(IngestionIssue(code="parser_dependency_missing", message="PDF 解析依赖未安装；资料已隔离，未调用视觉服务", severity=IssueSeverity.ERROR, blocking=False, source_path=str(path)),),
        )
    return _parse_pdf_with_docling(path, preferred_parser)


def _parse_pdf_with_docling(path: Path, preferred_parser: str) -> ParsedDocument:
    """逐页调用 Docling，避免大 PDF 的批量预处理内存峰值。"""
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        artifacts_path = Path(os.getenv("MULTIMODAL_DOCLING_ARTIFACTS_DIR", Path.home() / ".cache" / "docling" / "models"))
        options = PdfPipelineOptions(artifacts_path=artifacts_path)
        from pypdf import PdfReader

        items: list[ParsedItem] = []
        raw_artifacts: list[tuple[str, bytes]] = []
        restart_interval = int(os.getenv("MULTIMODAL_DOCLING_RESTART_INTERVAL", "20"))
        if restart_interval < 1:
            raise ValueError("MULTIMODAL_DOCLING_RESTART_INTERVAL must be positive")
        converter = None
        for page_number in range(1, len(PdfReader(path).pages) + 1):
            if converter is None or (page_number - 1) % restart_interval == 0:
                converter = DocumentConverter(
                    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
                )
            result = converter.convert(path, page_range=(page_number, page_number))
            page_items = _docling_items(result.document)
            if not page_items:
                raise ValueError(f"Docling did not return page {page_number}")
            items.extend(page_items)
            raw_artifacts.append(
                (
                    f"docling_page_{page_number:04d}.json",
                    json.dumps(result.document.export_to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8"),
                )
            )
    except Exception as exc:
        return ParsedDocument(
            "docling", "2.115.0",
            issues=(IngestionIssue(code="pdf_parse_failed", message=f"Docling PDF 解析失败：{type(exc).__name__}", severity=IssueSeverity.ERROR, blocking=False, source_path=str(path)),),
        )
    if not items:
        return ParsedDocument(
            "docling", "2.115.0",
            issues=(IngestionIssue(code="pdf_empty_output", message="Docling 未提取到可索引正文", severity=IssueSeverity.ERROR, blocking=False, source_path=str(path)),),
        )
    issues: tuple[IngestionIssue, ...] = ()
    if preferred_parser == "mineru":
        issues = (IngestionIssue(code="mineru_fallback_docling", message="MinerU 未配置为可运行解析路径，已使用 Docling fallback", severity=IssueSeverity.WARNING, blocking=False, source_path=str(path)),)
    return ParsedDocument("docling", "2.115.0", tuple(items), issues, tuple(raw_artifacts))


def _docling_items(document: object) -> list[ParsedItem]:
    """将 Docling 项映射为项目契约，不暴露其第三方对象。"""
    from docling_core.types.doc import FormulaItem, PictureItem, TableItem, TextItem

    items: list[ParsedItem] = []
    for index, (item, _) in enumerate(document.iterate_items(), 1):
        page_number, bbox = _docling_locator(item, document)
        if isinstance(item, TableItem):
            text = item.export_to_markdown(doc=document).strip()
            if text:
                items.append(ParsedItem("table", "table", raw_text=text, page_number=page_number, bbox=bbox, parent_key=f"page_{page_number}" if page_number else None))
        elif isinstance(item, FormulaItem):
            formula = (item.text or "").strip()
            if formula:
                items.append(ParsedItem("equation", "formula", raw_text=formula, page_number=page_number, bbox=bbox, parent_key=f"page_{page_number}" if page_number else None))
        elif isinstance(item, PictureItem):
            asset_bytes = _docling_image_bytes(item, document)
            if asset_bytes:
                items.append(ParsedItem("image", "image", page_number=page_number, bbox=bbox, asset_bytes=asset_bytes, asset_name=f"page_{page_number or 0:04d}_image_{index:04d}.png", parent_key=f"page_{page_number}" if page_number else None))
        elif isinstance(item, TextItem) and (item.text or "").strip():
            items.append(ParsedItem("text", "paragraph", raw_text=item.text.strip(), page_number=page_number, bbox=bbox, parent_key=f"page_{page_number}" if page_number else None))
    return items


def _docling_locator(item: object, document: object) -> tuple[int | None, dict[str, float] | None]:
    """把 Docling 的页码和坐标转换为一基、左上原点的归一化 bbox。"""
    provenance = next(iter(getattr(item, "prov", []) or []), None)
    if provenance is None:
        return None, None
    page_number = int(provenance.page_no)
    bbox = getattr(provenance, "bbox", None)
    page = getattr(document, "pages", {}).get(page_number)
    size = getattr(page, "size", None)
    if bbox is None or size is None or not size.width or not size.height:
        return page_number, None
    x0, x1 = sorted((bbox.l / size.width, bbox.r / size.width))
    y0, y1 = sorted((bbox.t / size.height, bbox.b / size.height))
    origin = str(getattr(bbox.coord_origin, "value", bbox.coord_origin)).lower()
    if origin.startswith("bottom"):
        y0, y1 = 1 - y1, 1 - y0
    if x0 >= x1 or y0 >= y1 or min(x0, y0) < 0 or max(x1, y1) > 1:
        return page_number, None
    return page_number, {"x0": x0, "y0": y0, "x1": x1, "y1": y1}


def _docling_image_bytes(item: object, document: object) -> bytes | None:
    """把可用图片渲染为 PNG；没有可靠图片时返回空而非猜测资源。"""
    try:
        image = item.get_image(document)
        if image is None:
            return None
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    except Exception:
        return None
