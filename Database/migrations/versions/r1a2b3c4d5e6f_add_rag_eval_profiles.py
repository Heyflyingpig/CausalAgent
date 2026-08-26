"""add persistent RAG evaluation profiles

Revision ID: r1a2b3c4d5e6f
Revises: e7a9b2c3d4f5
Create Date: 2026-08-01 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "r1a2b3c4d5e6f"
down_revision: Union[str, Sequence[str], None] = "e7a9b2c3d4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the user-owned custom evaluation profile store."""
    op.execute("""
        CREATE TABLE rag_eval_profiles (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            profile_id VARCHAR(80) NOT NULL,
            owner_user_id INT NULL,
            name VARCHAR(120) NOT NULL,
            retrieval_base_profile VARCHAR(80) NOT NULL,
            ragas_base_profile VARCHAR(80) NOT NULL,
            retrieval_config JSON NOT NULL,
            ragas_config JSON NOT NULL,
            version INT NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            CONSTRAINT uq_rag_eval_profiles_profile_id UNIQUE (profile_id),
            CONSTRAINT fk_rag_eval_profiles_owner
                FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE,
            INDEX idx_rag_eval_profiles_owner_updated (owner_user_id, updated_at DESC),
            INDEX idx_rag_eval_profiles_name (name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)


def downgrade() -> None:
    """Drop the custom evaluation profile store."""
    op.execute("DROP TABLE IF EXISTS rag_eval_profiles")
