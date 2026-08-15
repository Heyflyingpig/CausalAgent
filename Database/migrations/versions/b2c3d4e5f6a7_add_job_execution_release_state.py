"""add logical cancellation execution ownership and release audit fields

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-14 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为取消后的外部调用保留 draining 执行占用，并记录真实释放原因。"""
    op.execute(
        """
        ALTER TABLE analysis_jobs
            ADD COLUMN execution_state ENUM('leased', 'draining') DEFAULT NULL
                AFTER lease_epoch,
            ADD COLUMN execution_released_at DATETIME(6) DEFAULT NULL
                AFTER heartbeat_at,
            ADD COLUMN execution_release_reason ENUM('worker_confirmed', 'lease_expired')
                DEFAULT NULL AFTER execution_released_at,
            ADD INDEX idx_analysis_jobs_execution_state_heartbeat
                (execution_state, heartbeat_at),
            ADD CONSTRAINT chk_analysis_jobs_execution_state
                CHECK (
                    (
                        status = 'running'
                        AND execution_state = 'leased'
                        AND worker_id IS NOT NULL
                        AND locked_at IS NOT NULL
                        AND heartbeat_at IS NOT NULL
                    )
                    OR (status = 'canceled'
                        AND (
                            (
                                execution_state = 'draining'
                                AND worker_id IS NOT NULL
                                AND locked_at IS NOT NULL
                                AND heartbeat_at IS NOT NULL
                            )
                            OR (
                                execution_state IS NULL
                                AND worker_id IS NULL
                                AND locked_at IS NULL
                            )
                        ))
                    OR (status IN ('queued', 'waiting_input', 'succeeded', 'failed')
                        AND execution_state IS NULL
                        AND worker_id IS NULL
                        AND locked_at IS NULL)
                ),
            ADD CONSTRAINT chk_analysis_jobs_execution_release_pair
                CHECK (
                    (
                        execution_state IN ('leased', 'draining')
                        AND execution_released_at IS NULL
                        AND execution_release_reason IS NULL
                    )
                    OR (
                        execution_state IS NULL
                        AND (
                            (execution_released_at IS NULL AND execution_release_reason IS NULL)
                            OR (execution_released_at IS NOT NULL AND execution_release_reason IS NOT NULL)
                        )
                    )
                )
        """
    )


def downgrade() -> None:
    """仅移除本 revision 的执行占用字段和索引，不修改业务数据。"""
    op.execute(
        """
        ALTER TABLE analysis_jobs
            DROP CHECK chk_analysis_jobs_execution_release_pair,
            DROP CHECK chk_analysis_jobs_execution_state,
            DROP INDEX idx_analysis_jobs_execution_state_heartbeat,
            DROP COLUMN execution_release_reason,
            DROP COLUMN execution_released_at,
            DROP COLUMN execution_state
        """
    )
