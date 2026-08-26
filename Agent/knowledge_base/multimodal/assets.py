"""本地不可变资源存储。"""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath


class AssetStore:
    """把多模态原件写入受限的本地相对路径空间。"""

    def __init__(self, root: Path) -> None:
        """初始化资源根目录，不创建根目录外的任何文件。"""
        self.root = root.resolve()

    def put(self, document_id: str, name: str, content: bytes, category: str = "images") -> str:
        """不可变写入资源，并返回相对 POSIX URI。"""
        safe_name = Path(name).name
        if safe_name != name or not safe_name:
            raise ValueError("asset name must not contain a path")
        if len(safe_name.encode("utf-8")) > 80:
            safe_name = hashlib.sha256(safe_name.encode("utf-8")).hexdigest()[:24] + Path(safe_name).suffix
        uri = PurePosixPath(document_id) / category / safe_name
        path = self._path(uri.as_posix())
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != content:
            digest = hashlib.sha256(content).hexdigest()[:12]
            path = path.with_name(f"{path.stem}_{digest}{path.suffix}")
            uri = PurePosixPath(document_id) / category / path.name
        if not path.exists():
            path.write_bytes(content)
        return uri.as_posix()

    def read(self, asset_uri: str) -> bytes:
        """读取已验证的本地资源。"""
        return self._path(asset_uri).read_bytes()

    def exists(self, asset_uri: str) -> bool:
        """检查资源是否位于本地允许目录且存在。"""
        try:
            return self._path(asset_uri).is_file()
        except ValueError:
            return False

    def _path(self, asset_uri: str) -> Path:
        """解析 URI 并拒绝绝对路径和目录逃逸。"""
        if not asset_uri or "\\" in asset_uri:
            raise ValueError("asset_uri must be a relative POSIX path")
        pure = PurePosixPath(asset_uri)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError("asset_uri escapes asset root")
        path = (self.root / Path(*pure.parts)).resolve()
        if self.root != path and self.root not in path.parents:
            raise ValueError("asset_uri escapes asset root")
        return path
