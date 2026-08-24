"""已构建索引（staged index）与评测题集的统一绑定门禁。

评测必须显式声明“用哪个索引版本配哪份数据集”；
这里负责校验两者的身份指纹互相匹配，防止拿旧题集评新索引。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


_COLLECTION_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_INDEX_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True)
class IndexIdentity:
    ingestion_run_id: str
    index_version: str
    collection_name: str
    manifest_sha256: str
    embedding_fingerprint: dict[str, Any]
    index_dir: Path


class IndexBindingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class IndexBindingGate:
    """只接受已完成且身份完整的 staged index。"""

    def __init__(self, load_run: Callable[[str], dict[str, Any]], run_dir_factory: Callable[[str], Path], embedding_fingerprint_provider: Callable[[], dict[str, Any]]) -> None:
        self._load_run = load_run
        self._run_dir_factory = run_dir_factory
        self._embedding_fingerprint_provider = embedding_fingerprint_provider

    @staticmethod
    def _mismatch(message: str) -> None:
        raise IndexBindingError("index_binding_mismatch", message)

    def resolve_staged_index(self, ingestion_run_id: str, index_version: str) -> IndexIdentity:
        """校验摄取运行、manifest、单元数量和 embedding 后返回索引身份。"""
        requested_version = str(index_version or "").strip()
        if not _INDEX_VERSION_PATTERN.fullmatch(requested_version):
            self._mismatch("index_version is required")
        try:
            ingestion = self._load_run(ingestion_run_id)
        except Exception:
            self._mismatch("ingestion run is unavailable")
        if ingestion.get("kind") != "ingestion" or ingestion.get("status") != "staged":
            self._mismatch("ingestion run is not staged")
        if str(ingestion.get("index_version") or "") != requested_version:
            self._mismatch("index_version does not belong to ingestion run")
        collection_name = str(ingestion.get("collection_name") or "").strip()
        if not _COLLECTION_NAME_PATTERN.fullmatch(collection_name):
            self._mismatch("ingestion collection_name is invalid")
        try:
            run_dir = Path(self._run_dir_factory(ingestion_run_id)).resolve()
            indexes_dir = (run_dir / "indexes").resolve()
            index_dir = (indexes_dir / requested_version).resolve()
            index_dir.relative_to(indexes_dir)
        except (OSError, ValueError):
            self._mismatch("staged index location is invalid")
        required_files = ("manifest.json", "units.jsonl", "build_state.json")
        if any(not (index_dir / name).is_file() for name in required_files) or not (index_dir / "chroma").is_dir():
            self._mismatch("staged index is incomplete")
        try:
            manifest_path = index_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            build_state = json.loads((index_dir / "build_state.json").read_text(encoding="utf-8"))
            units = [line for line in (index_dir / "units.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            self._mismatch("staged index metadata is invalid")
        if build_state.get("status") != "staged_complete":
            self._mismatch("staged index is not complete")
        try:
            unit_count = int(build_state.get("unit_count"))
            vector_count = int(build_state.get("vector_count"))
            ingestion_units = int(ingestion.get("unit_count"))
            ingestion_vectors = int(ingestion.get("vector_count"))
        except (TypeError, ValueError):
            self._mismatch("staged index counts are invalid")
        if unit_count != vector_count or unit_count != len(units) or ingestion_units != unit_count or ingestion_vectors != vector_count:
            self._mismatch("staged index unit/vector counts do not match ingestion")
        if manifest.get("index_version") != requested_version:
            self._mismatch("staged index version does not match manifest")
        try:
            manifest_unit_count = int(manifest.get("unit_count"))
        except (TypeError, ValueError):
            self._mismatch("staged index manifest unit_count is invalid")
        if manifest_unit_count != len(units):
            self._mismatch("staged index manifest unit_count does not match units")
        manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if manifest_sha256 != str(ingestion.get("manifest_sha256") or ""):
            self._mismatch("staged index manifest hash does not match ingestion")
        current_embedding = self._embedding_fingerprint_provider()
        if manifest.get("embedding") != current_embedding:
            self._mismatch("staged index embedding fingerprint does not match runtime")
        return IndexIdentity(
            ingestion_run_id=str(ingestion_run_id), index_version=requested_version,
            collection_name=collection_name, manifest_sha256=manifest_sha256,
            embedding_fingerprint=dict(current_embedding), index_dir=index_dir,
        )

    def validate_dataset(self, dataset: dict[str, Any], identity: IndexIdentity, allowed_kinds: set[str] | frozenset[str]) -> dict[str, Any]:
        """确认评测题集与已解析的 staged index 完全匹配后返回规范化数据。"""
        from app.rag_eval.isolated_evaluation import normalize_dataset_payload
        from Agent.knowledge_base.rag.operation_datasets.benchmark_v2 import validate_frozen_gold_bundle

        canonical, _ = normalize_dataset_payload(dataset)
        kind = str(canonical.get("dataset_kind") or "")
        if kind not in allowed_kinds:
            raise IndexBindingError("dataset_kind_not_allowed", "dataset_kind is not allowed for this operation")
        explicit_collection = canonical.get("collection_name")
        explicit_embedding = canonical.get("embedding")
        if explicit_collection not in (None, "") and explicit_collection != identity.collection_name:
            self._mismatch("dataset collection_name does not match staged index")
        if explicit_embedding is not None and explicit_embedding != identity.embedding_fingerprint:
            self._mismatch("dataset embedding does not match staged index")
        if kind == "generated_candidate":
            snapshot = dict(canonical.get("source_snapshot") or {})
            if snapshot.get("index_version") != identity.index_version or snapshot.get("manifest_sha256") != identity.manifest_sha256:
                self._mismatch("generated candidate source_snapshot does not match staged index")
            expected = {"index_version": identity.index_version, "manifest_sha256": identity.manifest_sha256}
            try:
                validate_frozen_gold_bundle(canonical, index_dir=identity.index_dir, expected_snapshot=expected, require_generated_candidate=True)
            except (ValueError, FileNotFoundError) as exc:
                self._mismatch(str(exc))
        elif kind == "gold_regression":
            expected = {"index_version": identity.index_version, "manifest_sha256": identity.manifest_sha256}
            try:
                validate_frozen_gold_bundle(
                    canonical,
                    index_dir=identity.index_dir,
                    expected_snapshot=expected,
                    require_fixed_binding=True,
                )
            except (ValueError, FileNotFoundError) as exc:
                self._mismatch(str(exc))
        return canonical
