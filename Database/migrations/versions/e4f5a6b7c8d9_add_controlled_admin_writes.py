"""add controlled admin writes

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-07-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, Sequence[str], None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """增加会话失效、管理员幂等操作和 pending writes 幂等结构。"""
    op.execute("""
        ALTER TABLE users
        ADD COLUMN auth_version BIGINT UNSIGNED NOT NULL DEFAULT 1
            COMMENT '角色、状态或密码变更时递增，使旧 Cookie Session 失效',
        ADD COLUMN password_changed_at DATETIME(6) DEFAULT NULL
            COMMENT '最近一次受控密码变更时间'
    """)
    op.execute("""
        CREATE TABLE admin_operations (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            operation_id CHAR(36) NOT NULL,
            actor_user_id INT DEFAULT NULL,
            actor_username VARCHAR(255) NOT NULL,
            operation_type VARCHAR(64) NOT NULL,
            idempotency_key VARCHAR(128) NOT NULL,
            request_fingerprint CHAR(64) NOT NULL,
            status VARCHAR(16) NOT NULL,
            target_count INT UNSIGNED NOT NULL,
            succeeded_count INT UNSIGNED NOT NULL DEFAULT 0,
            failed_count INT UNSIGNED NOT NULL DEFAULT 0,
            result_json JSON DEFAULT NULL,
            request_id VARCHAR(64) NOT NULL,
            created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            completed_at DATETIME(6) DEFAULT NULL,
            CONSTRAINT ck_admin_operations_status
                CHECK (status IN ('running', 'succeeded', 'failed')),
            CONSTRAINT fk_admin_operations_actor
                FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL,
            UNIQUE KEY uq_admin_operations_operation_id (operation_id),
            UNIQUE KEY uq_admin_operations_actor_idempotency
                (actor_user_id, idempotency_key),
            INDEX idx_admin_operations_actor_created (actor_user_id, created_at DESC),
            INDEX idx_admin_operations_request (request_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    op.execute("""
        CREATE TABLE admin_operation_items (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            operation_id CHAR(36) NOT NULL,
            target_type VARCHAR(64) NOT NULL,
            target_id VARCHAR(255) NOT NULL,
            target_label VARCHAR(255) DEFAULT NULL,
            result VARCHAR(16) NOT NULL,
            error_code VARCHAR(64) DEFAULT NULL,
            old_values_json JSON DEFAULT NULL,
            new_values_json JSON DEFAULT NULL,
            created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            CONSTRAINT ck_admin_operation_items_result
                CHECK (result IN ('success', 'rejected', 'failed')),
            CONSTRAINT fk_admin_operation_items_operation
                FOREIGN KEY (operation_id) REFERENCES admin_operations(operation_id)
                ON DELETE CASCADE,
            UNIQUE KEY uq_admin_operation_items_target
                (operation_id, target_type, target_id),
            INDEX idx_admin_operation_items_target
                (target_type, target_id, created_at DESC)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    op.execute("""
        ALTER TABLE checkpoint_writes
        ADD COLUMN write_identity_hash BINARY(32) DEFAULT NULL
            COMMENT '完整 pending write 业务键摘要，避免 utf8mb4 联合索引超长'
    """)
    op.execute("""
        UPDATE checkpoint_writes
        SET write_identity_hash = UNHEX(SHA2(CONCAT(
            OCTET_LENGTH(thread_id), ':', thread_id,
            OCTET_LENGTH(checkpoint_ns), ':', checkpoint_ns,
            OCTET_LENGTH(checkpoint_id), ':', checkpoint_id,
            OCTET_LENGTH(task_id), ':', task_id,
            ':', idx
        ), 256))
        WHERE write_identity_hash IS NULL
    """)
    op.execute("""
        ALTER TABLE checkpoint_writes
        MODIFY COLUMN write_identity_hash BINARY(32) NOT NULL
            COMMENT '完整 pending write 业务键摘要，避免 utf8mb4 联合索引超长',
        ADD CONSTRAINT uq_checkpoint_writes_task_idx
            UNIQUE (write_identity_hash)
    """)
    op.execute("DROP INDEX idx_checkpoints_thread_ns_created ON checkpoints")
    op.execute("""
        CREATE INDEX idx_checkpoints_thread_ns_created_id
        ON checkpoints (
            thread_id,
            checkpoint_ns,
            created_at DESC,
            checkpoint_id DESC
        )
    """)


def downgrade() -> None:
    """按依赖顺序回滚 3.2 新表、约束、索引和用户安全字段。"""
    op.execute("DROP TABLE IF EXISTS admin_operation_items")
    op.execute("DROP TABLE IF EXISTS admin_operations")
    op.execute("""
        ALTER TABLE checkpoint_writes
        DROP INDEX uq_checkpoint_writes_task_idx,
        DROP COLUMN write_identity_hash
    """)
    op.execute("DROP INDEX idx_checkpoints_thread_ns_created_id ON checkpoints")
    op.execute("""
        CREATE INDEX idx_checkpoints_thread_ns_created
        ON checkpoints (thread_id, checkpoint_ns, created_at DESC)
    """)
    op.execute("""
        ALTER TABLE users
        DROP COLUMN password_changed_at,
        DROP COLUMN auth_version
    """)
