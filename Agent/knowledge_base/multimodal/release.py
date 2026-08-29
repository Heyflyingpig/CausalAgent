"""不可变多模态 release 身份、pointer 和正式发布事务。"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import sqlite3
import tempfile
import uuid
from typing import Any, Mapping

MANIFEST_SCHEMA_VERSION = 6
MANIFEST_SCHEMA_NAME = "multimodal_release_manifest_v1"
POINTER_SCHEMA_VERSION = "multimodal_release_pointer_v1"
RELEASE_ID_PATTERN = re.compile(r"^mm_[0-9a-f]{64}$")
LEGACY_RELEASE_ID_PATTERN = re.compile(r"^mm_[0-9a-f]{20}$")
_FORBIDDEN_TOP_LEVEL_IDENTITY_FIELDS = {
    "release_id",
    "identity_sha256",
    "manifest_sha256",
    "evaluation_binding",
    "artifact_integrity",
    "created_at",
    "producer",
    "status",
    "error",
    "failure",
}
_FORBIDDEN_MANIFEST_KEYS = {
    "api_key",
    "token",
    "cookie",
    "password",
    "connection_string",
    "database_url",
    "base_url",
}
_RAW_ASSET_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"}


class ReleaseValidationError(ValueError):
    """release 身份、产物或 pointer 校验失败。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class ReleaseConcurrencyError(RuntimeError):
    """发布时 active generation 或 release 身份发生并发变化。"""


