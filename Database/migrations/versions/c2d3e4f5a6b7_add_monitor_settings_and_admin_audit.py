"""add monitor settings and admin audit

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-07-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建数据库监控在线配置单例和可扩展管理员审计事件。"""
    op.execute("""
        CREATE TABLE database_monitor_settings (
            id TINYINT UNSIGNED NOT NULL PRIMARY KEY,
            auto_refresh_enabled BOOLEAN DEFAULT NULL,
            realtime_interval_seconds INT DEFAULT NULL,
            sql_interval_seconds INT DEFAULT NULL,
            table_capacity_interval_seconds INT DEFAULT NULL,
            slow_query_warning_delta INT DEFAULT NULL,
            integrity_enabled BOOLEAN DEFAULT NULL,
            integrity_interval_seconds INT DEFAULT NULL,
            version BIGINT UNSIGNED NOT NULL DEFAULT 1,
            updated_by_user_id INT DEFAULT NULL,
            updated_at DATETIME(6) NOT NULL
                DEFAULT CURRENT_TIMESTAMP(6)
                ON UPDATE CURRENT_TIMESTAMP(6),
            CONSTRAINT ck_database_monitor_settings_singleton CHECK (id = 1),
            CONSTRAINT ck_database_monitor_settings_auto
                CHECK (auto_refresh_enabled IS NULL OR auto_refresh_enabled IN (0, 1)),
            CONSTRAINT ck_database_monitor_settings_realtime
                CHECK (realtime_interval_seconds IS NULL
                    OR realtime_interval_seconds BETWEEN 5 AND 10),
            CONSTRAINT ck_database_monitor_settings_sql
                CHECK (sql_interval_seconds IS NULL
                    OR sql_interval_seconds BETWEEN 30 AND 60),
            CONSTRAINT ck_database_monitor_settings_capacity
                CHECK (table_capacity_interval_seconds IS NULL
                    OR table_capacity_interval_seconds BETWEEN 300 AND 900),
            CONSTRAINT ck_database_monitor_settings_slow_delta
                CHECK (slow_query_warning_delta IS NULL
                    OR slow_query_warning_delta >= 1),
            CONSTRAINT ck_database_monitor_settings_integrity_enabled
                CHECK (integrity_enabled IS NULL OR integrity_enabled IN (0, 1)),
            CONSTRAINT ck_database_monitor_settings_integrity_interval
                CHECK (integrity_interval_seconds IS NULL
                    OR integrity_interval_seconds >= 3600),
            CONSTRAINT fk_database_monitor_settings_user
                FOREIGN KEY (updated_by_user_id) REFERENCES users(id) ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    op.execute("""
        INSERT INTO database_monitor_settings (id)
        VALUES (1)
    """)
    op.execute("""
        CREATE TABLE admin_audit_events (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            actor_user_id INT DEFAULT NULL,
            actor_username VARCHAR(255) NOT NULL,
            action VARCHAR(100) NOT NULL,
            target_type VARCHAR(64) NOT NULL,
            target_id VARCHAR(255) DEFAULT NULL,
            old_values_json JSON DEFAULT NULL,
            new_values_json JSON DEFAULT NULL,
            result VARCHAR(32) NOT NULL,
            error_code VARCHAR(64) DEFAULT NULL,
            request_id VARCHAR(64) NOT NULL,
            created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            CONSTRAINT ck_admin_audit_events_result
                CHECK (result IN ('success', 'rejected', 'failed')),
            CONSTRAINT fk_admin_audit_events_actor
                FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL,
            INDEX idx_admin_audit_created (created_at),
            INDEX idx_admin_audit_actor_created (actor_user_id, created_at),
            INDEX idx_admin_audit_action_created (action, created_at),
            INDEX idx_admin_audit_request (request_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)


def downgrade() -> None:
    """按依赖顺序移除管理员审计和数据库监控配置表。"""
    op.execute("DROP TABLE IF EXISTS admin_audit_events")
    op.execute("DROP TABLE IF EXISTS database_monitor_settings")
