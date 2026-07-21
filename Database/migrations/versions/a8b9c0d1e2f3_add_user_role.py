"""add user role

Revision ID: a8b9c0d1e2f3
Revises: e7a9b2c3d4f5
Create Date: 2026-07-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "e7a9b2c3d4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为现有用户表增加最小的普通用户/管理员角色字段。"""
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN role ENUM('user', 'admin') NOT NULL DEFAULT 'user'"
    )


def downgrade() -> None:
    """撤销本迁移新增的用户角色字段。"""
    op.execute("ALTER TABLE users DROP COLUMN role")
