"""多模态知识库 inspect、ingest、evaluate、publish 与 rollback 编排。"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .assets import AssetStore
from .contracts import IngestionIssue, IssueSeverity, KnowledgeUnit, OutboundImageRecord, UnitStatus, canonical_json, render_retrieval_text, sha256_bytes, stable_id
from .index import ActiveIndexRegistry, StagedIndex, embedding_fingerprint, file_sha256
from .parsers import IMAGE_SUFFIXES, PAGE_QUALITY_GATE_VERSION, PAGE_QUALITY_MIN_TEXT_COVERAGE, TEXT_SPLIT, ParsedDocument, ParsedItem, decide_page_route, inspect_source, parse_document_page
from .remote_policy import RemoteSamplePolicy
from .vision import PROMPT_VERSION, REQUIRED_MODEL, VisionAnalyzer

LOCAL_PARSE_CHECKPOINT_SCHEMA = "local-parse-v2"

class MultimodalKnowledgeBaseMaintenance:
    """为 CLI 与未来 HTTP adapter 提供单一维护入口。"""

    def __init__(self, *, asset_root: Path | None = None, index_root: Path | None = None, active_config: Path | None = None) -> None:
        """使用隔离默认目录，绝不写入现有 db 或 PubMedQA collection。"""
        base = Path(__file__).resolve().parents[1]
        self.asset_root = asset_root or Path(os.getenv("MULTIMODAL_ASSET_DIR", base / "multimodal_assets"))
        self.index_root = index_root or Path(os.getenv("MULTIMODAL_INDEX_ROOT", base / "multimodal_indexes"))
        self.registry = ActiveIndexRegistry(active_config or Path(os.getenv("MULTIMODAL_ACTIVE_INDEX_CONFIG", base / "multimodal_runtime" / "active_index.json")))
        self.collection_prefix = os.getenv("MULTIMODAL_COLLECTION_PREFIX", "causal_multimodal")
        self.remote_policy = RemoteSamplePolicy()

    def inspect(self, sources: list[str]) -> dict[str, Any]:
        """生成确定性来源 manifest，不调用远程服务且不写 Chroma。"""
        entries, issues = self._scan(sources)
        return {"status": "inspected", "manifest": self._manifest(entries), "configuration": self._configuration_status(), "issues": [issue.model_dump(mode="json") for issue in issues]}

    def prepare_outbound_manifest(self, sources: list[str], output_path: str | Path, *, max_images: int | None = None, max_pages: int | None = None) -> dict[str, Any]:
        """仅本地解析批准来源并生成供人工审阅的远程图片清单。"""
        if max_images is not None and max_images < 1:
            raise ValueError("--max-images must be positive when preparing an outbound manifest")
        if max_pages is not None and max_pages < 1:
            raise ValueError("--max-pages must be positive when preparing an outbound manifest")
        entries, issues = self._scan(sources)
        if any(issue.severity is IssueSeverity.ERROR for issue in issues):
            raise ValueError("source scan contains blocking issues")
        analyzer = VisionAnalyzer(self.asset_root / "vision_cache", allow_remote_data=False, remote_policy_sha256=self.remote_policy.policy_sha256, model=REQUIRED_MODEL)
        records: list[OutboundImageRecord] = []
        prepared_pages = 0
        parser_name = os.getenv("MULTIMODAL_PARSER", "docling")
        for entry in entries:
            path = Path(entry["path"])
            document_id = stable_id("doc", {"path": entry["relative_path"], "content_hash": entry["content_hash"]})
            for page_number in range(1, self._source_page_count(path) + 1):
                if not self._remote_resource_allowed(path, page_number):
                    continue
                if max_pages is not None and prepared_pages >= max_pages:
                    break
                parsed = parse_document_page(path, parser_name, page_number)
                prepared_pages += 1
                issues.extend(parsed.issues)
                if any(issue.severity is IssueSeverity.ERROR for issue in parsed.issues):
                    raise ValueError(f"local parsing failed before outbound manifest preparation: {path.name} page {page_number}")
                decision = decide_page_route(path, page_number, parsed)
                if decision.route == "blocked":
                    raise ValueError(f"local page quality gate blocked outbound manifest preparation: {path.name} page {page_number}")
                page_items, _ = self._prepare_page_items(self._routed_page_items(parsed.items, decision.route))
                for item_index, item in enumerate(page_items, 1):
                    if not item.asset_bytes:
                        continue
                    prepared = analyzer.prepare_image(item.asset_bytes)
                    records.append(OutboundImageRecord(
                        source_relative_path=entry["relative_path"], source_sha256=entry["content_hash"],
                        document_id=document_id, page_number=item.page_number or page_number,
                        image_index=max(1, (page_number * 10000 + item_index) % 10000),
                        original_sha256=prepared.original_sha256, normalized_sha256=prepared.normalized_sha256,
                        media_type=prepared.media_type, width=prepared.width, height=prepared.height,
                        original_bytes=prepared.original_bytes, normalized_bytes=len(prepared.payload),
                        transformation=prepared.transformation,
                        context_sha256=sha256_bytes(self._same_page_context(item, page_items).encode("utf-8")),
                        provider="wcode", model=analyzer.model, prompt_version=PROMPT_VERSION,
                        remote_policy_sha256=self.remote_policy.policy_sha256,
                        route=decision.route,
                        quality_gate_version=decision.quality_gate_version,
                        route_reason=decision.reason,
                        quality_summary=decision.input_summary,
                    ))
                    if max_images is not None and len(records) >= max_images:
                        break
                if max_images is not None and len(records) >= max_images:
                    break
            if (max_images is not None and len(records) >= max_images) or (max_pages is not None and prepared_pages >= max_pages):
                break
        output = Path(output_path)
        self._write_outbound_manifest(output, records)
        return {
            "status": "prepared",
            "outbound_manifest": str(output),
            "outbound_manifest_sha256": sha256_bytes(output.read_bytes()),
            "outbound_image_count": len(records),
            "prepared_page_count": prepared_pages,
            "issues": [issue.model_dump(mode="json") for issue in issues],
        }

    def ingest(self, sources: list[str], *, allow_remote_data: bool = False, max_images: int | None = None, retry_failed: bool = False, retry_generation: int = 0, retry_from_index_version: str | None = None, reuse_local_from_index_version: str | None = None, outbound_manifest: str | Path | None = None) -> dict[str, Any]:
        """逐页解析、原子保存 checkpoint，并分批写入不可变暂存索引。"""
        if retry_from_index_version is not None and reuse_local_from_index_version is not None:
            raise ValueError("--reuse-local-checkpoints-from cannot be combined with --retry-from-index-version")
        entries, issues = self._scan(sources)
        outbound_records = self._frozen_outbound_records(outbound_manifest, entries) if allow_remote_data else []
        if allow_remote_data and max_images is not None and max_images < len(outbound_records):
            raise ValueError("--max-images cannot be smaller than the frozen outbound manifest")
        manifest = self._manifest(entries, allow_remote_data=allow_remote_data, max_images=max_images, retry_failed=retry_failed, retry_generation=retry_generation, outbound_records=outbound_records)
        version = self._index_version(manifest)
        version_dir = self.index_root / version
        retry_source = self._retry_source_directory(retry_from_index_version, manifest, retry_failed)
        local_reuse_source = self._local_reuse_source_directory(reuse_local_from_index_version, manifest, retry_source)
        if version_dir.exists() and not self._is_resumable_build(version_dir):
            raise ValueError("same source and configuration already has a staged version")
        version_dir.mkdir(parents=True, exist_ok=True)
        (version_dir / "page_checkpoints").mkdir(exist_ok=True)
        (version_dir / "local_parse_checkpoints").mkdir(exist_ok=True)
        self._write_build_state(version_dir, {"status": "building", "unit_count": 0, "attempted_pages": 0})
        embedding = embedding_fingerprint()
        store = AssetStore(self.asset_root)
        analyzer = VisionAnalyzer(self.asset_root / "vision_cache", allow_remote_data=allow_remote_data, max_images=max_images, retry_failed=retry_failed, remote_policy_sha256=self.remote_policy.policy_sha256)
        quality_keys = ("eligible_images", "enriched_images", "vision_failed_images", "skipped_images", "low_value_images_skipped", "filtered_short_text_units")
        quality = {key: 0 for key in quality_keys}
        documents: list[dict[str, Any]] = []
        outbound_manifest_path = version_dir / "outbound_manifest.json"
        self._write_outbound_manifest(outbound_manifest_path, outbound_records)
        parser_name = os.getenv("MULTIMODAL_PARSER", "docling")
        unit_count = 0
        attempted_pages = 0
        try:
            for entry in entries:
                path = Path(entry["path"])
                document_id = stable_id("doc", {"path": entry["relative_path"], "content_hash": entry["content_hash"]})
                source_asset_uri = store.put(document_id, path.name, path.read_bytes(), category="source")
                parser_artifacts: list[dict[str, str]] = []
                document_units = 0
                expected_pages = self._source_page_count(path)
                parsed_name = parser_name
                parsed_version = "unknown"
                for page_number in range(1, expected_pages + 1):
                    checkpoint = self._read_page_checkpoint(version_dir, document_id, page_number)
                    if checkpoint is None and retry_source is not None:
                        checkpoint = self._reusable_retry_checkpoint(retry_source, document_id, page_number)
                        if checkpoint is not None:
                            self._write_page_checkpoint(
                                version_dir,
                                document_id,
                                page_number,
                                checkpoint,
                                self._read_page_units(retry_source, document_id, page_number),
                            )
                    if checkpoint is None:
                        local_checkpoint = self._reusable_local_parse_checkpoint(version_dir, document_id, page_number, entry, expected_pages, store)
                        if local_checkpoint is None and local_reuse_source is not None:
                            local_checkpoint = self._reusable_local_parse_checkpoint(local_reuse_source, document_id, page_number, entry, expected_pages, store)
                            if local_checkpoint is not None:
                                self._write_local_parse_checkpoint(version_dir, document_id, page_number, local_checkpoint)
                        if local_checkpoint is not None:
                            parsed = self._parsed_document_from_local_checkpoint(local_checkpoint, store)
                        else:
                            parsed = parse_document_page(path, parser_name, page_number)
                            local_checkpoint = self._build_local_parse_checkpoint(path, document_id, page_number, parsed, entry, expected_pages, store)
                            self._write_local_parse_checkpoint(version_dir, document_id, page_number, local_checkpoint)
                        page_quality = {key: 0 for key in quality_keys}
                        page_issues = list(parsed.issues)
                        page_artifacts = [
                            {"name": name, "asset_uri": store.put(document_id, name, payload, category="parsed"), "content_hash": sha256_bytes(payload)}
                            for name, payload in parsed.raw_artifacts
                        ]
                        decision = decide_page_route(path, page_number, parsed)
                        if decision.route == "blocked":
                            page_issues.append(IngestionIssue(
                                code="page_quality_gate_failed",
                                message=f"第 {page_number} 页无法安全路由：{decision.reason}",
                                severity=IssueSeverity.ERROR,
                                blocking=True,
                                source_path=str(path),
                            ))
                        page_items, filtered = self._prepare_page_items(self._routed_page_items(parsed.items, decision.route))
                        page_quality["filtered_short_text_units"] = filtered
                        page_units: list[KnowledgeUnit] = []
                        for item_index, item in enumerate(page_items, 1):
                            unit = self._build_unit(
                                item, path, document_id, page_number * 10000 + item_index,
                                parsed.parser_name, parsed.parser_version, embedding, store, analyzer,
                                page_quality, page_issues, allow_remote_data,
                                context=self._same_page_context(item, page_items),
                                source_relative_path=entry["relative_path"],
                                source_sha256=entry["content_hash"],
                                outbound_records=outbound_records,
                            )
                            if unit is not None:
                                page_units.append(unit)
                        checkpoint = {"document_id": document_id, "page_number": page_number, "parser_name": parsed.parser_name, "parser_version": parsed.parser_version, "parser_artifacts": page_artifacts, "route": decision.route, "quality_gate_version": decision.quality_gate_version, "route_reason": decision.reason, "quality_input_summary": decision.input_summary, "issues": [issue.model_dump(mode="json") for issue in page_issues], "quality": page_quality, "unit_count": len(page_units)}
                        self._write_page_checkpoint(version_dir, document_id, page_number, checkpoint, page_units)
                    attempted_pages += 1
                    parsed_name, parsed_version = checkpoint["parser_name"], checkpoint["parser_version"]
                    parser_artifacts.extend(checkpoint["parser_artifacts"])
                    page_issues = [IngestionIssue.model_validate(issue) for issue in checkpoint["issues"]]
                    issues.extend(page_issues)
                    for key in quality_keys:
                        quality[key] += int(checkpoint["quality"].get(key, 0))
                    page_units = int(checkpoint["unit_count"])
                    unit_count += page_units
                    document_units += page_units
                    self._write_build_state(version_dir, {"status": "building", "unit_count": unit_count, "attempted_pages": attempted_pages})
                page_routes = []
                for page_number in range(1, expected_pages + 1):
                    page_checkpoint = self._read_page_checkpoint(version_dir, document_id, page_number) or {}
                    page_routes.append({key: page_checkpoint.get(key) for key in ("page_number", "route", "quality_gate_version", "route_reason", "quality_input_summary")})
                documents.append({"document_id": document_id, "relative_path": entry["relative_path"], "content_hash": entry["content_hash"], "source_asset_uri": source_asset_uri, "parser_artifact_uris": [artifact["asset_uri"] for artifact in parser_artifacts], "parser_artifacts": parser_artifacts, "parser_name": parsed_name, "parser_version": parsed_version, "expected_page_count": expected_pages, "attempted_page_count": expected_pages, "unit_count": document_units, "page_routes": page_routes})
            self._materialize_units(version_dir, documents)
            (version_dir / "issues.jsonl").write_text("".join(issue.model_dump_json() + "\n" for issue in issues), encoding="utf-8")
            self._write_outbound_manifest(outbound_manifest_path, outbound_records)
            manifest.update({"index_version": version, "embedding": embedding, "unit_count": unit_count, "issues_count": len(issues), "quality_policy": self._quality_policy(), "quality_observations": quality, "documents": documents, "outbound_manifest_sha256": sha256_bytes(outbound_manifest_path.read_bytes()), "outbound_image_count": len(outbound_records)})
            (version_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            vector_count = self._build_staged_vectors(version_dir, version, unit_count)
            self._write_build_state(version_dir, {"status": "staged_complete", "unit_count": unit_count, "vector_count": vector_count, "attempted_pages": attempted_pages})
            return {"status": "staged", "index_version": version, "unit_count": unit_count, "vector_count": vector_count, "issues": [issue.model_dump(mode="json") for issue in issues]}
        except Exception as exc:
            (version_dir / "issues.jsonl").write_text("".join(issue.model_dump_json() + "\n" for issue in issues), encoding="utf-8")
            self._write_build_state(version_dir, {"status": "failed", "unit_count": unit_count, "attempted_pages": attempted_pages, "error_type": type(exc).__name__})
            raise

    def run(self, sources: list[str], *, allow_remote_data: bool = False, max_images: int | None = None, retry_failed: bool = False, retry_generation: int = 0, retry_from_index_version: str | None = None, reuse_local_from_index_version: str | None = None, outbound_manifest: str | Path | None = None, timeout_seconds: int | None = None, cancel_check: Callable[[], bool] | None = None, publish_on_pass: bool = False) -> dict[str, Any]:
        """以版本锁执行 ingest 和评测；仅在显式授权时发布。"""
        started = time.monotonic()
        entries, _ = self._scan(sources)
        outbound_records = self._frozen_outbound_records(outbound_manifest, entries) if allow_remote_data else []
        if allow_remote_data and max_images is not None and max_images < len(outbound_records):
            raise ValueError("--max-images cannot be smaller than the frozen outbound manifest")
        manifest = self._manifest(entries, allow_remote_data=allow_remote_data, max_images=max_images, retry_failed=retry_failed, retry_generation=retry_generation, outbound_records=outbound_records)
        version = self._index_version(manifest)
        lock = self.index_root / ".locks" / version
        try:
            lock.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            return {"status": "already_running", "index_version": version, "published": False}
        try:
            self._check_run_control(started, timeout_seconds, cancel_check)
            version_exists = (self.index_root / version).is_dir()
            reused = self._is_reusable_staged_version(version)
            resumable = self._is_resumable_build(self.index_root / version)
            if version_exists and not reused and not resumable:
                return {"status": "incomplete_staged", "index_version": version, "published": False}
            staged = {"status": "reused_staged", "index_version": version} if reused else self.ingest(sources, allow_remote_data=allow_remote_data, max_images=max_images, retry_failed=retry_failed, retry_generation=retry_generation, retry_from_index_version=retry_from_index_version, reuse_local_from_index_version=reuse_local_from_index_version, outbound_manifest=outbound_manifest)
            self._check_run_control(started, timeout_seconds, cancel_check)
            evaluation = self.evaluate(version)
            self._check_run_control(started, timeout_seconds, cancel_check)
            if not evaluation["passed"]:
                return {"status": "gate_failed", "index_version": version, "staged": staged, "evaluation": evaluation, "published": False}
            if not publish_on_pass:
                return {"status": "ready_to_publish", "index_version": version, "staged": staged, "evaluation": evaluation, "published": False}
            published = self.publish(version)
            return {"status": "published", "index_version": version, "staged": staged, "evaluation": evaluation, "publish": published, "published": True}
        except TimeoutError as exc:
            return {"status": "timed_out", "index_version": version, "published": False, "error": str(exc)}
        except InterruptedError as exc:
            return {"status": "cancelled", "index_version": version, "published": False, "error": str(exc)}
        finally:
            shutil.rmtree(lock, ignore_errors=True)

    def _check_run_control(self, started: float, timeout_seconds: int | None, cancel_check: Callable[[], bool] | None) -> None:
        """只在阶段边界检查取消和总超时，确保失败时不切换 active pointer。"""
        if cancel_check and cancel_check():
            raise InterruptedError("multimodal maintenance run was cancelled")
        if timeout_seconds is not None and time.monotonic() - started > timeout_seconds:
            raise TimeoutError("multimodal maintenance run timed out")

    def evaluate(self, index_version: str) -> dict[str, Any]:
        """执行完整性门禁，并对正式资料执行冻结人工 gold 检索门禁。"""
        directory = self._version_dir(index_version)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        units = [KnowledgeUnit.model_validate_json(line) for line in (directory / "units.jsonl").read_text(encoding="utf-8").splitlines() if line]
        issues = [IngestionIssue.model_validate_json(line) for line in (directory / "issues.jsonl").read_text(encoding="utf-8").splitlines() if line]
        collection = f"{self.collection_prefix}_{index_version}"
        failures: list[str] = []
        if not units: failures.append("no_valid_units")
        if StagedIndex(directory, collection).count() != len(units): failures.append("vector_count_mismatch")
        if any(issue.severity is IssueSeverity.ERROR for issue in issues): failures.append("required_source_failed")
        if any(issue.blocking for issue in issues): failures.append("blocking_issue")
        store = AssetStore(self.asset_root)
        if any(unit.asset_uri and not store.exists(unit.asset_uri) for unit in units): failures.append("missing_asset")
        failures.extend(self._audit_manifest_chain(manifest, units, store))
        if manifest.get("schema_version", 0) >= 4:
            failures.extend(self._audit_outbound_manifest(directory, manifest))
        if any(not unit.retrieval_text.strip() for unit in units): failures.append("empty_retrieval_text")
        if manifest.get("embedding") != embedding_fingerprint(): failures.append("embedding_fingerprint_mismatch")
        if "build_configuration" not in manifest:
            failures.append("legacy_manifest_missing_build_configuration")
        if manifest.get("schema_version", 0) >= 3:
            if not self._is_reusable_staged_version(index_version):
                failures.append("staged_build_incomplete")
            documents = manifest.get("documents", [])
            if any(document.get("expected_page_count") != document.get("attempted_page_count") for document in documents):
                failures.append("source_page_count_mismatch")
            if any(
                document.get("parser_name") == "docling"
                and len(document.get("parser_artifacts", [])) != document.get("expected_page_count")
                for document in documents
            ):
                failures.append("parser_page_artifact_count_mismatch")
        quality = self._quality_evaluation(manifest, directory)
        if not quality["passed"]:
            failures.append("quality_gate_failed")
        production_evaluation = None
        from .production import evaluate_staged_index, is_production_manifest, validate_production_manifest
        if is_production_manifest(manifest):
            failures.extend(validate_production_manifest(manifest))
            if not failures:
                production_evaluation = evaluate_staged_index(directory, collection)
                if not production_evaluation["gate"]["passed"]:
                    failures.append("production_retrieval_gate_failed")
        result = {"index_version": index_version, "passed": not failures, "failures": failures, "manifest_sha256": file_sha256(directory / "manifest.json"), "quality": quality, "production_evaluation": production_evaluation, "evaluated_at": datetime.now(timezone.utc).isoformat()}
        (directory / "evaluation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def publish(self, index_version: str) -> dict[str, Any]:
        """仅在通过门禁后原子切换多模态 active pointer。"""
        directory = self._version_dir(index_version)
        evaluation_path = directory / "evaluation.json"
        if not evaluation_path.exists(): raise ValueError("index must be evaluated before publish")
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
        if not evaluation.get("passed"): raise ValueError("blocking evaluation failures prevent publication")
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("schema_version", 0) >= 3 and not self._is_reusable_staged_version(index_version):
            raise ValueError("staged build is incomplete and cannot be published")
        from .production import is_production_manifest
        if is_production_manifest(manifest):
            production_evaluation = directory / "production_evaluation.json"
            if not production_evaluation.exists() or not json.loads(production_evaluation.read_text(encoding="utf-8")).get("gate", {}).get("passed"):
                raise ValueError("production retrieval evaluation must pass before publication")
        if "build_configuration" not in manifest or "quality_policy" not in manifest or "quality_observations" not in manifest:
            raise ValueError("legacy manifest is not eligible for publication under P0 gates")
        self.registry.publish(index_root=self.index_root, index_version=index_version, collection_name=f"{self.collection_prefix}_{index_version}", manifest_sha256=file_sha256(directory / "manifest.json"), embedding=manifest["embedding"])
        return {"status": "published", "index_version": index_version}

    def rollback(self, index_version: str) -> dict[str, Any]:
        """只允许回滚至已通过评测的历史多模态版本。"""
        return self.publish(index_version) | {"status": "rolled_back"}

    def status(self, index_version: str | None = None) -> dict[str, Any]:
        """返回 active pointer 或一个版本的可审计状态。"""
        if index_version is None: return {"active": self.registry.read()}
        directory = self._version_dir(index_version)
        return {"manifest": json.loads((directory / "manifest.json").read_text(encoding="utf-8")), "evaluation": json.loads((directory / "evaluation.json").read_text(encoding="utf-8")) if (directory / "evaluation.json").exists() else None}

    def _scan(self, sources: list[str]) -> tuple[list[dict[str, str]], list[IngestionIssue]]:
        """扫描文件或目录并以相对输入名和内容哈希产生稳定条目。"""
        entries: list[dict[str, str]] = []; issues: list[IngestionIssue] = []
        for raw in sources:
            path = Path(raw)
            paths = sorted(item for item in path.rglob("*") if item.is_file()) if path.is_dir() else [path]
            for item in paths:
                issue = inspect_source(item)
                if issue: issues.append(issue); continue
                relative_path = (Path(path.name) / item.relative_to(path)).as_posix() if path.is_dir() else item.name
                entries.append({"path": str(item.resolve()), "relative_path": relative_path, "content_hash": sha256_bytes(item.read_bytes())})
        return sorted(entries, key=lambda item: (item["relative_path"].casefold(), item["content_hash"])), issues

    def _manifest(self, entries: list[dict[str, str]], *, allow_remote_data: bool = False, max_images: int | None = None, retry_failed: bool = False, retry_generation: int = 0, outbound_records: list[OutboundImageRecord] | None = None) -> dict[str, Any]:
        """构造不包含宿主绝对路径的来源清单。"""
        public = [{"relative_path": entry["relative_path"], "content_hash": entry["content_hash"]} for entry in entries]
        return {
            "schema_version": 4,
            "sources": public,
            "parser": os.getenv("MULTIMODAL_PARSER", "docling"),
            "build_configuration": {
                "ingestion_schema": "streaming-page-v1",
                "embedding": embedding_fingerprint(),
                "pdf_parser": {"page_range_mode": "single_page", "process_isolation": "spawn_per_page", "page_timeout_seconds": int(os.getenv("MULTIMODAL_DOCLING_PAGE_TIMEOUT_SECONDS", "900")), "do_ocr": False},
                "text_split": dict(TEXT_SPLIT),
                "page_quality_gate": {"version": PAGE_QUALITY_GATE_VERSION, "min_text_coverage": PAGE_QUALITY_MIN_TEXT_COVERAGE, "native_text_min_chars": 80},
                "remote_policy_hash": self.remote_policy.policy_sha256,
                "vision": {"enabled": allow_remote_data, "local_ocr_enabled": False, "model": os.getenv("VISION_MODEL", REQUIRED_MODEL), "prompt_version": PROMPT_VERSION, "max_images": max_images, "max_retries": int(os.getenv("VISION_MAX_RETRIES", "2")), "max_pixels": int(os.getenv("VISION_MAX_PIXELS", "16000000")), "max_image_bytes": int(os.getenv("VISION_MAX_IMAGE_BYTES", str(10 * 1024 * 1024))), "retry_failed": retry_failed, "retry_generation": retry_generation},
            },
            "outbound_manifest_sha256": sha256_bytes(self._outbound_manifest_payload(outbound_records or [])),
            "outbound_image_count": len(outbound_records or []),
        }

    def _is_reusable_staged_version(self, index_version: str) -> bool:
        """仅接受带完整状态、必要产物且单位/向量计数一致的暂存版本。"""
        directory = self.index_root / index_version
        required = ("manifest.json", "units.jsonl", "issues.jsonl", "build_state.json")
        if not directory.is_dir() or any(not (directory / name).is_file() for name in required):
            return False
        try:
            state = json.loads((directory / "build_state.json").read_text(encoding="utf-8"))
            unit_count = int(state.get("unit_count", -1))
            vector_count = int(state.get("vector_count", -1))
            persisted_units = sum(1 for line in (directory / "units.jsonl").read_text(encoding="utf-8").splitlines() if line)
            if state.get("status") != "staged_complete" or unit_count < 0 or unit_count != vector_count or persisted_units != unit_count:
                return False
            if vector_count == 0:
                return True
            if not (directory / "chroma").is_dir():
                return False
            return StagedIndex(directory, f"{self.collection_prefix}_{index_version}").count() == vector_count
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return False

    def _write_build_state(self, directory: Path, state: dict[str, Any]) -> None:
        """原子写入当前构建阶段，供崩溃诊断和复用判定使用。"""
        temporary = directory / "build_state.tmp"
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(directory / "build_state.json")

    def _is_resumable_build(self, directory: Path) -> bool:
        """判断目录是否为本 schema 可安全续跑的未完成构建。"""
        state_path = directory / "build_state.json"
        if not state_path.is_file():
            return False
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            return state.get("status") in {"building", "failed"} and (directory / "page_checkpoints").is_dir()
        except (OSError, json.JSONDecodeError):
            return False

    def _page_checkpoint_paths(self, directory: Path, document_id: str, page_number: int) -> tuple[Path, Path]:
        """返回页级元数据和标准化单元的隔离路径。"""
        page_root = directory / "page_checkpoints" / document_id
        return page_root / f"page_{page_number:04d}.json", page_root / f"page_{page_number:04d}.units.jsonl"

    def _read_page_checkpoint(self, directory: Path, document_id: str, page_number: int) -> dict[str, Any] | None:
        """只读取元数据与单元文件均存在且计数一致的页 checkpoint。"""
        metadata_path, units_path = self._page_checkpoint_paths(directory, document_id, page_number)
        if not metadata_path.is_file() or not units_path.is_file():
            return None
        try:
            checkpoint = json.loads(metadata_path.read_text(encoding="utf-8"))
            unit_count = sum(1 for line in units_path.read_text(encoding="utf-8").splitlines() if line)
            return checkpoint if checkpoint.get("unit_count") == unit_count else None
        except (OSError, json.JSONDecodeError):
            return None

    def _read_page_units(self, directory: Path, document_id: str, page_number: int) -> list[KnowledgeUnit]:
        """Read one complete page checkpoint's normalized units."""
        _, units_path = self._page_checkpoint_paths(directory, document_id, page_number)
        return [KnowledgeUnit.model_validate_json(line) for line in units_path.read_text(encoding="utf-8").splitlines() if line]

    def _reusable_retry_checkpoint(self, directory: Path, document_id: str, page_number: int) -> dict[str, Any] | None:
        """Reuse only a source page that has no blocking parsing issue."""
        checkpoint = self._read_page_checkpoint(directory, document_id, page_number)
        if checkpoint is None:
            return None
        issues = [IngestionIssue.model_validate(issue) for issue in checkpoint.get("issues", [])]
        return None if any(issue.severity is IssueSeverity.ERROR for issue in issues) else checkpoint

    def _local_parse_checkpoint_path(self, directory: Path, document_id: str, page_number: int) -> Path:
        """返回本地解析 checkpoint 的隔离路径。"""
        return directory / "local_parse_checkpoints" / document_id / f"page_{page_number:04d}.json"

    def _read_local_parse_checkpoint(self, directory: Path, document_id: str, page_number: int) -> dict[str, Any] | None:
        """读取本地解析 checkpoint；不存在或损坏时返回 None。"""
        path = self._local_parse_checkpoint_path(directory, document_id, page_number)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_local_parse_checkpoint(self, directory: Path, document_id: str, page_number: int, checkpoint: dict[str, Any]) -> None:
        """原子写入本地解析 checkpoint，绑定 source/Docling/OCR 契约而非视觉策略。"""
        path = self._local_parse_checkpoint_path(directory, document_id, page_number)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def _build_local_parse_checkpoint(self, path: Path, document_id: str, page_number: int, parsed: ParsedDocument, entry: dict[str, str], page_count: int, store: AssetStore) -> dict[str, Any]:
        """把 ParsedDocument 序列化为不含 asset_bytes 的可复用本地解析结果。"""
        serializable_items: list[dict[str, Any]] = []
        for item in parsed.items:
            asset_uri = None
            asset_content_hash = None
            if item.asset_bytes:
                asset_uri = store.put(document_id, item.asset_name or f"asset_{page_number}", item.asset_bytes)
                asset_content_hash = sha256_bytes(item.asset_bytes)
            serializable_items.append({"modality": item.modality, "content_kind": item.content_kind, "raw_text": item.raw_text, "page_number": item.page_number, "bbox": item.bbox, "asset_uri": asset_uri, "asset_content_hash": asset_content_hash, "asset_name": item.asset_name, "parent_key": item.parent_key})
        return {
            "schema_version": LOCAL_PARSE_CHECKPOINT_SCHEMA,
            "document_id": document_id,
            "page_number": page_number,
            "parser_name": parsed.parser_name,
            "parser_version": parsed.parser_version,
            "parser_artifacts": [{"name": name, "asset_uri": store.put(document_id, name, payload, category="parsed"), "content_hash": sha256_bytes(payload)} for name, payload in parsed.raw_artifacts],
            "issues": [issue.model_dump(mode="json") for issue in parsed.issues],
            "items": serializable_items,
            "contract": {
                "source_content_hash": entry["content_hash"],
                "page_count": page_count,
                "parser": {"name": parsed.parser_name, "version": parsed.parser_version},
                "docling_config": {"page_timeout_seconds": int(os.getenv("MULTIMODAL_DOCLING_PAGE_TIMEOUT_SECONDS", "900")), "generate_picture_images": True, "generate_page_images": True, "do_ocr": False},
                "image_text_strategy": "remote-vision-v2",
            },
        }

    def _parsed_document_from_local_checkpoint(self, checkpoint: dict[str, Any], store: AssetStore) -> ParsedDocument:
        """从已校验的本地解析 checkpoint 重建 ParsedDocument。"""
        items: list[ParsedItem] = []
        for item_dict in checkpoint.get("items", []):
            asset_uri = item_dict.get("asset_uri")
            asset_bytes = store.read(asset_uri) if asset_uri else None
            items.append(ParsedItem(modality=item_dict["modality"], content_kind=item_dict["content_kind"], raw_text=item_dict.get("raw_text", ""), page_number=item_dict.get("page_number"), bbox=item_dict.get("bbox"), asset_bytes=asset_bytes, asset_name=item_dict.get("asset_name"), parent_key=item_dict.get("parent_key")))
        raw_artifacts: list[tuple[str, bytes]] = []
        for artifact in checkpoint.get("parser_artifacts", []):
            asset_uri = artifact.get("asset_uri")
            if asset_uri:
                raw_artifacts.append((artifact["name"], store.read(asset_uri)))
        issues = [IngestionIssue.model_validate(issue) for issue in checkpoint.get("issues", [])]
        return ParsedDocument(parser_name=checkpoint.get("parser_name", "docling"), parser_version=checkpoint.get("parser_version", "unknown"), items=tuple(items), issues=tuple(issues), raw_artifacts=tuple(raw_artifacts))

    def _reusable_local_parse_checkpoint(self, directory: Path, document_id: str, page_number: int, entry: dict[str, str], page_count: int, store: AssetStore) -> dict[str, Any] | None:
        """校验契约后返回可复用的本地解析 checkpoint；不一致则返回 None 触发重解析。"""
        checkpoint = self._read_local_parse_checkpoint(directory, document_id, page_number)
        if checkpoint is None:
            return None
        if checkpoint.get("schema_version") != LOCAL_PARSE_CHECKPOINT_SCHEMA:
            return None
        if checkpoint.get("document_id") != document_id or checkpoint.get("page_number") != page_number:
            return None
        contract = checkpoint.get("contract", {})
        if contract.get("source_content_hash") != entry["content_hash"]:
            return None
        if contract.get("page_count") != page_count:
            return None
        expected_docling = {"page_timeout_seconds": int(os.getenv("MULTIMODAL_DOCLING_PAGE_TIMEOUT_SECONDS", "900")), "generate_picture_images": True, "generate_page_images": True, "do_ocr": False}
        if contract.get("docling_config") != expected_docling:
            return None
        if contract.get("image_text_strategy") != "remote-vision-v2":
            return None
        if contract.get("parser") != {"name": checkpoint.get("parser_name"), "version": checkpoint.get("parser_version")}:
            return None
        if Path(entry["relative_path"]).suffix.lower() == ".pdf" and contract.get("parser", {}).get("version") != self._docling_version():
            return None
        try:
            for item in checkpoint.get("items", []):
                if not isinstance(item, dict) or not isinstance(item.get("modality"), str) or not isinstance(item.get("content_kind"), str):
                    return None
                asset_uri, asset_hash = item.get("asset_uri"), item.get("asset_content_hash")
                if bool(asset_uri) != bool(asset_hash) or (asset_uri and not self._asset_matches(store, asset_uri, asset_hash)):
                    return None
            for artifact in checkpoint.get("parser_artifacts", []):
                if not isinstance(artifact, dict) or not isinstance(artifact.get("name"), str) or not self._asset_matches(store, artifact.get("asset_uri"), artifact.get("content_hash")):
                    return None
            [IngestionIssue.model_validate(issue) for issue in checkpoint.get("issues", [])]
        except (OSError, TypeError, ValueError):
            return None
        return checkpoint

    @staticmethod
    def _asset_matches(store: AssetStore, asset_uri: object, content_hash: object) -> bool:
        """确认 checkpoint 引用的资源存在且仍是记录时的不可变内容。"""
        return isinstance(asset_uri, str) and isinstance(content_hash, str) and sha256_bytes(store.read(asset_uri)) == content_hash

    @staticmethod
    def _docling_version() -> str:
        """读取当前 Docling 包版本，供 PDF 本地解析 checkpoint 复用校验。"""
        try:
            return importlib.metadata.version("docling")
        except importlib.metadata.PackageNotFoundError:
            return "unknown"

    def _local_reuse_source_directory(self, index_version: str | None, manifest: dict[str, Any], retry_source: Path | None) -> Path | None:
        """校验并返回跨版本本地解析复用源；与 --retry-from-index-version 互斥。"""
        if index_version is None:
            return None
        if retry_source is not None:
            raise ValueError("--reuse-local-checkpoints-from cannot be combined with --retry-from-index-version")
        directory = self._version_dir(index_version)
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file() or not (directory / "local_parse_checkpoints").is_dir():
            return None
        try:
            source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if self._local_parse_contract(source_manifest) != self._local_parse_contract(manifest):
            return None
        return directory

    @staticmethod
    def _local_parse_contract(manifest: dict[str, Any]) -> dict[str, Any]:
        """返回只绑定本地解析（不含视觉策略）的版本契约。"""
        configuration = json.loads(json.dumps(manifest.get("build_configuration", {})))
        configuration.pop("vision", None)
        return {
            "schema_version": manifest.get("schema_version"),
            "sources": manifest.get("sources"),
            "parser": manifest.get("parser"),
            "build_configuration": configuration,
        }

    def _retry_source_directory(self, index_version: str | None, manifest: dict[str, Any], retry_failed: bool) -> Path | None:
        """Validate an immutable checkpoint source before cross-version reuse."""
        if index_version is None:
            return None
        if not retry_failed:
            raise ValueError("retry source requires --retry-failed")
        directory = self.index_root / index_version
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file() or not (directory / "page_checkpoints").is_dir():
            raise ValueError("retry source has no page checkpoints")
        try:
            source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("retry source manifest is unreadable") from exc
        if self._retry_contract(source_manifest) != self._retry_contract(manifest):
            raise ValueError("retry source contract does not match this build")
        return directory

    @staticmethod
    def _retry_contract(manifest: dict[str, Any]) -> dict[str, Any]:
        """Return the content-affecting build contract, excluding retry controls."""
        configuration = json.loads(json.dumps(manifest.get("build_configuration", {})))
        vision = configuration.get("vision")
        if isinstance(vision, dict):
            vision.pop("retry_failed", None)
            vision.pop("retry_generation", None)
        return {
            "schema_version": manifest.get("schema_version"),
            "sources": manifest.get("sources"),
            "parser": manifest.get("parser"),
            "build_configuration": configuration,
        }

    def _write_page_checkpoint(self, directory: Path, document_id: str, page_number: int, checkpoint: dict[str, Any], units: list[KnowledgeUnit]) -> None:
        """先原子写页单元，再提交元数据，使中断后的半页结果不会被复用。"""
        metadata_path, units_path = self._page_checkpoint_paths(directory, document_id, page_number)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        units_temporary = units_path.with_suffix(units_path.suffix + ".tmp")
        units_temporary.write_text("".join(unit.model_dump_json() + "\n" for unit in units), encoding="utf-8")
        units_temporary.replace(units_path)
        metadata_temporary = metadata_path.with_suffix(".tmp")
        metadata_temporary.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
        metadata_temporary.replace(metadata_path)

    def _materialize_units(self, directory: Path, documents: list[dict[str, Any]]) -> None:
        """按文档和页码顺序流式汇总页级单元，生成最终 units.jsonl。"""
        temporary = directory / "units.tmp"
        with temporary.open("w", encoding="utf-8") as output:
            for document in documents:
                for page_number in range(1, int(document["expected_page_count"]) + 1):
                    _, units_path = self._page_checkpoint_paths(directory, document["document_id"], page_number)
                    with units_path.open(encoding="utf-8") as page_units:
                        shutil.copyfileobj(page_units, output)
        temporary.replace(directory / "units.jsonl")

    def _build_staged_vectors(self, directory: Path, version: str, unit_count: int) -> int:
        """在独立 attempt 目录构建 Chroma，成功后再提交为正式目录。"""
        if not unit_count:
            return 0
        attempt_number = 1
        while (directory / f"chroma_attempt_{attempt_number}").exists():
            attempt_number += 1
        attempt_name = f"chroma_attempt_{attempt_number}"
        count = StagedIndex(directory, f"{self.collection_prefix}_{version}", directory_name=attempt_name).write(self._read_units(directory))
        attempt_path = directory / attempt_name
        final_path = directory / "chroma"
        if attempt_path.exists():
            if final_path.exists():
                raise ValueError("completed chroma directory already exists")
            attempt_path.replace(final_path)
        return count

    def _source_page_count(self, path: Path) -> int:
        """返回来源的物理页数；非 PDF 来源按一个逻辑页计。"""
        if path.suffix.lower() != ".pdf":
            return 1
        from pypdf import PdfReader

        return len(PdfReader(path).pages)

    def _read_units(self, directory: Path):
        """从 JSONL 流式回读标准化单元，避免构建向量时全量驻留内存。"""
        with (directory / "units.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    yield KnowledgeUnit.model_validate_json(line)

    def _prepare_page_items(self, items: tuple[ParsedItem, ...]) -> tuple[list[ParsedItem], int]:
        """把短标题并入同页后续正文，避免产生孤立标题向量。"""
        prepared: list[ParsedItem] = []
        pending: list[str] = []
        pending_item: ParsedItem | None = None
        filtered = 0
        for item in items:
            short_text = item.modality == "text" and 0 < len(item.raw_text.strip()) < 30
            heading = item.content_kind in {"title", "section_header", "page_header", "page_footer"}
            if short_text or heading:
                pending.append(item.raw_text.strip())
                pending_item = item
                filtered += 1
                continue
            if pending and item.raw_text:
                item = replace(item, raw_text="\n".join(pending + [item.raw_text]))
                pending.clear()
                pending_item = None
            prepared.append(item)
        if pending and pending_item is not None:
            prepared.append(replace(pending_item, content_kind="paragraph", raw_text="\n".join(pending)))
        return prepared, filtered

    @staticmethod
    def _routed_page_items(items: tuple[ParsedItem, ...], route: str) -> tuple[ParsedItem, ...]:
        """按已冻结页路由保留唯一候选集合，避免整页与逐图重复外发。"""
        if route == "remote_page_fallback":
            return tuple(item for item in items if item.content_kind == "page_render" and item.asset_bytes)
        if route == "remote_pictures":
            return tuple(item for item in items if item.content_kind != "page_render")
        if route == "local_objects":
            return tuple(item for item in items if not item.asset_bytes)
        return ()

    def _build_unit(
        self,
        item: ParsedItem,
        path: Path,
        document_id: str,
        position: int,
        parser_name: str,
        parser_version: str,
        embedding: dict[str, Any],
        store: AssetStore,
        analyzer: VisionAnalyzer,
        quality: dict[str, int],
        issues: list[IngestionIssue],
        allow_remote_data: bool,
        *,
        context: str = "",
        source_relative_path: str | None = None,
        source_sha256: str | None = None,
        outbound_records: list[OutboundImageRecord] | None = None,
    ) -> KnowledgeUnit | None:
        """把解析项转为单索引单元；获准图片必须完整通过远程 OCR+VLM。"""
        analysis = None
        outbound_record = None
        asset_uri = None
        if item.asset_bytes:
            asset_uri = store.put(document_id, item.asset_name or f"asset_{position}", item.asset_bytes)
            if allow_remote_data and self._remote_resource_allowed(path, item.page_number):
                quality["eligible_images"] += 1
                try:
                    if not source_relative_path or not source_sha256 or outbound_records is None:
                        raise ValueError("outbound manifest metadata is incomplete")
                    identity = (document_id, item.page_number or 1, max(1, position % 10000))
                    record = next((candidate for candidate in outbound_records if (candidate.document_id, candidate.page_number, candidate.image_index) == identity), None)
                    if record is None:
                        raise PermissionError("image is absent from the frozen outbound manifest")
                    if record.source_relative_path != source_relative_path or record.source_sha256 != source_sha256:
                        raise PermissionError("outbound manifest source does not match the current source")
                    analysis = analyzer.analyze(item.asset_bytes, record.media_type, context, outbound_record=record)
                    outbound_record = record
                except Exception as exc:
                    quality["vision_failed_images"] += 1
                    issues.append(IngestionIssue(code="remote_image_failed", message=f"远程图片分析失败：{type(exc).__name__}", severity=IssueSeverity.ERROR, blocking=True, source_path=str(path)))
                    return None
            elif allow_remote_data:
                quality["skipped_images"] += 1
                issues.append(IngestionIssue(code="remote_source_not_allowed", message="该图片不在批准的远程外发清单中，禁止生成候选图片单元", severity=IssueSeverity.ERROR, blocking=True, source_path=str(path)))
                return None
            else:
                quality["skipped_images"] += 1
            if analysis:
                quality["enriched_images"] += 1
                has_semantics = any((analysis.summary.strip(), analysis.visible_facts, analysis.entities, analysis.table_markdown.strip(), analysis.formula_latex.strip(), analysis.directed_relations, analysis.uncertain_relations))
                if not analysis.ocr_text.strip() and not has_semantics:
                    quality["low_value_images_skipped"] += 1
                    issues.append(IngestionIssue(code="image_low_information", message=f"第 {item.page_number or 0} 页远程 OCR 与视觉语义均为空", severity=IssueSeverity.WARNING, blocking=False, source_path=str(path)))
                    return None
        if item.modality == "image" and not analysis and not item.raw_text.strip():
            quality["low_value_images_skipped"] += 1
            issues.append(IngestionIssue(code="image_text_missing", message=f"第 {item.page_number or 0} 页图片尚未完成远程 OCR 与视觉分析", severity=IssueSeverity.WARNING, blocking=False, source_path=str(path)))
            return None
        content_kind = analysis.content_kind if analysis else item.content_kind
        text = render_retrieval_text(content_kind=content_kind, title=path.name, analysis=analysis, raw_text=item.raw_text)
        if not text.strip():
            return None
        raw_text = "\n".join(dict.fromkeys(part for part in (item.raw_text.strip(), analysis.ocr_text.strip() if analysis else "") if part))
        if item.modality == "image" and item.asset_bytes:
            content_hash = sha256_bytes(item.asset_bytes)
        else:
            content_hash = sha256_bytes(item.raw_text.encode("utf-8") if item.raw_text else item.asset_bytes or b"")
        policy_fingerprint = getattr(analyzer, "remote_policy_sha256", "")
        if not isinstance(policy_fingerprint, str):
            policy_fingerprint = ""
        unit_id = stable_id("unit", {"document_id": document_id, "position": position, "modality": item.modality, "content_hash": content_hash, "parser": [parser_name, parser_version], "vision": [analyzer.model if analysis else "", PROMPT_VERSION, policy_fingerprint, sha256_bytes(context.encode("utf-8")) if analysis else "", outbound_record.normalized_sha256 if outbound_record else "", outbound_record.transformation if outbound_record else ""]})
        return KnowledgeUnit(unit_id=unit_id, document_id=document_id, parent_id=item.parent_key, modality=item.modality, content_kind=content_kind, page_number=item.page_number, bbox=item.bbox, raw_text=raw_text, retrieval_text=text, asset_uri=asset_uri, content_hash=content_hash, parser_name=parser_name, parser_version=parser_version, vision_model=analyzer.model if analysis else "", vision_prompt_version=PROMPT_VERSION if analysis else "", embedding_provider=embedding["provider"], embedding_model=embedding["model"], status=UnitStatus.ENRICHED if analysis else UnitStatus.COMPLETED)

    @staticmethod
    def _same_page_context(image: ParsedItem, items: list[ParsedItem]) -> str:
        """只拼接同一物理页的 caption、正文、表格和公式，最多 2000 字。"""
        parts = [image.raw_text.strip()] if image.raw_text.strip() else []
        parts.extend(
            item.raw_text.strip()
            for item in items
            if item is not image and item.page_number == image.page_number and item.modality in {"text", "table", "equation"} and item.raw_text.strip()
        )
        return "\n\n".join(dict.fromkeys(parts))[:2000]

    @staticmethod
    def _outbound_manifest_payload(records: list[OutboundImageRecord]) -> bytes:
        """把已验证记录稳定序列化为候选内冻结清单。"""
        return canonical_json({"schema_version": "outbound-v1", "images": [record.model_dump(mode="json") for record in records]}).encode("utf-8")

    def _frozen_outbound_records(self, outbound_manifest: str | Path | None, entries: list[dict[str, str]]) -> list[OutboundImageRecord]:
        """读取并验证外部预冻结清单，拒绝在远程运行中动态扩展授权范围。"""
        if outbound_manifest is None:
            return []
        path = Path(outbound_manifest)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            records = [OutboundImageRecord.model_validate(record) for record in payload.get("images", [])]
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("outbound manifest is unreadable or invalid") from exc
        if payload.get("schema_version") != "outbound-v1":
            raise ValueError("outbound manifest schema is unsupported")
        sources = {(entry["relative_path"], entry["content_hash"]) for entry in entries}
        identities = {(record.document_id, record.page_number, record.image_index) for record in records}
        if len(identities) != len(records):
            raise ValueError("outbound manifest contains duplicate image identities")
        if any((record.source_relative_path, record.source_sha256) not in sources for record in records):
            raise ValueError("outbound manifest does not match the current frozen sources")
        if any(record.remote_policy_sha256 != self.remote_policy.policy_sha256 for record in records):
            raise ValueError("outbound manifest does not match the current remote policy")
        return records

    @staticmethod
    def _write_outbound_manifest(path: Path, records: list[OutboundImageRecord]) -> None:
        """把已批准记录原子复制到候选目录，不保存图片、上下文或密钥。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = MultimodalKnowledgeBaseMaintenance._outbound_manifest_payload(records).decode("utf-8")
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _read_outbound_manifest(path: Path) -> list[OutboundImageRecord]:
        """恢复已原子写入的 outbound 记录，供同一不可变候选断点续跑。"""
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != "outbound-v1" or not isinstance(payload.get("images"), list):
            raise ValueError("invalid outbound manifest")
        return [OutboundImageRecord.model_validate(record) for record in payload["images"]]

    def _index_version(self, manifest: dict[str, Any]) -> str:
        """从完整配置和来源生成不含时钟的可重现版本名。"""
        return "mm_" + hashlib.sha256(json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest()[:20]

    def _quality_policy(self) -> dict[str, Any]:
        """读取显式质量阈值；默认零阈值只记录质量而不把 smoke 当生产标准。"""
        return {
            "min_eligible_images": int(os.getenv("MULTIMODAL_QUALITY_MIN_ELIGIBLE_IMAGES", "0")),
            "min_enriched_images": int(os.getenv("MULTIMODAL_QUALITY_MIN_ENRICHED_IMAGES", "0")),
            "min_enrichment_rate": float(os.getenv("MULTIMODAL_QUALITY_MIN_ENRICHMENT_RATE", "0")),
            "max_vision_failed_images": int(os.getenv("MULTIMODAL_QUALITY_MAX_VISION_FAILED_IMAGES", "0")),
            "max_ocr_probe_failed": int(os.getenv("MULTIMODAL_QUALITY_MAX_OCR_PROBE_FAILED", "0")),
        }

    def _quality_evaluation(self, manifest: dict[str, Any], directory: Path) -> dict[str, Any]:
        """将构建观察与可选 OCR probe 报告按 manifest 中的阈值判定。"""
        missing_contracts = [name for name in ("quality_policy", "quality_observations") if name not in manifest]
        if missing_contracts:
            return {"passed": False, "policy": manifest.get("quality_policy"), "observed": manifest.get("quality_observations"), "enrichment_rate": None, "failures": [f"legacy_manifest_missing_{name}" for name in missing_contracts]}
        policy = manifest["quality_policy"]
        observed = dict(manifest["quality_observations"])
        eligible = int(observed.get("eligible_images", 0)); enriched = int(observed.get("enriched_images", 0))
        probe = {"passed": 0, "failed": 0, "skipped": 0}
        report = directory / "omnidocbench_eval.json"
        if report.exists():
            payload = json.loads(report.read_text(encoding="utf-8"))
            probe = {"passed": int(payload.get("passed_cases", 0)), "failed": int(payload.get("failed_cases", 0)), "skipped": int(payload.get("skipped_cases", 0))}
        observed.update({"eligible_images": eligible, "enriched_images": enriched, "vision_failed_images": int(observed.get("vision_failed_images", 0)), "skipped_images": int(observed.get("skipped_images", 0)), "ocr_probe": probe})
        rate = enriched / eligible if eligible else 0.0
        failures: list[str] = []
        if eligible < int(policy["min_eligible_images"]): failures.append("eligible_images_below_minimum")
        if enriched < int(policy["min_enriched_images"]): failures.append("enriched_images_below_minimum")
        if rate < float(policy["min_enrichment_rate"]): failures.append("enrichment_rate_below_minimum")
        if observed["vision_failed_images"] > int(policy["max_vision_failed_images"]): failures.append("vision_failed_images_above_maximum")
        if probe["failed"] > int(policy["max_ocr_probe_failed"]): failures.append("ocr_probe_failed_above_maximum")
        return {"passed": not failures, "policy": policy, "observed": observed, "enrichment_rate": rate, "failures": failures}

    def _audit_manifest_chain(self, manifest: dict[str, Any], units: list[KnowledgeUnit], store: AssetStore) -> list[str]:
        """校验 source、解析原始产物、文档记录与标准化单元的不可变哈希链。"""
        documents = manifest.get("documents")
        sources = manifest.get("sources")
        if not isinstance(documents, list) or not documents or not isinstance(sources, list):
            return ["missing_document_audit_chain"]
        expected_sources = {(source.get("relative_path"), source.get("content_hash")) for source in sources if isinstance(source, dict)}
        document_ids: set[str] = set()
        for document in documents:
            if not isinstance(document, dict):
                return ["missing_audit_asset"]
            relative_path = document.get("relative_path")
            content_hash = document.get("content_hash")
            document_id = document.get("document_id")
            source_asset_uri = document.get("source_asset_uri")
            if (
                not isinstance(relative_path, str)
                or not isinstance(content_hash, str)
                or not isinstance(document_id, str)
                or document_id != stable_id("doc", {"path": relative_path, "content_hash": content_hash})
                or (relative_path, content_hash) not in expected_sources
                or not isinstance(source_asset_uri, str)
                or not store.exists(source_asset_uri)
                or sha256_bytes(store.read(source_asset_uri)) != content_hash
                or document_id in document_ids
            ):
                return ["missing_audit_asset"]
            document_ids.add(document_id)
            artifacts = document.get("parser_artifacts", [])
            if not isinstance(artifacts, list):
                return ["missing_audit_asset"]
            for artifact in artifacts:
                if not isinstance(artifact, dict) or not isinstance(artifact.get("asset_uri"), str) or not isinstance(artifact.get("content_hash"), str):
                    return ["missing_audit_asset"]
                if not store.exists(artifact["asset_uri"]) or sha256_bytes(store.read(artifact["asset_uri"])) != artifact["content_hash"]:
                    return ["missing_audit_asset"]
        if {(document["relative_path"], document["content_hash"]) for document in documents} != expected_sources:
            return ["missing_audit_asset"]
        if any(unit.document_id not in document_ids for unit in units):
            return ["orphaned_unit_document"]
        for unit in units:
            if unit.asset_uri and not store.exists(unit.asset_uri):
                continue
            if unit.modality == "image" and unit.asset_uri:
                if sha256_bytes(store.read(unit.asset_uri)) != unit.content_hash:
                    return ["unit_asset_hash_mismatch"]
            elif unit.asset_uri and not unit.raw_text and sha256_bytes(store.read(unit.asset_uri)) != unit.content_hash:
                return ["unit_asset_hash_mismatch"]
        return []

    @staticmethod
    def _audit_outbound_manifest(directory: Path, manifest: dict[str, Any]) -> list[str]:
        """校验 outbound 文件哈希、数量、来源和唯一图片身份。"""
        path = directory / "outbound_manifest.json"
        expected_hash = manifest.get("outbound_manifest_sha256")
        if not path.is_file() or not isinstance(expected_hash, str) or sha256_bytes(path.read_bytes()) != expected_hash:
            return ["outbound_manifest_mismatch"]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("images"), list):
                return ["invalid_outbound_manifest"]
            records = [OutboundImageRecord.model_validate(record) for record in payload.get("images", [])]
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return ["invalid_outbound_manifest"]
        policy_hash = manifest.get("build_configuration", {}).get("remote_policy_hash")
        if payload.get("schema_version") != "outbound-v1" or len(records) != manifest.get("outbound_image_count"):
            return ["invalid_outbound_manifest"]
        sources = {(source.get("relative_path"), source.get("content_hash")) for source in manifest.get("sources", []) if isinstance(source, dict)}
        identities = {(record.document_id, record.page_number, record.image_index) for record in records}
        if len(identities) != len(records) or any((record.source_relative_path, record.source_sha256) not in sources for record in records):
            return ["invalid_outbound_manifest"]
        if not isinstance(policy_hash, str) or any(record.remote_policy_sha256 != policy_hash for record in records):
            return ["invalid_outbound_manifest"]
        return []

    def _configuration_status(self) -> dict[str, Any]:
        """返回不含密钥或地址值的阶段零配置检查结果。"""
        parser_status = self._parser_status()
        return {
            "embedding": embedding_fingerprint(),
            "vision_provider": "wcode",
            "vision_model": os.getenv("VISION_MODEL", REQUIRED_MODEL),
            "vision_api_key_configured": bool(os.getenv("VISION_API_KEY")),
            "vision_base_url_configured": bool(os.getenv("VISION_BASE_URL")),
            "allowed_remote_sources": ["Pearl fixed samples", "OmniDocBench fixed subset"],
            "asset_root": str(self.asset_root),
            "index_root": str(self.index_root),
            "parser": parser_status,
        }

    def _parser_status(self) -> dict[str, Any]:
        """报告解析器包与 Docling 布局模型是否同时可用，不执行下载。"""
        try:
            import importlib.util

            docling_installed = importlib.util.find_spec("docling") is not None
        except Exception:
            docling_installed = False
        artifacts_path = Path(os.getenv("MULTIMODAL_DOCLING_ARTIFACTS_DIR", Path.home() / ".cache" / "docling" / "models"))
        legacy_layout_model = Path.home() / ".cache" / "huggingface" / "hub" / "models--docling-project--docling-layout-heron"
        return {
            "preferred": os.getenv("MULTIMODAL_PARSER", "docling"),
            "docling_installed": docling_installed,
            "docling_artifacts_path": str(artifacts_path),
            "docling_layout_model_available": any(artifacts_path.rglob("model.safetensors")) or (legacy_layout_model.exists() and any(legacy_layout_model.rglob("model.safetensors"))),
        }

    def _remote_resource_allowed(self, source_path: Path, page_number: int | None) -> bool:
        """只允许固定 Pearl 页或清单内 OmniDocBench 文件进入远程视觉。"""
        resolved = source_path.resolve()
        base = Path(__file__).resolve().parents[1]
        pearl_root = (base / "source").resolve()
        pearl_names = {"Pearl_2009_Causality-mono(1).pdf", "Pearl_Mackenzie_2018_The_Book_of_Why-mono(1).pdf"}
        if resolved.parent == pearl_root and resolved.name in pearl_names:
            return self.remote_policy.allows_pearl_page(resolved.name, page_number)
        raw_roots = os.getenv("MULTIMODAL_OMNIDOCBENCH_ROOT", "").strip()
        if not raw_roots:
            return False
        try:
            return self.remote_policy.allows_omnidocbench_path(Path(raw_roots), resolved)
        except ValueError:
            return False

    def _version_dir(self, index_version: str) -> Path:
        """校验版本名并解析到隔离暂存根目录。"""
        if not index_version.startswith("mm_") or "/" in index_version or "\\" in index_version: raise ValueError("invalid multimodal index version")
        path = self.index_root / index_version
        if not path.is_dir(): raise FileNotFoundError("multimodal index version does not exist")
        return path
