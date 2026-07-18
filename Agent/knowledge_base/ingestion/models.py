import hashlib
import json
import re
import unicodedata
from enum import Enum
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator


class ContractModel(BaseModel):
    """为知识摄取公开契约提供统一的严格校验行为。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Profile(str, Enum):
    """标识知识源所属的语料域。"""

    DEFAULT = "default"
    MEDICAL = "medical"


class SourceType(str, Enum):
    """标识知识源的顶层内容类型。"""

    TEXT = "text"
    TABLE = "table"
    PDF = "pdf"
    IMAGE = "image"


class ContentKind(str, Enum):
    """标识知识片段文字所表达的内容形态。"""

    TEXT = "text"
    TABLE = "table"
    OCR = "ocr"
    FORMULA = "formula"
    CHART = "chart"
    CAUSAL_GRAPH = "causal_graph"
    IMAGE_DESCRIPTION = "image_description"


class IssueSeverity(str, Enum):
    """标识结构化问题的严重程度。"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class IssuePhase(str, Enum):
    """标识结构化问题产生的维护阶段。"""

    INSPECT = "inspect"
    INGEST = "ingest"
    EVALUATE = "evaluate"
    PUBLISH = "publish"
    STATUS = "status"
    ROLLBACK = "rollback"


class DeviceMode(str, Enum):
    """标识本地摄取阶段的设备选择策略。"""

    AUTO = "auto"
    CPU = "cpu"
    GPU = "gpu"


class OcrMode(str, Enum):
    """标识 OCR 的启用策略。"""

    AUTO = "auto"
    DISABLED = "disabled"
    FORCE = "force"


class VisionMode(str, Enum):
    """标识视觉描述的执行位置。"""

    DISABLED = "disabled"
    LOCAL = "local"
    REMOTE = "remote"


class OutputFormat(str, Enum):
    """标识维护命令的终端输出格式。"""

    JSON = "json"
    TEXT = "text"


class RunState(str, Enum):
    """标识摄取运行状态机中的持久状态。"""

    CREATED = "created"
    INSPECTED = "inspected"
    INGESTING = "ingesting"
    STAGED = "staged"
    EVALUATED_PASS = "evaluated_pass"
    EVALUATED_FAIL = "evaluated_fail"
    PUBLISHED = "published"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResultStatus(str, Enum):
    """标识一次维护命令的可观察结果。"""

    PASSED = "passed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FixtureScenario(str, Enum):
    """标识技术 spike 与回归夹具覆盖的资料场景。"""

    TEXT = "text"
    MARKDOWN = "markdown"
    CSV = "csv"
    XLSX = "xlsx"
    DIGITAL_PDF = "digital_pdf"
    SCANNED_PDF = "scanned_pdf"
    MIXED_PDF = "mixed_pdf"
    CHINESE_IMAGE = "chinese_image"
    COMPLEX_TABLE = "complex_table"
    FORMULA = "formula"
    CHART = "chart"
    FLOWCHART = "flowchart"
    CAUSAL_GRAPH = "causal_graph"


class NormalizedBoundingBox(ContractModel):
    """描述左上角原点、取值为零到一的页面区域。"""

    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)
    original_width: int = Field(gt=0)
    original_height: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_area(self) -> "NormalizedBoundingBox":
        """拒绝没有正面积或坐标反向的区域。"""
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("bbox must have positive width and height")
        return self


class SourceLocator(ContractModel):
    """以统一的一基闭区间和归一化坐标定位来源内容。"""

    page_number: int | None = Field(default=None, ge=1)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    sheet_name: str | None = None
    row_start: int | None = Field(default=None, ge=1)
    row_end: int | None = Field(default=None, ge=1)
    column_start: int | None = Field(default=None, ge=1)
    column_end: int | None = Field(default=None, ge=1)
    bbox: NormalizedBoundingBox | None = None

    @model_validator(mode="after")
    def validate_ranges(self) -> "SourceLocator":
        """确保范围成对、递增，并且 locator 至少包含一种定位信息。"""
        for name in ("line", "row", "column"):
            start = getattr(self, f"{name}_start")
            end = getattr(self, f"{name}_end")
            if (start is None) != (end is None):
                raise ValueError(f"{name}_start and {name}_end must be provided together")
            if start is not None and start > end:
                raise ValueError(f"{name} range must be a closed ascending interval")
        if not any(
            (
                self.page_number,
                self.line_start,
                self.sheet_name,
                self.row_start,
                self.column_start,
                self.bbox,
            )
        ):
            raise ValueError("locator must identify at least one source position")
        return self


