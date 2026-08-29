"""add admin read indexes

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-07-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, Sequence[str], None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为 3.1 有界管理员列表增加稳定排序和筛选索引。"""
    op.execute("""
        CREATE INDEX idx_users_admin_role_active
        ON users (role, is_active, id)
    """)
    op.execute("""
        CREATE INDEX idx_sessions_admin_activity
        ON sessions (last_activity_at DESC, id)
    """)
    op.execute("""
        CREATE INDEX idx_analysis_jobs_admin_created
        ON analysis_jobs (created_at DESC, id)
    """)
    op.execute("""
        CREATE INDEX idx_uploaded_files_admin_uploaded
        ON uploaded_files (upload_timestamp DESC, id)
    """)
    op.execute("""
        CREATE INDEX idx_admin_audit_target_created
        ON admin_audit_events (target_type, created_at DESC, id)
    """)


def downgrade() -> None:
    """只移除本 migration 新增的管理员只读索引。"""
    op.execute("DROP INDEX idx_admin_audit_target_created ON admin_audit_events")
    op.execute("DROP INDEX idx_uploaded_files_admin_uploaded ON uploaded_files")
    op.execute("DROP INDEX idx_analysis_jobs_admin_created ON analysis_jobs")
    op.execute("DROP INDEX idx_sessions_admin_activity ON sessions")
    op.execute("DROP INDEX idx_users_admin_role_active ON users")
