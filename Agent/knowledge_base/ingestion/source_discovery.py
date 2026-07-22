import csv
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path
from typing import Iterable
from xml.etree.ElementTree import fromstring
from zipfile import ZipFile

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

from .models import (
    IngestionIssue,
    IssuePhase,
    IssueSeverity,
    KnowledgeSource,
    KnowledgeSourceSet,
    Profile,
    SourceType,
)


_SOURCE_TYPES = {
    ".txt": SourceType.TEXT,
    ".md": SourceType.TEXT,
    ".csv": SourceType.TABLE,
    ".xlsx": SourceType.TABLE,
    ".pdf": SourceType.PDF,
    ".png": SourceType.IMAGE,
    ".jpg": SourceType.IMAGE,
    ".jpeg": SourceType.IMAGE,
    ".webp": SourceType.IMAGE,
    ".tif": SourceType.IMAGE,
    ".tiff": SourceType.IMAGE,
}


@dataclass(frozen=True)
class DiscoveryLimits:
    """定义来源发现阶段可接受的文件、页数与像素上限。"""

    max_file_size_bytes: int
    max_pdf_pages: int
    max_image_pixels: int

    def __post_init__(self) -> None:
        """拒绝无法形成有效安全上限的配置。"""
        if min(
            self.max_file_size_bytes,
            self.max_pdf_pages,
            self.max_image_pixels,
        ) <= 0:
            raise ValueError("discovery limits must be positive")


@dataclass(frozen=True)
class SourceDiscoveryResult:
    """承载已通过检查的知识源与结构化问题。"""

    sources: tuple[KnowledgeSource, ...]
    issues: tuple[IngestionIssue, ...]


def _candidate_files(source_paths: Iterable[Path]) -> list[tuple[Path, str]]:
    """按稳定顺序展开文件或目录输入并生成来源根下相对路径。"""
    candidates: list[tuple[Path, str]] = []
    for source_path in source_paths:
        if source_path.is_file():
            candidates.append((source_path, source_path.name))
        elif source_path.is_dir():
            candidates.extend(
                (path, path.relative_to(source_path).as_posix())
                for path in source_path.rglob("*")
                if path.is_file()
            )
    return sorted(
        candidates,
        key=lambda item: (
            item[1].casefold(),
            item[1],
            item[0].as_posix().casefold(),
            item[0].as_posix(),
        ),
    )


def _source_issue(
    code: str,
    relative_path: str,
    detail: str,
    *,
    source_id: str | None = None,
) -> IngestionIssue:
    """构造可选绑定 source_id 的阻塞性来源检查问题。"""
    return IngestionIssue(
        code=code,
        message=f"{relative_path}: {detail}",
        severity=IssueSeverity.ERROR,
        phase=IssuePhase.INSPECT,
        blocking=True,
        source_id=source_id,
    )


def _has_known_binary_signature(content: bytes) -> bool:
    """识别不能被文字扩展名掩盖的稳定二进制文件签名。"""
    return content.startswith(
        (
            b"%PDF-",
            b"PK\x03\x04",
            b"\x89PNG\r\n\x1a\n",
            b"\xff\xd8\xff",
            b"II*\x00",
            b"MM\x00*",
        )
    ) or (
        len(content) >= 12
        and content.startswith(b"RIFF")
        and content[8:12] == b"WEBP"
    )


def _validate_pdf(
    content: bytes,
    relative_path: str,
    limits: DiscoveryLimits,
) -> IngestionIssue | None:
    """校验 PDF 文件签名、基础结构和页数上限。"""
    if not content.startswith(b"%PDF-"):
        return _source_issue(
            "SIGNATURE_MISMATCH",
            relative_path,
            "PDF signature does not match its extension",
        )
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            return _source_issue(
                "ENCRYPTED_PDF",
                relative_path,
                "encrypted PDF is not supported",
            )
        page_count = len(reader.pages)
    except Exception:
        return _source_issue("CORRUPT_FILE", relative_path, "PDF structure is invalid")
    if page_count > limits.max_pdf_pages:
        return _source_issue(
            "PDF_PAGE_LIMIT_EXCEEDED",
            relative_path,
            f"PDF exceeds {limits.max_pdf_pages} pages",
        )
    return None


