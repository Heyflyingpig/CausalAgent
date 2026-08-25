"""Agent 与 MySQL 文件库之间的冻结输入访问边界。"""

from __future__ import annotations

from typing import Any

import mysql.connector

from app.db import get_write_connection, record_database_failure


class FrozenFileNotFoundError(FileNotFoundError):
    """表示 Job 的冻结文件快照不存在或归属校验失败。"""


def get_frozen_file_for_job(
    user_id: int,
    job_id: str,
    input_user_file_id: int | None,
    input_object_id: int | None,
) -> dict[str, Any] | None:
    """按 Job 冻结的两个对象 ID 读取文件，并原子记录一次真实访问。"""
    if not input_user_file_id or not input_object_id:
        return None

    try:
        with get_write_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT uf.id AS user_file_id,
                       fo.id AS object_id,
                       fo.content_hash AS file_hash,
                       fo.file_content,
                       uf.filename,
                       uf.mime_type,
                       uf.file_size
                FROM analysis_jobs AS j
                JOIN user_files AS uf
                  ON uf.id = j.input_user_file_id
                 AND uf.user_id = j.user_id
                JOIN file_objects AS fo
                  ON fo.id = j.input_object_id
                 AND fo.owner_user_id = j.user_id
                 AND fo.id = uf.object_id
                WHERE j.job_id = %s
                  AND j.user_id = %s
                  AND j.input_user_file_id = %s
                  AND j.input_object_id = %s
                FOR UPDATE
                """,
                (job_id, user_id, input_user_file_id, input_object_id),
            )
            row = cursor.fetchone()
            if not row:
                connection.rollback()
                return None

            cursor.execute(
                """
                UPDATE user_files
                SET last_accessed_at = UTC_TIMESTAMP(6),
                    access_count = access_count + 1
                WHERE id = %s AND user_id = %s
                """,
                (row["user_file_id"], user_id),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return None
            connection.commit()
            return row
    except mysql.connector.Error as exc:
        record_database_failure(exc, operation="frozen_file_query")
        raise


def require_frozen_file_for_job(
    user_id: int,
    job_id: str,
    input_user_file_id: int | None,
    input_object_id: int | None,
) -> dict[str, Any]:
    """读取并返回 Job 冻结文件；缺失时抛出不含文件正文的明确错误。"""
    file_row = get_frozen_file_for_job(
        user_id,
        job_id,
        input_user_file_id,
        input_object_id,
    )
    if not file_row:
        raise FrozenFileNotFoundError("任务冻结的文件不存在或归属关系无效")
    return file_row
