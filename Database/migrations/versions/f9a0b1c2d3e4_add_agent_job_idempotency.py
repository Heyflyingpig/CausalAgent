"""add request idempotency fields to analysis jobs

Revision ID: f9a0b1c2d3e4
Revises: f8b9c0d1e2f3
Create Date: 2026-08-05 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, Sequence[str], None] = "f8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为分析任务增加请求级幂等键和请求指纹。"""
    op.execute(
        """
        ALTER TABLE analysis_jobs
        ADD COLUMN idempotency_key VARCHAR(128) DEFAULT NULL,
        ADD COLUMN request_fingerprint CHAR(64) DEFAULT NULL,
        ADD UNIQUE KEY uq_analysis_jobs_user_idempotency
            (user_id, idempotency_key)
        """
    )


def downgrade() -> None:
    """只回滚本 revision 新增的请求幂等字段和唯一索引。"""
    op.execute(
        """
        ALTER TABLE analysis_jobs
        DROP INDEX uq_analysis_jobs_user_idempotency,
        DROP COLUMN request_fingerprint,
        DROP COLUMN idempotency_key
        """
    )
