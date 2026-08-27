"""兼容入口：将执行逻辑委托给 windows-client/causalagent_desktop。"""

from __future__ import annotations

import sys
from pathlib import Path


_desktop_root = Path(__file__).resolve().parent / "windows-client"
if str(_desktop_root) not in sys.path:
    sys.path.insert(0, str(_desktop_root))

from causalagent_desktop.launcher import main


if __name__ == "__main__":
    raise SystemExit(main())
