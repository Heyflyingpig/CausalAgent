'''

app.chat.services - 聊天服务

- 获取聊天记录
'''
from app.db import get_read_connection, get_write_connection
from app.chat.response_storage import prepare_ai_response_for_storage
from app.chat.session_title import build_session_title
import mysql.connector
import logging
from datetime import datetime
def get_chat_history(session_id: str, user_id: int, limit: int) -> list:
    """从数据库获取指定会话的最近聊天记录。"""
    history = []
    try:
        with get_read_connection(consistency="strong") as conn:
            cursor = conn.cursor(dictionary=True)
            # 获取最近的 'limit' 条记录
            # 为什么这里需要先反转，再反转排序呢？
            # 我需要获取一个子集，也就是所有记录中的最新的子集，然后在从老到新进行排序
            # 最后通过一个append,从老到新进行添加
            
            cursor.execute("""
                SELECT message_type, content FROM chat_messages
                WHERE session_id = %s AND user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (session_id, user_id, limit))
            recent_chats = cursor.fetchall()

            # 按时间倒序获取，所以要反转回来才是正确的对话顺序
            for row in reversed(recent_chats):
                role = "user" if row['message_type'] == 'user' else "assistant"
                history.append({"role": role, "content": row['content']})
            
            logging.info(f"为会话 {session_id} 获取了 {len(history)} 条历史消息。")
            return history
            
    except mysql.connector.Error as e:
        logging.error(f"为会话 {session_id} 获取历史记录时数据库出错: {e}")
        return []
    except Exception as e:
        logging.error(f"为会话 {session_id} 获取历史记录时发生未知错误: {e}")
        return []
    


## 保存历史文件     
class SessionNotFoundError(ValueError):
    """表示写入请求引用了不存在或不属于当前用户的会话。"""


def _save_chat_rows(cursor, user_id, session_id, user_msg, ai_response, timestamp_dt):
    """使用已有事务游标写入聊天消息、附件和会话元数据，不提交事务。"""
    cursor.execute(
        "SELECT message_count, title FROM sessions WHERE id = %s AND user_id = %s FOR UPDATE",
        (session_id, user_id),
    )
    session_data = cursor.fetchone()

    if not session_data:
        raise SessionNotFoundError("会话不存在或无权访问")

    is_first_message = session_data["message_count"] == 0
    cursor.execute(
        """
        INSERT INTO chat_messages (session_id, user_id, message_type, content, created_at)
        VALUES (%s, %s, 'user', %s, %s)
        """,
        (session_id, user_id, user_msg, timestamp_dt),
    )

    ai_content, attachment_to_save = prepare_ai_response_for_storage(ai_response)
    has_attachment = len(attachment_to_save) > 0
    cursor.execute(
        """
        INSERT INTO chat_messages (session_id, user_id, message_type, content, has_attachment, created_at)
        VALUES (%s, %s, 'ai', %s, %s, %s)
        """,
        (session_id, user_id, ai_content, has_attachment, timestamp_dt),
    )
    ai_message_id = cursor.lastrowid

    if has_attachment and attachment_to_save:
        for attachment in attachment_to_save:
            logging.info(
                "准备保存附件: type=%s, content_size=%s 字节",
                attachment["type"],
                len(attachment["content"]),
            )
            cursor.execute(
                """
                INSERT INTO chat_attachments (message_id, attachment_type, content, created_at)
                VALUES (%s, %s, %s, %s)
                """,
                (ai_message_id, attachment["type"], attachment["content"], timestamp_dt),
            )

    if is_first_message:
        new_title = build_session_title(user_msg)
        cursor.execute(
            """
            UPDATE sessions
            SET title = %s, last_activity_at = %s, message_count = message_count + 2
            WHERE id = %s AND user_id = %s
            """,
            (new_title, timestamp_dt, session_id, user_id),
        )
    else:
        cursor.execute(
            """
            UPDATE sessions
            SET last_activity_at = %s, message_count = message_count + 2
            WHERE id = %s AND user_id = %s
            """,
            (timestamp_dt, session_id, user_id),
        )


def save_chat_for_job_in_transaction(
    cursor,
    job_id,
    user_id,
    session_id,
    user_msg,
    ai_response,
) -> bool:
    """在 worker 的终态事务中幂等保存聊天，不提交调用方事务。"""
    cursor.execute(
        """
        SELECT chat_saved_at
        FROM analysis_jobs
        WHERE job_id = %s AND user_id = %s
        FOR UPDATE
        """,
        (job_id, user_id),
    )
    job_data = cursor.fetchone()
    if not job_data:
        raise ValueError("任务不存在或不属于当前用户")
    if job_data["chat_saved_at"] is not None:
        return False

    cursor.execute(
        """
        UPDATE analysis_jobs
        SET chat_saved_at = UTC_TIMESTAMP(6)
        WHERE job_id = %s AND user_id = %s AND chat_saved_at IS NULL
        """,
        (job_id, user_id),
    )
    if cursor.rowcount != 1:
        return False

    _save_chat_rows(cursor, user_id, session_id, user_msg, ai_response, datetime.now())
    return True


def save_chat(user_id, session_id, user_msg, ai_response):
    """独立事务保存用户和 AI 的聊天消息、附件及会话元数据。"""
    timestamp_dt = datetime.now()

    try:
        with get_write_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                _save_chat_rows(cursor, user_id, session_id, user_msg, ai_response, timestamp_dt)
            except SessionNotFoundError:
                conn.rollback()
                raise
            conn.commit()
            return True
    except SessionNotFoundError:
        raise
    except mysql.connector.Error as e:
        logging.error(f"保存聊天记录到数据库时出错 (用户 ID: {user_id}, 会话: {session_id}): {e}")
        return False
    except Exception as e:
        logging.error(f"保存聊天时发生未知错误: {e}")
        return False

