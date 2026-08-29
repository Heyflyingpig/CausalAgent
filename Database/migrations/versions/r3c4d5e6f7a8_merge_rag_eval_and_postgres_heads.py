"""合并 RAG 评测与 PostgreSQL checkpoint 迁移分支

Revision ID: r3c4d5e6f7a8
Revises: r2b3c4d5e6f7, f8b9c0d1e2f3
Create Date: 2026-08-02 21:25:00

"""

from typing import Sequence, Union


revision: str = "r3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = (
    "r2b3c4d5e6f7",
    "f8b9c0d1e2f3",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """合并两个并行迁移分支，不执行额外数据变更。"""


def downgrade() -> None:
    """回退到合并前的两个迁移 head。"""
