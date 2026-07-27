"""多模态生产默认配置的无网络解析层。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import sha256_bytes


ROOT = Path(__file__).resolve().parents[3]
DEFAULTS_PATH = Path(__file__).with_name("production_defaults.json")


def load_production_defaults(path: Path = DEFAULTS_PATH) -> dict[str, Any]:
    """读取并校验冻结配置的必要字段。"""
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schema_version") != "multimodal_production_defaults_v1":
        raise ValueError("unsupported multimodal production defaults schema")
    if not config.get("sources") or not config.get("evaluation", {}).get("dataset_path"):
        raise ValueError("production defaults require sources and an evaluation dataset")
    return config


def production_source_paths(config: dict[str, Any] | None = None) -> list[Path]:
    """解析并核验冻结来源，拒绝路径逃逸、缺失文件或内容漂移。"""
    config = config or load_production_defaults()
    paths: list[Path] = []
    for source in config["sources"]:
        relative = Path(source["path"])
        path = (ROOT / relative).resolve()
        try:
            path.relative_to(ROOT)
        except ValueError as exc:
            raise ValueError("production source must stay inside the repository") from exc
        if not path.is_file():
            if source.get("required", False):
                raise FileNotFoundError(f"required production source is missing: {relative.as_posix()}")
            continue
        if sha256_bytes(path.read_bytes()) != source["sha256"]:
            raise ValueError(f"production source hash mismatch: {relative.as_posix()}")
        paths.append(path)
    return paths


def resolve_production_embedding_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """从受版本控制的冻结配置解析本地 embedding，不读取旧医疗环境变量。"""
    config = config or load_production_defaults()
    embedding = config["embedding"]
    if embedding["provider"] != "huggingface":
        raise ValueError("only the frozen local huggingface embedding is supported")
    model_path = ROOT / "Agent" / "knowledge_base" / "models" / embedding["model"]
    path_exists = model_path.is_dir()
    actual_dimension = None
    model_config = model_path / "config.json"
    if model_config.is_file():
        actual_dimension = json.loads(model_config.read_text(encoding="utf-8")).get("hidden_size")
    if actual_dimension is not None and actual_dimension != embedding["dimension"]:
        raise ValueError("frozen embedding dimension does not match local model config")
    return {
        "status": "ready" if path_exists else "missing",
        "mode": "local",
        "provider": embedding["provider"],
        "provider_setting": "frozen",
        "model": embedding["model"],
        "dimension": embedding["dimension"],
        "normalized": embedding["normalized"],
        "path": str(model_path.resolve()),
        "path_exists": path_exists,
        "missing": [] if path_exists else [str(model_path)],
        "message": "本地模型目录存在" if path_exists else "冻结的本地 embedding 模型目录不存在",
    }
