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


def save_chat(user_id, session_id, user_msg, ai_response):
    """
    将用户和 AI 的交互保存到数据库中。
    - 只接受已由 new_chat 创建且仍归属于当前用户的 session
    - 在 chat_messages 中为用户和AI分别创建记录。
    - 如果AI响应包含附件，则在 chat_attachments 中创建记录。
    - 更新 sessions 表的元数据。
    """
    timestamp_dt = datetime.now()

    try:
        with get_write_connection() as conn:
            cursor = conn.cursor(dictionary=True)

            cursor.execute(
                "SELECT message_count, title FROM sessions WHERE id = %s AND user_id = %s FOR UPDATE",
                (session_id, user_id),
            )
            session_data = cursor.fetchone()
            
            if not session_data:
                conn.rollback()
                raise SessionNotFoundError("会话不存在或无权访问")

            is_first_message = session_data['message_count'] == 0
            
            # 保存用户消息
            sql_user = """
                INSERT INTO chat_messages (session_id, user_id, message_type, content, created_at)
                VALUES (%s, %s, 'user', %s, %s)
            """
            cursor.execute(sql_user, (session_id, user_id, user_msg, timestamp_dt))
            
            # 保存AI消息
            ai_content, attachment_to_save = prepare_ai_response_for_storage(ai_response)
            
            # 处理数据库保存格式
            sql_ai = """
                INSERT INTO chat_messages (session_id, user_id, message_type, content, has_attachment, created_at)
                VALUES (%s, %s, 'ai', %s, %s, %s)
            """
            has_attachment = len(attachment_to_save) > 0
            cursor.execute(sql_ai, (session_id, user_id, ai_content, has_attachment, timestamp_dt))
            ai_message_id = cursor.lastrowid # 获取AI消息的ID，用于关联附件

            # 3. 如果有附件，保存到 chat_attachments
            if has_attachment and attachment_to_save:
                for attachment in attachment_to_save:
                    sql_attachment = """
                    INSERT INTO chat_attachments (message_id, attachment_type, content, created_at)
                    VALUES (%s, %s, %s, %s)
                    """
                    logging.info(f"准备保存附件: type={attachment['type']}, content_size={len(attachment['content'])} 字节")
                    cursor.execute(sql_attachment,
                    (ai_message_id, attachment['type'], attachment['content'], timestamp_dt))
                    logging.info(f"成功保存附件: {attachment['type']}")
            

            # 根据是否为第一条消息，决定是否更新标题
            if is_first_message:
                #  更新会话，包括新标题（或确认创建时的标题）
                new_title = build_session_title(user_msg)
                sql_update_session = """
                    UPDATE sessions 
                    SET title = %s, last_activity_at = %s, message_count = message_count + 2
                    WHERE id = %s AND user_id = %s
                """
                cursor.execute(sql_update_session, (new_title, timestamp_dt, session_id, user_id))
            else:
                #  只更新活动时间和消息数
                sql_update_session = """
                    UPDATE sessions 
                    SET last_activity_at = %s, message_count = message_count + 2
                    WHERE id = %s AND user_id = %s
                """
                cursor.execute(sql_update_session, (timestamp_dt, session_id, user_id))
            
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

