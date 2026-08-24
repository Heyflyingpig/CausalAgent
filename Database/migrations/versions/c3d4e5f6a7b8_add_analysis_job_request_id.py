"""persist the original request ID on analysis jobs

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-18 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """保存创建 Job 的原始请求 ID，历史记录保持 NULL。"""
    op.execute(
        """
        ALTER TABLE analysis_jobs
            ADD COLUMN request_id VARCHAR(64) NULL AFTER session_id
        """
    )


def downgrade() -> None:
    """仅移除本 revision 新增的 request_id 字段。"""
    op.execute(
        """
        ALTER TABLE analysis_jobs
            DROP COLUMN request_id
        """
    )