def _validate_image(
    content: bytes,
    suffix: str,
    relative_path: str,
    limits: DiscoveryLimits,
) -> IngestionIssue | None:
    """校验图片文件签名、基础结构和像素上限。"""
    if suffix == ".png":
        signature_matches = content.startswith(b"\x89PNG\r\n\x1a\n")
    elif suffix in {".jpg", ".jpeg"}:
        signature_matches = content.startswith(b"\xff\xd8\xff")
    elif suffix == ".webp":
        signature_matches = (
            len(content) >= 12
            and content.startswith(b"RIFF")
            and content[8:12] == b"WEBP"
        )
    else:
        signature_matches = content.startswith((b"II*\x00", b"MM\x00*"))
    if not signature_matches:
        return _source_issue(
            "SIGNATURE_MISMATCH",
            relative_path,
            "image signature does not match its extension",
        )
    try:
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
            image.verify()
    except Image.DecompressionBombError:
        return _source_issue(
            "IMAGE_PIXEL_LIMIT_EXCEEDED",
            relative_path,
            "image dimensions exceed the safe pixel limit",
        )
    except (UnidentifiedImageError, OSError, ValueError):
        return _source_issue("CORRUPT_FILE", relative_path, "image structure is invalid")
    if width * height > limits.max_image_pixels:
        return _source_issue(
            "IMAGE_PIXEL_LIMIT_EXCEEDED",
            relative_path,
            f"image exceeds {limits.max_image_pixels} pixels",
        )
    return None


