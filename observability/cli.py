"""离线维护 CLI 的标准输出辅助。"""

from __future__ import annotations

import sys


def write_cli_output(payload: str) -> None:
    """向 stdout 写入一条完整 CLI 输出，并补齐单个结尾换行。"""
    if not isinstance(payload, str):
        raise TypeError("CLI 输出必须是字符串")
    sys.stdout.write(payload)
    if not payload.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()


__all__ = ["write_cli_output"]
