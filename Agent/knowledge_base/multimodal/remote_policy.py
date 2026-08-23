"""远程视觉资料范围与固定抽样策略。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


class RemoteSamplePolicy:
    """只允许已记录的页面或公开数据集固定文件进入远程视觉调用。"""

    def __init__(self, manifest_path: Path | None = None) -> None:
        """加载仓库内不可变的抽样清单。"""
        self.manifest_path = manifest_path or Path(__file__).with_name("remote_samples.json")
        self.payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))

    @property
    def policy_sha256(self) -> str:
        """返回白名单文件字节哈希，供 manifest 版本化契约使用。"""
        return hashlib.sha256(self.manifest_path.read_bytes()).hexdigest()

    def allows_pearl_page(self, filename: str, page_number: int | None) -> bool:
        """仅允许清单中精确指定的 Pearl 页码。"""
        return page_number is not None and page_number in self.payload["pearl_pdf_pages"].get(filename, [])
