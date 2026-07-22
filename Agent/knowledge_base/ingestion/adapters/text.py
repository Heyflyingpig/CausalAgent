import hashlib
import re
from pathlib import PurePosixPath

from ..models import (
    ContentKind,
    KnowledgeFragment,
    KnowledgeSource,
    SourceLocator,
    SourceType,
)


_EXTRACTOR = "text-adapter"
_EXTRACTOR_VERSION = "1.0"
_ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*$")
_SETEXT_UNDERLINE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_FENCE_START = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _plain_paragraphs(lines: list[str]) -> list[tuple[int, int, str]]:
    """按空行切分文字，同时保留原始一基闭区间行号。"""
    paragraphs = []
    start = None
    buffer = []
    for line_number, line in enumerate(lines, start=1):
        if line.strip():
            if start is None:
                start = line_number
            buffer.append(line.rstrip())
        elif start is not None:
            paragraphs.append((start, line_number - 1, "\n".join(buffer)))
            start = None
            buffer = []
    if start is not None:
        paragraphs.append((start, len(lines), "\n".join(buffer)))
    return paragraphs


def _markdown_blocks(
    lines: list[str],
) -> list[tuple[int, int, str, str | None, str | None]]:
    """切分 Markdown 标题和段落，并为每块记录当前标题层级。"""
    blocks = []
    headings: dict[int, str] = {}
    paragraph_start = None
    paragraph_lines = []
    active_fence = None

    def flush_paragraph(end_line: int) -> None:
        """把当前段落写入块列表并重置累积状态。"""
        nonlocal paragraph_start, paragraph_lines
        if paragraph_start is None:
            return
        ordered_headings = [headings[level] for level in sorted(headings)]
        blocks.append(
            (
                paragraph_start,
                end_line,
                "\n".join(paragraph_lines),
                ordered_headings[-1] if ordered_headings else None,
                " > ".join(ordered_headings) or None,
            )
        )
        paragraph_start = None
        paragraph_lines = []

    def append_heading(start_line: int, end_line: int, level: int, title: str) -> None:
        """更新当前标题路径并写入标题块。"""
        nonlocal headings
        headings = {
            existing_level: existing_title
            for existing_level, existing_title in headings.items()
            if existing_level < level
        }
        headings[level] = title
        section = " > ".join(headings[key] for key in sorted(headings))
        blocks.append((start_line, end_line, title, title, section))

    for line_number, line in enumerate(lines, start=1):
        if active_fence is not None:
            paragraph_lines.append(line.rstrip())
            if re.fullmatch(
                rf" {{0,3}}{re.escape(active_fence[0])}{{{len(active_fence)},}}[ \t]*",
                line,
            ):
                flush_paragraph(line_number)
                active_fence = None
            continue
        fence_match = _FENCE_START.match(line)
        if fence_match:
            flush_paragraph(line_number - 1)
            paragraph_start = line_number
            paragraph_lines = [line.rstrip()]
            active_fence = fence_match.group(1)
            continue
        heading_match = _ATX_HEADING.match(line)
        setext_match = _SETEXT_UNDERLINE.match(line)
        if (
            setext_match
            and paragraph_start is not None
            and len(paragraph_lines) == 1
            and re.match(r"^ {0,3}\S", paragraph_lines[0]) is not None
        ):
            title = paragraph_lines[0].strip()
            start_line = paragraph_start
            paragraph_start = None
            paragraph_lines = []
            append_heading(
                start_line,
                line_number,
                1 if setext_match.group(1).startswith("=") else 2,
                title,
            )
        elif heading_match:
            flush_paragraph(line_number - 1)
            level = len(heading_match.group(1))
            title = re.sub(r"[ \t]+#+[ \t]*$", "", heading_match.group(2)).strip()
            append_heading(line_number, line_number, level, title)
        elif line.strip():
            if paragraph_start is None:
                paragraph_start = line_number
            paragraph_lines.append(line.rstrip())
        else:
            flush_paragraph(line_number - 1)
    flush_paragraph(len(lines))
    return blocks


def extract_text_fragments(
    source: KnowledgeSource,
    content: bytes,
) -> tuple[KnowledgeFragment, ...]:
    """将 UTF-8 TXT/Markdown 转换为带稳定行定位的文字片段。"""
    if source.source_type is not SourceType.TEXT:
        raise ValueError("text adapter requires a text source")
    if hashlib.sha256(content).hexdigest() != source.content_sha256:
        raise ValueError("text content does not match the source version")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("text source is not valid UTF-8") from exc
    lines = text.splitlines()
    if PurePosixPath(source.relative_path).suffix.casefold() == ".md":
        blocks = _markdown_blocks(lines)
    else:
        blocks = [(*paragraph, None, None) for paragraph in _plain_paragraphs(lines)]
    return tuple(
        KnowledgeFragment.create(
            source=source,
            locator=SourceLocator(line_start=start, line_end=end),
            content_kind=ContentKind.TEXT,
            text=paragraph,
            extractor=_EXTRACTOR,
            extractor_version=_EXTRACTOR_VERSION,
            title=title,
            section=section,
        )
        for start, end, paragraph, title, section in blocks
    )
