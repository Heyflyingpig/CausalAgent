"""R5 隔离知识源摄取与 staged index RAG 查询任务。"""

from __future__ import annotations

import json
import hashlib
from io import BytesIO
import logging
import math
import os
import queue
import re
import shutil
import sys
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from werkzeug.utils import secure_filename

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Agent.knowledge_base.multimodal.defaults import (
    production_source_paths,
    resolve_production_embedding_config,
)
from Agent.knowledge_base.multimodal.index import embedding_fingerprint, replace_with_retry
from Agent.knowledge_base.multimodal.parsers import SUPPORTED_SUFFIXES, inspect_source
from Agent.knowledge_base.multimodal.pipeline import MultimodalKnowledgeBaseMaintenance
from Agent.knowledge_base.rag_runtime import RagRuntimeConfig, create_rag_runtime
from Agent.knowledge_base.rag_service import RagService
from Agent.knowledge_base.query_rag import (
    PRODUCTION_RAG_CONFIG_PATH,
    _normalize_question_payload,
)
from config.settings import settings


ISOLATED_RUN_ROOT = Path(
    os.getenv("R5_ISOLATED_RUN_ROOT", str(_PROJECT_ROOT / "tmp" / "r5_isolated_runs"))
).resolve()
R5_SOURCE_ROOT = Path(
    os.getenv("R5_SOURCE_ROOT", str(_PROJECT_ROOT / "tmp" / "r5_sources"))
).resolve()
_RUN_ID_PATTERN = re.compile(r"^[0-9A-Za-z_-]{8,80}$")
_MAX_EVENTS = 500
_MAX_SOURCES = 20
_MAX_QUESTIONS = 100
try:
    _EVALUATION_STALE_AFTER_SECONDS = max(
        int(os.getenv("R5_EVALUATION_STALE_AFTER_SECONDS", "1800")),
        60,
    )
except ValueError:
    _EVALUATION_STALE_AFTER_SECONDS = 1800
_ACTIVE_EVALUATION_STATUSES = {"created", "queued", "running", "cancelling"}


def _remote_data_enabled() -> bool:
    """读取 R5 内测远程视觉开关，默认开启并支持显式关闭。"""
    return os.getenv("VISION_ALLOW_REMOTE_DATA", "true").strip().lower() in {"1", "true", "yes", "on"}


def _remote_data_enabled_for_sources(source_paths: List[Path]) -> bool:
    """在 R5 内测开关开启时为显式选中的来源启用远程视觉。"""
    del source_paths
    return _remote_data_enabled()


def _timestamp() -> str:
    """生成可展示的本地时间戳。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _new_run_id(prefix: str) -> str:
    """生成不会命中旧 staged 版本的运行身份。"""
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:10]}"


def _safe_run_id(run_id: str) -> str:
    """校验外部传入的运行身份，阻止路径逃逸。"""
    value = str(run_id or "").strip()
    if not _RUN_ID_PATTERN.fullmatch(value):
        raise ValueError("invalid isolated run id")
    return value


def _run_dir(run_id: str) -> Path:
    """返回隔离运行目录，并确认它仍位于固定根目录内。"""
    safe_id = _safe_run_id(run_id)
    target = (ISOLATED_RUN_ROOT / safe_id).resolve()
    target.relative_to(ISOLATED_RUN_ROOT)
    return target


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    """原子写入运行状态或结果文件，并吸收 Windows 短暂文件占用。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    replace_with_retry(temporary, path)


def _json_default(value: Any) -> Any:
    """将检索 trace 中的集合稳定转换为 JSON 数组。"""
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _read_json(path: Path) -> Dict[str, Any]:
    """读取隔离运行目录中的 JSON；缺失或损坏时返回空对象。"""
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _public_dataset_identity(identity: Dict[str, Any]) -> Dict[str, Any]:
    """返回题集身份，但不把隔离目录的宿主机路径暴露给 API。"""
    result = dict(identity or {})
    result.pop("dataset_path", None)
    return result


def _parse_timestamp(value: str) -> datetime:
    """解析前端 ISO 时间，并兼容 Python 3.10 对 Z 后缀的限制。"""
    normalized = str(value).strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized)


def _evaluation_last_activity(state: Dict[str, Any]) -> datetime | None:
    """读取评测最近活动时间，兼容旧 run.json 的事件记录。"""
    candidates: List[Any] = [state.get("last_activity_at")]
    if state.get("execution_backend") == "persistent_worker":
        heartbeat_path = _run_dir(str(state.get("run_id") or "")) / "worker_heartbeat.json"
        heartbeat = _read_json(heartbeat_path)
        candidates.insert(0, heartbeat.get("heartbeat_at"))
    events = state.get("events")
    if isinstance(events, list) and events:
        last_event = events[-1]
        if isinstance(last_event, dict):
            candidates.append(last_event.get("timestamp"))
    candidates.extend([state.get("started_at"), state.get("created_at")])
    for value in candidates:
        if not value:
            continue
        try:
            return _parse_timestamp(str(value))
        except (TypeError, ValueError):
            continue
    return None


def _is_stale_evaluation(state: Dict[str, Any], now: datetime | None = None) -> bool:
    """判断运行中评测是否超过无事件活动窗口。"""
    if state.get("kind") != "evaluation" or state.get("status") not in _ACTIVE_EVALUATION_STATUSES:
        return False
    last_activity = _evaluation_last_activity(state)
    if last_activity is None:
        return False
    current = now or datetime.now().astimezone()
    if last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=current.tzinfo)
    return current - last_activity >= timedelta(seconds=_EVALUATION_STALE_AFTER_SECONDS)


