"""add durable RAG_EVAL evaluation jobs

Revision ID: r2b3c4d5e6f7
Revises: r1a2b3c4d5e6f
Create Date: 2026-08-02 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "r2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "r1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the durable queue and lease table for isolated RAG evaluations."""
    op.execute(
        """
        CREATE TABLE rag_eval_jobs (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            run_id VARCHAR(80) NOT NULL,
            status ENUM('queued', 'running', 'succeeded', 'failed', 'cancelled')
                NOT NULL DEFAULT 'queued',
            payload_json JSON NOT NULL,
            worker_id VARCHAR(160) NULL,
            locked_at DATETIME(6) NULL,
            heartbeat_at DATETIME(6) NULL,
            attempt_count INT NOT NULL DEFAULT 0,
            max_attempts INT NOT NULL DEFAULT 1,
            error_message TEXT NULL,
            last_error TEXT NULL,
            created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            started_at DATETIME(6) NULL,
            finished_at DATETIME(6) NULL,
            CONSTRAINT uq_rag_eval_jobs_run_id UNIQUE (run_id),
            INDEX idx_rag_eval_jobs_queue (status, created_at, id),
            INDEX idx_rag_eval_jobs_heartbeat (status, heartbeat_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )


def downgrade() -> None:
    """Drop the durable RAG_EVAL evaluation queue."""
    op.execute("DROP TABLE IF EXISTS rag_eval_jobs")
