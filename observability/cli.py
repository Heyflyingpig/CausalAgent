"""共享离线 CLI 输出适配器。"""

from __future__ import annotations

import sys


def write_cli_output(text: str) -> None:
    """将离线命令结果写到标准输出，并统一补充换行。"""

    sys.stdout.write(f"{text}\n")


__all__ = ["write_cli_output"]
