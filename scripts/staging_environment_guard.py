"""阻断带生产标识的预发容器启动。"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping


_IDENTIFIER_KEYS = ("MYSQL_DATABASE", "MYSQL_HOST", "MYSQL_WRITE_HOST", "MYSQL_READ_HOSTS", "COMPOSE_PROJECT_NAME", "STAGING_VOLUME_NAMES")
_PRODUCTION_IDENTIFIER = re.compile(r"(?:^|[-_./:@])prod(?:$|[-_./:@])|production", re.IGNORECASE)


def validate_staging_environment(environment: Mapping[str, str]) -> None:
    """拒绝任何指向生产标识的 DSN、数据库、Compose 项目或卷名。"""
    for key in _IDENTIFIER_KEYS:
        value = str(environment.get(key) or "")
        if value and _PRODUCTION_IDENTIFIER.search(value):
            raise ValueError(f"production identifier rejected in {key}")


def main() -> int:
    validate_staging_environment(os.environ)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
