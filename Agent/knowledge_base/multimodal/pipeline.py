"""多模态知识库 inspect、ingest、evaluate、publish 与 rollback 编排。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .assets import AssetStore
from .contracts import IngestionIssue, IssueSeverity, KnowledgeUnit, UnitStatus, render_retrieval_text, sha256_bytes, stable_id
from .index import ActiveIndexRegistry, StagedIndex, embedding_fingerprint, file_sha256
from .parsers import IMAGE_SUFFIXES, inspect_source, parse_document
from .remote_policy import RemoteSamplePolicy
from .vision import PROMPT_VERSION, REQUIRED_MODEL, VisionAnalyzer


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

    def ingest(self, sources: list[str], *, allow_remote_data: bool = False, max_images: int = 12, retry_failed: bool = False, retry_generation: int = 0) -> dict[str, Any]:
        """解析、增强并写入一个新的不可变暂存索引版本。"""
        entries, issues = self._scan(sources)
        manifest = self._manifest(entries, allow_remote_data=allow_remote_data, max_images=max_images, retry_failed=retry_failed, retry_generation=retry_generation)
        version = self._index_version(manifest)
        version_dir = self.index_root / version
        if version_dir.exists():
            raise ValueError("same source and configuration already has an immutable staged version")
        embedding = embedding_fingerprint()
        store = AssetStore(self.asset_root)
        analyzer = VisionAnalyzer(self.asset_root / "vision_cache", allow_remote_data=allow_remote_data, max_images=max_images, retry_failed=retry_failed)
        quality = {"eligible_images": 0, "enriched_images": 0, "vision_failed_images": 0, "skipped_images": 0, "low_value_images_skipped": 0}
        units: list[KnowledgeUnit] = []
        documents: list[dict[str, Any]] = []
        parser_name = os.getenv("MULTIMODAL_PARSER", "docling")
        for entry in entries:
            path = Path(entry["path"])
            parsed = parse_document(path, parser_name)
            issues.extend(parsed.issues)
            document_id = stable_id("doc", {"path": entry["relative_path"], "content_hash": entry["content_hash"]})
            source_asset_uri = store.put(document_id, path.name, path.read_bytes(), category="source")
            parser_artifacts = [
                {"name": name, "asset_uri": store.put(document_id, name, payload, category="parsed"), "content_hash": sha256_bytes(payload)}
                for name, payload in parsed.raw_artifacts
            ]
            documents.append({"document_id": document_id, "relative_path": entry["relative_path"], "content_hash": entry["content_hash"], "source_asset_uri": source_asset_uri, "parser_artifact_uris": [artifact["asset_uri"] for artifact in parser_artifacts], "parser_artifacts": parser_artifacts, "parser_name": parsed.parser_name, "parser_version": parsed.parser_version})
            for number, item in enumerate(parsed.items, 1):
                analysis = None
                asset_uri = None
                if item.asset_bytes:
                    asset_uri = store.put(document_id, item.asset_name or f"asset_{number}", item.asset_bytes)
                    if allow_remote_data and self._remote_resource_allowed(path, item.page_number):
                        quality["eligible_images"] += 1
                        try:
                            media_type = "image/" + (Path(item.asset_name or "png").suffix.lstrip(".").replace("jpg", "jpeg") or "png")
                            analysis = analyzer.analyze(item.asset_bytes, media_type)
                        except Exception as exc:
                            quality["vision_failed_images"] += 1
                            issues.append(IngestionIssue(code="vision_failed", message=f"视觉增强失败：{type(exc).__name__}", severity=IssueSeverity.WARNING, blocking=False, source_path=str(path)))
                    elif allow_remote_data:
                        quality["skipped_images"] += 1
                        issues.append(IngestionIssue(code="remote_source_not_allowed", message="该资料不在远程视觉数据 allowlist 中，已跳过外发", severity=IssueSeverity.WARNING, blocking=False, source_path=str(path)))
                    else:
                        quality["skipped_images"] += 1
                    if analysis and not analysis.informative:
                        quality["skipped_images"] += 1
                        continue
                    if analysis:
                        quality["enriched_images"] += 1
                text = render_retrieval_text(content_kind=item.content_kind, title=path.name, analysis=analysis, raw_text=item.raw_text)
                if item.modality == "image" and not analysis and not item.raw_text.strip():
                    quality["low_value_images_skipped"] += 1
                    continue
                if not text.strip():
                    continue
                content_hash = sha256_bytes((item.raw_text.encode("utf-8") if item.raw_text else item.asset_bytes or b""))
                unit_id = stable_id("unit", {"document_id": document_id, "position": number, "modality": item.modality, "content_hash": content_hash, "parser": [parsed.parser_name, parsed.parser_version], "vision": [analyzer.model if analysis else "", "vision-v1"]})
                units.append(KnowledgeUnit(unit_id=unit_id, document_id=document_id, parent_id=item.parent_key, modality=item.modality, content_kind=analysis.content_kind if analysis else item.content_kind, page_number=item.page_number, bbox=item.bbox, raw_text=item.raw_text, retrieval_text=text, asset_uri=asset_uri, content_hash=content_hash, parser_name=parsed.parser_name, parser_version=parsed.parser_version, vision_model=analyzer.model if analysis else "", embedding_provider=embedding["provider"], embedding_model=embedding["model"], status=UnitStatus.ENRICHED if analysis else UnitStatus.COMPLETED))
        version_dir.mkdir(parents=True)
        (version_dir / "units.jsonl").write_text("".join(unit.model_dump_json() + "\n" for unit in units), encoding="utf-8")
        (version_dir / "issues.jsonl").write_text("".join(issue.model_dump_json() + "\n" for issue in issues), encoding="utf-8")
        manifest.update({"index_version": version, "embedding": embedding, "unit_count": len(units), "issues_count": len(issues), "quality_policy": self._quality_policy(), "quality_observations": quality})
        manifest["documents"] = documents
        manifest_path = version_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        vector_count = StagedIndex(version_dir, f"{self.collection_prefix}_{version}").write(units) if units else 0
        return {"status": "staged", "index_version": version, "unit_count": len(units), "vector_count": vector_count, "issues": [issue.model_dump(mode="json") for issue in issues]}

    def run(self, sources: list[str], *, allow_remote_data: bool = False, max_images: int = 12, retry_failed: bool = False, retry_generation: int = 0, timeout_seconds: int | None = None, cancel_check: Callable[[], bool] | None = None) -> dict[str, Any]:
        """以版本锁串行执行 ingest、评测和条件发布，并保留暂存失败版本。"""
        started = time.monotonic()
        entries, _ = self._scan(sources)
        manifest = self._manifest(entries, allow_remote_data=allow_remote_data, max_images=max_images, retry_failed=retry_failed, retry_generation=retry_generation)
        version = self._index_version(manifest)
        lock = self.index_root / ".locks" / version
        try:
            lock.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            return {"status": "already_running", "index_version": version, "published": False}
        try:
            self._check_run_control(started, timeout_seconds, cancel_check)
            reused = (self.index_root / version).is_dir()
            staged = {"status": "reused_staged", "index_version": version} if reused else self.ingest(sources, allow_remote_data=allow_remote_data, max_images=max_images, retry_failed=retry_failed, retry_generation=retry_generation)
            self._check_run_control(started, timeout_seconds, cancel_check)
            evaluation = self.evaluate(version)
            self._check_run_control(started, timeout_seconds, cancel_check)
            if not evaluation["passed"]:
                return {"status": "gate_failed", "index_version": version, "staged": staged, "evaluation": evaluation, "published": False}
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
        if any(not unit.retrieval_text.strip() for unit in units): failures.append("empty_retrieval_text")
        if manifest.get("embedding") != embedding_fingerprint(): failures.append("embedding_fingerprint_mismatch")
        if "build_configuration" not in manifest:
            failures.append("legacy_manifest_missing_build_configuration")
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

    def _manifest(self, entries: list[dict[str, str]], *, allow_remote_data: bool = False, max_images: int = 12, retry_failed: bool = False, retry_generation: int = 0) -> dict[str, Any]:
        """构造不包含宿主绝对路径的来源清单。"""
        public = [{"relative_path": entry["relative_path"], "content_hash": entry["content_hash"]} for entry in entries]
        return {
            "schema_version": 2,
            "sources": public,
            "parser": os.getenv("MULTIMODAL_PARSER", "docling"),
            "build_configuration": {
                "embedding": embedding_fingerprint(),
                "pdf_parser": {"page_range_mode": "single_page", "converter_restart_interval": int(os.getenv("MULTIMODAL_DOCLING_RESTART_INTERVAL", "20"))},
                "vision": {"enabled": allow_remote_data, "model": os.getenv("VISION_MODEL", REQUIRED_MODEL), "prompt_version": PROMPT_VERSION, "max_images": min(max_images, 100), "max_retries": int(os.getenv("VISION_MAX_RETRIES", "2")), "retry_failed": retry_failed, "retry_generation": retry_generation},
            },
        }

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
            if unit.asset_uri and not unit.raw_text and sha256_bytes(store.read(unit.asset_uri)) != unit.content_hash:
                return ["unit_asset_hash_mismatch"]
        return []

    def _configuration_status(self) -> dict[str, Any]:
        """返回不含密钥或地址值的阶段零配置检查结果。"""
        parser_status = self._parser_status()
        return {
            "embedding": embedding_fingerprint(),
            "vision_provider": "wcode",
            "vision_model": os.getenv("VISION_MODEL", "qwen/qwen3-vl-flash"),
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
