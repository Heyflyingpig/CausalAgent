"""让从仓库根目录执行 pytest 时也能导入桌面包。"""

from __future__ import annotations

import sys
from pathlib import Path


DESKTOP_ROOT = Path(__file__).resolve().parents[1]
if str(DESKTOP_ROOT) not in sys.path:
    sys.path.insert(0, str(DESKTOP_ROOT))

