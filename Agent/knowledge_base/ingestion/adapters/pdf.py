"""数字 PDF 到可追溯文字与表格片段的本地适配器。"""

import hashlib
from dataclasses import dataclass

from ..models import (
    ContentKind,
    KnowledgeFragment,
    KnowledgeSource,
    NormalizedBoundingBox,
    SourceLocator,
    SourceType,
)

_EXTRACTOR = "pymupdf-pdf-adapter"
_EXTRACTOR_VERSION = "1.0"


@dataclass(frozen=True)
class PdfEmbeddedImage:
    """描述 PDF 中待后续 OCR 或视觉适配器处理的嵌图位置。"""

    page_number: int
    bbox: NormalizedBoundingBox


def _bbox(rect: object, page: object) -> NormalizedBoundingBox:
    """把 PyMuPDF 页面坐标转换为公开归一化 bbox。"""
    width, height = page.rect.width, page.rect.height
    x0, y0, x1, y1 = rect[:4] if isinstance(rect, tuple) else (rect.x0, rect.y0, rect.x1, rect.y1)
    return NormalizedBoundingBox(
        x0=max(0, min(1, x0 / width)),
        y0=max(0, min(1, y0 / height)),
        x1=max(0, min(1, x1 / width)),
        y1=max(0, min(1, y1 / height)),
        original_width=round(width),
        original_height=round(height),
    )


def _open_pdf(content: bytes):
    """打开 PDF 并把加密、损坏输入转换为稳定的领域错误。"""
    try:
        import fitz

        document = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise ValueError("invalid PDF source") from exc
    if document.needs_pass:
        document.close()
        raise ValueError("PDF source is encrypted")
    return document


def _table_text(table: object) -> str:
    """将页内表格稳定地转为 Markdown，不执行或推断单元格内容。"""
    rows = table.extract()
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [[(cell or "").strip() or "<empty>" for cell in row] for row in rows]
    normalized = [row + ["<empty>"] * (width - len(row)) for row in normalized]
    headers, data = normalized[0], normalized[1:]
    return "\n".join(
        ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
        + ["| " + " | ".join(row) + " |" for row in data]
    )


def extract_pdf_fragments(source: KnowledgeSource, content: bytes) -> tuple[KnowledgeFragment, ...]:
    """提取数字 PDF 的阅读顺序文字和页内表格，保留页码与 bbox。"""
    if source.source_type is not SourceType.PDF:
        raise ValueError("pdf adapter requires a PDF source")
    if hashlib.sha256(content).hexdigest() != source.content_sha256:
        raise ValueError("PDF content does not match the source version")
    document = _open_pdf(content)
    try:
        fragments: list[KnowledgeFragment] = []
        for page in document:
            for block in page.get_text("blocks", sort=True):
                text = block[4].strip()
                if text:
                    fragments.append(KnowledgeFragment.create(
                        source=source,
                        locator=SourceLocator(page_number=page.number + 1, bbox=_bbox(block, page)),
                        content_kind=ContentKind.TEXT,
                        text=text,
                        extractor=_EXTRACTOR,
                        extractor_version=_EXTRACTOR_VERSION,
                    ))
            for table in page.find_tables().tables:
                text = _table_text(table)
                if text:
                    fragments.append(KnowledgeFragment.create(
                        source=source,
                        locator=SourceLocator(page_number=page.number + 1, bbox=_bbox(table.bbox, page)),
                        content_kind=ContentKind.TABLE,
                        text=text,
                        extractor=_EXTRACTOR,
                        extractor_version=_EXTRACTOR_VERSION,
                    ))
        return tuple(fragments)
    finally:
        document.close()


def discover_pdf_images(content: bytes) -> tuple[PdfEmbeddedImage, ...]:
    """返回 PDF 嵌图位置，供后续 OCR/视觉编排处理，不生成猜测性文本。"""
    document = _open_pdf(content)
    try:
        images = []
        for page in document:
            for image in page.get_images(full=True):
                for rect in page.get_image_rects(image[0]):
                    images.append(PdfEmbeddedImage(page.number + 1, _bbox(rect, page)))
        return tuple(images)
    finally:
        document.close()
