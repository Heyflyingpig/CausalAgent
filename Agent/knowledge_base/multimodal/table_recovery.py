"""Provider-neutral recovery of tables that Docling discovered but could not decode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from .contracts import OutboundImageRecord, VisionAnalysis
from .vision import PROMPT_VERSION, RESPONSE_ADAPTER_VERSION, VisionAnalyzer

TABLE_RECOVERY_ADAPTER_VERSION = "table-recovery-v1"

if TYPE_CHECKING:
    from typing import Any


class TableRecoveryError(ValueError):
    """Raised when an adapter cannot return a usable table."""


@dataclass(frozen=True)
class TableRecoveryResult:
    """The small result contract shared by local and remote table adapters."""

    table_markdown: str
    ocr_text: str = ""
    confidence: float = 0.0
    status: str = "success"
    provider: str = ""
    model: str = ""
    prompt_version: str = ""
    response_adapter_version: str = ""

    def as_vision_analysis(self) -> VisionAnalysis:
        """Adapt the table result to the existing retrieval text renderer."""
        return VisionAnalysis(
            content_kind="table",
            ocr_text=self.ocr_text,
            visible_facts=[],
            summary="",
            entities=[],
            table_markdown=self.table_markdown,
            formula_latex="",
            directed_relations=[],
            uncertain_relations=[],
            confidence=self.confidence,
            informative=True,
        )


class TableRecoveryProvider(Protocol):
    """Interface used by ingestion; implementations own model and transport details."""

    provider_name: str
    model: str
    prompt_version: str
    response_adapter_version: str

    def recover(
        self,
        image_bytes: bytes,
        media_type: str,
        context: str = "",
        *,
        outbound_record: OutboundImageRecord | dict[str, Any] | None = None,
    ) -> TableRecoveryResult:
        """Recover one table image into deterministic retrieval text."""


class RemoteVlmTableRecoveryProvider:
    """Adapter that maps the existing remote vision client to the table seam."""

    provider_name = "remote_vlm"
    requires_outbound_manifest = True
    prompt_version = PROMPT_VERSION
    response_adapter_version = RESPONSE_ADAPTER_VERSION

    def __init__(self, analyzer: VisionAnalyzer) -> None:
        """Reuse the caller's configured analyzer and its outbound checks/cache."""
        self.analyzer = analyzer
        self.model = analyzer.model

    def recover(
        self,
        image_bytes: bytes,
        media_type: str,
        context: str = "",
        *,
        outbound_record: OutboundImageRecord | dict[str, Any] | None = None,
    ) -> TableRecoveryResult:
        """Call remote vision once and reject responses without a real table."""
        analysis = self.analyzer.analyze(
            image_bytes,
            media_type,
            context,
            outbound_record=outbound_record,
        )
        table_markdown = analysis.table_markdown.strip()
        if not looks_like_markdown_table(table_markdown):
            raise TableRecoveryError("table_markdown_missing_or_invalid")
        return TableRecoveryResult(
            table_markdown=table_markdown,
            ocr_text=analysis.ocr_text.strip(),
            confidence=analysis.confidence,
            provider=self.provider_name,
            model=self.model,
            prompt_version=self.prompt_version,
            response_adapter_version=self.response_adapter_version,
        )


def looks_like_markdown_table(value: str) -> bool:
    """Require a header, separator, and row before admitting a table unit."""
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) < 3 or any("|" not in line for line in lines[:3]):
        return False
    return any("---" in line for line in lines[1:-1])
