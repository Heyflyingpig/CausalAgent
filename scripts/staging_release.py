"""预发发布三接口的安全门禁。

此模块只校验和编排预发工件；真实 ``docker compose up`` 必须由受控部署
执行器在目标环境中调用，不能因为导入本模块而意外创建资源。
"""

from __future__ import annotations

import re
from typing import Any


_REQUIRED = {"project", "database", "volume", "image_digest", "git_revision", "migration_head", "config_sha256", "matrix_version", "sbom"}
_IDENTIFIER_FIELDS = ("project", "database", "volume", "dsn")
_PRODUCTION_IDENTIFIER = re.compile(r"(?:^|[-_./:@])prod(?:$|[-_./:@])|production", re.IGNORECASE)


def _reject_production_identifiers(manifest: dict[str, Any]) -> None:
    """先拒绝任何已给出的生产标识，避免不完整清单绕过隔离门禁。"""
    for key in _IDENTIFIER_FIELDS:
        value = str(manifest.get(key) or "")
        if value and _PRODUCTION_IDENTIFIER.search(value):
            raise ValueError(f"production identifier rejected in {key}")


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    _reject_production_identifiers(manifest)
    missing = sorted(_REQUIRED - set(manifest))
    if missing:
        raise ValueError(f"manifest missing fields: {', '.join(missing)}")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(manifest["image_digest"])):
        raise ValueError("image_digest must be a sha256 digest")
    for key in ("config_sha256",):
        if not re.fullmatch(r"[0-9a-f]{64}", str(manifest[key])):
            raise ValueError(f"{key} must be a sha256 hex value")
    for key in ("project", "database", "volume", "git_revision", "migration_head", "matrix_version", "sbom"):
        if not str(manifest[key]).strip():
            raise ValueError(f"{key} must not be empty")
    return dict(manifest)


def deploy(manifest: dict[str, Any]) -> dict[str, Any]:
    validated = validate_manifest(manifest)
    return {"status": "validated", "project": validated["project"]}


def run_acceptance(layer: str, confirmation: bool) -> dict[str, Any]:
    if not confirmation:
        raise ValueError("explicit confirmation is required")
    if layer not in {"contract", "integration", "production"}:
        raise ValueError("layer must be contract, integration, or production")
    return {"status": "planned", "layer": layer}


def collect_evidence(release_id: str) -> dict[str, str]:
    if not release_id:
        raise ValueError("release_id is required")
    return {"release_id": release_id, "status": "planned"}