def _evaluation_history_record(run_dir: Path, state: Dict[str, Any]) -> Dict[str, Any]:
    """从单次隔离评测目录构造可供 history 和前端比较的摘要。"""
    summary = _read_json(run_dir / "summary.json")
    manifest = _read_json(run_dir / "run_manifest.json")
    config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
    retrieval = config.get("retrieval") if isinstance(config.get("retrieval"), dict) else {}
    ragas = config.get("ragas") if isinstance(config.get("ragas"), dict) else {}
    identity = summary.get("dataset_identity") or state.get("input_identity") or {}
    ingestion_state = _read_json(_run_dir(str(state.get("ingestion_run_id") or "")) / "run.json") if state.get("ingestion_run_id") else {}
    source_ids = ingestion_state.get("source_ids", [])
    source_names = ingestion_state.get("source_names", [])
    return {
        "run_id": state.get("run_id", run_dir.name),
        "kind": "evaluation",
        "status": summary.get("status", state.get("status", "unknown")),
        "status_reason": summary.get("status_reason", ""),
        "created_at": state.get("created_at", ""),
        "started_at": state.get("started_at", ""),
        "finished_at": state.get("finished_at", ""),
        "stale": _is_stale_evaluation(state),
        "ingestion_run_id": summary.get("ingestion_run_id", state.get("ingestion_run_id", "")),
        "index_version": summary.get("index_version", state.get("index_version", "")),
        "source_ids": source_ids if isinstance(source_ids, list) else [],
        "source_names": source_names if isinstance(source_names, list) else [],
        "source_label": "、".join(str(item) for item in source_names) if isinstance(source_names, list) else "",
        "question_count": identity.get("sample_count", state.get("question_count", 0)),
        "dataset_identity": _public_dataset_identity(identity),
        "config_identity": summary.get("config_identity", manifest.get("config_identity", "")),
        "strategy": {
            "profile_id": (
                (config.get("strategy_profile") or {}).get("profile_id", "")
                if isinstance(config.get("strategy_profile"), dict)
                else ""
            ),
            "profile_name": (
                (config.get("strategy_profile") or {}).get("name", "")
                if isinstance(config.get("strategy_profile"), dict)
                else ""
            ),
            "retrieval_profile": retrieval.get("profile", ""),
            "retrieval_overrides": retrieval.get("overrides", {}),
            "ragas_profile": ragas.get("profile", ""),
            "judge_profile": ragas.get("judge_profile", ""),
            "metrics": ragas.get("selected_metrics", []),
        },
        "key_metrics": summary.get("key_metrics", {}),
        "steps": summary.get("steps", []),
        "error": state.get("error", ""),
    }


