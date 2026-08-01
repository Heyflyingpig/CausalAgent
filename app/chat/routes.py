'''
app.chat.routes - 聊天路由
'''
from flask import Blueprint, request, jsonify, session
from app.auth.session_guard import get_current_session_user
import logging
import json
from app.chat.response_storage import render_summary_for_display

chat_bp = Blueprint('chat', __name__, url_prefix='/api')
import uuid

# 新对话
@chat_bp.route('/new_chat',methods=['POST'])
def new_chat():
    """生成会话 ID，并在返回前把会话元数据持久化到主库。"""
    import mysql.connector
    from app.db import get_write_connection

    current_user = get_current_session_user()
    if not current_user:
        return jsonify({'success': False, 'error': '用户未登录或会话已过期'}), 401
    
    user_id = current_user['id']
    username = current_user['username']
    new_session_id = str(uuid.uuid4())

    try:
        with get_write_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sessions (
                    id, user_id, title, created_at, last_activity_at, message_count
                ) VALUES (%s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)
                """,
                (new_session_id, user_id, "新对话"),
            )
            conn.commit()
    except mysql.connector.Error as exc:
        logging.error(
            "用户 %s (ID: %s) 创建会话 %s 时数据库出错: %s",
            username,
            user_id,
            new_session_id,
            exc,
        )
        return jsonify({'success': False, 'error': '创建新对话失败'}), 500

    logging.info(f"用户 {username} (ID: {user_id}) 创建新会话: {new_session_id}")
    return jsonify({'success': True, 'new_session_id': new_session_id})

# 会话管理接口,获取会话
@chat_bp.route('/sessions')
def get_sessions():
    import mysql.connector
    from app.db import get_read_connection

    current_user = get_current_session_user()
    if not current_user:
        return jsonify({"error": "用户未登录或会话已过期"}), 401
    
    user_id = current_user['id']
    logging.info(f"用户 {user_id} 请求会话列表 (新版逻辑)")

    try:
        with get_read_connection(consistency="eventual") as conn:
            cursor = conn.cursor(dictionary=True)
            # 高效地直接从 sessions 表查询
            cursor.execute("""
                SELECT id, title, last_activity_at
                FROM sessions
                WHERE user_id = %s AND is_archived = FALSE
                ORDER BY last_activity_at DESC
            """, (user_id,)) 
            session_rows = cursor.fetchall()

        if not session_rows:
            logging.info(f"用户 {user_id} 没有会话记录")
            return jsonify([])

        # 格式化以适应前端期望的 (id, {preview, last_time}) 结构
        session_list_for_frontend = [
            (
                row["id"], 
                {
                    "preview": row["title"], 
                    "last_time": row["last_activity_at"].strftime("%m-%d %H:%M")
                }
            )
            for row in session_rows
        ]

    except mysql.connector.Error as e:
        logging.error(f"为用户 {user_id} 读取会话列表时数据库出错: {e}")
        return jsonify({"error": f"读取历史记录时出错: {e}"}), 500
    
    logging.info(f"为用户 {user_id} 返回 {len(session_list_for_frontend)} 个会话")
    return jsonify(session_list_for_frontend)

# 加载特定会话内容 
@chat_bp.route('/load_session')
def load_session_content():
    import mysql.connector
    from app.db import get_read_connection

    current_user = get_current_session_user()
    if not current_user:
        return jsonify({"success": False, "error": "用户未登录或会话已过期"}), 401
    
    user_id = current_user['id']
    username = current_user['username']

    session_id = request.args.get('session')

    if not session_id:
        return jsonify({"success": False, "error": "缺少 session ID"}), 400

    logging.info(f"用户 {username} (ID: {user_id}) 请求加载会话: {session_id}")

    messages = []
    try:
        with get_read_connection(consistency="strong") as conn:
            cursor = conn.cursor(dictionary=True)

            cursor.execute("SELECT id FROM sessions WHERE id = %s AND user_id = %s", (session_id, user_id))
            session_exists = cursor.fetchone()

            if not session_exists:
                logging.info(f"用户 {user_id} 请求了不存在或无权访问的会话 {session_id}")
                return jsonify({"success": False, "error": "会话不存在或无权访问"}), 404

            # 按照id获取所有消息和其附件，并且顺序排序，时间由早到晚
            cursor.execute("""
                SELECT
                    id,message_type,content,has_attachment
                FROM chat_messages
                WHERE session_id = %s
                ORDER BY created_at ASC
            """, (session_id,))
            chat_rows = cursor.fetchall()

            # 处理每条消息（在 with 语句内部）
            for row in chat_rows:
                sender = "user" if row["message_type"] == 'user' else "ai"

                # 如果是AI消息，且有附件，则优先使用附件内容
                if sender == "ai" and row["has_attachment"]:
                    cursor.execute("""
                        SELECT attachment_type, content
                         FROM chat_attachments
                        WHERE message_id = %s
                    """, (row["id"],))
                    attachments = cursor.fetchall()

                    causal_graph_data = None
                    visualization_mapping = None

                    ## attachment格式：{"type": "causal_graph", "content": {...}}
                    for attachment in attachments:
                        if attachment["attachment_type"] == "causal_graph":
                            try:
                                causal_graph_data = json.loads(attachment["content"])
                            except json.JSONDecodeError:
                                logging.warning(f"无法解析 causal_graph 附件，Message ID: {row['id']}")

                        elif attachment["attachment_type"] == "visualization":
                            try:
                                visualization_mapping = json.loads(attachment["content"])
                            except json.JSONDecodeError:
                                logging.warning(f"无法解析 visualization 附件，Message ID: {row['id']}")

                    if causal_graph_data:
                        message_content = causal_graph_data

                        if visualization_mapping and "summary" in message_content:
                            message_content["summary"] = render_summary_for_display(
                                message_content["summary"],
                                visualization_mapping,
                            )

                        messages.append({"sender": "ai", "text": message_content})
                    else:
                        message_text = row["content"]

                        if visualization_mapping:
                            message_text = render_summary_for_display(message_text, visualization_mapping)

                        messages.append({"sender": "ai", "text": message_text})

                else:
                    # 对于用户消息或没有附件的AI消息，直接使用content
                    messages.append({"sender": sender, "text": row["content"]})

        logging.info(f"用户 {username} 成功加载会话 {session_id} ({len(messages)} 条消息)")
        return jsonify({"success": True, "messages": messages})

    except mysql.connector.Error as e:
        logging.error(f"加载会话 {session_id} (用户 {username}) 时数据库出错: {e}")
        return jsonify({"success": False, "error": f"加载会话时出错: {e}"}), 500
    except Exception as e:
        logging.error(f"加载会话 {session_id} (用户 {username}) 时发生未知错误: {e}")
        return jsonify({"success": False, "error": f"加载会话时出错: {e}"}), 500

## 更改会话
@chat_bp.route('/change_session', methods=['POST'])
def change_session():
    import mysql.connector
    from app.db import get_write_connection

    #  用户认证检查 
    current_user = get_current_session_user()
    if not current_user:
        return jsonify({"success": False, "error": "用户未登录或会话已过期"}), 401
    
    user_id = current_user['id']
    
    #  修改：从 POST 请求的 JSON body 中获取数据 
    data = request.json
    title = data.get('title')
    session_id = data.get('session_id')

    if not title or not session_id:
        return jsonify({"success": False, "error": "缺少标题或会话ID"}), 400

    try:
        with get_write_connection() as conn:
            # 增加 user_id 条件以确保安全，并锁定已存在的 session。
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM sessions WHERE id = %s AND user_id = %s FOR UPDATE",
                (session_id, user_id),
            )
            if not cursor.fetchone():
                conn.rollback()
                return jsonify({"success": False, "error": "会话不存在或无权访问"}), 404

            cursor.execute(
                "UPDATE sessions SET title = %s WHERE id = %s AND user_id = %s",
                (title, session_id, user_id),
            )
            conn.commit()
            
        logging.info(f"用户 {user_id} 成功将会话 {session_id} 的标题更新为 '{title}'")
        return jsonify({"success": True, "message": "会话标题已更新"})
    except mysql.connector.Error as e:
        logging.error(f"更新会话标题时数据库出错 (用户ID: {user_id}, 会话ID: {session_id}): {e}")
        return jsonify({"success": False, "error": "更新会话标题时数据库出错"}), 500

## 删除会话
@chat_bp.route('/delete_session', methods=['POST'])
def delete_session():
    """在同一事务中删除用户会话及其消息、附件和 MySQL checkpoint。"""
    import mysql.connector
    from app.db import get_write_connection

    #  核心修改：安全和完整的删除逻辑，支持延迟创建 
    current_user = get_current_session_user()
    if not current_user:
        return jsonify({"success": False, "error": "用户未登录或会话已过期"}), 401
    
    user_id = current_user['id']
    data = request.json
    session_id = data.get('session_id')

    if not session_id:
        return jsonify({"success": False, "error": "缺少会话ID"}), 400

    try:
        with get_write_connection() as conn:
            cursor = conn.cursor()
            
            # 开启事务
            conn.start_transaction()
            
            # 锁定目标会话，阻止删除过程中并发创建引用该会话的新任务。
            cursor.execute(
                "SELECT id FROM sessions WHERE id = %s AND user_id = %s FOR UPDATE",
                (session_id, user_id),
            )
            session_exists = cursor.fetchone()
            
            if not session_exists:
                conn.rollback()
                logging.info(f"用户 {user_id} 请求删除不存在或无权访问的会话 {session_id}")
                return jsonify({"success": False, "error": "会话不存在或无权访问"}), 404

            cursor.execute("""
                SELECT 1
                FROM analysis_jobs
                WHERE session_id = %s
                  AND user_id = %s
                  AND status IN ('queued', 'running')
                LIMIT 1
            """, (session_id, user_id))
            if cursor.fetchone():
                conn.rollback()
                logging.info(f"用户 {user_id} 尝试删除仍有 active job 的会话 {session_id}")
                return jsonify({"success": False, "error": "当前会话仍有任务正在运行，请等待完成后再删除"}), 409

            try:
                # 1. 删除该会话对应的 LangGraph checkpoint。
                # checkpoint_writes 通过 fk_checkpoint_writes_checkpoint 级联删除，
                # 不能调用 MySQLSaver.delete_thread()，否则会脱离当前事务。
                cursor.execute("DELETE FROM checkpoints WHERE thread_id = %s", (session_id,))
                deleted_checkpoints = cursor.rowcount
                logging.info(f"为会话 {session_id} 删除了 {deleted_checkpoints} 条 checkpoint")

                # 2. 删除与该会话相关的附件 (通过连接 chat_messages)
                # 这是为了处理 chat_attachments 和 chat_messages 之间没有直接外键的情况
                sql_delete_attachments = """
                    DELETE ca FROM chat_attachments ca
                    JOIN chat_messages cm ON ca.message_id = cm.id
                    WHERE cm.session_id = %s AND cm.user_id = %s
                """
                cursor.execute(sql_delete_attachments, (session_id, user_id))
                deleted_attachments = cursor.rowcount
                logging.info(f"为会话 {session_id} 删除了 {deleted_attachments} 个附件")

                # 3. 删除该会话的所有聊天记录
                cursor.execute("DELETE FROM chat_messages WHERE session_id = %s AND user_id = %s", (session_id, user_id))
                deleted_messages = cursor.rowcount
                logging.info(f"为会话 {session_id} 删除了 {deleted_messages} 条聊天记录")

                # 4. 删除会话本身（如果存在）
                if session_exists:
                    cursor.execute("DELETE FROM sessions WHERE id = %s AND user_id = %s", (session_id, user_id))
                    logging.info(f"删除了会话记录 {session_id}")

                conn.commit()
                logging.info(f"用户 {user_id} 成功删除了会话 {session_id} 及其所有数据")
                return jsonify({"success": True, "message": "会话已成功删除"})
            except Exception:
                conn.rollback()
                raise

    except mysql.connector.Error as e:
        logging.error(f"删除会话 {session_id} (用户 {user_id}) 时数据库出错: {e}")
        return jsonify({"success": False, "error": "删除会话时数据库出错"}), 500
    except Exception as e:
        logging.error(f"删除会话 {session_id} (用户 {user_id}) 时发生未知错误: {e}")
        return jsonify({"success": False, "error": "删除会话时发生未知错误"}), 500
