"""将已验证知识源路由到 P05/P06 adapter 的最小摄取编排。"""

import hashlib
from pathlib import Path

from .adapters.ocr import OcrDescriptor, OcrPort, PaddleOcrPort
from .models import (
    DeviceMode,
    IngestCommand,
    IngestionIssue,
    IssuePhase,
    IssueSeverity,
    KnowledgeFragment,
    MaintenanceResult,
    OcrMode,
    ResultStatus,
    RunState,
    SourceType,
)
from .source_discovery import DiscoveryLimits, discover_sources


_DEFAULT_LIMITS = DiscoveryLimits(
    max_file_size_bytes=50 * 1024 * 1024,
    max_pdf_pages=500,
    max_image_pixels=40_000_000,
)


def _source_content(command: IngestCommand, relative_path: str, content_sha256: str) -> bytes:
    """从命令输入中重新读取已发现来源的原始字节。"""
    for raw_path in command.sources:
        root = Path(raw_path)
        candidate = root if root.is_file() else root / relative_path
        try:
            content = candidate.read_bytes()
        except OSError:
            continue
        if hashlib.sha256(content).hexdigest() == content_sha256:
            return content
    raise RuntimeError(f"discovered source disappeared or changed: {relative_path}")


def _issue(
    code: str,
    message: str,
    *,
    source_id: str | None,
    blocking: bool,
) -> IngestionIssue:
    """创建由 adapter 编排阶段产生的可审计问题。"""
    return IngestionIssue(
        code=code,
        message=message,
        severity=IssueSeverity.WARNING if not blocking else IssueSeverity.ERROR,
        phase=IssuePhase.INGEST,
        blocking=blocking,
        source_id=source_id,
    )


def _run_id(command: IngestCommand, source_ids: tuple[str, ...]) -> str:
    """从稳定的命令名称或已发现来源生成运行标识。"""
    if command.run_name:
        return command.run_name
    return "ingest_" + hashlib.sha256("\n".join(source_ids).encode("utf-8")).hexdigest()[:16]


def execute_ingest(command: IngestCommand, *, ocr_port: OcrPort | None = None) -> MaintenanceResult:
    """发现来源并执行受 P01S 约束的 P05/P06 摄取，不写索引。"""
    discovery = discover_sources(
        (Path(path) for path in command.sources),
        profile=command.profile,
        limits=_DEFAULT_LIMITS,
    )
    fragments: list[KnowledgeFragment] = []
    issues = list(discovery.issues)
    if not discovery.sources:
        issues.append(_issue(
            "NO_VALID_SOURCES",
            "no valid knowledge sources were found",
            source_id=None,
            blocking=True,
        ))
    port = ocr_port
    for source in discovery.sources:
        if source.source_type is SourceType.PDF:
            issues.append(_issue(
                "PDF_LICENSE_REVIEW_REQUIRED",
                "PyMuPDF PDF ingestion is blocked until its release license review passes",
                source_id=source.source_id,
                blocking=True,
            ))
            continue
        if source.source_type is not SourceType.IMAGE:
            issues.append(_issue(
                "ADAPTER_NOT_IMPLEMENTED",
                f"no formal pipeline adapter is enabled for {source.source_type.value}",
                source_id=source.source_id,
                blocking=True,
            ))
            continue
        if command.ocr is OcrMode.DISABLED:
            issues.append(_issue(
                "OCR_DISABLED",
                "image OCR is disabled by the ingest command",
                source_id=source.source_id,
                blocking=False,
            ))
            continue
        if port is None:
            device = "gpu" if command.device is DeviceMode.GPU else "cpu"
            port = PaddleOcrPort(device=device)
        extraction = OcrDescriptor(port, languages=command.ocr_languages).extract(
            source,
            _source_content(command, source.relative_path, source.content_sha256),
        )
        fragments.extend(extraction.fragments)
        issues.extend(extraction.issues)
    blocking = any(issue.blocking for issue in issues)
    if not discovery.sources and issues:
        status, run_state = ResultStatus.FAILED, RunState.FAILED
    elif blocking:
        status, run_state = ResultStatus.PARTIAL, RunState.PARTIAL
    else:
        status, run_state = ResultStatus.PASSED, RunState.INGESTING
    return MaintenanceResult(
        status=status,
        run_state=run_state,
        run_id=_run_id(command, tuple(source.source_id for source in discovery.sources)),
        fragments=tuple(fragments),
        issues=tuple(issues),
    )
