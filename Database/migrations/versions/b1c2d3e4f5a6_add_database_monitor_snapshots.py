"""add database monitor snapshots

Revision ID: b1c2d3e4f5a6
Revises: a8b9c0d1e2f3
Create Date: 2026-07-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建跨 Web 进程共享的数据库监控快照表。"""
    op.execute("""
        CREATE TABLE database_monitor_snapshots (
            snapshot_key VARCHAR(32) PRIMARY KEY,
            payload_json JSON DEFAULT NULL,
            observed_at DATETIME(6) DEFAULT NULL,
            refresh_requested_at DATETIME(6) DEFAULT NULL,
            updated_at DATETIME(6) NOT NULL
                DEFAULT CURRENT_TIMESTAMP(6)
                ON UPDATE CURRENT_TIMESTAMP(6)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    op.execute("""
        INSERT INTO database_monitor_snapshots (snapshot_key)
        VALUES ('realtime'), ('sql_performance'), ('capacity'), ('integrity')
    """)


def downgrade() -> None:
    """移除数据库监控快照表。"""
    op.execute("DROP TABLE IF EXISTS database_monitor_snapshots")
