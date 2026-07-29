"""多模态知识库的稳定数据契约。"""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def canonical_json(value: Any) -> str:
    """返回用于指纹和持久化的确定性 JSON。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    """计算字节内容的 SHA-256。"""
    return hashlib.sha256(value).hexdigest()


def stable_id(prefix: str, value: Any) -> str:
    """以规范 JSON 创建具有领域前缀的稳定标识。"""
    return f"{prefix}_{sha256_bytes(canonical_json(value).encode('utf-8'))}"


class UnitStatus(str, Enum):
    """知识单元可持久化的处理状态。"""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    ENRICHED = "enriched"


class IssueSeverity(str, Enum):
    """摄取问题的严重程度。"""

    WARNING = "warning"
    ERROR = "error"


class BoundingBox(BaseModel):
    """使用左上角原点的归一化矩形。"""

    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_order(self) -> "BoundingBox":
        """拒绝退化或反向的边界框。"""
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("bbox requires x0 < x1 and y0 < y1")
        return self


class DirectedRelation(BaseModel):
    """由视觉服务明确识别的一条有向关系。"""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    condition: str | None = None


class VisionAnalysis(BaseModel):
    """vision-v2 必须完整返回的、仅记录可见事实的输出。"""

    model_config = ConfigDict(extra="forbid")

    content_kind: Literal["causal_graph", "chart", "table", "formula", "illustration", "other"]
    ocr_text: str
    visible_facts: list[str]
    summary: str
    entities: list[str]
    table_markdown: str
    formula_latex: str
    directed_relations: list[DirectedRelation]
    uncertain_relations: list[str]
    confidence: float = Field(ge=0, le=1)
    informative: bool


class OutboundImageRecord(BaseModel):
    """批准外发的单张图片及其不可变哈希边界。"""

    model_config = ConfigDict(extra="forbid")

    source_relative_path: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_id: str = Field(pattern=r"^doc_[0-9a-f]{64}$")
    page_number: int = Field(ge=1)
    image_index: int = Field(ge=1)
    original_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str = Field(pattern=r"^image/(png|jpeg)$")
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    original_bytes: int = Field(ge=1)
    normalized_bytes: int = Field(ge=1)
    transformation: str = Field(min_length=1)
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str = Field(pattern=r"^wcode$")
    model: str = Field(min_length=1)
    prompt_version: str = Field(pattern=r"^vision-v2$")
    remote_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("source_relative_path")
    @classmethod
    def validate_source_relative_path(cls, value: str) -> str:
        """拒绝绝对路径、反斜杠和目录逃逸进入外发审计。"""
        if value.startswith("/") or "\\" in value or ".." in value.split("/"):
            raise ValueError("source_relative_path must be a safe relative POSIX path")
        return value


class KnowledgeUnit(BaseModel):
    """进入多模态文本索引的最小可追溯单元。"""

    unit_id: str = Field(pattern=r"^unit_[0-9a-f]{64}$")
    document_id: str = Field(pattern=r"^doc_[0-9a-f]{64}$")
    parent_id: str | None = None
    modality: str = Field(pattern=r"^(text|image|table|equation|page)$")
    content_kind: str = Field(min_length=1)
    page_number: int | None = Field(default=None, ge=1)
    bbox: BoundingBox | None = None
    raw_text: str = ""
    retrieval_text: str = Field(min_length=1)
    asset_uri: str | None = None
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    vision_model: str = ""
    vision_prompt_version: str = "vision-v1"
    embedding_provider: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    status: UnitStatus

    @field_validator("asset_uri")
    @classmethod
    def validate_asset_uri(cls, uri: str | None) -> str | None:
        """确保资源 URI 是安全的相对 POSIX 路径。"""
        if uri is None:
            return None
        if not uri or uri.startswith("/") or "\\" in uri or ".." in uri.split("/"):
            raise ValueError("asset_uri must be a safe relative POSIX path")
        return uri

    @model_validator(mode="after")
    def validate_asset_requirement(self) -> "KnowledgeUnit":
        """要求带图片资源的单元保留其本地引用。"""
        if self.modality in {"image", "page"} and not self.asset_uri:
            raise ValueError("image and page units require asset_uri")
        return self

    def chroma_metadata(self) -> dict[str, str | int]:
        """把复杂契约安全映射为 Chroma 标量 metadata。"""
        locator = {"page_number": self.page_number, "bbox": self.bbox.model_dump() if self.bbox else None}
        return {
            "unit_id": self.unit_id,
            "document_id": self.document_id,
            "parent_id": self.parent_id or "",
            "modality": self.modality,
            "content_kind": self.content_kind,
            "page_number": self.page_number or 0,
            "asset_uri": self.asset_uri or "",
            "content_hash": self.content_hash,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "vision_model": self.vision_model,
            "vision_prompt_version": self.vision_prompt_version,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "locator_json": canonical_json(locator),
        }


class IngestionIssue(BaseModel):
    """记录一个不会泄露资料正文的摄取问题。"""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: IssueSeverity
    blocking: bool = False
    source_path: str | None = None


def render_retrieval_text(*, content_kind: str, title: str = "", analysis: VisionAnalysis | None = None, raw_text: str = "") -> str:
    """以固定顺序把正文和视觉观察渲染为实际嵌入的文本。"""
    parts = [f"类型：{content_kind}"]
    if title:
        parts.append(f"标题：{title}")
    if analysis:
        if analysis.ocr_text:
            parts.append(f"OCR：\n{analysis.ocr_text}")
        if analysis.summary:
            parts.append(f"摘要：{analysis.summary}")
        if analysis.visible_facts:
            parts.append("可见事实：\n" + "\n".join(f"- {item}" for item in analysis.visible_facts))
        if analysis.table_markdown:
            parts.append(f"表格：\n{analysis.table_markdown}")
        if analysis.formula_latex:
            parts.append(f"公式：\n{analysis.formula_latex}")
        if analysis.entities:
            parts.append("实体：" + "、".join(analysis.entities))
        if analysis.directed_relations:
            parts.append("明确关系：\n" + "\n".join(f"- {item.source} -> {item.target}" for item in analysis.directed_relations))
        if analysis.uncertain_relations:
            parts.append("不确定关系：\n" + "\n".join(f"- {item}" for item in analysis.uncertain_relations))
    if raw_text:
        parts.append(raw_text)
    return "\n".join(parts).strip()
