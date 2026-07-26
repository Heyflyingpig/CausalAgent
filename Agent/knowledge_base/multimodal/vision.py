"""WCode OpenAI-compatible 视觉增强适配器。"""

from __future__ import annotations

import base64
import json
import os
import time
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from openai import OpenAI

from .contracts import VisionAnalysis, canonical_json, sha256_bytes

PROMPT_VERSION = "vision-v1"
REQUIRED_MODEL = "qwen/qwen3-vl-flash"
_PROMPT = "仅描述图像中直接可见的事实。返回 JSON：content_kind, ocr_text, visible_facts, summary, entities, table_markdown, formula_latex, directed_relations, uncertain_relations, confidence, informative。箭头方向不明确时只写 uncertain_relations。"


class VisionAnalyzer:
    """限制外发范围、重试次数与预算的 WCode 视觉客户端。"""

    def __init__(self, cache_dir: Path, *, allow_remote_data: bool, max_images: int | None = None, retry_failed: bool = False) -> None:
        """仅读取环境配置，不持久化密钥或原始响应。"""
        self.cache_dir = cache_dir
        self.allow_remote_data = allow_remote_data
        self.model = os.getenv("VISION_MODEL", REQUIRED_MODEL)
        self.timeout = int(os.getenv("VISION_TIMEOUT_SECONDS", "30"))
        self.max_retries = int(os.getenv("VISION_MAX_RETRIES", "2"))
        self.max_images = min(max_images or int(os.getenv("VISION_MAX_IMAGES_PER_RUN", "100")), 100)
        self.max_concurrency = max(1, int(os.getenv("VISION_MAX_CONCURRENCY", "2")))
        self.retry_failed = retry_failed
        self._semaphore = threading.BoundedSemaphore(self.max_concurrency)
        self._calls_lock = threading.Lock()
        self.calls = 0

    def configured(self) -> bool:
        """报告远程调用所需配置是否完整且非占位。"""
        api_key = os.getenv("VISION_API_KEY", "")
        base_url = os.getenv("VISION_BASE_URL", "")
        hostname = urlparse(base_url).hostname or ""
        return (
            self.model == REQUIRED_MODEL
            and hostname.lower().endswith("wcode.net")
            and all(value and "placeholder" not in value.lower() for value in (api_key, base_url))
        )

    def analyze(self, image_bytes: bytes, media_type: str, context: str = "") -> VisionAnalysis:
        """对一个允许的图片执行带本地缓存的结构化视觉观察。"""
        if not self.allow_remote_data:
            raise PermissionError("remote vision requires explicit allow_remote_data")
        if not self.configured():
            raise RuntimeError("WCode vision configuration is missing, invalid, or not approved")
        key = sha256_bytes(canonical_json({"image": sha256_bytes(image_bytes), "model": self.model, "prompt": PROMPT_VERSION, "context": context}).encode())
        cache_path = self.cache_dir / f"{key}.json"
        failure_path = self.cache_dir / f"{key}.failure.json"
        if cache_path.exists():
            return VisionAnalysis.model_validate_json(cache_path.read_text(encoding="utf-8"))
        if failure_path.exists() and not self.retry_failed:
            failure = json.loads(failure_path.read_text(encoding="utf-8"))
            raise RuntimeError(f"vision failure is already recorded: {failure.get('failure_type', 'unknown')}")
        with self._calls_lock:
            if self.calls >= self.max_images:
                raise RuntimeError("vision image budget exhausted")
            self.calls += 1
        payload = base64.b64encode(image_bytes).decode("ascii")
        message = [{"type": "text", "text": _PROMPT + (f"\n邻近正文：{context[:2000]}" if context else "")}, {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{payload}"}}]
        client = OpenAI(api_key=os.environ["VISION_API_KEY"], base_url=os.environ["VISION_BASE_URL"], timeout=self.timeout)
        last_error: Exception | None = None
        with self._semaphore:
            for attempt in range(self.max_retries + 1):
                try:
                    response = self._invoke(client, message, structured=True)
                    analysis = VisionAnalysis.model_validate_json(response.choices[0].message.content or "{}")
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
                    self._append_audit(response, "success", cache_path.name)
                    return analysis
                except Exception as exc:  # SDK exceptions vary by installed version.
                    last_error = exc
                    status = getattr(exc, "status_code", 0)
                    if status == 400:
                        try:
                            response = self._invoke(client, message, structured=False)
                            analysis = VisionAnalysis.model_validate_json(response.choices[0].message.content or "{}")
                            cache_path.parent.mkdir(parents=True, exist_ok=True)
                            cache_path.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
                            self._append_audit(response, "success_json_prompt_fallback", cache_path.name)
                            return analysis
                        except Exception as fallback_error:
                            last_error = fallback_error
                        break
                    if status and status < 500 and status not in {408, 429}:
                        break
                    if attempt < self.max_retries:
                        time.sleep(2 ** attempt)
        self._record_failure(failure_path, last_error)
        self._append_audit(None, f"failed_{type(last_error).__name__}", cache_path.name)
        raise RuntimeError("vision analysis failed without persisting response content") from last_error

    def _invoke(self, client: OpenAI, message: list[dict[str, Any]], *, structured: bool) -> Any:
        """用结构化输出或兼容 JSON Prompt 请求一次完整响应。"""
        kwargs: dict[str, Any] = {"model": self.model, "messages": [{"role": "user", "content": message}], "stream": False}
        if structured:
            kwargs["response_format"] = {"type": "json_object"}
        return client.chat.completions.create(**kwargs)

    def _append_audit(self, response: Any | None, status: str, cache_key: str) -> None:
        """追加不含图片、Prompt、响应正文与密钥的调用审计记录。"""
        usage = getattr(response, "usage", None)
        record = {"model": self.model, "status": status, "cache_key": cache_key, "request_id": getattr(response, "_request_id", None), "prompt_tokens": getattr(usage, "prompt_tokens", None), "completion_tokens": getattr(usage, "completion_tokens", None)}
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with (self.cache_dir / "vision_audit.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _record_failure(self, failure_path: Path, error: Exception | None) -> None:
        """持久化可复用的脱敏失败状态，不保存响应或异常正文。"""
        failure_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"status": "failed", "failure_type": type(error).__name__ if error else "UnknownError", "model": self.model, "prompt_version": PROMPT_VERSION}
        failure_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
