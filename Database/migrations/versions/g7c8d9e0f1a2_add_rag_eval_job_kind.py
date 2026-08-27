"""为评测持久队列增加任务类型

Revision ID: g7c8d9e0f1a2
Revises: r3c4d5e6f7a8
Create Date: 2026-08-13 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "g7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "r3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """扩展现有队列，而不是引入第二个任务队列。"""
    op.execute("ALTER TABLE rag_eval_jobs ADD COLUMN job_kind VARCHAR(40) NOT NULL DEFAULT 'evaluation' AFTER run_id")
    op.execute("CREATE INDEX idx_rag_eval_jobs_kind_queue ON rag_eval_jobs (job_kind, status, created_at, id)")


def downgrade() -> None:
    """恢复仅支持评测任务的队列表结构。"""
    op.execute("DROP INDEX idx_rag_eval_jobs_kind_queue ON rag_eval_jobs")
    op.execute("ALTER TABLE rag_eval_jobs DROP COLUMN job_kind")
