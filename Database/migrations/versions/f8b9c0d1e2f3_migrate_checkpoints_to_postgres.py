"""move LangGraph checkpoints to PostgreSQL and add MySQL cleanup outbox

Revision ID: f8b9c0d1e2f3
Revises: e4f5a6b7c8d9, e7a9b2c3d4f5
Create Date: 2026-07-31 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "f8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = (
    "e4f5a6b7c8d9",
    "e7a9b2c3d4f5",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """建立跨库清理 outbox，再删除不再使用的 MySQL checkpoint 数据。"""
    op.execute(
        """
        CREATE TABLE checkpoint_cleanup_outbox (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            thread_id VARCHAR(255) NOT NULL,
            operation_id CHAR(36) DEFAULT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            attempts TINYINT UNSIGNED NOT NULL DEFAULT 0,
            available_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            lease_expires_at DATETIME(6) DEFAULT NULL,
            last_error TEXT DEFAULT NULL,
            created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            completed_at DATETIME(6) DEFAULT NULL,
            CONSTRAINT ck_checkpoint_cleanup_outbox_status
                CHECK (status IN ('pending', 'processing', 'succeeded', 'failed')),
            CONSTRAINT fk_checkpoint_cleanup_outbox_operation
                FOREIGN KEY (operation_id) REFERENCES admin_operations(operation_id)
                ON DELETE SET NULL,
            UNIQUE KEY uq_checkpoint_cleanup_outbox_thread (thread_id),
            INDEX idx_checkpoint_cleanup_outbox_claim
                (status, available_at, id),
            INDEX idx_checkpoint_cleanup_outbox_operation
                (operation_id, status, id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )

    # PostgreSQL is the source of truth after this revision.  The explicit
    # drop is intentional: old checkpoint rows are not recoverable by Alembic.
    op.execute("DROP TABLE IF EXISTS checkpoint_writes")
    op.execute("DROP TABLE IF EXISTS checkpoints")


def downgrade() -> None:
    """恢复 MySQL checkpoint 空表结构，不恢复已删除的数据。"""
    op.execute("DROP TABLE IF EXISTS checkpoint_cleanup_outbox")
    op.execute(
        """
        CREATE TABLE checkpoints (
            thread_id VARCHAR(255) NOT NULL,
            checkpoint_ns VARCHAR(255) NOT NULL DEFAULT '',
            checkpoint_id VARCHAR(255) NOT NULL,
            parent_checkpoint_id VARCHAR(255) DEFAULT NULL,
            checkpoint LONGBLOB NOT NULL,
            metadata_data JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id),
            INDEX idx_parent (parent_checkpoint_id),
            INDEX idx_checkpoints_thread_ns_created_id
                (thread_id, checkpoint_ns, created_at DESC, checkpoint_id DESC)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
        CREATE TABLE checkpoint_writes (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            thread_id VARCHAR(255) NOT NULL,
            checkpoint_ns VARCHAR(255) NOT NULL DEFAULT '',
            checkpoint_id VARCHAR(255) NOT NULL,
            task_id VARCHAR(255) NOT NULL,
            idx INT NOT NULL,
            channel VARCHAR(255) NOT NULL,
            value LONGBLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            write_identity_hash BINARY(32) NOT NULL,
            INDEX idx_checkpoint_writes_checkpoint
                (thread_id, checkpoint_ns, checkpoint_id),
            UNIQUE KEY uq_checkpoint_writes_task_idx (write_identity_hash),
            CONSTRAINT fk_checkpoint_writes_checkpoint
                FOREIGN KEY (thread_id, checkpoint_ns, checkpoint_id)
                REFERENCES checkpoints(thread_id, checkpoint_ns, checkpoint_id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
