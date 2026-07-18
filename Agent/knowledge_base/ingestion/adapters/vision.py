import base64
import hashlib
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from ..models import (
    ContentKind,
    IngestCommand,
    IngestionIssue,
    IssuePhase,
    IssueSeverity,
    KnowledgeFragment,
    KnowledgeSource,
    SourceLocator,
    SourceType,
    VisionMode,
)


@dataclass(frozen=True)
class DirectedEdge:
    """描述视觉中方向明确的有向边。"""

    source: str
    target: str
    condition: str | None = None

    def __post_init__(self) -> None:
        """拒绝空节点和自环猜测。"""
        if not self.source.strip() or not self.target.strip():
            raise ValueError("directed edge nodes must not be empty")
        if self.source.strip() == self.target.strip():
            raise ValueError("directed edge must connect different nodes")


@dataclass(frozen=True)
class VisionObservation:
    """承载只基于可见事实形成的结构化视觉观察。"""

    content_kind: ContentKind
    visible_facts: str
    nodes: tuple[str, ...] = ()
    directed_edges: tuple[DirectedEdge, ...] = ()
    uncertain_connections: tuple[tuple[str, str], ...] = ()
    confidence: float | None = None
    informative: bool = True

    def __post_init__(self) -> None:
        """校验观察内容、置信度与因果图结构。"""
        if self.content_kind not in {
            ContentKind.CHART,
            ContentKind.CAUSAL_GRAPH,
            ContentKind.IMAGE_DESCRIPTION,
        }:
            raise ValueError("vision observation requires a visual content kind")
        if self.informative and not self.visible_facts.strip():
            raise ValueError("informative vision observation requires visible facts")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("vision confidence must be between zero and one")
        if self.content_kind is not ContentKind.CAUSAL_GRAPH and (
            self.nodes or self.directed_edges or self.uncertain_connections
        ):
            raise ValueError("graph structure is only valid for causal graph observations")
        if any(
            len(connection) != 2 or not all(node.strip() for node in connection)
            for connection in self.uncertain_connections
        ):
            raise ValueError("uncertain connections require two non-empty nodes")
        graph_nodes = {node.strip() for node in self.nodes}
        if any(
            edge.source.strip() not in graph_nodes or edge.target.strip() not in graph_nodes
            for edge in self.directed_edges
        ):
            raise ValueError("directed edge endpoints must be declared graph nodes")
        if any(
            left.strip() not in graph_nodes or right.strip() not in graph_nodes
            for left, right in self.uncertain_connections
        ):
            raise ValueError("uncertain connection endpoints must be declared graph nodes")
        directed_pairs = {
            frozenset((edge.source.strip(), edge.target.strip()))
            for edge in self.directed_edges
        }
        uncertain_pairs = {
            frozenset((left.strip(), right.strip()))
            for left, right in self.uncertain_connections
        }
        if directed_pairs & uncertain_pairs:
            raise ValueError("a connection cannot be both directed and uncertain")

    def render(self) -> str:
        """以确定顺序渲染可检索文字，并保留未知方向标记。"""
        sections = [f"Visible facts:\n{self.visible_facts.strip()}"]
        if self.content_kind is ContentKind.CAUSAL_GRAPH:
            sections.append("Nodes:\n" + "\n".join(f"- {node}" for node in sorted(set(self.nodes))))
            sections.append(
                "Directed edges:\n"
                + "\n".join(
                    f"- {edge.source} -> {edge.target}"
                    + (f" [condition: {edge.condition}]" if edge.condition else "")
                    for edge in sorted(
                        self.directed_edges,
                        key=lambda item: (item.source, item.target, item.condition or ""),
                    )
                )
            )
            sections.append(
                "Uncertain connections:\n"
                + "\n".join(
                    f"- {left} ? {right}"
                    for left, right in sorted(set(self.uncertain_connections))
                )
            )
        return "\n\n".join(sections)


