"""独立的 PostgreSQL checkpoint 配置，供 setup/cleanup worker 使用。"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _load_dotenv_if_available() -> None:
    """在独立命令入口中加载项目根目录 .env，不输出任何敏感值。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    base_dir = Path(__file__).resolve().parents[1]
    env_path = base_dir / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def _int_env(name: str, default: int) -> int:
    """读取一个整数环境变量并保留明确的错误信息。"""
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"配置错误: {name} 必须是整数。") from exc


def _float_env(name: str, default: float) -> float:
    """读取一个浮点环境变量并保留明确的错误信息。"""
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"配置错误: {name} 必须是数字。") from exc


@dataclass(frozen=True)
class CheckpointPostgresConfig:
    """LangGraph checkpoint PostgreSQL 的连接与连接池参数。"""

    host: str
    port: int
    database: str
    user: str
    password: str | None
    connect_timeout_seconds: float
    pool_min_size: int
    pool_max_size: int

    @classmethod
    def from_env(cls) -> "CheckpointPostgresConfig":
        """从环境变量读取 PostgreSQL checkpoint 配置。"""
        _load_dotenv_if_available()
        return cls(
            host=os.getenv("CHECKPOINT_POSTGRES_HOST", "postgres-checkpoint"),
            port=_int_env("CHECKPOINT_POSTGRES_PORT", 5432),
            database=os.getenv("CHECKPOINT_POSTGRES_DATABASE", "causalchat_checkpoints"),
            user=os.getenv("CHECKPOINT_POSTGRES_USER", "causalchat_checkpoint"),
            password=os.getenv("CHECKPOINT_POSTGRES_PASSWORD") or None,
            connect_timeout_seconds=_float_env(
                "CHECKPOINT_POSTGRES_CONNECT_TIMEOUT_SECONDS",
                5.0,
            ),
            pool_min_size=_int_env("CHECKPOINT_POSTGRES_POOL_MIN_SIZE", 1),
            pool_max_size=_int_env("CHECKPOINT_POSTGRES_POOL_MAX_SIZE", 5),
        )

    def missing_required(self) -> list[str]:
        """返回运行连接所需但为空的配置名。"""
        values = {
            "CHECKPOINT_POSTGRES_HOST": self.host,
            "CHECKPOINT_POSTGRES_DATABASE": self.database,
            "CHECKPOINT_POSTGRES_USER": self.user,
            "CHECKPOINT_POSTGRES_PASSWORD": self.password,
        }
        return [name for name, value in values.items() if not value]

    def validate(self, *, require_credentials: bool = False) -> None:
        """校验端口、超时和池大小等不会随环境变化的约束。"""
        if require_credentials:
            missing = self.missing_required()
            if missing:
                raise RuntimeError(f"PostgreSQL checkpoint 配置缺失: {', '.join(missing)}")
        if not 1 <= self.port <= 65535:
            raise ValueError("配置错误: CHECKPOINT_POSTGRES_PORT 必须是有效端口。")
        if self.connect_timeout_seconds <= 0:
            raise ValueError(
                "配置错误: CHECKPOINT_POSTGRES_CONNECT_TIMEOUT_SECONDS 必须大于 0。"
            )
        if self.pool_min_size <= 0:
            raise ValueError("配置错误: CHECKPOINT_POSTGRES_POOL_MIN_SIZE 必须大于 0。")
        if self.pool_max_size < self.pool_min_size:
            raise ValueError(
                "配置错误: CHECKPOINT_POSTGRES_POOL_MAX_SIZE 不能小于 MIN_SIZE。"
            )
