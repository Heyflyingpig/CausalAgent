"""add web_search_enabled to analysis jobs

Revision ID: 1c2d3e4f5a6b
Revises: b2c3d4e5f6a7
Create Date: 2026-08-16 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "1c2d3e4f5a6b"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为分析任务增加联网搜索开关。"""
    op.execute(
        """
        ALTER TABLE analysis_jobs
        ADD COLUMN web_search_enabled TINYINT(1) NOT NULL DEFAULT 0
        """
    )


def downgrade() -> None:
    """回滚联网搜索开关列。"""
    op.execute(
        """
        ALTER TABLE analysis_jobs
        DROP COLUMN web_search_enabled
        """
    )