class VisionDescriptionPort(Protocol):
    """隔离视觉描述生产实现与摄取编排。"""

    name: str
    version: str
    is_remote: bool

    def describe(self, image: bytes, media_type: str) -> VisionObservation:
        """根据图片字节返回结构化可见事实。"""
        ...


class FakeVisionDescriptionPort:
    """按内容哈希返回确定性观察的测试 fake。"""

    name = "fake-vision"
    version = "1.0"
    is_remote = False

    def __init__(self, observations: dict[bytes, VisionObservation]) -> None:
        """把测试图片字节映射为稳定内容哈希。"""
        self._observations = {
            hashlib.sha256(content).hexdigest(): observation
            for content, observation in observations.items()
        }
        self.call_count = 0

    def describe(self, image: bytes, media_type: str) -> VisionObservation:
        """返回匹配观察并记录实际调用次数。"""
        del media_type
        self.call_count += 1
        return self._observations[hashlib.sha256(image).hexdigest()]


class _DirectedEdgePayload(BaseModel):
    """定义远程结构化输出中的有向边字段。"""

    source: str
    target: str
    condition: str | None


class _VisionObservationPayload(BaseModel):
    """定义远程视觉服务必须返回的结构化字段。"""

    content_kind: ContentKind
    visible_facts: str
    nodes: tuple[str, ...]
    directed_edges: tuple[_DirectedEdgePayload, ...]
    uncertain_connections: tuple[tuple[str, str], ...]
    confidence: float | None
    informative: bool


class OpenAICompatibleVisionPort:
    """通过 OpenAI-compatible Responses API 生成结构化视觉观察。"""

    name = "openai-compatible-vision"
    is_remote = True
    _MEDIA_TYPES = {"image/jpeg", "image/png", "image/tiff", "image/webp"}

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 30,
        max_retries: int = 2,
        client: Any | None = None,
    ) -> None:
        """绑定独立模型配置，并把超时与重试交给官方 SDK。"""
        if not model.strip():
            raise ValueError("vision model must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("vision timeout must be positive")
        if max_retries < 0:
            raise ValueError("vision max_retries must not be negative")
        if client is None:
            if not api_key:
                raise ValueError("vision api_key is required")
            from openai import OpenAI

            options: dict[str, Any] = {
                "api_key": api_key,
                "timeout": timeout_seconds,
                "max_retries": max_retries,
            }
            if base_url:
                options["base_url"] = base_url
            client = OpenAI(**options)
        self.version = model.strip()
        self._model = model.strip()
        self._client = client

    def describe(self, image: bytes, media_type: str) -> VisionObservation:
        """发送一张图片并把结构化响应转换为统一视觉观察。"""
        if media_type not in self._MEDIA_TYPES:
            raise ValueError(f"unsupported vision media type: {media_type}")
        image_url = f"data:{media_type};base64,{base64.b64encode(image).decode('ascii')}"
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Describe only facts directly visible in the image. "
                        "Classify charts and causal graphs explicitly. For causal graphs, "
                        "list nodes and only directed edges whose arrow direction is visible; "
                        "put ambiguous links in uncertain_connections and never guess direction. "
                        "Use informative=false for decorative images with no useful information."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Extract visible knowledge from this image.",
                        },
                        {"type": "input_image", "image_url": image_url},
                    ],
                },
            ],
            text_format=_VisionObservationPayload,
            max_output_tokens=800,
            store=False,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("vision service returned no structured observation")
        return VisionObservation(
            content_kind=ContentKind(parsed.content_kind),
            visible_facts=parsed.visible_facts,
            nodes=tuple(parsed.nodes),
            directed_edges=tuple(
                DirectedEdge(
                    source=edge.source,
                    target=edge.target,
                    condition=edge.condition,
                )
                for edge in parsed.directed_edges
            ),
            uncertain_connections=tuple(
                tuple(connection) for connection in parsed.uncertain_connections
            ),
            confidence=parsed.confidence,
            informative=parsed.informative,
        )


