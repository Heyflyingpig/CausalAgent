"""replace legacy files and add resumable analysis-job inputs

Revision ID: a1b2c3d4e5f6
Revises: f9a0b1c2d3e4
Create Date: 2026-08-07 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """直接替换测试库旧文件表，并建立冻结输入与可恢复 Job 所需结构。"""
    op.execute("DROP TABLE IF EXISTS uploaded_files")

    op.execute(
        """
        CREATE TABLE file_objects (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            owner_user_id INT NOT NULL,
            content_hash CHAR(64) NOT NULL,
            file_size BIGINT NOT NULL,
            mime_type VARCHAR(100) NOT NULL,
            file_content LONGBLOB NOT NULL,
            created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            CONSTRAINT fk_file_objects_owner
                FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE KEY uq_file_objects_owner_hash (owner_user_id, content_hash),
            INDEX idx_file_objects_owner_created (owner_user_id, created_at DESC)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
        CREATE TABLE user_files (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            object_id BIGINT NOT NULL,
            filename VARCHAR(255) NOT NULL,
            mime_type VARCHAR(100) NOT NULL,
            file_size BIGINT NOT NULL,
            uploaded_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            last_accessed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            access_count INT NOT NULL DEFAULT 0,
            CONSTRAINT fk_user_files_user
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            CONSTRAINT fk_user_files_object
                FOREIGN KEY (object_id) REFERENCES file_objects(id) ON DELETE RESTRICT,
            UNIQUE KEY uq_user_files_name_object (user_id, object_id, filename),
            INDEX idx_user_files_user_accessed (user_id, last_accessed_at DESC, id),
            INDEX idx_user_files_user_filename (user_id, filename),
            INDEX idx_user_files_object (object_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )

    op.execute(
        """
        ALTER TABLE analysis_jobs
            MODIFY status ENUM(
                'queued', 'running', 'waiting_input', 'succeeded', 'failed', 'canceled'
            ) NOT NULL DEFAULT 'queued',
            ADD COLUMN lease_epoch BIGINT NOT NULL DEFAULT 0 AFTER worker_id,
            ADD COLUMN recovery_count INT NOT NULL DEFAULT 0 AFTER attempt_count,
            ADD COLUMN resume_count INT NOT NULL DEFAULT 0 AFTER recovery_count,
            ADD COLUMN input_user_file_id BIGINT DEFAULT NULL AFTER message,
            ADD COLUMN input_object_id BIGINT DEFAULT NULL AFTER input_user_file_id,
            ADD COLUMN input_file_hash CHAR(64) DEFAULT NULL AFTER input_object_id,
            ADD COLUMN input_filename VARCHAR(255) DEFAULT NULL AFTER input_file_hash,
            ADD COLUMN current_question_id VARCHAR(255) DEFAULT NULL AFTER input_filename,
            ADD COLUMN current_waiting_prompt MEDIUMTEXT DEFAULT NULL AFTER current_question_id,
            ADD COLUMN cancel_idempotency_key CHAR(36) DEFAULT NULL AFTER current_waiting_prompt,
            ADD COLUMN cancel_request_fingerprint CHAR(64) DEFAULT NULL AFTER cancel_idempotency_key,
            ADD INDEX idx_analysis_jobs_input_user_file_status
                (input_user_file_id, status),
            ADD UNIQUE KEY uq_analysis_jobs_cancel_idempotency
                (job_id, cancel_idempotency_key),
            ADD CONSTRAINT fk_analysis_jobs_input_user_file
                FOREIGN KEY (input_user_file_id) REFERENCES user_files(id)
                ON DELETE SET NULL,
            ADD CONSTRAINT fk_analysis_jobs_input_object
                FOREIGN KEY (input_object_id) REFERENCES file_objects(id)
                ON DELETE SET NULL
        """
    )

    op.execute(
        """
        CREATE TABLE analysis_job_inputs (
            input_id BIGINT AUTO_INCREMENT PRIMARY KEY,
            job_id VARCHAR(36) NOT NULL,
            sequence INT NOT NULL,
            input_type ENUM('initial', 'resume') NOT NULL,
            input_text MEDIUMTEXT NOT NULL,
            question_id VARCHAR(255) DEFAULT NULL,
            idempotency_key CHAR(36) NOT NULL,
            request_fingerprint CHAR(64) NOT NULL,
            chat_message_id BIGINT DEFAULT NULL,
            created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            UNIQUE KEY uq_analysis_job_inputs_sequence (job_id, sequence),
            UNIQUE KEY uq_analysis_job_inputs_idempotency (job_id, idempotency_key),
            INDEX idx_analysis_job_inputs_job_created (job_id, created_at, input_id),
            CONSTRAINT fk_analysis_job_inputs_job
                FOREIGN KEY (job_id) REFERENCES analysis_jobs(job_id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )

    op.execute(
        """
        ALTER TABLE analysis_job_events
            ADD COLUMN event_key VARCHAR(255) DEFAULT NULL AFTER event_type,
            ADD UNIQUE KEY uq_analysis_job_events_event_key (job_id, event_key)
        """
    )

    # 当前 head 已由 f6b8c9d0e1a2 移除 chat_messages 分区并将主键改为 id。
    # 这里直接增加全局唯一的 source_event_id，不重复移除分区布局。
    op.execute(
        """
        ALTER TABLE chat_messages
            ADD COLUMN analysis_job_id VARCHAR(36) DEFAULT NULL AFTER user_id,
            ADD COLUMN analysis_job_input_id BIGINT DEFAULT NULL AFTER analysis_job_id,
            ADD COLUMN source_event_id BIGINT DEFAULT NULL AFTER analysis_job_input_id,
            ADD UNIQUE KEY uq_chat_messages_source_event (source_event_id),
            ADD INDEX idx_chat_messages_analysis_job (analysis_job_id, created_at),
            ADD INDEX idx_chat_messages_analysis_input (analysis_job_input_id)
        """
    )


def downgrade() -> None:
    """回滚新增结构；旧文件表只恢复空表结构，不恢复被替换的数据。"""
    op.execute("DROP TABLE IF EXISTS analysis_job_inputs")
    op.execute(
        """
        ALTER TABLE chat_messages
            DROP INDEX idx_chat_messages_analysis_input,
            DROP INDEX idx_chat_messages_analysis_job,
            DROP INDEX uq_chat_messages_source_event,
            DROP COLUMN source_event_id,
            DROP COLUMN analysis_job_input_id,
            DROP COLUMN analysis_job_id
        """
    )
    op.execute(
        """
        ALTER TABLE analysis_job_events
            DROP INDEX uq_analysis_job_events_event_key,
            DROP COLUMN event_key
        """
    )
    op.execute(
        """
        ALTER TABLE analysis_jobs
            DROP FOREIGN KEY fk_analysis_jobs_input_object,
            DROP FOREIGN KEY fk_analysis_jobs_input_user_file,
            DROP INDEX idx_analysis_jobs_input_user_file_status,
            DROP COLUMN input_filename,
            DROP COLUMN input_file_hash,
            DROP COLUMN input_object_id,
            DROP COLUMN input_user_file_id,
            DROP COLUMN current_waiting_prompt,
            DROP COLUMN current_question_id,
            DROP INDEX uq_analysis_jobs_cancel_idempotency,
            DROP COLUMN cancel_request_fingerprint,
            DROP COLUMN cancel_idempotency_key,
            DROP COLUMN resume_count,
            DROP COLUMN recovery_count,
            DROP COLUMN lease_epoch,
            MODIFY status ENUM(
                'queued', 'running', 'succeeded', 'failed', 'canceled'
            ) NOT NULL DEFAULT 'queued'
        """
    )
    op.execute("DROP TABLE IF EXISTS user_files")
    op.execute("DROP TABLE IF EXISTS file_objects")
    op.execute(
        """
        CREATE TABLE uploaded_files (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            filename VARCHAR(255) NOT NULL,
            original_filename VARCHAR(255) NOT NULL,
            mime_type VARCHAR(100) NOT NULL,
            file_size BIGINT NOT NULL,
            file_hash VARCHAR(64) NOT NULL,
            file_content LONGBLOB NOT NULL,
            upload_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            access_count INT DEFAULT 0,
            CONSTRAINT fk_uploaded_files_user
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE KEY unique_user_hash (user_id, file_hash),
            INDEX idx_user_files (user_id, upload_timestamp DESC),
            INDEX idx_filename_search (user_id, filename),
            INDEX idx_size_cleanup (file_size, last_accessed_at),
            INDEX idx_hash_dedup (file_hash),
            INDEX idx_uploaded_files_user_accessed (user_id, last_accessed_at DESC),
            INDEX idx_uploaded_files_user_filename_accessed
                (user_id, original_filename, last_accessed_at DESC),
            INDEX idx_uploaded_files_admin_uploaded (upload_timestamp DESC, id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
