'''
node节点中的数据库交互
'''
import mysql.connector
import logging
from app.db import get_write_connection


# 这些函数帮助节点与应用程序的数据库进行交互，以获取文件等资源。
def get_file_content(user_id: int, filename: str) -> bytes | None:
    """读取指定文件正文，并在同一主库事务中更新真实使用次数。"""
    try:
        with get_write_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, file_content
                FROM uploaded_files
                WHERE user_id = %s AND original_filename = %s
                ORDER BY last_accessed_at DESC
                LIMIT 1
                FOR UPDATE
                """,
                (user_id, filename)
            )
            result = cursor.fetchone()
            if not result:
                conn.rollback()
                return None
            cursor.execute(
                """
                UPDATE uploaded_files
                SET last_accessed_at = UTC_TIMESTAMP(6),
                    access_count = access_count + 1
                WHERE id = %s
                """,
                (result["id"],),
            )
            conn.commit()
            return result["file_content"]
    except mysql.connector.Error as e:
        logging.error(f"Agent Node: 从数据库获取文件 '{filename}' (用户ID: {user_id}) 时出错: {e}")
        return None

def get_recent_file(user_id: int) -> tuple[bytes | None, str | None]:
    """读取最近文件正文和名称，并原子更新真实使用次数。"""
    try:
        with get_write_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, file_content, original_filename
                FROM uploaded_files
                WHERE user_id = %s
                ORDER BY last_accessed_at DESC
                LIMIT 1
                FOR UPDATE
                """,
                (user_id,)
            )
            result = cursor.fetchone()
            if result:
                cursor.execute(
                    """
                    UPDATE uploaded_files
                    SET last_accessed_at = UTC_TIMESTAMP(6),
                        access_count = access_count + 1
                    WHERE id = %s
                    """,
                    (result["id"],),
                )
                conn.commit()
                return result["file_content"], result["original_filename"]
            conn.rollback()
            return None, None
    except mysql.connector.Error as e:
        logging.error(f"Agent Node: 为用户 {user_id} 获取最近文件时出错: {e}")
        return None, None