@dataclass(frozen=True)
class VisionExtractionResult:
    """承载可选视觉片段和不阻断其他适配器的结构化问题。"""

    fragment: KnowledgeFragment | None
    issues: tuple[IngestionIssue, ...] = ()


class VisionDescriptor:
    """执行隐私门禁、调用预算、内容缓存和失败降级。"""

    def __init__(self, port: VisionDescriptionPort, command: IngestCommand) -> None:
        """绑定视觉 port 与 P01 冻结的摄取命令。"""
        if command.vision is not VisionMode.DISABLED and (
            port.is_remote != (command.vision is VisionMode.REMOTE)
        ):
            raise ValueError("vision port does not match configured vision mode")
        self._port = port
        self._command = command
        self._cache: dict[tuple[str, str, str], VisionObservation] = {}
        self._remote_calls = 0

    def _issue(
        self,
        code: str,
        message: str,
        source: KnowledgeSource,
        locator: SourceLocator,
    ) -> VisionExtractionResult:
        """创建不会阻断 OCR 或正文摄取的视觉 warning。"""
        return VisionExtractionResult(
            fragment=None,
            issues=(
                IngestionIssue(
                    code=code,
                    message=message,
                    severity=IssueSeverity.WARNING,
                    phase=IssuePhase.INGEST,
                    blocking=False,
                    source_id=source.source_id,
                    locator=locator,
                ),
            ),
        )

    def describe(
        self,
        source: KnowledgeSource,
        image: bytes,
        media_type: str,
        locator: SourceLocator,
    ) -> VisionExtractionResult:
        """安全描述图片；失败只返回 warning，不抛出到其他摄取路径。"""
        if source.source_type not in {SourceType.IMAGE, SourceType.PDF}:
            raise ValueError("vision descriptor requires an image or PDF source")
        image_hash = hashlib.sha256(image).hexdigest()
        if source.source_type is SourceType.IMAGE and image_hash != source.content_sha256:
            raise ValueError("vision image does not match the source version")
        if self._command.vision is VisionMode.DISABLED:
            return VisionExtractionResult(fragment=None)
        cache_key = (image_hash, self._port.name, self._port.version)
        observation = self._cache.get(cache_key)
        if observation is None:
            if self._port.is_remote:
                if self._remote_calls >= self._command.vision_max_images:
                    return self._issue(
                        "VISION_REMOTE_LIMIT_REACHED",
                        "remote vision image limit has been reached",
                        source,
                        locator,
                    )
                self._remote_calls += 1
            try:
                observation = self._port.describe(image, media_type)
            except Exception:
                return self._issue(
                    "VISION_DESCRIPTION_FAILED",
                    "vision description failed; OCR and text extraction may continue",
                    source,
                    locator,
                )
            self._cache[cache_key] = observation
        if not observation.informative:
            return self._issue(
                "VISION_NO_INFORMATION",
                "image contains no useful visible information",
                source,
                locator,
            )
        review_issues: tuple[IngestionIssue, ...] = ()
        if observation.uncertain_connections:
            review_issues = (
                IngestionIssue(
                    code="VISION_DIRECTION_REVIEW_REQUIRED",
                    message="causal graph contains connections with uncertain direction",
                    severity=IssueSeverity.WARNING,
                    phase=IssuePhase.INGEST,
                    blocking=True,
                    source_id=source.source_id,
                    locator=locator,
                ),
            )
        fragment = KnowledgeFragment.create(
            source=source,
            locator=locator,
            content_kind=observation.content_kind,
            text=observation.render(),
            extractor=self._port.name,
            extractor_version=self._port.version,
            confidence=observation.confidence,
            warnings=review_issues,
        )
        return VisionExtractionResult(fragment=fragment, issues=review_issues)
