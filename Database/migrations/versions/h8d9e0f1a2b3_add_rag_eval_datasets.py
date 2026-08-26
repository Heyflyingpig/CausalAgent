"""增加不可变的评测数据集注册表

Revision ID: h8d9e0f1a2b3
Revises: g7c8d9e0f1a2
Create Date: 2026-08-21 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "h8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "g7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建不可变元数据注册表；数据集快照仍由文件系统保存。"""
    op.execute(
        """
        CREATE TABLE rag_eval_datasets (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            dataset_id VARCHAR(64) NOT NULL,
            dataset_revision VARCHAR(128) NOT NULL,
            dataset_kind VARCHAR(40) NOT NULL,
            schema_version VARCHAR(40) NOT NULL,
            content_sha256 CHAR(64) NOT NULL,
            sample_count INT NOT NULL,
            storage_uri VARCHAR(512) NOT NULL,
            binding_mode VARCHAR(32) NOT NULL,
            binding_json JSON NOT NULL,
            lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'registered',
            created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            CONSTRAINT uq_rag_eval_datasets_identity UNIQUE (dataset_id, dataset_revision),
            INDEX idx_rag_eval_datasets_list (dataset_kind, lifecycle_status, created_at, id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )


def downgrade() -> None:
    """只删除本迁移版本创建的表。"""
    op.execute("DROP TABLE rag_eval_datasets")
