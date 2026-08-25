"""merge web_search and analysis_job_request_id migration heads

Revision ID: a0b1c2d3e4f5
Revises: 2d3e4f5a6b7c, c3d4e5f6a7b8
Create Date: 2026-08-25 00:00:00.000000

"""

from typing import Sequence, Union

revision: str = "a0b1c2d3e4f5"
down_revision: Union[str, Sequence[str], None] = (
    "2d3e4f5a6b7c",
    "c3d4e5f6a7b8",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """合并两个并行 head，两个分支迁移互不冲突，无独立 schema 变更。"""
    pass


def downgrade() -> None:
    """撤销合并点（无操作）。"""
    pass