def canonical_identity_bytes(value: Mapping[str, Any]) -> bytes:
    """返回平台换行无关的稳定身份字节。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def identity_projection(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """去掉发布时可变字段，保留影响索引/查询兼容性的身份字段。"""
    projection = copy.deepcopy(dict(manifest))
    for key in _FORBIDDEN_TOP_LEVEL_IDENTITY_FIELDS | {"index_version"}:
        projection.pop(key, None)
    return projection


def compute_identity_sha256(manifest: Mapping[str, Any]) -> str:
    """计算稳定身份哈希，不把 release_id 自身带入投影。"""
    return hashlib.sha256(canonical_identity_bytes(identity_projection(manifest))).hexdigest()


def release_id_for_manifest(manifest: Mapping[str, Any]) -> str:
    """由稳定身份生成全长内容身份 release ID。"""
    return f"mm_{compute_identity_sha256(manifest)}"


def manifest_bytes(manifest: Mapping[str, Any]) -> bytes:
    """以确定性缩进 JSON 和 LF 换行序列化 manifest。"""
    return (json.dumps(dict(manifest), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _normalize_manifest_newlines(payload: bytes) -> bytes:
    """只规范 manifest 的换行；来源和索引文件仍按原始字节计算。"""
    return payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def compute_manifest_sha256(manifest: Mapping[str, Any] | Path | bytes) -> str:
    """计算换行无关的最终 manifest 文件哈希。"""
    if isinstance(manifest, Path):
        payload = manifest.read_bytes()
    elif isinstance(manifest, bytes):
        payload = manifest
    else:
        payload = manifest_bytes(manifest)
    return hashlib.sha256(_normalize_manifest_newlines(payload)).hexdigest()


def directory_sha256(directory: Path) -> tuple[str, int]:
    """按相对 POSIX 路径和稳定文件内容计算目录哈希及总字节数。"""
    base = Path(directory).resolve()
    if not base.is_dir():
        raise ReleaseValidationError("artifact_missing", "release artifact directory is missing")
    digest = hashlib.sha256()
    total_size = 0
    files = sorted(
        (path for path in base.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(base).as_posix(),
    )
    for path in files:
        relative = path.relative_to(base).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as canonical:
            for chunk in _stable_file_chunks(path):
                canonical.write(chunk)
            size = canonical.tell()
            digest.update(size.to_bytes(8, "big"))
            canonical.seek(0)
            while chunk := canonical.read(1024 * 1024):
                digest.update(chunk)
        total_size += size
    return digest.hexdigest(), total_size


def _stable_file_chunks(path: Path):
    """返回文件的稳定内容；忽略 Chroma 运行时写入的 acquire_write 锁表。"""
    if path.name != "chroma.sqlite3":
        yield path.read_bytes()
        return
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if "acquire_write" not in tables:
            yield path.read_bytes()
            return
        for line in connection.iterdump():
            stripped = line.lstrip()
            if (
                stripped.startswith("CREATE TABLE acquire_write")
                or stripped.startswith('CREATE TABLE "acquire_write"')
                or stripped.startswith("INSERT INTO acquire_write")
                or stripped.startswith('INSERT INTO "acquire_write"')
            ):
                continue
            yield (line + "\n").encode("utf-8")
    except sqlite3.DatabaseError:
        yield path.read_bytes()
    finally:
        if "connection" in locals():
            connection.close()


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """原子写入封存 manifest，并返回写入后的副本。"""
    sealed = seal_manifest(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(manifest_bytes(sealed))
    temporary.replace(path)
    return sealed


def seal_manifest(
    manifest: Mapping[str, Any],
    *,
    evaluation_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """写入一次 release identity；评测绑定不改变 identity。"""
    sealed = copy.deepcopy(dict(manifest))
    sealed.setdefault("schema_version", MANIFEST_SCHEMA_VERSION)
    if evaluation_binding is not None:
        sealed["evaluation_binding"] = copy.deepcopy(dict(evaluation_binding))
    identity_sha256 = compute_identity_sha256(sealed)
    sealed["identity_sha256"] = identity_sha256
    sealed["release_id"] = f"mm_{identity_sha256}"
    if not sealed.get("index_version"):
        sealed["index_version"] = sealed["release_id"]
    validate_manifest_contract(sealed)
    return sealed


def seal_evaluation_binding(path: Path, binding: Mapping[str, Any]) -> dict[str, Any]:
    """在不改变 release identity 的前提下封存评测绑定并原子写回 manifest。"""
    if not isinstance(binding, Mapping):
        raise ReleaseValidationError("evaluation_binding_invalid", "evaluation binding must be an object")
    required = ("evaluation_run_id", "dataset_revision", "dataset_sha256", "report_sha256", "gate_sha256")
    if any(not str(binding.get(key) or "").strip() for key in required):
        raise ReleaseValidationError("evaluation_binding_incomplete", "evaluation binding is incomplete")
    for key in ("dataset_sha256", "report_sha256", "gate_sha256"):
        if re.fullmatch(r"[0-9a-f]{64}", str(binding[key])) is None:
            raise ReleaseValidationError("evaluation_binding_invalid", f"evaluation binding {key} is invalid")
    manifest_path = Path(path).resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseValidationError("manifest_invalid", "release manifest is unreadable") from exc
    existing_binding = manifest.get("evaluation_binding")
    if existing_binding is not None:
        if existing_binding != dict(binding):
            raise ReleaseValidationError("evaluation_binding_sealed", "evaluation binding is already sealed")
        return manifest
    release_id = str(manifest.get("release_id") or "")
    sealed = seal_manifest(manifest, evaluation_binding=binding)
    if release_id and sealed["release_id"] != release_id:
        raise ReleaseValidationError("identity_mismatch", "evaluation binding changed release identity")
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temporary.write_bytes(manifest_bytes(sealed))
    temporary.replace(manifest_path)
    return sealed


def _contains_forbidden_manifest_data(value: Any, *, key: str = "") -> bool:
    key_name = key.lower()
    if key_name in _FORBIDDEN_MANIFEST_KEYS:
        return True
    if isinstance(value, Mapping):
        return any(
            _contains_forbidden_manifest_data(child, key=str(child_key))
            for child_key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_manifest_data(child, key=key) for child in value)
    if isinstance(value, str):
        lower = value.lower()
        return "bearer " in lower or "basic " in lower or "@" in value and "://" in value
    return False


def _is_safe_relative_path(value: Any) -> bool:
    """检查 manifest/pointer 内的 POSIX 相对路径。"""
    if not isinstance(value, str) or not value or "\x00" in value:
        return False
    normalized = value.replace("\\", "/")
    windows = PureWindowsPath(value)
    if normalized.startswith("/") or windows.drive or windows.root or PurePosixPath(normalized).is_absolute():
        return False
    return not any(part in {"", ".", ".."} for part in normalized.split("/"))


def validate_manifest_counts(
    manifest: Mapping[str, Any],
    *,
    actual_counts: Mapping[str, Any] | None = None,
) -> None:
    """校验 manifest 计数类型、内部约束以及可用产物的实际计数。"""
    counts = manifest.get("counts")
    required_numeric = ("document_count", "page_count", "unit_count", "vector_count", "issues_count")
    if not isinstance(counts, Mapping) or not all(field in counts for field in (*required_numeric, "partial")):
        raise ReleaseValidationError("counts_incomplete", "release manifest counts are required")
    for field in required_numeric:
        value = counts[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ReleaseValidationError("counts_invalid", f"release manifest counts field {field} is invalid")
    if not isinstance(counts["partial"], bool):
        raise ReleaseValidationError("counts_invalid", "release manifest counts field partial is invalid")
    if counts["unit_count"] != counts["vector_count"]:
        raise ReleaseValidationError("counts_invalid", "release manifest unit and vector counts do not match")
    for top_level, count_field in (("unit_count", "unit_count"), ("issues_count", "issues_count")):
        if top_level in manifest and manifest[top_level] != counts[count_field]:
            raise ReleaseValidationError("counts_invalid", f"release manifest {top_level} disagrees with counts")
    if "partial_ingestion" in manifest and manifest["partial_ingestion"] != counts["partial"]:
        raise ReleaseValidationError("counts_invalid", "release manifest partial flags do not match")
    documents = manifest.get("documents")
    if documents is not None:
        if not isinstance(documents, list):
            raise ReleaseValidationError("counts_invalid", "release manifest documents are invalid")
        page_count = 0
        for document in documents:
            if not isinstance(document, Mapping):
                raise ReleaseValidationError("counts_invalid", "release manifest document is invalid")
            attempted_pages = document.get("attempted_page_count", 0)
            if isinstance(attempted_pages, bool) or not isinstance(attempted_pages, int) or attempted_pages < 0:
                raise ReleaseValidationError("counts_invalid", "release manifest attempted page count is invalid")
            page_count += attempted_pages
        if counts["document_count"] != len(documents) or counts["page_count"] != page_count:
            raise ReleaseValidationError("counts_mismatch", "release manifest document/page counts do not match documents")
    for field, actual in (actual_counts or {}).items():
        if actual is not None and counts.get(field) != actual:
            raise ReleaseValidationError("counts_mismatch", f"release manifest counts field {field} does not match artifacts")


def validate_manifest_contract(
    manifest: Mapping[str, Any],
    *,
    expected_release_id: str | None = None,
    expected_manifest_sha256: str | None = None,
    allow_legacy: bool = False,
) -> None:
    """校验不可变 manifest 的身份字段、embedding 安全边界和可选产物说明。"""
    if not isinstance(manifest, Mapping):
        raise ReleaseValidationError("manifest_not_object", "release manifest must be an object")
    schema = manifest.get("schema_version")
    is_new = schema == MANIFEST_SCHEMA_VERSION or schema == MANIFEST_SCHEMA_NAME
    if not is_new:
        if not allow_legacy:
            raise ReleaseValidationError("manifest_schema_unsupported", "release manifest schema is unsupported")
        if not manifest.get("index_version"):
            raise ReleaseValidationError("manifest_identity_missing", "legacy release manifest has no index_version")
    if _contains_forbidden_manifest_data(manifest):
        raise ReleaseValidationError("manifest_contains_secret", "release manifest contains forbidden credential data")
    if is_new:
        identity = manifest.get("identity_sha256")
        release_id = manifest.get("release_id")
        if not isinstance(identity, str) or re.fullmatch(r"[0-9a-f]{64}", identity) is None:
            raise ReleaseValidationError("identity_missing", "release manifest identity_sha256 is required")
        if not isinstance(release_id, str) or RELEASE_ID_PATTERN.fullmatch(release_id) is None:
            raise ReleaseValidationError("release_id_invalid", "release manifest release_id is invalid")
        if release_id != f"mm_{identity}" or compute_identity_sha256(manifest) != identity:
            raise ReleaseValidationError("identity_mismatch", "release manifest identity hash does not match content")
        embedding = manifest.get("embedding_config") or manifest.get("embedding")
        if not isinstance(embedding, Mapping):
            raise ReleaseValidationError("embedding_config_missing", "release manifest embedding configuration is required")
        for key in ("mode", "provider", "model", "dimension", "distance_metric", "request_contract_version"):
            if key not in embedding:
                raise ReleaseValidationError("embedding_config_incomplete", f"release manifest embedding_config lacks {key}")
        if "normalized" not in embedding and "normalization" not in embedding:
            raise ReleaseValidationError("embedding_config_incomplete", "release manifest embedding_config lacks normalization")
        dimension = embedding.get("dimension")
        if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension < 1:
            raise ReleaseValidationError("embedding_dimension_invalid", "release manifest embedding dimension must be positive")
        if str(embedding.get("mode") or "") == "api" and not str(embedding.get("endpoint_identity") or "").strip():
            raise ReleaseValidationError("embedding_endpoint_missing", "API embedding endpoint identity is required")
        from Agent.knowledge_base.embedding_runtime import EmbeddingConfiguration
        from Agent.knowledge_base.embedding_runtime import validate_embedding_env_references

        try:
            embedding_configuration = EmbeddingConfiguration.from_mapping(embedding)
            validate_embedding_env_references(embedding_configuration)
            expected_fingerprint = embedding_configuration.fingerprint()
            if isinstance(manifest.get("embedding_config"), Mapping) and manifest.get("embedding") is not None and manifest.get("embedding") != expected_fingerprint:
                raise ReleaseValidationError("embedding_fingerprint_mismatch", "release manifest embedding fingerprint does not match configuration")
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ReleaseValidationError):
                raise
            raise ReleaseValidationError("embedding_config_incomplete", "release manifest embedding configuration is invalid") from exc
        sources = manifest.get("sources")
        if not isinstance(sources, list):
            raise ReleaseValidationError("sources_invalid", "release manifest sources must be a list")
        for source in sources:
            if not isinstance(source, Mapping):
                raise ReleaseValidationError("source_invalid", "release manifest source must be an object")
            for key in ("source_id", "document_id", "relative_path", "content_hash"):
                if key not in source:
                    raise ReleaseValidationError("source_incomplete", f"release manifest source lacks {key}")
            if not _is_safe_relative_path(source.get("relative_path")):
                raise ReleaseValidationError("source_path_invalid", "release manifest source path is unsafe")
        validate_manifest_counts(manifest)
    elif release_id := manifest.get("release_id"):
        if not isinstance(release_id, str) or LEGACY_RELEASE_ID_PATTERN.fullmatch(release_id) is None:
            raise ReleaseValidationError("release_id_invalid", "legacy release manifest release_id is invalid")
    if expected_release_id and manifest.get("release_id", manifest.get("index_version")) != expected_release_id:
        raise ReleaseValidationError("release_id_mismatch", "release manifest release_id does not match pointer")
    if expected_manifest_sha256:
        actual = compute_manifest_sha256(manifest)
        if actual != expected_manifest_sha256:
            raise ReleaseValidationError("manifest_hash_mismatch", "release manifest hash does not match pointer")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ReleaseValidationError("artifacts_missing", "release manifest artifacts are required")
    for artifact in artifacts:
        if not isinstance(artifact, Mapping) or not _is_safe_relative_path(artifact.get("path", artifact.get("relative_path"))):
            raise ReleaseValidationError("artifact_path_invalid", "release artifact path is unsafe")
        if not isinstance(artifact.get("type"), str) or not isinstance(artifact.get("required"), bool):
            raise ReleaseValidationError("artifact_contract_invalid", "release artifact type and required flag are required")
        digest = artifact.get("sha256")
        if digest is not None and re.fullmatch(r"[0-9a-f]{64}", str(digest)) is None:
            raise ReleaseValidationError("artifact_hash_invalid", "release artifact hash is invalid")
        if artifact.get("required") and artifact.get("type") != "directory" and (digest is None or artifact.get("size_bytes", artifact.get("size")) is None):
            raise ReleaseValidationError("artifact_contract_incomplete", "required release file needs size and hash")
    integrity = manifest.get("artifact_integrity")
    if integrity is not None:
        if not isinstance(integrity, Mapping):
            raise ReleaseValidationError("artifact_integrity_invalid", "artifact_integrity must be an object")
        chroma_integrity = integrity.get("chroma")
        if chroma_integrity is not None:
            if not isinstance(chroma_integrity, Mapping) or re.fullmatch(r"[0-9a-f]{64}", str(chroma_integrity.get("sha256") or "")) is None:
                raise ReleaseValidationError("artifact_integrity_invalid", "chroma artifact integrity hash is invalid")
            if isinstance(chroma_integrity.get("size_bytes"), bool) or not isinstance(chroma_integrity.get("size_bytes"), int) or chroma_integrity.get("size_bytes") < 0:
                raise ReleaseValidationError("artifact_integrity_invalid", "chroma artifact integrity size is invalid")


def embedding_config_from_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """取 manifest 的完整 embedding 配置并恢复本机运行状态。"""
    from Agent.knowledge_base.embedding_runtime import embedding_configuration_from_manifest

    return embedding_configuration_from_manifest(manifest).to_runtime_dict()


def validate_manifest_artifacts(manifest: Mapping[str, Any], release_dir: Path) -> None:
    """按 manifest 校验正式 release 的必要文件、目录、大小和哈希。"""
    base = Path(release_dir).resolve()
    for artifact in manifest.get("artifacts") or []:
        relative = str(artifact.get("path") or artifact.get("relative_path") or "")
        if not _is_safe_relative_path(relative):
            raise ReleaseValidationError("artifact_path_invalid", "release artifact path is unsafe")
        target = (base / PurePosixPath(relative)).resolve()
        try:
            target.relative_to(base)
        except ValueError as exc:
            raise ReleaseValidationError("artifact_path_invalid", "release artifact escapes release directory") from exc
        if not target.is_file() and not (target.is_dir() and artifact.get("type") == "directory"):
            raise ReleaseValidationError("artifact_missing", "release artifact is missing")
        size = artifact.get("size_bytes", artifact.get("size"))
        expected_hash = artifact.get("sha256")
        if target.is_dir() and relative == "chroma" and not expected_hash:
            integrity = manifest.get("artifact_integrity")
            chroma_integrity = integrity.get("chroma") if isinstance(integrity, Mapping) else None
            if not isinstance(chroma_integrity, Mapping):
                if manifest.get("identity_sha256") or manifest.get("schema_version") in (MANIFEST_SCHEMA_VERSION, MANIFEST_SCHEMA_NAME):
                    raise ReleaseValidationError("artifact_integrity_missing", "release Chroma content integrity is missing")
            else:
                expected_hash = chroma_integrity.get("sha256")
                size = chroma_integrity.get("size_bytes")
        if target.is_file():
            actual_size = target.stat().st_size
            actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        else:
            actual_hash, actual_size = directory_sha256(target)
        if size is not None and int(size) != actual_size:
            raise ReleaseValidationError("artifact_size_mismatch", "release artifact size does not match manifest")
        if expected_hash and actual_hash != str(expected_hash):
            raise ReleaseValidationError("artifact_hash_mismatch", "release artifact hash does not match manifest")


def normalize_pointer(payload: Mapping[str, Any] | None, previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """把新 pointer 与旧 active/previous 双文件规范化为同一选择器。"""
    if not payload:
        return {"schema_version": POINTER_SCHEMA_VERSION, "generation": 0, "active": None, "fallback": None}
    if isinstance(payload.get("active"), Mapping) or payload.get("active") is None and "fallback" in payload:
        return {
            "schema_version": str(payload.get("schema_version") or POINTER_SCHEMA_VERSION),
            "generation": int(payload.get("generation") or 0),
            "active": dict(payload.get("active") or {}) or None,
            "fallback": dict(payload.get("fallback") or {}) or None,
        }
    if payload.get("active_release_id"):
        active_id = str(payload["active_release_id"])
        active = {
            "release_id": active_id,
            "index_version": str(payload.get("active_index_version") or active_id),
            "index_path": str(payload.get("active_index_path") or f"{active_id}/chroma"),
            "manifest_sha256": str(payload.get("active_manifest_sha256") or ""),
            "collection_name": str(payload.get("active_collection_name") or ""),
        }
        fallback_id = str(payload.get("fallback_release_id") or "")
        fallback = None
        if fallback_id:
            fallback = {
                "release_id": fallback_id,
                "index_version": str(payload.get("fallback_index_version") or fallback_id),
                "index_path": str(payload.get("fallback_index_path") or f"{fallback_id}/chroma"),
                "manifest_sha256": str(payload.get("fallback_manifest_sha256") or ""),
                "collection_name": str(payload.get("fallback_collection_name") or ""),
            }
        return {
            "schema_version": str(payload.get("schema_version") or POINTER_SCHEMA_VERSION),
            "generation": int(payload.get("generation") or 0),
            "active": active,
            "fallback": fallback,
        }
    active_id = str(payload.get("release_id") or payload.get("index_version") or "").strip()
    active = None
    if active_id:
        index_path = str(payload.get("index_path") or f"{active_id}/chroma")
        active = {
            "release_id": active_id,
            "index_version": str(payload.get("index_version") or active_id),
            "index_path": index_path,
            "manifest_sha256": str(payload.get("manifest_sha256") or ""),
            "collection_name": str(payload.get("collection_name") or ""),
        }
        if isinstance(payload.get("embedding"), Mapping):
            active["embedding"] = dict(payload["embedding"])
    fallback = None
    if previous:
        fallback = normalize_pointer(previous).get("active")
    return {"schema_version": POINTER_SCHEMA_VERSION, "generation": 0, "active": active, "fallback": fallback}


def pointer_bytes(pointer: Mapping[str, Any]) -> bytes:
    """规范化新 pointer 的 LF JSON 字节。"""
    payload = {
        "schema_version": POINTER_SCHEMA_VERSION,
        "generation": int(pointer.get("generation") or 0),
        "active": pointer.get("active"),
        "fallback": pointer.get("fallback"),
    }
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


@contextlib.contextmanager
def _file_lock(lock_path: Path):
    """跨进程独占发布锁，兼容 Windows 与 POSIX。"""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


class ReleaseManager:
    """集中管理 formal active/fallback、物化、quarantine 与回退。"""

    def __init__(
        self,
        release_root: Path,
        pointer_path: Path,
        *,
        quarantine_root: Path | None = None,
        lock_path: Path | None = None,
    ) -> None:
        self.release_root = Path(release_root).resolve()
        self.pointer_path = Path(pointer_path).resolve()
        self.quarantine_root = (quarantine_root or self.release_root / "quarantine").resolve()
        self.lock_path = (lock_path or self.release_root / ".release.lock").resolve()
        self.release_root.mkdir(parents=True, exist_ok=True)
        self.release_root.relative_to(self.release_root.parent)

    def _read_pointer(self) -> dict[str, Any]:
        payload = None
        if self.pointer_path.is_file():
            payload = json.loads(self.pointer_path.read_text(encoding="utf-8"))
            if isinstance(payload, Mapping) and "active" in payload and payload.get("schema_version") != POINTER_SCHEMA_VERSION:
                raise ReleaseValidationError("pointer_schema_unsupported", "release pointer schema is unsupported")
        previous_path = self.pointer_path.with_name("previous_index.json")
        previous = None
        if previous_path.is_file():
            previous = json.loads(previous_path.read_text(encoding="utf-8"))
        return normalize_pointer(payload, previous)

    def _write_pointer(self, pointer: Mapping[str, Any]) -> None:
        self.pointer_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.pointer_path.with_suffix(self.pointer_path.suffix + ".tmp")
        temporary.write_bytes(pointer_bytes(pointer))
        temporary.replace(self.pointer_path)

    def _release_dir(self, entry: Mapping[str, Any]) -> Path:
        release_id = self._entry_release_id(entry)
        if release_id and RELEASE_ID_PATTERN.fullmatch(release_id) is None and LEGACY_RELEASE_ID_PATTERN.fullmatch(release_id) is None:
            raise ReleaseValidationError("release_id_invalid", "release pointer release_id is invalid")
        raw = str(entry.get("release_path") or entry.get("index_path") or "")
        if raw.endswith("/chroma") or raw.endswith("\\chroma"):
            raw = raw.rsplit("/", 1)[0].rsplit("\\", 1)[0]
        if not _is_safe_relative_path(raw):
            raise ReleaseValidationError("pointer_path_invalid", "release pointer path is unsafe")
        target = (self.release_root / PurePosixPath(raw)).resolve()
        try:
            target.relative_to(self.release_root)
        except ValueError as exc:
            raise ReleaseValidationError("pointer_path_invalid", "release pointer path escapes release root") from exc
        return target

    @staticmethod
    def _entry_release_id(entry: Mapping[str, Any] | None) -> str:
        return str((entry or {}).get("release_id") or (entry or {}).get("index_version") or "")

    def _validate_release_dir(
        self,
        directory: Path,
        entry: Mapping[str, Any] | None = None,
        *,
        allow_legacy: bool = False,
        require_complete: bool = True,
    ) -> dict[str, Any]:
        manifest_path = directory / "manifest.json"
        if not directory.is_dir() or not manifest_path.is_file():
            raise ReleaseValidationError("release_missing", "release directory or manifest is unavailable")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleaseValidationError("manifest_invalid", "release manifest is unreadable") from exc
        manifest_hash = compute_manifest_sha256(manifest_path)
        expected_id = self._entry_release_id(entry) if entry else None
        validate_manifest_contract(
            manifest,
            expected_release_id=expected_id or None,
            allow_legacy=allow_legacy,
        )
        if isinstance((entry or {}).get("embedding"), Mapping) and (entry or {}).get("embedding") != manifest.get("embedding"):
            raise ReleaseValidationError("embedding_fingerprint_mismatch", "release embedding fingerprint does not match pointer")
        expected_manifest_hash = str((entry or {}).get("manifest_sha256") or "")
        if expected_manifest_hash and manifest_hash != expected_manifest_hash:
            raise ReleaseValidationError("manifest_hash_mismatch", "release manifest hash does not match pointer")
        if require_complete:
            required = ("units.jsonl", "build_state.json")
            if any(not (directory / name).is_file() for name in required) or not (directory / "chroma").is_dir():
                raise ReleaseValidationError("release_incomplete", "release is missing required index artifacts")
            try:
                state = json.loads((directory / "build_state.json").read_text(encoding="utf-8"))
                unit_count = int(state.get("unit_count"))
                vector_count = int(state.get("vector_count"))
                persisted = sum(1 for line in (directory / "units.jsonl").read_text(encoding="utf-8").splitlines() if line.strip())
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ReleaseValidationError("release_counts_invalid", "release build state is invalid") from exc
            if state.get("status") != "staged_complete" or unit_count != vector_count or persisted != unit_count:
                raise ReleaseValidationError("release_counts_invalid", "release build state and units count do not match")
            if manifest.get("identity_sha256") or manifest.get("schema_version") in (MANIFEST_SCHEMA_VERSION, MANIFEST_SCHEMA_NAME):
                actual_counts: dict[str, Any] = {
                    "unit_count": unit_count,
                    "vector_count": vector_count,
                }
                issues_path = directory / "issues.jsonl"
                if issues_path.is_file():
                    actual_counts["issues_count"] = sum(
                        1 for line in issues_path.read_text(encoding="utf-8").splitlines() if line.strip()
                    )
                validate_manifest_counts(manifest, actual_counts=actual_counts)
        validate_manifest_artifacts(manifest, directory)
        return {
            "manifest": manifest,
            "manifest_sha256": manifest_hash,
            "release_id": str(manifest.get("release_id") or manifest.get("index_version") or directory.name),
        }

    def _candidate_id(self, manifest: Mapping[str, Any], directory: Path) -> str:
        release_id = str(manifest.get("release_id") or manifest.get("index_version") or directory.name)
        if RELEASE_ID_PATTERN.fullmatch(release_id) is None and LEGACY_RELEASE_ID_PATTERN.fullmatch(release_id) is None:
            raise ReleaseValidationError("release_id_invalid", "candidate release id is invalid")
        return release_id

    @staticmethod
    def _contains_raw_asset(directory: Path) -> bool:
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            relative_parts = {part.lower() for part in path.relative_to(directory).parts}
            if relative_parts.intersection({"assets", "images", "vision_cache", "source"}):
                return True
            if path.suffix.lower() in _RAW_ASSET_SUFFIXES:
                return True
        return False

    @staticmethod
    def _copy_formal_artifacts(source: Path, target: Path) -> None:
        """只物化正式 release 所需产物，不复制 checkpoint 或评测报告。"""
        required = {"manifest.json", "units.jsonl", "build_state.json", "chroma"}
        optional = {"issues.jsonl"}
        target.mkdir(parents=True, exist_ok=True)
        for name in required | optional:
            source_path = source / name
            if not source_path.exists():
                if name in required:
                    raise ReleaseValidationError("release_incomplete", "release is missing required index artifacts")
                continue
            target_path = target / name
            if source_path.is_dir():
                shutil.copytree(source_path, target_path)
            else:
                shutil.copy2(source_path, target_path)

    def _materialize(self, candidate_dir: Path, release_id: str) -> tuple[Path, bool, Path | None]:
        target = (self.release_root / release_id).resolve()
        target.relative_to(self.release_root)
        if self._contains_raw_asset(candidate_dir):
            raise ReleaseValidationError("raw_asset_in_formal_release", "formal release must not contain raw source assets")
        if target.exists() and target != candidate_dir.resolve():
            existing = self._validate_release_dir(target, allow_legacy=True)
            candidate_hash = compute_manifest_sha256(candidate_dir / "manifest.json")
            if existing["manifest_sha256"] != candidate_hash:
                raise ReleaseValidationError("release_conflict", "formal release id already has a different manifest")
            return target, False, None
        if target == candidate_dir.resolve():
            return target, False, None
        incoming = self.release_root / f".incoming-{release_id}-{uuid.uuid4().hex}"
        try:
            self._copy_formal_artifacts(candidate_dir, incoming)
            return target, True, incoming
        except Exception:
            shutil.rmtree(incoming, ignore_errors=True)
            raise

    def _entry(self, release_id: str, directory: Path, manifest: Mapping[str, Any], manifest_hash: str) -> dict[str, Any]:
        retrieval_index = manifest.get("retrieval_index") or {}
        collection_template = str(retrieval_index.get("collection_template") or "") if isinstance(retrieval_index, Mapping) else ""
        templated_collection = collection_template.replace("<release_id>", release_id)
        collection = str(
            manifest.get("collection_name")
            or (retrieval_index.get("collection") if isinstance(retrieval_index, Mapping) else "")
            or templated_collection
            or f"causal_multimodal_{release_id}"
        )
        return {
            "release_id": release_id,
            "index_version": release_id,
            "index_path": f"{release_id}/chroma",
            "manifest_sha256": manifest_hash,
            "collection_name": collection,
        }

    def _record_cleanup_pending(self, entries: list[Mapping[str, Any]]) -> None:
        payload = {
            "schema_version": "multimodal_release_cleanup_v1",
            "release_ids": [self._entry_release_id(entry) for entry in entries if self._entry_release_id(entry)],
        }
        temporary = self.release_root / "cleanup_pending.json.tmp"
        temporary.write_bytes((json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
        temporary.replace(self.release_root / "cleanup_pending.json")

    def _cleanup_unreferenced_releases(self, protected: set[str]) -> list[dict[str, Any]]:
        """清理 formal root 中未被新 pointer 保护的 release 目录。"""
        pending: list[dict[str, Any]] = []
        for child in self.release_root.iterdir():
            if not child.is_dir() or not child.name.startswith("mm_") or child.name in protected:
                continue
            try:
                shutil.rmtree(child)
            except OSError:
                pending.append({"release_id": child.name, "index_path": f"{child.name}/chroma"})
        return pending

    def _finish_publish_cleanup(self, pointer: Mapping[str, Any]) -> bool:
        legacy_previous = self.pointer_path.with_name("previous_index.json")
        try:
            if legacy_previous.is_file():
                legacy_previous.unlink()
        except OSError:
            pass
        protected = {
            self._entry_release_id(pointer.get("active")),
            self._entry_release_id(pointer.get("fallback")),
        }
        try:
            pending = self._cleanup_unreferenced_releases(protected)
        except OSError:
            return True
        if pending:
            try:
                self._record_cleanup_pending(pending)
            except OSError:
                pass
        return bool(pending)

    def publish(
        self,
        candidate_dir: Path,
        *,
        expected_generation: int | None = None,
        expected_active_release_id: str | None = None,
        expected_manifest_sha256: str | None = None,
        allow_legacy: bool = False,
    ) -> dict[str, Any]:
        """物化、校验并原子晋级 candidate；所有 pointer 失败都保留旧选择。"""
        candidate_dir = Path(candidate_dir).resolve()
        manifest_path = candidate_dir / "manifest.json"
        if not manifest_path.is_file():
            raise ReleaseValidationError("candidate_missing", "staged candidate manifest is unavailable")
        candidate_manifest_sha256 = compute_manifest_sha256(manifest_path)
        if expected_manifest_sha256 and candidate_manifest_sha256 != expected_manifest_sha256:
            raise ReleaseConcurrencyError("staged candidate manifest changed during publication")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleaseValidationError("manifest_invalid", "staged candidate manifest is unreadable") from exc
        validate_manifest_contract(manifest, allow_legacy=allow_legacy)
        release_id = self._candidate_id(manifest, candidate_dir)
        target, _, incoming = self._materialize(candidate_dir, release_id)
        target_created = False
        pointer_written = False
        try:
            validation_dir = incoming or target
            self._validate_release_dir(validation_dir, allow_legacy=allow_legacy)
            if incoming is not None:
                with _file_lock(self.lock_path):
                    current = self._read_pointer()
                    if expected_generation is not None and current["generation"] != expected_generation:
                        raise ReleaseConcurrencyError("active pointer generation changed during publication")
                    current_active_id = self._entry_release_id(current.get("active"))
                    if expected_active_release_id is not None and current_active_id != expected_active_release_id:
                        raise ReleaseConcurrencyError("active release changed during publication")
                    if target.exists():
                        existing = self._validate_release_dir(target, allow_legacy=True)
                        candidate_hash = compute_manifest_sha256(manifest_path)
                        if existing["manifest_sha256"] != candidate_hash:
                            raise ReleaseValidationError("release_conflict", "formal release id already has a different manifest")
                        shutil.rmtree(incoming)
                        incoming = None
                    else:
                        incoming.replace(target)
                        target_created = True
                    manifest_hash = compute_manifest_sha256(target / "manifest.json")
                    new_entry = self._entry(release_id, target, manifest, manifest_hash)
                    old_active = current.get("active")
                    old_fallback = current.get("fallback")
                    fallback = old_fallback if current_active_id == release_id else old_active
                    pointer = {
                        "schema_version": POINTER_SCHEMA_VERSION,
                        "generation": int(current["generation"]) + 1,
                        "active": new_entry,
                        "fallback": fallback,
                    }
                    try:
                        self._write_pointer(pointer)
                    except Exception:
                        if target_created:
                            shutil.rmtree(target, ignore_errors=True)
                        raise
                    pointer_written = True
                    cleanup_pending = self._finish_publish_cleanup(pointer)
                return {
                    "status": "published",
                    "release_id": release_id,
                    "active": pointer["active"],
                    "fallback": pointer["fallback"],
                    "generation": pointer["generation"],
                    "cleanup_pending": cleanup_pending,
                    "requires_worker_restart": True,
                }

            with _file_lock(self.lock_path):
                current = self._read_pointer()
                if expected_generation is not None and current["generation"] != expected_generation:
                    raise ReleaseConcurrencyError("active pointer generation changed during publication")
                current_active_id = self._entry_release_id(current.get("active"))
                if expected_active_release_id is not None and current_active_id != expected_active_release_id:
                    raise ReleaseConcurrencyError("active release changed during publication")
                manifest_hash = compute_manifest_sha256(target / "manifest.json")
                new_entry = self._entry(release_id, target, manifest, manifest_hash)
                old_active = current.get("active")
                old_fallback = current.get("fallback")
                fallback = old_fallback if current_active_id == release_id else old_active
                pointer = {
                    "schema_version": POINTER_SCHEMA_VERSION,
                    "generation": int(current["generation"]) + 1,
                    "active": new_entry,
                    "fallback": fallback,
                }
                self._write_pointer(pointer)
                pointer_written = True
                cleanup_pending = self._finish_publish_cleanup(pointer)
            return {
                "status": "published",
                "release_id": release_id,
                "active": pointer["active"],
                "fallback": pointer["fallback"],
                "generation": pointer["generation"],
                "cleanup_pending": cleanup_pending,
                "requires_worker_restart": True,
            }
        except Exception:
            if incoming is not None:
                shutil.rmtree(incoming, ignore_errors=True)
            elif target_created and not pointer_written:
                shutil.rmtree(target, ignore_errors=True)
            raise

    def _move_to_quarantine(self, entry: Mapping[str, Any], *, reason_code: str) -> dict[str, Any]:
        source = self._release_dir(entry)
        if not source.exists():
            return {"release_id": self._entry_release_id(entry), "status": "missing"}
        self.quarantine_root.mkdir(parents=True, exist_ok=True)
        target = self.quarantine_root / self._entry_release_id(entry)
        if target.exists():
            target = self.quarantine_root / f"{self._entry_release_id(entry)}-{uuid.uuid4().hex[:8]}"
        shutil.move(str(source), str(target))
        failure = {
            "schema_version": "multimodal_release_quarantine_v1",
            "release_id": self._entry_release_id(entry),
            "manifest_sha256": str(entry.get("manifest_sha256") or ""),
            "reason_code": reason_code,
        }
        (target / "failure.json").write_bytes((json.dumps(failure, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
        return {"release_id": self._entry_release_id(entry), "status": "quarantined", "path": str(target)}

    def _record_rollback_audit(self, *, from_release_id: str, to_release_id: str, generation: int, reason_code: str) -> None:
        """追加不含路径/凭据/正文的回退审计事件。"""
        payload = {
            "event": "release_rollback",
            "from_release_id": from_release_id,
            "to_release_id": to_release_id,
            "generation": generation,
            "reason_code": reason_code,
            "requires_worker_restart": True,
        }
        try:
            with (self.release_root / "rollback_audit.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        except OSError:
            pass

    def rollback(
        self,
        release_id: str | None = None,
        *,
        expected_generation: int | None = None,
        expected_active_release_id: str | None = None,
        quarantine_active: bool = False,
        reason_code: str = "release_rollback",
        enforce_production_policy: bool = False,
    ) -> dict[str, Any]:
        """把唯一 fallback 提升为 active；自动故障回退可隔离旧 active。"""
        with _file_lock(self.lock_path):
            current = self._read_pointer()
            if expected_generation is not None and current["generation"] != expected_generation:
                raise ReleaseConcurrencyError("active pointer generation changed during rollback")
            active = current.get("active")
            fallback = current.get("fallback")
            active_id = self._entry_release_id(active)
            if expected_active_release_id is not None and active_id != expected_active_release_id:
                raise ReleaseConcurrencyError("active release changed during rollback")
            target_id = str(release_id or self._entry_release_id(fallback))
            if not fallback or target_id != self._entry_release_id(fallback):
                raise ReleaseValidationError("fallback_unavailable", "requested release is not the current fallback")
            target_dir = self._release_dir(fallback)
            target_validation = self._validate_release_dir(target_dir, fallback, allow_legacy=True)
            if enforce_production_policy and target_validation["manifest"].get("identity_sha256"):
                from .production import has_frozen_production_identity, validate_production_manifest

                if not has_frozen_production_identity(target_validation["manifest"]):
                    raise ReleaseValidationError(
                        "production_source_identity_mismatch",
                        "fallback release does not match the frozen production sources",
                    )
                if validate_production_manifest(target_validation["manifest"]):
                    raise ReleaseValidationError(
                        "production_policy_mismatch",
                        "fallback release does not satisfy production policy",
                    )
            pointer = {
                "schema_version": POINTER_SCHEMA_VERSION,
                "generation": int(current["generation"]) + 1,
                "active": fallback,
                "fallback": None if quarantine_active else active,
            }
            self._write_pointer(pointer)
            self._record_rollback_audit(
                from_release_id=active_id,
                to_release_id=target_id,
                generation=pointer["generation"],
                reason_code=reason_code,
            )
            quarantine = None
            if quarantine_active and active:
                try:
                    quarantine = self._move_to_quarantine(active, reason_code=reason_code)
                except OSError:
                    try:
                        self._record_cleanup_pending([active])
                    except OSError:
                        pass
                    quarantine = {"release_id": active_id, "status": "pending"}
        return {
            "status": "rolled_back",
            "release_id": target_id,
            "active": pointer["active"],
            "fallback": pointer["fallback"],
            "generation": pointer["generation"],
            "quarantine": quarantine,
            "requires_worker_restart": True,
        }

    def validate_active(self, *, enforce_production_policy: bool = False) -> dict[str, Any]:
        """验证 active；身份/产物或显式策略失败时受控提升 fallback。"""
        pointer = self._read_pointer()
        active = pointer.get("active")
        if not active:
            raise ReleaseValidationError("active_missing", "active release is not configured")
        try:
            validation = self._validate_release_dir(self._release_dir(active), active, allow_legacy=True)
            if enforce_production_policy and validation["manifest"].get("identity_sha256"):
                from .production import has_frozen_production_identity, validate_production_manifest

                if not has_frozen_production_identity(validation["manifest"]):
                    raise ReleaseValidationError(
                        "production_source_identity_mismatch",
                        "active release does not match the frozen production sources",
                    )
                if validate_production_manifest(validation["manifest"]):
                    raise ReleaseValidationError(
                        "production_policy_mismatch",
                        "active release does not satisfy production policy",
                    )
        except (OSError, ValueError) as exc:
            if not isinstance(exc, ReleaseValidationError):
                exc = ReleaseValidationError("release_invalid", "active release validation failed")
            if not pointer.get("fallback"):
                raise
            return self.rollback(
                self._entry_release_id(pointer["fallback"]),
                expected_generation=pointer["generation"],
                expected_active_release_id=self._entry_release_id(active),
                quarantine_active=True,
                reason_code=exc.code,
                enforce_production_policy=enforce_production_policy,
            )
        return {
            "status": "available",
            "release_id": validation["release_id"],
            "manifest_sha256": validation["manifest_sha256"],
            "requires_worker_restart": False,
        }

    def status(self) -> dict[str, Any]:
        """返回 pointer、quarantine 和稳定版本摘要。"""
        pointer = self._read_pointer()
        quarantined = sorted(
            child.name
            for child in self.quarantine_root.iterdir()
            if child.is_dir()
        ) if self.quarantine_root.is_dir() else []
        return {**pointer, "quarantine": quarantined}


__all__ = [
    "LEGACY_RELEASE_ID_PATTERN",
    "MANIFEST_SCHEMA_NAME",
    "MANIFEST_SCHEMA_VERSION",
    "POINTER_SCHEMA_VERSION",
    "RELEASE_ID_PATTERN",
    "ReleaseConcurrencyError",
    "ReleaseManager",
    "ReleaseValidationError",
    "canonical_identity_bytes",
    "compute_identity_sha256",
    "compute_manifest_sha256",
    "directory_sha256",
    "embedding_config_from_manifest",
    "identity_projection",
    "manifest_bytes",
    "normalize_pointer",
    "release_id_for_manifest",
    "seal_evaluation_binding",
    "seal_manifest",
    "validate_manifest_contract",
    "validate_manifest_counts",
    "validate_manifest_artifacts",
    "write_manifest",
]
