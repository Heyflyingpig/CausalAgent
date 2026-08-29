"""隔离评测不可变数据集快照注册中心。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from Agent.knowledge_base.rag.rag_eval.contracts import DATASET_KINDS
from app.rag_eval.isolated_evaluation import normalize_dataset_payload


_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_REVISION_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


@dataclass(frozen=True)
class DatasetRef:
    dataset_id: str
    dataset_revision: str


class DatasetRevisionConflict(ValueError):
    """同一数据集版本被不同内容占用。"""


class MysqlDatasetRepository:
    """延迟取得连接的 MySQL repository，供常驻进程默认使用。"""

    @staticmethod
    def _row_to_dict(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
        result = dict(row) if isinstance(row, dict) else dict(zip(columns, row))
        for key in ("binding_json",):
            value = result.get(key)
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            if isinstance(value, str):
                result[key] = json.loads(value)
        return result

    def find(self, reference: DatasetRef) -> dict[str, Any] | None:
        from app.db import get_read_connection

        columns = _metadata_columns()
        with get_read_connection(consistency="strong") as connection:
            cursor = connection.cursor()
            cursor.execute(
                f"SELECT {', '.join(columns)} FROM rag_eval_datasets "
                "WHERE dataset_id = %s AND dataset_revision = %s",
                (reference.dataset_id, reference.dataset_revision),
            )
            row = cursor.fetchone()
        return self._row_to_dict(row, columns) if row else None

    def insert(self, metadata: dict[str, Any]) -> None:
        from app.db import get_write_connection

        columns = _metadata_columns()
        values = [
            json.dumps(metadata[column], ensure_ascii=False, sort_keys=True)
            if column == "binding_json"
            else metadata[column]
            for column in columns
        ]
        with get_write_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                f"INSERT INTO rag_eval_datasets ({', '.join(columns)}) "
                f"VALUES ({', '.join(['%s'] * len(columns))})",
                values,
            )
            connection.commit()

    def list_datasets(self, *, dataset_kind=None, lifecycle_status=None, page=1, page_size=50):
        where, values = _list_filters(dataset_kind, lifecycle_status)
        columns = _metadata_columns()
        with _strong_read_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM rag_eval_datasets {where}", values)
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"SELECT {', '.join(columns)} FROM rag_eval_datasets {where} "
                "ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
                [*values, page_size, (page - 1) * page_size],
            )
            rows = [self._row_to_dict(row, columns) for row in cursor.fetchall()]
        return rows, total

    def list_revisions(self, dataset_id, *, page=1, page_size=50):
        columns = _metadata_columns()
        with _strong_read_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM rag_eval_datasets WHERE dataset_id = %s", (dataset_id,))
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"SELECT {', '.join(columns)} FROM rag_eval_datasets WHERE dataset_id = %s "
                "ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
                (dataset_id, page_size, (page - 1) * page_size),
            )
            rows = [self._row_to_dict(row, columns) for row in cursor.fetchall()]
        return rows, total


def _strong_read_connection():
    from app.db import get_read_connection

    return get_read_connection(consistency="strong")


def _metadata_columns() -> tuple[str, ...]:
    return (
        "dataset_id", "dataset_revision", "dataset_kind", "schema_version",
        "content_sha256", "sample_count", "storage_uri", "binding_mode",
        "binding_json", "lifecycle_status", "created_at",
    )


def _list_filters(dataset_kind: str | None, lifecycle_status: str | None) -> tuple[str, list[Any]]:
    conditions: list[str] = []
    values: list[Any] = []
    if dataset_kind is not None:
        conditions.append("dataset_kind = %s")
        values.append(dataset_kind)
    if lifecycle_status is not None:
        conditions.append("lifecycle_status = %s")
        values.append(lifecycle_status)
    return (f"WHERE {' AND '.join(conditions)}" if conditions else "", values)


class DatasetRegistry:
    def __init__(self, root: Path, repository=None) -> None:
        self.root = Path(root).resolve()
        self.repository = repository if repository is not None else MysqlDatasetRepository()

    def register(self, bundle: dict[str, Any]) -> dict[str, Any]:
        """规范化题集、写入文件快照，并以内容哈希登记不可变版本。"""
        canonical, samples = normalize_dataset_payload(bundle)
        dataset_id = str(canonical["dataset_id"]).strip()
        dataset_revision = str(canonical["dataset_revision"]).strip()
        self._validate_identity(dataset_id, dataset_revision, canonical["dataset_kind"])
        canonical["dataset_id"] = dataset_id
        canonical["dataset_revision"] = dataset_revision
        canonical["samples"] = samples
        serialized = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        content_sha256 = hashlib.sha256(serialized).hexdigest()
        reference = DatasetRef(dataset_id, dataset_revision)
        existing = self.repository.find(reference)
        if existing:
            if existing["content_sha256"] != content_sha256:
                raise DatasetRevisionConflict(f"dataset revision already registered: {dataset_id}@{dataset_revision}")
            return existing

        relative_path = Path(dataset_id) / dataset_revision / f"{content_sha256}.json"
        snapshot = self._resolve_storage_path(relative_path)
        metadata = self._metadata(canonical, samples, content_sha256, relative_path)
        created = False
        try:
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            try:
                with snapshot.open("xb") as handle:
                    handle.write(serialized)
                created = True
            except FileExistsError:
                if snapshot.read_bytes() != serialized:
                    raise DatasetRevisionConflict(f"snapshot hash collision: {relative_path}")
            self.repository.insert(metadata)
        except Exception:
            registered = self.repository.find(reference)
            if registered and registered.get("content_sha256") == content_sha256:
                return registered
            if created:
                try:
                    snapshot.unlink()
                except OSError:
                    pass
            if registered:
                raise DatasetRevisionConflict(
                    f"dataset revision already registered: {dataset_id}@{dataset_revision}"
                )
            raise
        return metadata

    def list_datasets(self, *, dataset_kind=None, lifecycle_status=None, page=1, page_size=50) -> dict[str, Any]:
        page, page_size = _validate_pagination(page, page_size)
        rows, total = self.repository.list_datasets(
            dataset_kind=dataset_kind, lifecycle_status=lifecycle_status, page=page, page_size=page_size,
        )
        return {"items": [_public_metadata(row) for row in rows], "page": page, "page_size": page_size, "total": total}

    def list_revisions(self, dataset_id: str, *, page=1, page_size=50) -> dict[str, Any]:
        if not _IDENTITY_PATTERN.fullmatch(dataset_id):
            raise ValueError("invalid dataset_id")
        page, page_size = _validate_pagination(page, page_size)
        rows, total = self.repository.list_revisions(dataset_id, page=page, page_size=page_size)
        return {"items": [_public_metadata(row) for row in rows], "page": page, "page_size": page_size, "total": total}

    def resolve(self, reference: DatasetRef | Mapping[str, Any]) -> dict[str, Any]:
        reference = _coerce_reference(reference)
        metadata = self.repository.find(reference)
        if not metadata:
            raise ValueError("dataset revision is not registered")
        storage_uri = str(metadata.get("storage_uri") or "")
        if Path(storage_uri).is_absolute():
            raise ValueError("dataset storage URI must be relative")
        snapshot = self._resolve_storage_path(Path(storage_uri))
        try:
            serialized = snapshot.read_bytes()
        except OSError as exc:
            raise ValueError("dataset snapshot is unavailable") from exc
        if hashlib.sha256(serialized).hexdigest() != metadata.get("content_sha256"):
            raise ValueError("dataset snapshot hash mismatch")
        try:
            payload = json.loads(serialized)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("dataset snapshot is invalid") from exc
        if payload.get("dataset_id") != reference.dataset_id or payload.get("dataset_revision") != reference.dataset_revision:
            raise ValueError("dataset snapshot identity mismatch")
        return {**metadata, "bundle": payload}

    def _validate_identity(self, dataset_id: str, dataset_revision: str, dataset_kind: Any) -> None:
        if not _IDENTITY_PATTERN.fullmatch(dataset_id):
            raise ValueError("invalid dataset_id")
        if not _REVISION_PATTERN.fullmatch(dataset_revision):
            raise ValueError("invalid dataset_revision")
        if dataset_kind not in DATASET_KINDS:
            raise ValueError("unsupported dataset_kind")

    def _resolve_storage_path(self, storage_uri: Path) -> Path:
        candidate = (self.root / storage_uri).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("dataset storage path escapes root") from exc
        return candidate

    @staticmethod
    def _metadata(canonical, samples, content_sha256, relative_path) -> dict[str, Any]:
        source_snapshot = canonical.get("source_snapshot") or {}
        is_bound = canonical["dataset_kind"] in {"generated_candidate", "gold_regression"} and bool(
            source_snapshot.get("index_version") or source_snapshot.get("bound_index_version")
        )
        return {
            "dataset_id": canonical["dataset_id"], "dataset_revision": canonical["dataset_revision"],
            "dataset_kind": canonical["dataset_kind"], "schema_version": canonical["schema_version"],
            "content_sha256": content_sha256, "sample_count": len(samples),
            "storage_uri": relative_path.as_posix(), "binding_mode": "index_bound" if is_bound else "portable",
            "binding_json": dict(source_snapshot), "lifecycle_status": "registered",
            "created_at": datetime.now(timezone.utc).replace(tzinfo=None),
        }


def _coerce_reference(reference: DatasetRef | Mapping[str, Any]) -> DatasetRef:
    if isinstance(reference, DatasetRef):
        return reference
    try:
        dataset_id = str(reference["dataset_id"])
        dataset_revision = str(reference["dataset_revision"])
    except (KeyError, TypeError) as exc:
        raise ValueError("dataset reference is invalid") from exc
    if not _IDENTITY_PATTERN.fullmatch(dataset_id) or not _REVISION_PATTERN.fullmatch(dataset_revision):
        raise ValueError("dataset reference is invalid")
    return DatasetRef(dataset_id, dataset_revision)


def _validate_pagination(page: int, page_size: int) -> tuple[int, int]:
    if not isinstance(page, int) or page < 1:
        raise ValueError("page must be at least 1")
    if not isinstance(page_size, int) or not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    return page, page_size


def _public_metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "samples"}
