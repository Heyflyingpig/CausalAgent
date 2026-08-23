"""merge the agent-job and RAG evaluation migration branches.

Revision ID: j9e0f1a2b3c4
Revises: i9e0f1a2b3c4, k0b2c3d4e5f6
Create Date: 2026-08-23 17:00:00.000000
"""

from typing import Sequence, Union


revision: str = "j9e0f1a2b3c4"
down_revision: Union[str, Sequence[str], None] = (
    "i9e0f1a2b3c4",
    "k0b2c3d4e5f6",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge two already-applied schema branches without additional DDL."""


def downgrade() -> None:
    """Restore the two branch heads without changing schema."""
