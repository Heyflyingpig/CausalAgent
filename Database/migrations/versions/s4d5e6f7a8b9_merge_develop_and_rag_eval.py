"""合并 develop 主链与 RAG 评测业务迁移分支。

Revision ID: s4d5e6f7a8b9
Revises: a0b1c2d3e4f5, i9e0f1a2b3c4
Create Date: 2026-08-25 00:00:00.000000

"""

from typing import Sequence, Union


revision: str = "s4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = (
    "a0b1c2d3e4f5",
    "i9e0f1a2b3c4",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """合并已完成的 develop 与 RAG DDL，不执行额外 schema 变更。"""
    pass


def downgrade() -> None:
    """撤销合流点，回到 develop 与 RAG 两个独立迁移 head。"""
    pass
