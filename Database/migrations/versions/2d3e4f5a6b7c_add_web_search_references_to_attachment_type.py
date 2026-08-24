"""add web_search_references to chat_attachments attachment_type

Revision ID: 2d3e4f5a6b7c
Revises: 1c2d3e4f5a6b
Create Date: 2026-08-23 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "2d3e4f5a6b7c"
down_revision: Union[str, Sequence[str], None] = "1c2d3e4f5a6b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为 chat_attachments.attachment_type 增加 web_search_references 枚举值。"""
    op.execute(
        """
        ALTER TABLE chat_attachments
        MODIFY COLUMN attachment_type
        ENUM('causal_graph', 'analysis_result', 'file_content', 'other', 'visualization', 'web_search_references')
        NOT NULL
        """
    )


def downgrade() -> None:
    """先删除 web_search_references 数据，再收缩 ENUM。"""
    op.execute(
        """
        DELETE FROM chat_attachments
        WHERE attachment_type = 'web_search_references'
        """
    )
    op.execute(
        """
        ALTER TABLE chat_attachments
        MODIFY COLUMN attachment_type
        ENUM('causal_graph', 'analysis_result', 'file_content', 'other', 'visualization')
        NOT NULL
        """
    )
