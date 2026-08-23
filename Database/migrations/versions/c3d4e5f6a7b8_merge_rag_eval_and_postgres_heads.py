"""合并 RAG 评测与 PostgreSQL checkpoint 迁移分支

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7, f8b9c0d1e2f3
Create Date: 2026-08-02 21:25:00

"""

from typing import Sequence, Union


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = (
    "b2c3d4e5f6a7",
    "f8b9c0d1e2f3",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """合并两个并行迁移分支，不执行额外数据变更。"""


def downgrade() -> None:
    """回退到合并前的两个迁移 head。"""