class IngestionIssue(ContractModel):
    """描述可机器处理的摄取警告或错误。"""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: IssueSeverity
    phase: IssuePhase
    blocking: bool = False
    retryable: bool = False
    source_id: str | None = None
    locator: SourceLocator | None = None


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    """对规范化负载生成带类型前缀的稳定 SHA-256 标识。"""
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(canonical).hexdigest()}"


def _normalize_relative_path(path: str) -> str:
    """把来源相对路径规范为 NFC、正斜杠形式并拒绝路径逃逸。"""
    normalized = unicodedata.normalize("NFC", path.strip().replace("\\", "/"))
    if not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
        raise ValueError("relative_path must be a non-empty relative path")
    parts = normalized.split("/")
    if ".." in parts:
        raise ValueError("relative_path must not escape its source root")
    normalized = str(PurePosixPath(normalized))
    if normalized == ".":
        raise ValueError("relative_path must identify a source")
    return normalized


def _normalize_text(text: str) -> str:
    """统一 Unicode 与换行并移除首尾空白。"""
    return unicodedata.normalize(
        "NFC",
        text.replace("\r\n", "\n").replace("\r", "\n"),
    ).strip()


def _normalize_required_text(text: str, field_name: str) -> str:
    """规范必填正文并用领域字段名报告空值错误。"""
    normalized = _normalize_text(text)
    if not normalized:
        raise ValueError(f"{field_name} text must not be empty")
    return normalized


class KnowledgeSource(ContractModel):
    """描述一个逻辑知识源及其当前内容版本。"""

    profile: Profile
    source_id: str
    source_version_id: str
    source_name: str
    source_type: SourceType
    relative_path: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    manifest_id: str | None = None

    @classmethod
    def from_content(
        cls,
        *,
        profile: Profile,
        relative_path: str,
        content: bytes,
        source_type: SourceType,
        manifest_id: str | None = None,
    ) -> "KnowledgeSource":
        """根据相对路径和原始字节创建带稳定标识的知识源。"""
        normalized_path = _normalize_relative_path(relative_path)
        normalized_manifest_id = (
            unicodedata.normalize("NFC", manifest_id.strip()) if manifest_id else None
        )
        logical_key = (
            f"manifest:{normalized_manifest_id}"
            if normalized_manifest_id
            else f"path:{normalized_path}"
        )
        source_id = _stable_id(
            "src",
            {"profile": profile.value, "logical_key": logical_key},
        )
        content_sha256 = hashlib.sha256(content).hexdigest()
        source_version_id = _stable_id(
            "srcv",
            {"source_id": source_id, "content_sha256": content_sha256},
        )
        return cls(
            profile=profile,
            source_id=source_id,
            source_version_id=source_version_id,
            source_name=PurePosixPath(normalized_path).name,
            source_type=source_type,
            relative_path=normalized_path,
            content_sha256=content_sha256,
            size_bytes=len(content),
            manifest_id=normalized_manifest_id,
        )