def _validate_xlsx(
    content: bytes,
    relative_path: str,
    limits: DiscoveryLimits,
) -> IngestionIssue | None:
    """校验 XLSX 的 ZIP 签名、必需成员和基础 XML 结构。"""
    if not content.startswith(b"PK\x03\x04"):
        return _source_issue(
            "SIGNATURE_MISMATCH",
            relative_path,
            "XLSX signature does not match its extension",
        )
    required_entries = ("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml")
    try:
        with ZipFile(BytesIO(content)) as workbook:
            names = set(workbook.namelist())
            if not set(required_entries).issubset(names):
                return _source_issue(
                    "CORRUPT_FILE",
                    relative_path,
                    "XLSX is missing required workbook members",
                )
            roots = {}
            for entry in required_entries:
                if workbook.getinfo(entry).file_size > limits.max_file_size_bytes:
                    return _source_issue(
                        "FILE_TOO_LARGE",
                        relative_path,
                        f"XLSX member {entry} exceeds the file size limit",
                    )
                roots[entry] = fromstring(workbook.read(entry))
    except Exception:
        return _source_issue("CORRUPT_FILE", relative_path, "XLSX structure is invalid")
    content_types_namespace = (
        "http://schemas.openxmlformats.org/package/2006/content-types"
    )
    relationships_namespace = (
        "http://schemas.openxmlformats.org/package/2006/relationships"
    )
    spreadsheet_namespace = (
        "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    )
    content_types = roots["[Content_Types].xml"]
    package_relationships = roots["_rels/.rels"]
    workbook_root = roots["xl/workbook.xml"]
    has_workbook_content_type = any(
        child.tag == f"{{{content_types_namespace}}}Override"
        and child.get("PartName") == "/xl/workbook.xml"
        and child.get("ContentType")
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
        for child in content_types
    )
    has_workbook_relationship = any(
        child.tag == f"{{{relationships_namespace}}}Relationship"
        and (child.get("Type") or "").endswith("/officeDocument")
        and (child.get("Target") or "").lstrip("/") == "xl/workbook.xml"
        for child in package_relationships
    )
    if (
        content_types.tag != f"{{{content_types_namespace}}}Types"
        or package_relationships.tag != f"{{{relationships_namespace}}}Relationships"
        or workbook_root.tag != f"{{{spreadsheet_namespace}}}workbook"
        or not has_workbook_content_type
        or not has_workbook_relationship
    ):
        return _source_issue("CORRUPT_FILE", relative_path, "XLSX package type is invalid")
    return None


def discover_sources(
    source_paths: Iterable[Path],
    *,
    profile: Profile,
    limits: DiscoveryLimits,
) -> SourceDiscoveryResult:
    """递归发现并验证知识源，不解析正文或写入向量库。"""
    input_paths = tuple(Path(path) for path in source_paths)
    sources = []
    issues = [
        _source_issue(
            "SOURCE_NOT_FOUND",
            path.name or path.as_posix(),
            "source path does not exist",
        )
        for path in sorted(input_paths, key=lambda item: item.as_posix().casefold())
        if not path.exists()
    ]
    seen_source_ids: set[str] = set()
    seen_casefold_paths: dict[str, str] = {}
    seen_content_paths: dict[str, str] = {}
    for path, relative_path in _candidate_files(input_paths):
        source_type = _SOURCE_TYPES.get(path.suffix.lower())
        if source_type is None:
            issues.append(
                _source_issue(
                    "UNSUPPORTED_FORMAT",
                    relative_path,
                    f"unsupported extension {path.suffix.lower() or '<none>'}",
                )
            )
            continue
        try:
            size_bytes = path.stat().st_size
        except OSError:
            issues.append(
                _source_issue(
                    "SOURCE_READ_FAILED",
                    relative_path,
                    "file metadata could not be read",
                )
            )
            continue
        if size_bytes > limits.max_file_size_bytes:
            issues.append(
                _source_issue(
                    "FILE_TOO_LARGE",
                    relative_path,
                    f"file exceeds {limits.max_file_size_bytes} bytes",
                )
            )
            continue
        try:
            content = path.read_bytes()
        except OSError:
            issues.append(
                _source_issue(
                    "SOURCE_READ_FAILED",
                    relative_path,
                    "file content could not be read",
                )
            )
            continue
        if len(content) > limits.max_file_size_bytes:
            issues.append(
                _source_issue(
                    "FILE_TOO_LARGE",
                    relative_path,
                    f"file exceeds {limits.max_file_size_bytes} bytes",
                )
            )
            continue
        if not content:
            issues.append(_source_issue("EMPTY_FILE", relative_path, "file is empty"))
            continue
        if source_type is SourceType.PDF:
            issue = _validate_pdf(content, relative_path, limits)
            if issue is not None:
                issues.append(issue)
                continue
        elif source_type is SourceType.IMAGE:
            issue = _validate_image(content, path.suffix.lower(), relative_path, limits)
            if issue is not None:
                issues.append(issue)
                continue
        elif path.suffix.lower() == ".xlsx":
            issue = _validate_xlsx(content, relative_path, limits)
            if issue is not None:
                issues.append(issue)
                continue
        else:
            if _has_known_binary_signature(content):
                issues.append(
                    _source_issue(
                        "SIGNATURE_MISMATCH",
                        relative_path,
                        "binary signature does not match the text extension",
                    )
                )
                continue
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                issues.append(
                    _source_issue(
                        "INVALID_ENCODING",
                        relative_path,
                        "text source is not valid UTF-8",
                    )
                )
                continue
            if path.suffix.lower() == ".csv":
                try:
                    for _ in csv.reader(StringIO(text), strict=True):
                        pass
                except csv.Error:
                    issues.append(
                        _source_issue(
                            "INVALID_CSV",
                            relative_path,
                            "CSV structure is invalid",
                        )
                    )
                    continue
        source = KnowledgeSource.from_content(
            profile=profile,
            relative_path=relative_path,
            content=content,
            source_type=source_type,
        )
        if source.source_id in seen_source_ids:
            issues.append(
                _source_issue(
                    "DUPLICATE_SOURCE",
                    relative_path,
                    "source was discovered more than once",
                    source_id=source.source_id,
                )
            )
            continue
        path_key = source.relative_path.casefold()
        original_source_path = seen_casefold_paths.get(path_key)
        if original_source_path is not None:
            issues.append(
                _source_issue(
                    "DUPLICATE_SOURCE",
                    relative_path,
                    f"path collides with {original_source_path} after casefold",
                    source_id=source.source_id,
                )
            )
            continue
        original_path = seen_content_paths.get(source.content_sha256)
        if original_path is not None:
            issues.append(
                _source_issue(
                    "DUPLICATE_CONTENT",
                    relative_path,
                    f"content matches {original_path}",
                    source_id=source.source_id,
                )
            )
            continue
        seen_source_ids.add(source.source_id)
        seen_casefold_paths[path_key] = source.relative_path
        seen_content_paths[source.content_sha256] = relative_path
        sources.append(source)
    if sources:
        sources = list(KnowledgeSourceSet(sources=tuple(sources)).sources)
    return SourceDiscoveryResult(sources=tuple(sources), issues=tuple(issues))
