"""图片 OCR 到可追溯文字片段的适配器。"""

import hashlib
from io import BytesIO
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from ..models import (
    ContentKind,
    IngestionIssue,
    IssuePhase,
    IssueSeverity,
    KnowledgeFragment,
    KnowledgeSource,
    NormalizedBoundingBox,
    SourceLocator,
    SourceType,
)

_EXTRACTOR = "paddleocr-ppstructurev3"
_EXTRACTOR_VERSION = "3.7.0"
# ponytail: one global CPU OCR slot; revisit only after P13 has concurrency data.
_PADDLE_OCR_SLOT = Lock()
_PADDLE_OCR_PIPELINE = None
_PADDLE_OCR_CONFIG: tuple[str, tuple[str, ...]] | None = None


@dataclass(frozen=True)
class OcrObservation:
    """承载 OCR 已识别的一行文字及其页面几何信息。"""

    text: str
    bbox: NormalizedBoundingBox
    confidence: float | None = None
    rotation_degrees: int = 0


@dataclass(frozen=True)
class OcrExtractionResult:
    """承载 OCR 片段及不阻断的质量诊断。"""

    fragments: tuple[KnowledgeFragment, ...]
    issues: tuple[IngestionIssue, ...]


class OcrPort(Protocol):
    """定义本地 OCR 引擎向统一适配器返回观察结果的边界。"""

    def recognize(self, content: bytes, languages: tuple[str, ...]) -> tuple[OcrObservation, ...]:
        """识别图片字节并返回已完成方向校正的观察结果。"""


@dataclass(frozen=True)
class FakeOcrPort:
    """为测试提供确定性 OCR 观察结果。"""

    observations: tuple[OcrObservation, ...]

    def recognize(self, content: bytes, languages: tuple[str, ...]) -> tuple[OcrObservation, ...]:
        """返回预设结果，不读取图片或调用外部服务。"""
        return self.observations


class PaddleOcrPort:
    """使用 P01S 选定的 PP-StructureV3 执行本地图片 OCR。"""

    def __init__(self, *, device: str = "cpu") -> None:
        """延迟创建模型，避免未启用 OCR 的路径加载大型依赖。"""
        self._device = device

    def recognize(self, content: bytes, languages: tuple[str, ...]) -> tuple[OcrObservation, ...]:
        """解析 PP-StructureV3 的 OCR 行结果并归一化其 bbox。"""
        global _PADDLE_OCR_CONFIG, _PADDLE_OCR_PIPELINE
        try:
            import numpy
            from PIL import Image
            from paddleocr import PPStructureV3
        except ImportError as exc:
            raise RuntimeError("PaddleOCR PP-StructureV3 is not installed") from exc
        image = numpy.array(Image.open(BytesIO(content)).convert("RGB"))
        with _PADDLE_OCR_SLOT:
            config = (self._device, languages)
            if _PADDLE_OCR_PIPELINE is None:
                language = "ch" if "chi_sim" in languages else "en"
                _PADDLE_OCR_PIPELINE = PPStructureV3(device=self._device, lang=language)
                _PADDLE_OCR_CONFIG = config
            elif config != _PADDLE_OCR_CONFIG:
                raise ValueError("one process cannot mix Paddle OCR configurations")
            outputs = tuple(_PADDLE_OCR_PIPELINE.predict(image))
        return tuple(
            observation
            for output in outputs
            for observation in self._observations_from_output(output, image.shape[:2])
        )

    @staticmethod
    def _observations_from_output(output: object, image_shape: tuple[int, int]) -> tuple[OcrObservation, ...]:
        """将 PP-StructureV3 实际输出的逐行 OCR 字段转为项目观察对象。"""
        import numpy

        payload = getattr(output, "json", output)
        payload = payload() if callable(payload) else payload
        result = payload.get("res", payload)
        height, width = image_shape
        rotation = int(result.get("doc_preprocessor_res", {}).get("angle") or 0)
        ocr_result = result.get("overall_ocr_res", {})
        observations = []
        texts = ocr_result.get("rec_texts", ())
        polygons = ocr_result.get("rec_polys") or ocr_result.get("dt_polys") or ()
        confidences = ocr_result.get("rec_scores", ())
        for index, (text, polygon) in enumerate(zip(texts, polygons)):
            text = str(text).strip()
            if not text or not polygon:
                continue
            confidence = confidences[index] if index < len(confidences) else None
            points = PaddleOcrPort._source_points(numpy.asarray(polygon), width, height, rotation)
            x0, y0 = points.min(axis=0)
            x1, y1 = points.max(axis=0)
            observations.append(OcrObservation(
                text=text,
                bbox=NormalizedBoundingBox(x0=float(x0 / width), y0=float(y0 / height), x1=float(x1 / width), y1=float(y1 / height), original_width=width, original_height=height),
                confidence=float(confidence) if confidence is not None else None,
                rotation_degrees=rotation,
            ))
        if observations:
            return tuple(observations)
        for line in result.get("ocr_res_list", []):
            text = str(line.get("rec_text", "")).strip()
            polygon = line.get("dt_polys") or line.get("dt_poly")
            if not text or not polygon:
                continue
            points = PaddleOcrPort._source_points(numpy.asarray(polygon), width, height, rotation)
            x0, y0 = points.min(axis=0)
            x1, y1 = points.max(axis=0)
            observations.append(OcrObservation(
                text=text,
                bbox=NormalizedBoundingBox(x0=float(x0 / width), y0=float(y0 / height), x1=float(x1 / width), y1=float(y1 / height), original_width=width, original_height=height),
                confidence=float(line["rec_score"]) if line.get("rec_score") is not None else None,
                rotation_degrees=rotation,
            ))
        return tuple(observations)

    @staticmethod
    def _source_points(points: object, width: int, height: int, rotation: int) -> object:
        """将方向校正后坐标逆变换回原始图片坐标系。"""
        rotation %= 360
        if rotation == 0:
            return points
        if rotation == 90:
            return points[:, [1, 0]] * [-1, 1] + [width, 0]
        if rotation == 180:
            return points * [-1, -1] + [width, height]
        if rotation == 270:
            return points[:, [1, 0]] * [1, -1] + [0, height]
        raise ValueError(f"unsupported PP-StructureV3 rotation: {rotation}")