class KnowledgeSourceSet(ContractModel):
    """承载同一 profile 下已消除路径冲突的一批知识源。"""

    sources: tuple[KnowledgeSource, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_sources(self) -> "KnowledgeSourceSet":
        """拒绝跨 profile、重复 ID 和仅大小写不同的来源路径。"""
        if len({source.profile for source in self.sources}) != 1:
            raise ValueError("a source set must belong to exactly one profile")
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source_id values must be unique")
        paths = [source.relative_path.casefold() for source in self.sources]
        if len(paths) != len(set(paths)):
            raise ValueError("source paths must remain unique after casefold")
        return self


class KnowledgeFragment(ContractModel):
    """描述保留来源定位的最小文字化知识单元。"""

    source_id: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_version_id: str
    fragment_id: str
    source_name: str
    source_type: SourceType
    content_kind: ContentKind
    text: str
    locator: SourceLocator
    title: str | None = None
    section: str | None = None
    extractor: str = Field(min_length=1)
    extractor_version: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    warnings: tuple[IngestionIssue, ...] = ()

    @field_validator("text")
    @classmethod
    def validate_text(cls, text: str) -> str:
        """规范正文并拒绝空知识片段。"""
        return _normalize_required_text(text, "fragment")

    @classmethod
    def create(
        cls,
        *,
        source: KnowledgeSource,
        locator: SourceLocator,
        content_kind: ContentKind,
        text: str,
        extractor: str,
        extractor_version: str,
        title: str | None = None,
        section: str | None = None,
        confidence: float | None = None,
        warnings: tuple[IngestionIssue, ...] = (),
    ) -> "KnowledgeFragment":
        """根据规范化正文、定位和提取器指纹创建稳定片段。"""
        normalized_text = _normalize_text(text)
        fragment_id = _stable_id(
            "frag",
            {
                "source_version_id": source.source_version_id,
                "locator": locator.model_dump(mode="json", exclude_none=True),
                "content_kind": content_kind.value,
                "extractor": extractor,
                "extractor_version": extractor_version,
                "text_sha256": hashlib.sha256(normalized_text.encode("utf-8")).hexdigest(),
            },
        )
        return cls(
            source_id=source.source_id,
            content_sha256=source.content_sha256,
            source_version_id=source.source_version_id,
            fragment_id=fragment_id,
            source_name=source.source_name,
            source_type=source.source_type,
            content_kind=content_kind,
            text=normalized_text,
            locator=locator,
            title=title,
            section=section,
            extractor=extractor,
            extractor_version=extractor_version,
            confidence=confidence,
            warnings=warnings,
        )


class KnowledgeChunk(ContractModel):
    """描述实际进入文字检索索引的稳定知识单元。"""

    chunk_id: str
    source_id: str
    source_version_id: str
    fragment_id: str
    source_name: str
    source_type: SourceType
    content_kind: ContentKind
    text: str
    locator: SourceLocator
    extractor: str
    extractor_version: str
    chunk_config_fingerprint: str = Field(min_length=1)
    title: str | None = None
    section: str | None = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, text: str) -> str:
        """规范检索正文并拒绝空知识块。"""
        return _normalize_required_text(text, "chunk")

    @classmethod
    def create(
        cls,
        *,
        fragment: KnowledgeFragment,
        text: str,
        chunk_config_fingerprint: str,
    ) -> "KnowledgeChunk":
        """根据片段、检索正文与分块配置生成稳定知识块。"""
        normalized_text = _normalize_text(text)
        chunk_id = _stable_id(
            "chunk",
            {
                "fragment_id": fragment.fragment_id,
                "text_sha256": hashlib.sha256(normalized_text.encode("utf-8")).hexdigest(),
                "chunk_config_fingerprint": chunk_config_fingerprint,
            },
        )
        return cls(
            chunk_id=chunk_id,
            source_id=fragment.source_id,
            source_version_id=fragment.source_version_id,
            fragment_id=fragment.fragment_id,
            source_name=fragment.source_name,
            source_type=fragment.source_type,
            content_kind=fragment.content_kind,
            text=normalized_text,
            locator=fragment.locator,
            extractor=fragment.extractor,
            extractor_version=fragment.extractor_version,
            chunk_config_fingerprint=chunk_config_fingerprint,
            title=fragment.title,
            section=fragment.section,
        )

    def to_chroma_metadata(self) -> dict[str, str | int | float | bool]:
        """返回仅含 Chroma 支持标量并保留完整定位 JSON 的 metadata。"""
        locator = self.locator.model_dump(mode="json", exclude_none=True)
        locator_json = json.dumps(
            locator,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        bbox = locator.pop("bbox", None)
        metadata: dict[str, str | int | float | bool] = {
            "source_id": self.source_id,
            "source_version_id": self.source_version_id,
            "fragment_id": self.fragment_id,
            "source_name": self.source_name,
            "source_type": self.source_type.value,
            "content_kind": self.content_kind.value,
            "extractor": self.extractor,
            "extractor_version": self.extractor_version,
            "chunk_config_fingerprint": self.chunk_config_fingerprint,
            "locator_json": locator_json,
            **locator,
        }
        if bbox:
            metadata.update({f"bbox_{key}": value for key, value in bbox.items()})
        if self.title is not None:
            metadata["title"] = self.title
        if self.section is not None:
            metadata["section"] = self.section
        return metadata


class MaintenanceCommandBase(ContractModel):
    """定义所有维护命令共享的输出字段。"""

    report_dir: str | None = None
    output: OutputFormat = OutputFormat.JSON


class SourceCommandBase(MaintenanceCommandBase):
    """定义 inspect 与 ingest 共享的来源和运行配置。"""

    sources: tuple[str, ...] = Field(min_length=1)
    profile: Literal[Profile.DEFAULT] = Profile.DEFAULT
    device: DeviceMode = DeviceMode.AUTO
    ocr: OcrMode = OcrMode.AUTO
    ocr_languages: tuple[str, ...] = ()
    vision: VisionMode = VisionMode.DISABLED
    vision_max_images: int = Field(default=0, ge=0)
    run_name: str | None = None


class InspectCommand(SourceCommandBase):
    """请求检查知识源而不产生暂存索引。"""

    action: Literal["inspect"] = "inspect"


class IngestCommand(SourceCommandBase):
    """请求把知识源摄取到不可变暂存索引。"""

    action: Literal["ingest"] = "ingest"
    allow_remote_data: bool = False

    @model_validator(mode="after")
    def validate_remote_consent(self) -> "IngestCommand":
        """远程视觉模式必须得到显式数据外发许可。"""
        if self.vision is VisionMode.REMOTE and not self.allow_remote_data:
            raise ValueError("vision=remote requires allow_remote_data=true")
        return self


class EvaluateCommand(MaintenanceCommandBase):
    """请求评估指定的不可变索引版本。"""

    action: Literal["evaluate"] = "evaluate"
    index_version: str = Field(min_length=1)


class PublishCommand(MaintenanceCommandBase):
    """请求发布已经通过质量门禁的索引版本。"""

    action: Literal["publish"] = "publish"
    index_version: str = Field(min_length=1)


class StatusCommand(MaintenanceCommandBase):
    """请求读取一个摄取运行或索引版本的状态。"""

    action: Literal["status"] = "status"
    run_id: str | None = None
    index_version: str | None = None

    @model_validator(mode="after")
    def validate_target(self) -> "StatusCommand":
        """确保状态查询恰好指定一种目标。"""
        if (self.run_id is None) == (self.index_version is None):
            raise ValueError("status requires exactly one of run_id or index_version")
        return self


class RollbackCommand(MaintenanceCommandBase):
    """请求切换到可验证的历史索引版本。"""

    action: Literal["rollback"] = "rollback"
    to_index_version: str = Field(min_length=1)


MaintenanceCommand: TypeAlias = Annotated[
    InspectCommand
    | IngestCommand
    | EvaluateCommand
    | PublishCommand
    | StatusCommand
    | RollbackCommand,
    Field(discriminator="action"),
]

_MAINTENANCE_COMMAND_ADAPTER = TypeAdapter(MaintenanceCommand)


def validate_maintenance_command(payload: Any) -> MaintenanceCommand:
    """把 CLI 或 HTTP 负载校验为统一的维护领域命令。"""
    return _MAINTENANCE_COMMAND_ADAPTER.validate_python(payload)


class ReportReference(ContractModel):
    """引用一次维护运行生成的机器可读报告。"""

    name: str = Field(min_length=1)
    path: str = Field(min_length=1)
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class MaintenanceResult(ContractModel):
    """定义 CLI 与未来 HTTP adapter 共享的维护结果。"""

    status: ResultStatus
    run_state: RunState
    run_id: str = Field(min_length=1)
    index_version: str | None = None
    reports: tuple[ReportReference, ...] = ()
    issues: tuple[IngestionIssue, ...] = ()
    publishable: bool = False

    @model_validator(mode="after")
    def validate_result(self) -> "MaintenanceResult":
        """确保失败类结果不可发布且索引状态绑定确切版本。"""
        expected_statuses = {
            RunState.CREATED: ResultStatus.PASSED,
            RunState.INSPECTED: ResultStatus.PASSED,
            RunState.INGESTING: ResultStatus.PASSED,
            RunState.STAGED: ResultStatus.PASSED,
            RunState.EVALUATED_PASS: ResultStatus.PASSED,
            RunState.EVALUATED_FAIL: ResultStatus.FAILED,
            RunState.PUBLISHED: ResultStatus.PASSED,
            RunState.PARTIAL: ResultStatus.PARTIAL,
            RunState.FAILED: ResultStatus.FAILED,
            RunState.CANCELLED: ResultStatus.CANCELLED,
        }
        expected_status = expected_statuses[self.run_state]
        if self.status is not expected_status:
            raise ValueError(
                f"run_state={self.run_state.value} requires status={expected_status.value}"
            )
        if self.status is not ResultStatus.PASSED and self.publishable:
            raise ValueError("partial, failed, and cancelled results are not publishable")
        if self.publishable and self.run_state not in {
            RunState.EVALUATED_PASS,
            RunState.PUBLISHED,
        }:
            raise ValueError("only evaluated or published versions can be publishable")
        if self.publishable and any(issue.blocking for issue in self.issues):
            raise ValueError("blocking issues prevent publication")
        if self.run_state in {
            RunState.STAGED,
            RunState.EVALUATED_PASS,
            RunState.EVALUATED_FAIL,
            RunState.PUBLISHED,
        } and not self.index_version:
            raise ValueError(f"run_state={self.run_state.value} requires index_version")
        return self


class TableCellExpectation(ContractModel):
    """描述表格夹具中需要精确验证的单元格显示值。"""

    row: int = Field(ge=1)
    column: int = Field(ge=1)
    display_value: str
    sheet_name: str | None = None


class CausalEdgeExpectation(ContractModel):
    """描述因果图夹具中的一条有向条件边。"""

    cause: str = Field(min_length=1)
    effect: str = Field(min_length=1)
    condition: str | None = None


class IssueExpectation(ContractModel):
    """描述夹具期望产生的问题语义而不绑定易变消息文本。"""

    code: str = Field(min_length=1)
    severity: IssueSeverity
    phase: IssuePhase
    blocking: bool = False


class FixtureExpectation(ContractModel):
    """描述夹具的定位、文字和结构质量 gold。"""

    expected_content_kinds: tuple[ContentKind, ...] = Field(min_length=1)
    expected_locators: tuple[SourceLocator, ...] = Field(min_length=1)
    gold_text: str | None = None
    table_cells: tuple[TableCellExpectation, ...] = ()
    formulas: tuple[str, ...] = ()
    causal_nodes: tuple[str, ...] = ()
    causal_edges: tuple[CausalEdgeExpectation, ...] = ()
    expected_issues: tuple[IssueExpectation, ...] = ()


class FixtureCase(ContractModel):
    """描述一份合法小型夹具及其质量标注。"""

    fixture_id: str = Field(min_length=1)
    relative_path: str
    source_type: SourceType
    scenario: FixtureScenario
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expectation: FixtureExpectation

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, path: str) -> str:
        """把夹具路径规范为跨平台相对路径。"""
        return _normalize_relative_path(path)


class FixtureManifest(ContractModel):
    """冻结 P01S 与后续回归测试共享的夹具清单格式。"""

    schema_version: Literal["1.0"] = "1.0"
    fixtures: tuple[FixtureCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_fixtures(self) -> "FixtureManifest":
        """拒绝重复 ID 和仅大小写不同的来源路径。"""
        fixture_ids = [fixture.fixture_id for fixture in self.fixtures]
        if len(fixture_ids) != len(set(fixture_ids)):
            raise ValueError("fixture_id values must be unique")
        paths = [fixture.relative_path.casefold() for fixture in self.fixtures]
        if len(paths) != len(set(paths)):
            raise ValueError("fixture paths must remain unique after casefold")
        return self