def _is_number(value: Any) -> bool:
    """判断值是否可安全参与评测指标差值计算。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _metric_deltas(base: Dict[str, Any], candidate: Dict[str, Any]) -> List[Dict[str, Any]]:
    """对两个指标对象做通用数值 diff，保留未评分的 null。"""
    rows = []
    for name in sorted(set(base or {}) | set(candidate or {})):
        base_value = (base or {}).get(name)
        candidate_value = (candidate or {}).get(name)
        rows.append({
            "metric": name,
            "base": base_value,
            "candidate": candidate_value,
            "delta": round(float(candidate_value) - float(base_value), 4)
            if _is_number(base_value) and _is_number(candidate_value)
            else None,
        })
    return rows


def _sample_result_map(run_dir: Path) -> Dict[str, Dict[str, Any]]:
    """按通用 sample_id 聚合单次运行的 retrieval 与 Ragas 逐题结果。"""
    retrieval = _read_json(run_dir / "machine" / "rag_eval_result.json")
    ragas = _read_json(run_dir / "machine" / "ragas_eval_result.json")
    rows: Dict[str, Dict[str, Any]] = {}

    for detail in retrieval.get("details", []):
        if not isinstance(detail, dict):
            continue
        key = str(detail.get("sample_id") or detail.get("question") or "")
        if not key:
            continue
        rows.setdefault(key, {"sample_id": key, "question": detail.get("question", "")})["retrieval"] = {
            "recall": detail.get("recall"),
            "reciprocal_rank": detail.get("reciprocal_rank"),
            "match_mode": detail.get("retrieval_match_mode", ""),
        }

    metadata = ragas.get("metadata", [])
    records = ragas.get("score_records", [])
    bad_cases = {
        str(case.get("question") or ""): case
        for case in (ragas.get("cross_metric_bad_cases", {}) or {}).get("cases", [])
        if isinstance(case, dict)
    }
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        meta = metadata[index] if index < len(metadata) and isinstance(metadata[index], dict) else {}
        key = str(meta.get("sample_id") or meta.get("question") or record.get("user_input") or "")
        if not key:
            continue
        question = str(meta.get("question") or record.get("user_input") or "")
        scores = {name: value for name, value in record.items() if _is_number(value)}
        rows.setdefault(key, {"sample_id": key, "question": question})["ragas"] = scores
        if question in bad_cases:
            rows[key]["bad_case"] = bad_cases[question]
    return rows


def _config_deltas(base: Dict[str, Any], candidate: Dict[str, Any]) -> List[Dict[str, Any]]:
    """按路径比较 retrieval/Ragas 配置，避免绑定任何题集字段。"""
    def flatten(value: Any, prefix: str = "") -> Dict[str, Any]:
        if not isinstance(value, dict):
            return {prefix: value}
        result: Dict[str, Any] = {}
        for key, child in value.items():
            result.update(flatten(child, f"{prefix}.{key}" if prefix else str(key)))
        return result

    base_flat = flatten(base)
    candidate_flat = flatten(candidate)
    return [
        {"field": name, "base": base_flat.get(name), "candidate": candidate_flat.get(name)}
        for name in sorted(set(base_flat) | set(candidate_flat))
        if base_flat.get(name) != candidate_flat.get(name)
    ]


def _pdf_page_count(content: bytes) -> int | None:
    """读取 PDF 页数；上传目录中的损坏文件只返回未知页数，不阻塞目录展示。"""
    try:
        from pypdf import PdfReader

        return len(PdfReader(BytesIO(content)).pages)
    except Exception:
        return None


def _uploaded_source_catalog_records() -> List[tuple[Path, Dict[str, Any]]]:
    """读取独立上传目录中的用户来源，不扫描其它运行产物目录。"""
    if not R5_SOURCE_ROOT.is_dir():
        return []

    catalog: List[tuple[Path, Dict[str, Any]]] = []
    for path in sorted(R5_SOURCE_ROOT.glob("upload_*__*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            content = path.read_bytes()
        except OSError:
            continue
        content_hash = hashlib.sha256(content).hexdigest()
        source_id = f"upload_{content_hash[:24]}"
        _, display_name = path.name.split("__", 1)
        catalog.append((path, {
            "source_id": source_id,
            "name": display_name or path.name,
            "size_bytes": len(content),
            "content_sha256": content_hash,
            "source_kind": "uploaded",
            "page_count": _pdf_page_count(content) if path.suffix.lower() == ".pdf" else 1,
        }))
    return catalog


def _source_catalog_records() -> List[tuple[Path, Dict[str, Any]]]:
    """构造来源目录及其内部路径，内部路径不会进入 HTTP 响应。"""
    catalog: List[tuple[Path, Dict[str, Any]]] = []
    for path in production_source_paths():
        content = path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()
        source_id = "source_" + hashlib.sha256(
            f"{path.name}:{content_hash}".encode("utf-8")
        ).hexdigest()[:20]
        catalog.append((path, {
                "source_id": source_id,
                "name": path.name,
                "size_bytes": len(content),
                "content_sha256": content_hash,
                "source_kind": "frozen",
                "page_count": _pdf_page_count(content),
            }))
    return catalog + _uploaded_source_catalog_records()


def _source_catalog() -> List[Dict[str, Any]]:
    """返回可供页面选择的来源目录，不把宿主路径暴露给调用方。"""
    return [entry for _, entry in _source_catalog_records()]


def list_source_catalog() -> List[Dict[str, Any]]:
    """列出当前可选择的来源，供前端提交显式 source_id。"""
    return _source_catalog()


def register_uploaded_source(filename: str | None, content: bytes) -> Dict[str, Any]:
    """校验并幂等保存一个上传来源，但不启动摄取或远程视觉调用。"""
    original_name = str(filename or "").strip()
    if not original_name:
        raise ValueError("没有选择文件")
    suffix = Path(original_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise ValueError(f"不支持该文件格式，可上传：{supported}")
    if len(content) == 0:
        raise ValueError("上传文件为空")
    if len(content) > settings.MAX_UPLOAD_SIZE_BYTES:
        raise ValueError(f"文件大小不能超过 {settings.MAX_UPLOAD_SIZE_MB}MB")

    content_hash = hashlib.sha256(content).hexdigest()
    source_id = f"upload_{content_hash[:24]}"
    safe_name = secure_filename(Path(original_name).name) or f"document{suffix}"
    R5_SOURCE_ROOT.mkdir(parents=True, exist_ok=True)

    for existing_path, existing in _uploaded_source_catalog_records():
        if existing["source_id"] == source_id:
            return existing

    target = R5_SOURCE_ROOT / f"{source_id}__{safe_name}"
    temporary = R5_SOURCE_ROOT / f".{uuid.uuid4().hex}.{safe_name}"
    temporary.write_bytes(content)
    try:
        issue = inspect_source(temporary)
        if issue is not None:
            raise ValueError(issue.message)
        replace_with_retry(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()

    page_count = _pdf_page_count(content) if suffix == ".pdf" else 1
    if suffix == ".pdf" and (page_count is None or page_count < 1):
        target.unlink(missing_ok=True)
        raise ValueError("上传文件不是可读取的 PDF")
    return {
        "source_id": source_id,
        "name": safe_name,
        "size_bytes": len(content),
        "content_sha256": content_hash,
        "source_kind": "uploaded",
        "page_count": page_count,
    }


def register_uploaded_pdf(filename: str | None, content: bytes) -> Dict[str, Any]:
    """兼容旧调用名；新上传入口统一使用 register_uploaded_source。"""
    return register_uploaded_source(filename, content)


def delete_uploaded_source(source_id: str) -> Dict[str, Any]:
    """删除一个用户上传的来源文件，不删除 staged index、评测或共享知识库。"""
    normalized_id = str(source_id or "").strip()
    if not normalized_id.startswith("upload_"):
        raise ValueError("只能删除用户上传的知识源")

    match = next(
        ((path, entry) for path, entry in _uploaded_source_catalog_records() if entry["source_id"] == normalized_id),
        None,
    )
    if match is None:
        raise KeyError(f"uploaded source not found: {normalized_id}")

    active_runs = []
    if ISOLATED_RUN_ROOT.is_dir():
        for run_dir in ISOLATED_RUN_ROOT.iterdir():
            if not run_dir.is_dir():
                continue
            state = _read_json(run_dir / "run.json")
            if (
                state.get("kind") == "ingestion"
                and state.get("status") in {"created", "running", "cancelling"}
                and normalized_id in state.get("source_ids", [])
            ):
                active_runs.append(str(state.get("run_id") or run_dir.name))
    if active_runs:
        raise RuntimeError(f"知识源正在摄取，暂不能删除：{active_runs[0]}")

    path, entry = match
    path.resolve().relative_to(R5_SOURCE_ROOT.resolve())
    path.unlink()
    return {"source_id": normalized_id, "name": entry["name"], "status": "deleted", "deleted": True}


def _resolve_source_inputs(
    source_ids: List[str] | None,
    sources: List[Dict[str, Any]] | None,
) -> tuple[List[Path], List[str]]:
    """解析来源目录 ID 或显式 URI，格式判断交给摄取解析层。"""
    if source_ids and sources:
        raise ValueError("source_ids and sources cannot be used together")
    if source_ids:
        requested = [str(value).strip() for value in source_ids]
        if not requested or len(requested) > _MAX_SOURCES or any(not value for value in requested):
            raise ValueError(f"source_ids must contain 1 to {_MAX_SOURCES} items")
        records = _source_catalog_records()
        entries = {entry["source_id"]: (path, entry) for path, entry in records}
        missing = [value for value in requested if value not in entries]
        if missing:
            raise ValueError(f"unknown source_id: {missing[0]}")
        ordered_paths = [entries[source_id][0] for source_id in requested]
        return ordered_paths, requested

    if not sources or len(sources) > _MAX_SOURCES:
        raise ValueError(f"sources must contain 1 to {_MAX_SOURCES} items")
    paths: List[Path] = []
    source_names: List[str] = []
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("each source must be an object")
        uri = str(source.get("uri") or "").strip()
        if not uri:
            raise ValueError("each source requires a uri")
        path = Path(uri).expanduser().resolve()
        if not path.is_file() and not path.is_dir():
            raise FileNotFoundError(f"source uri is unavailable: {uri}")
        paths.append(path)
        source_names.append(str(source.get("source_id") or path.name))
    return paths, source_names


def _normalize_page_ranges(
    page_ranges: List[Dict[str, Any]] | None,
    source_paths: List[Path],
    source_names: List[str],
) -> tuple[List[Dict[str, int | str]], Dict[str, tuple[int, int]]]:
    """校验每个来源的物理页范围，并转换为解析层使用的路径映射。"""
    if page_ranges is None:
        return [], {}
    if not isinstance(page_ranges, list) or len(page_ranges) != len(source_paths):
        raise ValueError("page_ranges must contain exactly one range for each selected source")
    selected = dict(zip(source_names, source_paths))
    normalized: Dict[str, Dict[str, int | str]] = {}
    for item in page_ranges:
        if not isinstance(item, dict):
            raise ValueError("each page range must be an object")
        source_id = str(item.get("source_id") or "").strip()
        if source_id in normalized or source_id not in selected:
            raise ValueError(f"page range source_id is not selected: {source_id}")
        start_page = item.get("start_page")
        end_page = item.get("end_page")
        if (
            isinstance(start_page, bool) or not isinstance(start_page, int)
            or isinstance(end_page, bool) or not isinstance(end_page, int)
            or start_page < 1 or end_page < start_page
        ):
            raise ValueError("page range must use positive integers with start_page <= end_page")
        path = selected[source_id]
        page_count = 1
        if path.suffix.lower() == ".pdf":
            from pypdf import PdfReader

            page_count = len(PdfReader(str(path)).pages)
        if end_page > page_count:
            raise ValueError(f"page range exceeds {source_id} page count {page_count}")
        normalized[source_id] = {"source_id": source_id, "start_page": start_page, "end_page": end_page}
    if set(normalized) != set(selected):
        missing = next(source_id for source_id in selected if source_id not in normalized)
        raise ValueError(f"missing page range for selected source: {missing}")
    ordered = [normalized[source_id] for source_id in source_names]
    by_path = {
        str(selected[item["source_id"]].resolve()): (int(item["start_page"]), int(item["end_page"]))
        for item in ordered
    }
    return ordered, by_path


class IsolatedRunManager:
    """管理 R5 隔离运行状态、SSE 事件和 staged index 查询。"""

    def __init__(self) -> None:
        """初始化进程内事件缓存；实际索引产物写入每次独立运行目录。"""
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._queues: Dict[str, queue.Queue] = {}
        self._lock = threading.RLock()

    def start_ingestion(
        self,
        *,
        source_ids: List[str] | None = None,
        sources: List[Dict[str, Any]] | None = None,
        max_pages: int | None = None,
        page_ranges: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """异步摄取显式来源，并返回新的隔离运行身份。"""
        if max_pages is not None and (isinstance(max_pages, bool) or max_pages < 1):
            raise ValueError("max_pages must be positive")
        if max_pages is not None and page_ranges is not None:
            raise ValueError("max_pages and page_ranges cannot be combined")
        source_paths, source_names = _resolve_source_inputs(source_ids, sources)
        normalized_ranges, page_range_map = _normalize_page_ranges(page_ranges, source_paths, source_names)

        run_id = _new_run_id("ingest")
        run_dir = _run_dir(run_id)
        state = {
            "run_id": run_id,
            "kind": "ingestion",
            "source_ids": list(source_ids or []),
            "source_names": source_names,
            "max_pages": max_pages,
            "page_ranges": normalized_ranges,
            "remote_enabled": _remote_data_enabled_for_sources(source_paths),
            "status": "created",
            "created_at": _timestamp(),
            "started_at": "",
            "finished_at": "",
            "current_stage": "",
            "cancel_requested": False,
            "index_version": "",
            "collection_name": "",
            "manifest_sha256": "",
            "unit_count": 0,
            "vector_count": 0,
            "events": [],
        }
        with self._lock:
            self._runs[run_id] = state
            _write_json(run_dir / "run.json", state)
        self._emit(run_id, "run_created", "创建隔离知识源摄取任务", {
            "source_ids": list(source_ids or []),
            "source_count": len(source_paths),
        })

        thread = threading.Thread(
            target=self._run_ingestion,
            args=(run_id, [str(path) for path in source_paths], max_pages, page_range_map),
            daemon=True,
            name=f"r5_ingestion_{run_id}",
        )
        thread.start()
        return self.get(run_id)

    def start_rag_query(
        self,
        ingestion_run_id: str,
        index_version: str,
        questions: List[Dict[str, Any]],
        input_identity: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """在指定摄取运行的 staged index 上异步执行真实检索与回答。"""
        if not questions or len(questions) > _MAX_QUESTIONS:
            raise ValueError(f"questions must contain 1 to {_MAX_QUESTIONS} items")
        for question in questions:
            if not str(question.get("question") or "").strip():
                raise ValueError("each question requires non-empty question text")

        ingestion = self._load(ingestion_run_id)
        if ingestion.get("kind") != "ingestion" or ingestion.get("status") != "staged":
            raise ValueError("ingestion run is not staged and cannot be queried")
        if ingestion.get("index_version") != index_version:
            raise ValueError("index_version does not belong to ingestion run")
        index_dir = _run_dir(ingestion_run_id) / "indexes" / index_version
        self._validate_staged_index(index_dir, ingestion)

        run_id = _new_run_id("rag")
        state = {
            "run_id": run_id,
            "kind": "rag_query",
            "status": "created",
            "created_at": _timestamp(),
            "started_at": "",
            "finished_at": "",
            "current_stage": "",
            "cancel_requested": False,
            "ingestion_run_id": ingestion_run_id,
            "index_version": index_version,
            "question_count": len(questions),
            "input_identity": dict(input_identity or {"schema_version": "isolated_question_v1"}),
            "result_path": str(_run_dir(run_id) / "result.json"),
            "events": [],
        }
        with self._lock:
            self._runs[run_id] = state
            _write_json(_run_dir(run_id) / "run.json", state)
        self._emit(run_id, "run_created", "创建 staged index RAG 测试任务", {"index_version": index_version})

        thread = threading.Thread(
            target=self._run_rag_query,
            args=(run_id, ingestion_run_id, index_version, questions),
            daemon=True,
            name=f"r5_rag_{run_id}",
        )
        thread.start()
        return self.get(run_id)

    def start_evaluation(
        self,
        ingestion_run_id: str,
        index_version: str,
        eval_dataset: Dict[str, Any],
        retrieval_options: Dict[str, Any] | None = None,
        ragas_options: Dict[str, Any] | None = None,
        strategy_profile: Dict[str, Any] | None = None,
        steps: List[str] | None = None,
    ) -> Dict[str, Any]:
        """在指定 staged index 上启动完整 R5 评测流程。"""
        from app.rag_eval.isolated_evaluation import normalize_dataset_payload
        from Agent.knowledge_base.rag.rag_eval.contracts import evaluation_identity

        canonical_dataset, samples = normalize_dataset_payload(eval_dataset)
        if len(samples) > _MAX_QUESTIONS:
            raise ValueError(f"eval_dataset.samples must contain at most {_MAX_QUESTIONS} items")
        ingestion = self._load(ingestion_run_id)
        if ingestion.get("kind") != "ingestion" or ingestion.get("status") != "staged":
            raise ValueError("ingestion run is not staged and cannot be evaluated")
        if ingestion.get("index_version") != index_version:
            raise ValueError("index_version does not belong to ingestion run")
        self._validate_staged_index(_run_dir(ingestion_run_id) / "indexes" / index_version, ingestion)

        run_id = _new_run_id("eval")
        run_dir = _run_dir(run_id)
        dataset_path = run_dir / "dataset_snapshot.json"
        _write_json(dataset_path, canonical_dataset)
        dataset_identity = evaluation_identity(dataset_path)
        dataset_identity.pop("dataset_path", None)
        state = {
            "run_id": run_id,
            "kind": "evaluation",
            "status": "queued",
            "created_at": _timestamp(),
            "started_at": "",
            "finished_at": "",
            "current_stage": "queued",
            "cancel_requested": False,
            "execution_backend": "persistent_worker",
            "job_id": run_id,
            "ingestion_run_id": ingestion_run_id,
            "index_version": index_version,
            "question_count": len(samples),
            "input_identity": dataset_identity,
            "strategy_profile": dict(strategy_profile or {}),
            "retrieval_options": dict(retrieval_options or {}),
            "ragas_options": dict(ragas_options or {}),
            "steps": list(steps or []),
            "dataset_path": str(dataset_path),
            "result_path": str(run_dir / "result.json"),
            "events": [],
        }
        with self._lock:
            self._runs[run_id] = state
            _write_json(run_dir / "run.json", state)
        self._emit(run_id, "run_created", "创建 staged index RAG 评测任务", {
            "index_version": index_version,
            "question_count": len(samples),
        })

        try:
            from app.rag_eval.job_service import enqueue_evaluation

            enqueue_evaluation(
                run_id,
                {
                    "run_id": run_id,
                    "ingestion_run_id": ingestion_run_id,
                    "index_version": index_version,
                    "dataset_path": str(dataset_path),
                },
            )
        except Exception as exc:
            self._set_status(
                run_id,
                "failed",
                finished_at=_timestamp(),
                current_stage="failed",
                error=f"评测任务入队失败: {exc}",
            )
            self._emit(run_id, "run_error", "评测任务入队失败", {"error": str(exc)})
            raise
        return self.get(run_id)

    def get(self, run_id: str) -> Dict[str, Any]:
        """返回单次隔离运行状态。"""
        state = self._load(run_id)
        if state.get("kind") == "evaluation" and _is_stale_evaluation(state):
            self._mark_stale_evaluation(run_id)
            state = self._load(run_id)
        return self._public_state(state)

    def mark_worker_started(self, run_id: str, worker_id: str) -> None:
        """记录评测由哪个持久 worker 接管，并立即建立心跳文件。"""
        self._set_status(
            run_id,
            "running",
            started_at=_timestamp(),
            current_stage="evaluation",
            worker_id=worker_id,
        )
        self.touch_worker_heartbeat(run_id, worker_id)

    def touch_worker_heartbeat(self, run_id: str, worker_id: str) -> None:
        """更新独立心跳文件，避免和 run.json 事件写入互相覆盖。"""
        _write_json(
            _run_dir(run_id) / "worker_heartbeat.json",
            {"run_id": run_id, "worker_id": worker_id, "heartbeat_at": _timestamp()},
        )

    def mark_worker_timeout(self, run_id: str, message: str) -> None:
        """把 worker 失联的评测落盘为失败，并让 SSE 收到终止事件。"""
        state = self._load(run_id)
        if state.get("kind") != "evaluation" or state.get("status") not in _ACTIVE_EVALUATION_STATUSES:
            return
        self._set_status(
            run_id,
            "failed",
            finished_at=_timestamp(),
            current_stage="failed",
            error=message,
            status_reason="worker heartbeat timeout",
        )
        self._emit(run_id, "run_error", "评测 worker 异常退出或心跳超时", {"error": message})

    def _mark_stale_evaluation(self, run_id: str) -> None:
        """在读取失活评测时，将其从 active 收敛为 failed。"""
        message = "评测任务长时间没有活动，已自动标记为失败"
        state = self._load(run_id)
        if state.get("execution_backend") == "persistent_worker":
            try:
                from app.rag_eval.job_service import fail_evaluation

                fail_evaluation(run_id, message)
            except Exception as exc:
                # run.json 仍然必须收敛；SQL 会由下一次 worker reconcile 再检查。
                logging.warning("failed to reconcile stale evaluation job %s: %s", run_id, exc)
        self.mark_worker_timeout(run_id, message)

    def delete_evaluation_run(self, run_id: str, *, force: bool = False) -> Dict[str, Any]:
        """删除已结束或确认失活的隔离评测，不触碰关联摄取目录。"""
        state = self._load(run_id)
        if state.get("kind") != "evaluation":
            raise ValueError("run is not an evaluation")
        stale = _is_stale_evaluation(state)
        if stale and state.get("execution_backend") == "persistent_worker":
            try:
                from app.rag_eval.job_service import fail_evaluation

                fail_evaluation(run_id, "评测任务长时间没有活动，已自动标记为失败")
            except Exception as exc:
                logging.warning("failed to reconcile deleted stale evaluation job %s: %s", run_id, exc)
        if state.get("status") in _ACTIVE_EVALUATION_STATUSES and not (force and stale):
            message = "run is stale; force delete is required" if stale else "run is still running"
            return {"run_id": run_id, "status": "running", "stale": stale, "message": message}

        target = _run_dir(run_id)
        if not target.is_dir():
            raise KeyError(f"isolated evaluation not found: {run_id}")
        with self._lock:
            if state.get("status") in _ACTIVE_EVALUATION_STATUSES:
                state["cancel_requested"] = True
            shutil.rmtree(target)
            self._runs.pop(run_id, None)
            self._queues.pop(run_id, None)
        return {"run_id": run_id, "status": "deleted", "deleted": True}

    def list_ingestion_history(
        self,
        *,
        status: Optional[str] = None,
        source_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """从持久化 run.json 枚举摄取运行，供页面在丢失本地 run id 时恢复。"""
        safe_page = max(int(page or 1), 1)
        safe_page_size = min(max(int(page_size or 50), 1), 100)
        records: List[Dict[str, Any]] = []
        root = ISOLATED_RUN_ROOT
        if root.is_dir():
            for run_dir in root.iterdir():
                if not run_dir.is_dir():
                    continue
                state = _read_json(run_dir / "run.json")
                if state.get("kind") != "ingestion":
                    continue
                if status and state.get("status") != status:
                    continue
                source_ids = state.get("source_ids", [])
                if source_id and source_id not in source_ids:
                    continue
                records.append(self._public_state(state))

        records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        total = len(records)
        total_pages = max((total + safe_page_size - 1) // safe_page_size, 1)
        safe_page = min(safe_page, total_pages)
        start = (safe_page - 1) * safe_page_size
        return {
            "items": records[start:start + safe_page_size],
            "page": safe_page,
            "page_size": safe_page_size,
            "total": total,
            "total_pages": total_pages,
        }

    def get_result(self, run_id: str) -> Dict[str, Any]:
        """读取已完成 RAG 任务的结果，不向调用方暴露内部文件路径。"""
        state = self._load(run_id)
        if state.get("kind") not in {"rag_query", "evaluation"}:
            raise ValueError("run is not a RAG query or evaluation")
        result_path = Path(str(state.get("result_path") or ""))
        if state.get("status") != "succeeded" or not result_path.is_file():
            raise ValueError("run result is not available")
        return json.loads(result_path.read_text(encoding="utf-8"))

    def list_evaluation_history(
        self,
        *,
        dataset_id: Optional[str] = None,
        index_version: Optional[str] = None,
        status: Optional[str] = None,
        source_name: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """列出隔离 evaluation run 摘要，不读取 legacy output 或 active pointer。"""
        safe_page = max(int(page or 1), 1)
        safe_page_size = min(max(int(page_size or 50), 1), 100)
        since_dt = _parse_timestamp(since) if since else None
        until_dt = _parse_timestamp(until) if until else None
        records: List[Dict[str, Any]] = []
        root = ISOLATED_RUN_ROOT
        if root.is_dir():
            for run_dir in root.iterdir():
                if not run_dir.is_dir():
                    continue
                state = _read_json(run_dir / "run.json")
                if state.get("kind") != "evaluation":
                    continue
                record = _evaluation_history_record(run_dir, state)
                identity = record.get("dataset_identity", {})
                if dataset_id and identity.get("dataset_id") != dataset_id:
                    continue
                if index_version and record.get("index_version") != index_version:
                    continue
                if status and record.get("status") != status:
                    continue
                if source_name:
                    source_names = [str(item) for item in record.get("source_names", [])]
                    if source_name not in source_names:
                        continue
                created_at = record.get("created_at", "")
                created_dt = _parse_timestamp(created_at) if created_at else None
                if since_dt and (created_dt is None or created_dt < since_dt):
                    continue
                if until_dt and (created_dt is None or created_dt > until_dt):
                    continue
                records.append(record)

        records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        total = len(records)
        total_pages = max((total + safe_page_size - 1) // safe_page_size, 1)
        safe_page = min(safe_page, total_pages)
        start = (safe_page - 1) * safe_page_size
        return {
            "items": records[start:start + safe_page_size],
            "page": safe_page,
            "page_size": safe_page_size,
            "total": total,
            "total_pages": total_pages,
        }

    def get_evaluation_diff(self, base_run_id: str, candidate_run_id: str) -> Dict[str, Any]:
        """比较两个通用 rag_eval_v1 运行，拒绝跨题集身份的伪 A/B。"""
        base_state = self._load(base_run_id)
        candidate_state = self._load(candidate_run_id)
        if base_state.get("kind") != "evaluation" or candidate_state.get("kind") != "evaluation":
            raise ValueError("both runs must be evaluations")

        base_dir = _run_dir(base_run_id)
        candidate_dir = _run_dir(candidate_run_id)
        base_record = _evaluation_history_record(base_dir, base_state)
        candidate_record = _evaluation_history_record(candidate_dir, candidate_state)
        if base_record.get("dataset_identity") != candidate_record.get("dataset_identity"):
            raise ValueError("evaluation runs use different dataset identities")

        base_samples = _sample_result_map(base_dir)
        candidate_samples = _sample_result_map(candidate_dir)
        sample_deltas = []
        for sample_id in sorted(set(base_samples) | set(candidate_samples)):
            base_sample = base_samples.get(sample_id, {})
            candidate_sample = candidate_samples.get(sample_id, {})
            metric_rows = _metric_deltas(
                {
                    **(base_sample.get("retrieval") or {}),
                    **(base_sample.get("ragas") or {}),
                },
                {
                    **(candidate_sample.get("retrieval") or {}),
                    **(candidate_sample.get("ragas") or {}),
                },
            )
            deltas = [row["delta"] for row in metric_rows if row["delta"] is not None]
            if not deltas:
                classification = "unscored"
            elif all(delta == 0 for delta in deltas):
                classification = "unchanged"
            elif any(delta > 0 for delta in deltas) and any(delta < 0 for delta in deltas):
                classification = "mixed"
            elif any(delta > 0 for delta in deltas):
                classification = "improved"
            else:
                classification = "regressed"
            sample_deltas.append({
                "sample_id": sample_id,
                "question": candidate_sample.get("question") or base_sample.get("question", ""),
                "classification": classification,
                "metrics": metric_rows,
                "base_bad_case": bool(base_sample.get("bad_case")),
                "candidate_bad_case": bool(candidate_sample.get("bad_case")),
            })

        base_config = _read_json(base_dir / "run_manifest.json").get("config", {})
        candidate_config = _read_json(candidate_dir / "run_manifest.json").get("config", {})
        return {
            "available": True,
            "base": base_record,
            "candidate": candidate_record,
            "metric_deltas": _metric_deltas(
                base_record.get("key_metrics", {}),
                candidate_record.get("key_metrics", {}),
            ),
            "config_deltas": _config_deltas(base_config, candidate_config),
            "sample_deltas": sample_deltas,
            "summary": {
                "sample_count": len(sample_deltas),
                "improved_count": sum(item["classification"] == "improved" for item in sample_deltas),
                "regressed_count": sum(item["classification"] == "regressed" for item in sample_deltas),
                "persistent_bad_case_count": sum(
                    item["base_bad_case"] and item["candidate_bad_case"] for item in sample_deltas
                ),
            },
        }

    def get_artifact_path(self, run_id: str, artifact_name: str) -> Path:
        """解析评测产物路径并阻止跳出该次评测目录。"""
        state = self._load(run_id)
        if state.get("kind") != "evaluation":
            raise ValueError("run is not an evaluation")
        name = str(artifact_name or "").replace("\\", "/").lstrip("/")
        if not name or ".." in Path(name).parts:
            raise ValueError("invalid artifact name")
        root = _run_dir(run_id).resolve()
        path = (root / name).resolve()
        path.relative_to(root)
        if not path.is_file():
            raise KeyError(f"evaluation artifact not found: {name}")
        return path

    def subscribe(self, run_id: str) -> queue.Queue:
        """订阅并回放隔离运行事件。"""
        state = self._load(run_id)
        with self._lock:
            event_queue: queue.Queue = queue.Queue(maxsize=512)
            self._queues[run_id] = event_queue
            for event in state.get("events", []):
                try:
                    event_queue.put_nowait(event)
                except queue.Full:
                    break
            return event_queue

    def unsubscribe(self, run_id: str) -> None:
        """解除 SSE 订阅。"""
        with self._lock:
            self._queues.pop(run_id, None)

    def read_events(self, run_id: str, after_index: int = 0) -> tuple[list[Dict[str, Any]], int]:
        """从 run.json 读取跨进程事件，返回事件和新的列表游标。"""
        state = self._load(run_id)
        events = state.get("events") if isinstance(state.get("events"), list) else []
        start = min(max(int(after_index or 0), 0), len(events))
        selected = [event for event in events[start:] if isinstance(event, dict)]
        return selected, len(events)

    def cancel(self, run_id: str) -> Dict[str, Any]:
        """请求在当前页或当前问题完成后取消任务。"""
        state = self._load(run_id)
        if state.get("status") not in {"created", "running", "cancelling"}:
            return self._public_state(state)
        self._set_status(run_id, "cancelling", cancel_requested=True)
        self._emit(run_id, "cancel_requested", "已请求取消，等待当前阶段结束", {})
        if state.get("kind") == "evaluation" and state.get("execution_backend") == "persistent_worker":
            from app.rag_eval.job_service import cancel_evaluation

            job = cancel_evaluation(run_id)
            if job and job.get("status") == "cancelled":
                self._set_status(
                    run_id,
                    "cancelled",
                    finished_at=_timestamp(),
                    current_stage="cancelled",
                    error="cancelled by user",
                )
                self._emit(run_id, "run_cancelled", "评测任务已取消", {"error": "cancelled by user"})
        return self.get(run_id)

    def _run_ingestion(
        self,
        run_id: str,
        sources: List[str],
        max_pages: int | None = None,
        page_ranges: Dict[str, tuple[int, int]] | None = None,
    ) -> None:
        """执行隔离摄取；旧 index_root、asset_root 和 active pointer 不参与。"""
        run_dir = _run_dir(run_id)
        maintenance = MultimodalKnowledgeBaseMaintenance(
            asset_root=run_dir / "assets",
            index_root=run_dir / "indexes",
            active_config=run_dir / "active_index.json",
        )
        remote_enabled = _remote_data_enabled_for_sources([Path(source) for source in sources])
        self._emit(run_id, "stage_start", "开始解析并构建 staged Chroma", {"stage": "ingest"})
        self._set_status(run_id, "running", started_at=_timestamp(), current_stage="ingest")
        try:
            result = maintenance.ingest(
                sources,
                allow_remote_data=remote_enabled,
                auto_outbound_manifest=remote_enabled,
                progress_callback=lambda event: self._emit(
                    run_id,
                    "ingestion_progress",
                    event.get("message", "摄取处理中"),
                    event,
                ),
                cancel_check=lambda: bool(self._load(run_id).get("cancel_requested")),
                max_pages=max_pages,
                page_ranges=page_ranges or None,
            )
            index_version = str(result["index_version"])
            collection_name = f"{maintenance.collection_prefix}_{index_version}"
            manifest_path = run_dir / "indexes" / index_version / "manifest.json"
            self._set_status(
                run_id,
                "staged",
                finished_at=_timestamp(),
                current_stage="staged",
                index_version=index_version,
                collection_name=collection_name,
                manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                unit_count=int(result.get("unit_count", 0)),
                vector_count=int(result.get("vector_count", 0)),
            )
            self._emit(run_id, "run_done", "知识源已完成解析、嵌入和 staged Chroma 写入", {
                "status": "staged",
                "index_version": index_version,
                "unit_count": result.get("unit_count", 0),
                "vector_count": result.get("vector_count", 0),
            })
        except InterruptedError as exc:
            self._set_status(run_id, "cancelled", finished_at=_timestamp(), current_stage="cancelled", error=str(exc))
            self._emit(run_id, "run_cancelled", "知识源摄取已取消", {"error": str(exc)})
        except Exception as exc:
            self._set_status(run_id, "failed", finished_at=_timestamp(), current_stage="failed", error=str(exc))
            self._emit(run_id, "run_error", f"知识源摄取失败: {type(exc).__name__}", {"error": str(exc)})

    def _run_rag_query(
        self,
        run_id: str,
        ingestion_run_id: str,
        index_version: str,
        questions: List[Dict[str, Any]],
    ) -> None:
        """在隔离 staged index 上执行检索、回答和结果落盘。"""
        self._set_status(run_id, "running", started_at=_timestamp(), current_stage="runtime")
        try:
            service = self._create_isolated_rag_service(ingestion_run_id, index_version)
            retrieval_config = service._load_retrieval_config()
            results: List[Dict[str, Any]] = []
            for index, raw_question in enumerate(questions, start=1):
                if self._load(run_id).get("cancel_requested"):
                    raise InterruptedError("isolated RAG query was cancelled")
                question_payload = _normalize_question_payload(raw_question)
                question = question_payload["question"].strip()
                self._set_status(run_id, "running", current_stage="retrieval", question_index=index)
                self._emit(run_id, "question_start", f"检索第 {index}/{len(questions)} 个问题", {"question_index": index, "question": question})
                trace = service.build_retrieval_trace(question, config=retrieval_config)
                evidence = trace["evidence_payload"]
                self._set_status(run_id, "running", current_stage="answer", question_index=index)
                answer = service.answer_question(question_payload, evidence)
                results.append({
                    "sample_id": raw_question.get("sample_id"),
                    "question": question,
                    "trace": trace,
                    "answer": answer,
                })
                self._emit(run_id, "question_done", f"完成第 {index}/{len(questions)} 个问题", {"question_index": index, "evidence_count": len(evidence)})

            result = {
                "schema_version": "isolated_rag_query_v1",
                "run_id": run_id,
                "ingestion_run_id": ingestion_run_id,
                "index_version": index_version,
                "input_identity": self._load(run_id).get("input_identity", {}),
                "question_count": len(results),
                "results": results,
            }
            result_path = Path(self._load(run_id)["result_path"])
            _write_json(result_path, result)
            self._set_status(run_id, "succeeded", finished_at=_timestamp(), current_stage="done", result_path=str(result_path))
            self._emit(run_id, "run_done", "staged index RAG 测试完成", {"status": "succeeded", "result_available": True, "question_count": len(results)})
        except InterruptedError as exc:
            self._set_status(run_id, "cancelled", finished_at=_timestamp(), current_stage="cancelled", error=str(exc))
            self._emit(run_id, "run_cancelled", "staged index RAG 测试已取消", {"error": str(exc)})
        except Exception as exc:
            self._set_status(run_id, "failed", finished_at=_timestamp(), current_stage="failed", error=str(exc))
            self._emit(run_id, "run_error", f"staged index RAG 测试失败: {type(exc).__name__}", {"error": str(exc)})

    def run_evaluation_sync(self, run_id: str) -> None:
        """由持久 worker 同步执行一个已入队的隔离评测。"""
        state = self._load(run_id)
        ingestion_run_id = str(state.get("ingestion_run_id") or "")
        index_version = str(state.get("index_version") or "")
        self._set_status(
            run_id,
            "running",
            started_at=state.get("started_at") or _timestamp(),
            current_stage="evaluation",
        )
        try:
            from app.rag_eval.isolated_evaluation import execute_isolated_evaluation

            state = self._load(run_id)
            result = execute_isolated_evaluation(
                run_id=run_id,
                ingestion_run_id=ingestion_run_id,
                index_version=index_version,
                dataset_path=Path(state["dataset_path"]),
                output_dir=_run_dir(run_id),
                service=self._create_isolated_rag_service(ingestion_run_id, index_version),
                retrieval_options=state.get("retrieval_options"),
                ragas_options=state.get("ragas_options"),
                strategy_profile=state.get("strategy_profile"),
                steps=state.get("steps"),
                event_callback=lambda event_type, message, data: self._emit(run_id, event_type, message, data),
                cancel_checker=lambda: bool(self._load(run_id).get("cancel_requested")),
            )
            self._set_status(
                run_id,
                "succeeded",
                finished_at=_timestamp(),
                current_stage="done",
                result_path=str(_run_dir(run_id) / "result.json"),
                summary=result.get("summary", {}),
            )
            self._emit(run_id, "run_done", "隔离评测流程完成", {
                "status": result.get("summary", {}).get("status", "unknown"),
                "result_available": True,
            })
        except InterruptedError as exc:
            self._set_status(run_id, "cancelled", finished_at=_timestamp(), current_stage="cancelled", error=str(exc))
            self._emit(run_id, "run_cancelled", "隔离评测已取消", {"error": str(exc)})
        except Exception as exc:
            self._set_status(run_id, "failed", finished_at=_timestamp(), current_stage="failed", error=str(exc))
            self._emit(run_id, "run_error", f"隔离评测失败: {type(exc).__name__}", {"error": str(exc)})

    def _run_evaluation(self, run_id: str, ingestion_run_id: str, index_version: str) -> None:
        """兼容旧调用点；新的评测入口由 persistent worker 调用同步执行。"""
        del ingestion_run_id, index_version
        self.run_evaluation_sync(run_id)

    def _create_isolated_rag_service(self, ingestion_run_id: str, index_version: str) -> RagService:
        """以显式 staged index identity 创建 RAG Service，不读取 active pointer。"""
        ingestion = self._load(ingestion_run_id)
        index_dir = _run_dir(ingestion_run_id) / "indexes" / index_version
        self._validate_staged_index(index_dir, ingestion)
        embedding_config = resolve_production_embedding_config()
        runtime_config = RagRuntimeConfig(
            vector_db_dir=str(index_dir / "chroma"),
            collection_name=str(ingestion["collection_name"]),
            production_config_path=PRODUCTION_RAG_CONFIG_PATH,
            embedding_config=embedding_config,
            release_id=f"isolated:{ingestion_run_id}:{index_version}",
        )
        from langchain_openai import ChatOpenAI

        answer_llm = ChatOpenAI(api_key=settings.API_KEY, base_url=settings.BASE_URL, model=settings.MODEL)
        return RagService(create_rag_runtime(runtime_config, answer_llm))

    @staticmethod
    def _validate_staged_index(index_dir: Path, ingestion: Dict[str, Any]) -> None:
        """校验 staged 版本完整性与 embedding 指纹后才允许进入 RAG。"""
        required = ("manifest.json", "units.jsonl", "build_state.json")
        if any(not (index_dir / name).is_file() for name in required):
            raise ValueError("staged index is incomplete")
        state = json.loads((index_dir / "build_state.json").read_text(encoding="utf-8"))
        if state.get("status") != "staged_complete":
            raise ValueError("staged index is not complete")
        if state.get("unit_count") != state.get("vector_count"):
            raise ValueError("staged index unit/vector count mismatch")
        if ingestion.get("vector_count") != state.get("vector_count"):
            raise ValueError("staged index does not match ingestion run")
        manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("index_version") != index_dir.name:
            raise ValueError("staged index version mismatch")
        if manifest.get("embedding") != embedding_fingerprint():
            raise ValueError("staged index embedding fingerprint mismatch")
        if not (index_dir / "chroma").is_dir():
            raise ValueError("staged Chroma directory is missing")

    def _load(self, run_id: str) -> Dict[str, Any]:
        """读取内存状态或隔离目录中的持久化运行状态。"""
        safe_id = _safe_run_id(run_id)
        path = _run_dir(safe_id) / "run.json"
        if path.is_file():
            state = json.loads(path.read_text(encoding="utf-8"))
        else:
            with self._lock:
                state = self._runs.get(safe_id)
            if state is None:
                raise KeyError(f"isolated run not found: {safe_id}")
        with self._lock:
            self._runs[safe_id] = state
        return state

    def _set_status(self, run_id: str, status: str, **fields: Any) -> None:
        """更新运行状态并同步到 run.json。"""
        with self._lock:
            state = self._load(run_id)
            state.update({"status": status, "last_activity_at": _timestamp(), **fields})
            _write_json(_run_dir(run_id) / "run.json", state)

    def _emit(self, run_id: str, event_type: str, message: str, data: Dict[str, Any]) -> None:
        """记录事件并推送到 SSE；事件推送失败不能改变任务结果。"""
        event = {"type": event_type, "message": message, "timestamp": _timestamp(), "data": data}
        with self._lock:
            state = self._load(run_id)
            state.setdefault("events", []).append(event)
            state["events"] = state["events"][-_MAX_EVENTS:]
            state["last_activity_at"] = event["timestamp"]
            _write_json(_run_dir(run_id) / "run.json", state)
            event_queue = self._queues.get(run_id)
        if event_queue is not None:
            try:
                event_queue.put(event, timeout=1)
            except queue.Full:
                pass

    @staticmethod
    def _public_state(state: Dict[str, Any]) -> Dict[str, Any]:
        """复制可返回前端的状态，隐藏内部路径与运行控制对象。"""
        public = dict(state)
        public.pop("root", None)
        public.pop("result_path", None)
        public.pop("dataset_path", None)
        public["events"] = list(state.get("events", []))
        public["result_available"] = bool(
            state.get("kind") in {"rag_query", "evaluation"}
            and state.get("status") == "succeeded"
        )
        if state.get("kind") == "evaluation":
            public["stale"] = _is_stale_evaluation(state)
        return public


isolated_run_manager = IsolatedRunManager()
