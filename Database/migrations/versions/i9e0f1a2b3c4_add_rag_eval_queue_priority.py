"""增加评测队列优先级

Revision ID: i9e0f1a2b3c4
Revises: h8d9e0f1a2b3
Create Date: 2026-08-21 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "i9e0f1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "h8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """增加服务端定义的优先级及队列扫描索引。"""
    op.execute("ALTER TABLE rag_eval_jobs ADD COLUMN priority SMALLINT NOT NULL DEFAULT 0 AFTER job_kind")
    op.execute(
        """
        UPDATE rag_eval_jobs
        SET priority = CASE job_kind
            WHEN 'rag_query' THEN 60
            WHEN 'evaluation' THEN 50
            WHEN 'dataset_governance' THEN 40
            WHEN 'tuning_dataset_governance' THEN 30
            WHEN 'candidate_generation' THEN 20
            WHEN 'ingestion' THEN 10
            ELSE 0
        END
        """
    )
    op.execute(
        "CREATE INDEX idx_rag_eval_jobs_priority_queue "
        "ON rag_eval_jobs (status, priority, created_at, id)"
    )


def downgrade() -> None:
    """删除本迁移版本引入的优先级队列结构。"""
    op.execute("DROP INDEX idx_rag_eval_jobs_priority_queue ON rag_eval_jobs")
    op.execute("ALTER TABLE rag_eval_jobs DROP COLUMN priority")
