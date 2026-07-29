"""将允许的资料转换为项目内部的标准化解析结果。"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import csv
import hashlib
import json
import multiprocessing
import os
import time
from dataclasses import dataclass, field
from io import BytesIO
from collections.abc import Iterator
from pathlib import Path

from .contracts import IngestionIssue, IssueSeverity

TEXT_SUFFIXES = {".txt", ".md", ".markdown"}
TABLE_SUFFIXES = {".csv", ".xlsx"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
PDF_SUFFIXES = {".pdf"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | TABLE_SUFFIXES | IMAGE_SUFFIXES | PDF_SUFFIXES
_RAPID_OCR_ENGINE: object | None = None
_OCR_FINGERPRINT: dict[str, str] | None = None
_RAPIDOCR_MODEL_NAMES = (
    "PP-OCRv6_det_small.onnx",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    "PP-OCRv6_rec_small.onnx",
)


@dataclass(frozen=True)
class OcrResult:
    """本地 OCR 引擎一次推理的分类结果，区分无文字、依赖缺失与推理失败。

    ponytail: 不进入 KnowledgeUnit 公共接口，仅作 parser 内部契约和 manifest 指纹来源。
    """

    text: str
    engine: str
    engine_version: str
    model_fingerprint: str
    line_count: int
    mean_confidence: float
    elapsed_ms: int
    status: str  # "ok" | "no_text" | "failed" | "engine_unavailable"
    failure_type: str = ""


def ocr_fingerprint() -> dict[str, str]:
    """返回 RapidOCR 包与固定本地模型文件的内容指纹，不加载模型。"""
    global _OCR_FINGERPRINT
    if _OCR_FINGERPRINT is not None:
        return dict(_OCR_FINGERPRINT)
    engine = "rapidocr-onnxruntime"
    try:
        version = importlib.metadata.version("rapidocr-onnxruntime")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    spec = importlib.util.find_spec("rapidocr")
    model_root = Path(next(iter(spec.submodule_search_locations), "")) / "models" if spec and spec.submodule_search_locations else None
    model_paths = [model_root / name for name in _RAPIDOCR_MODEL_NAMES] if model_root else []
    if not model_paths or any(not path.is_file() for path in model_paths):
        _OCR_FINGERPRINT = {
            "engine": engine,
            "engine_version": version,
            "model_fingerprint": "missing",
            "status": "unavailable",
        }
        return dict(_OCR_FINGERPRINT)
    digest = hashlib.sha256()
    for path in model_paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    _OCR_FINGERPRINT = {
        "engine": engine,
        "engine_version": version,
        "model_fingerprint": digest.hexdigest(),
        "status": "available",
    }
    return dict(_OCR_FINGERPRINT)


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
        payload = path.read_bytes()
        probe = _rapidocr_probe(payload)
        return ParsedDocument("image", "builtin-1", (ParsedItem("image", "image", raw_text=probe.text, asset_bytes=payload, asset_name=path.name),), issues=_ocr_issues(probe, path))
    if suffix in PDF_SUFFIXES:
        return _parse_pdf(path, preferred_parser)
    raise ValueError(f"unsupported source suffix: {suffix}")


def iter_document_pages(path: Path, preferred_parser: str) -> Iterator[ParsedDocument]:
    """逐页产生解析结果；PDF 每页使用独立进程以释放原生模型内存。"""
    if path.suffix.lower() != ".pdf":
        yield parse_document(path, preferred_parser)
        return
    if importlib.util.find_spec("docling") is None:
        yield _parse_pdf(path, preferred_parser)
        return
    yield from _iter_pdf_with_docling(path, preferred_parser)


def parse_document_page(path: Path, preferred_parser: str, page_number: int) -> ParsedDocument:
    """解析指定物理页，供可恢复摄取按页调度。"""
    if page_number < 1:
        raise ValueError("page_number must be positive")
    if path.suffix.lower() != ".pdf":
        if page_number != 1:
            raise ValueError("non-PDF sources contain one logical page")
        return parse_document(path, preferred_parser)
    if importlib.util.find_spec("docling") is None:
        return _parse_pdf(path, preferred_parser)
    return _parse_docling_page_isolated(path, page_number)


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
    """聚合逐页结果，供兼容调用者和小型测试使用。"""
    pages = list(_iter_pdf_with_docling(path, preferred_parser))
    items = [item for page in pages for item in page.items]
    issues = [issue for page in pages for issue in page.issues]
    raw_artifacts = [artifact for page in pages for artifact in page.raw_artifacts]
    if not items:
        return ParsedDocument(
            "docling", "2.115.0",
            issues=(IngestionIssue(code="pdf_empty_output", message="Docling 未提取到可索引正文", severity=IssueSeverity.ERROR, blocking=False, source_path=str(path)),),
        )
    if preferred_parser == "mineru":
        issues.append(IngestionIssue(code="mineru_fallback_docling", message="MinerU 未配置为可运行解析路径，已使用 Docling fallback", severity=IssueSeverity.WARNING, blocking=False, source_path=str(path)))
    return ParsedDocument("docling", "2.115.0", tuple(items), tuple(issues), tuple(raw_artifacts))


def _iter_pdf_with_docling(path: Path, preferred_parser: str) -> Iterator[ParsedDocument]:
    """按物理页隔离运行 Docling，并为每页保留成功或失败证据。"""
    from pypdf import PdfReader

    page_count = len(PdfReader(path).pages)
    for page_number in range(1, page_count + 1):
        yield _parse_docling_page_isolated(path, page_number)


def _parse_docling_page_isolated(path: Path, page_number: int) -> ParsedDocument:
    """在 spawn 子进程中解析一页，超时或崩溃时返回阻断 issue。"""
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_docling_page_worker, args=(str(path), page_number, sender))
    process.start()
    sender.close()
    timeout = int(os.getenv("MULTIMODAL_DOCLING_PAGE_TIMEOUT_SECONDS", "900"))
    try:
        if receiver.poll(timeout):
            parsed = receiver.recv()
            process.join(30)
            return parsed
        process.terminate()
        process.join(30)
        return _page_failure(path, page_number, "TimeoutError")
    except (EOFError, OSError):
        process.join(30)
        return _page_failure(path, page_number, f"ProcessExit{process.exitcode}")
    finally:
        receiver.close()


def _docling_page_worker(path_value: str, page_number: int, sender: object) -> None:
    """子进程入口：解析单页并通过管道返回纯本地结果。"""
    path = Path(path_value)
    try:
        from docling.datamodel.pipeline_options import PdfPipelineOptions

        artifacts_path = Path(os.getenv("MULTIMODAL_DOCLING_ARTIFACTS_DIR", Path.home() / ".cache" / "docling" / "models"))
        options = PdfPipelineOptions(artifacts_path=artifacts_path)
        options.generate_picture_images = True
        converter = _new_docling_converter(options)
        result, _ = _convert_docling_page(path, page_number, options, converter)
        items_list, ocr_issues = _docling_items(result.document, path)
        issues: tuple[IngestionIssue, ...] = tuple(ocr_issues)
        if not items_list:
            content_exists = _pdf_page_has_content(path, page_number)
            issues = issues + (IngestionIssue(
                code="pdf_page_content_missing" if content_exists else "pdf_page_empty",
                message=f"Docling 第 {page_number} 页未返回可索引内容",
                severity=IssueSeverity.ERROR if content_exists else IssueSeverity.WARNING,
                blocking=content_exists,
                source_path=str(path),
            ),)
        artifact = (
            f"docling_page_{page_number:04d}.json",
            json.dumps(result.document.export_to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8"),
        )
        sender.send(ParsedDocument("docling", "2.115.0", tuple(items_list), issues, (artifact,)))
    except Exception as exc:
        sender.send(_page_failure(path, page_number, type(exc).__name__))
    finally:
        sender.close()


def _page_failure(path: Path, page_number: int, error_name: str) -> ParsedDocument:
    """为单页隔离失败创建可审计的阻断结果。"""
    issue = IngestionIssue(
        code="pdf_page_parse_failed",
        message=f"Docling 第 {page_number} 页解析失败：{error_name}",
        severity=IssueSeverity.ERROR,
        blocking=True,
        source_path=str(path),
    )
    return ParsedDocument("docling", "2.115.0", issues=(issue,))


def _pdf_page_has_content(path: Path, page_number: int) -> bool:
    """独立检查 PDF 页是否包含文本或图片对象，防止把解析遗漏当作空白页。"""
    from pypdf import PdfReader

    page = PdfReader(path).pages[page_number - 1]
    if (page.extract_text() or "").strip():
        return True
    resources = page.get("/Resources") or {}
    xobjects = resources.get("/XObject") if hasattr(resources, "get") else None
    return bool(xobjects)


def _new_docling_converter(options: object) -> object:
    """创建使用同一离线模型配置的 Docling converter。"""
    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import DocumentConverter, PdfFormatOption

    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})


def _convert_docling_page(path: Path, page_number: int, options: object, converter: object) -> tuple[object, object]:
    """转换单页；converter 状态异常时仅重建并重试一次。"""
    try:
        return converter.convert(path, page_range=(page_number, page_number)), converter
    except Exception:
        replacement = _new_docling_converter(options)
        return replacement.convert(path, page_range=(page_number, page_number)), replacement


def _docling_items(document: object, source_path: Path) -> tuple[list[ParsedItem], list[IngestionIssue]]:
    """将 Docling 项映射为项目契约，不暴露其第三方对象。"""
    from docling_core.types.doc import FormulaItem, PictureItem, TableItem, TextItem

    items: list[ParsedItem] = []
    ocr_issues: list[IngestionIssue] = []
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
                caption = (item.caption_text(document) or "").strip()
                probe = _rapidocr_probe(asset_bytes)
                raw_text = "\n".join(dict.fromkeys(part for part in (caption, probe.text) if part))
                items.append(ParsedItem("image", "image", raw_text=raw_text, page_number=page_number, bbox=bbox, asset_bytes=asset_bytes, asset_name=f"page_{page_number or 0:04d}_image_{index:04d}.png", parent_key=f"page_{page_number}" if page_number else None))
                ocr_issues.extend(_ocr_issues(probe, source_path))
            else:
                ocr_issues.append(IngestionIssue(code="image_asset_missing", message=f"第 {page_number or 0} 页图片资源无法提取", severity=IssueSeverity.WARNING, blocking=False, source_path=str(source_path)))
        elif isinstance(item, TextItem) and (item.text or "").strip():
            label = str(getattr(getattr(item, "label", None), "value", getattr(item, "label", "paragraph")))
            items.append(ParsedItem("text", label or "paragraph", raw_text=item.text.strip(), page_number=page_number, bbox=bbox, parent_key=f"page_{page_number}" if page_number else None))
    return items, ocr_issues


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


def _rapidocr_probe(image_bytes: bytes) -> OcrResult:
    """使用本地 RapidOCR 为图片生成分类 OCR 结果，永不抛异常。

    ponytail: 把原来吞所有异常返回空串的 helper 拆成可观测契约；
    状态机 ok|no_text|failed|engine_unavailable 覆盖 §5.4 全部分类。
    """
    started = time.monotonic()
    fp = ocr_fingerprint()
    if fp["status"] != "available":
        return OcrResult("", fp["engine"], fp["engine_version"], fp["model_fingerprint"], 0, 0.0, 0, "engine_unavailable")
    global _RAPID_OCR_ENGINE
    if _RAPID_OCR_ENGINE is None:
        try:
            from rapidocr import RapidOCR
            _RAPID_OCR_ENGINE = RapidOCR()
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return OcrResult("", fp["engine"], fp["engine_version"], fp["model_fingerprint"], 0, 0.0, elapsed_ms, "engine_unavailable", type(exc).__name__)
    try:
        result = _RAPID_OCR_ENGINE(image_bytes)
        texts = [text.strip() for text in (result.txts or ()) if text and text.strip()]
        scores = [float(score) for score in (getattr(result, "scores", None) or ()) if score is not None]
        mean_confidence = round(sum(scores) / len(scores), 6) if scores else 0.0
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if not texts:
            return OcrResult("", fp["engine"], fp["engine_version"], fp["model_fingerprint"], 0, 0.0, elapsed_ms, "no_text")
        return OcrResult("\n".join(texts), fp["engine"], fp["engine_version"], fp["model_fingerprint"], len(texts), mean_confidence, elapsed_ms, "ok")
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return OcrResult("", fp["engine"], fp["engine_version"], fp["model_fingerprint"], 0, 0.0, elapsed_ms, "failed", type(exc).__name__)


def _ocr_issues(probe: OcrResult, path: Path) -> tuple[IngestionIssue, ...]:
    """把 OCR 分类状态映射为可追踪 issue，不记录图片正文。"""
    if probe.status == "engine_unavailable":
        return (IngestionIssue(code="ocr_engine_unavailable", message="RapidOCR 引擎或模型不可用，无法识别图片文字", severity=IssueSeverity.ERROR, blocking=True, source_path=str(path)),)
    if probe.status == "failed":
        return (IngestionIssue(code="ocr_failed", message=f"RapidOCR 推理失败：{probe.failure_type or 'UnknownError'}，已隔离该图片", severity=IssueSeverity.WARNING, blocking=False, source_path=str(path)),)
    if probe.status == "no_text":
        return (IngestionIssue(code="ocr_no_text", message="图片未识别到文字，可由后续 VLM 判断是否为信息图", severity=IssueSeverity.WARNING, blocking=False, source_path=str(path)),)
    return ()