class OcrDescriptor:
    """把本地 OCR 观察转换为带来源定位的 OCR 知识片段。"""

    def __init__(self, port: OcrPort, *, low_confidence: float = 0.6, languages: tuple[str, ...] = ()) -> None:
        """绑定 OCR port、低置信度阈值与语言配置。"""
        self._port = port
        self._low_confidence = low_confidence
        self._languages = languages

    def extract(self, source: KnowledgeSource, content: bytes) -> OcrExtractionResult:
        """执行 OCR，并在低置信度、旋转或无文字时保留可审计非阻断问题。"""
        if source.source_type is not SourceType.IMAGE:
            raise ValueError("OCR descriptor requires an image source")
        if hashlib.sha256(content).hexdigest() != source.content_sha256:
            raise ValueError("image content does not match the source version")
        observations = self._port.recognize(content, self._languages)
        fragments, issues = [], []
        for observation in observations:
            if not observation.text.strip():
                continue
            warnings = []
            if observation.confidence is not None and observation.confidence < self._low_confidence:
                warnings.append(IngestionIssue(code="OCR_LOW_CONFIDENCE", message="OCR text is below the configured confidence threshold", severity=IssueSeverity.WARNING, phase=IssuePhase.INGEST, source_id=source.source_id, locator=SourceLocator(bbox=observation.bbox)))
            if observation.rotation_degrees % 360:
                warnings.append(IngestionIssue(code="OCR_ROTATION_CORRECTED", message="OCR engine corrected image orientation", severity=IssueSeverity.INFO, phase=IssuePhase.INGEST, source_id=source.source_id, locator=SourceLocator(bbox=observation.bbox)))
            fragments.append(KnowledgeFragment.create(source=source, locator=SourceLocator(bbox=observation.bbox), content_kind=ContentKind.OCR, text=observation.text, extractor=_EXTRACTOR, extractor_version=_EXTRACTOR_VERSION, confidence=observation.confidence, warnings=tuple(warnings)))
        if not fragments:
            issues.append(IngestionIssue(code="OCR_NO_TEXT", message="OCR found no text in image", severity=IssueSeverity.WARNING, phase=IssuePhase.INGEST, source_id=source.source_id))
        return OcrExtractionResult(tuple(fragments), tuple(issues))
