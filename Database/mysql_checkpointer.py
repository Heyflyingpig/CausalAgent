"""历史兼容的 MySQL Checkpointer，不再用于现行运行或管理员读取链路。

现行 LangGraph checkpoint 事实源是 PostgreSQL。本文件仅供旧代码迁移参考，
不得被 Web、worker、管理员服务或现行测试导入。

"""

from typing import Any, AsyncIterator, Dict, Iterator, Optional, Sequence, Tuple
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    WRITES_IDX_MAP,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
import mysql.connector
from contextlib import contextmanager
import hashlib
import json
import logging
import asyncio
from app.db import get_read_connection, get_write_connection
from Database.mysql_checkpointer_helpers import is_missing_checkpoint_foreign_key_error

# 配置日志
logger = logging.getLogger(__name__)

_SERDE_PREFIX = b"LGST1"


def _pending_write_identity_hash(
    thread_id: str,
    checkpoint_ns: str,
    checkpoint_id: str,
    task_id: str,
    idx: int,
) -> bytes:
    """生成与 migration 回填完全一致的 pending write 业务键摘要。"""
    payload = b"".join(
        str(len(encoded)).encode("ascii") + b":" + encoded
        for encoded in (
            thread_id.encode("utf-8"),
            checkpoint_ns.encode("utf-8"),
            checkpoint_id.encode("utf-8"),
            task_id.encode("utf-8"),
        )
    )
    payload += b":" + str(idx).encode("ascii")
    return hashlib.sha256(payload).digest()


class MySQLSaver(BaseCheckpointSaver):
    """
    MySQL 实现的 LangGraph Checkpointer
    
    使用示例：
        checkpointer = MySQLSaver(
            connection_config={
                'host': 'localhost',
                'user': 'root',
                'password': 'password',
                'database': 'causalagent'
            }
        )
        checkpointer.setup()  # 初始化表（如果使用Alembic则不需要）
        
        graph = workflow.compile(checkpointer=checkpointer)
    """
    
    def __init__(
        self,
        connection_config: Dict[str, Any],
        serde: Optional[JsonPlusSerializer] = None
    ):
        """
        初始化 MySQL Checkpointer
        
        Args:
            connection_config (dict): MySQL 连接配置
                {
                    'host': 'localhost',
                    'port': 3306,
                    'user': 'root',
                    'password': 'your_password',
                    'database': 'causalagent'
                }
            
            serde (JsonPlusSerializer, optional): 序列化器
                用于将 Python 对象转换为 bytes
                默认使用 JsonPlusSerializer(pickle_fallback=True)
                这样可以处理 Pandas DataFrame 等复杂对象
        """
        # 调用父类构造函数，初始化序列化器
        super().__init__(serde=serde or JsonPlusSerializer(pickle_fallback=True))
        
        # 保存数据库配置。保留参数用于兼容旧调用，实际连接统一由 app.db 管理。
        self.connection_config = connection_config
        self._deferred_writes: list[tuple[Dict[str, Any], Sequence[Tuple[str, Any]], str, str]] = []
        
        logger.info("MySQLSaver 初始化完成")

    def _serialize_blob(self, value: Any) -> bytes:
        """
        使用新版 LangGraph typed serializer 序列化值。

        langgraph-checkpoint 4.x 的 JsonPlusSerializer 不再暴露 dumps/loads，
        而是使用 dumps_typed/loads_typed 返回 `(type, bytes)`。当前数据库
        schema 只有一个 LONGBLOB 字段，因此这里把 type 头和 payload 合并
        存储，避免为序列化类型新增 schema 字段。
        """
        value_type, payload = self.serde.dumps_typed(value)
        type_bytes = value_type.encode("utf-8")
        if len(type_bytes) > 65535:
            raise ValueError(f"序列化类型名过长: {value_type}")
        return _SERDE_PREFIX + len(type_bytes).to_bytes(2, "big") + type_bytes + payload

    def _deserialize_blob(self, blob: Any) -> Any:
        """
        反序列化 checkpoint / pending write blob。

        新写入的数据带有 `_SERDE_PREFIX` 头；旧数据没有头时，按新版
        JsonPlusSerializer 支持的 msgpack / pickle / json 顺序做兼容读取。
        """
        if blob is None:
            return None

        data = bytes(blob)
        if data.startswith(_SERDE_PREFIX):
            type_len_start = len(_SERDE_PREFIX)
            type_len_end = type_len_start + 2
            type_len = int.from_bytes(data[type_len_start:type_len_end], "big")
            value_type = data[type_len_end:type_len_end + type_len].decode("utf-8")
            payload = data[type_len_end + type_len:]
            return self.serde.loads_typed((value_type, payload))

        last_error: Exception | None = None
        for value_type in ("msgpack", "pickle", "json", "bytes"):
            try:
                return self.serde.loads_typed((value_type, data))
            except Exception as exc:
                last_error = exc

        raise ValueError(f"无法反序列化 checkpoint blob: {last_error}") from last_error
    
    @contextmanager
    def _get_connection(self):
        """
        获取数据库连接的上下文管理器
        Returns:
            mysql.connector.connection.MySQLConnection
        """
        conn = None
        try:
            conn = get_write_connection()
            yield conn
        except mysql.connector.Error as e:
            logger.error(f"数据库连接失败: {e}")
            raise
        finally:
            # 确保连接被关闭
            if conn and conn.is_connected():
                conn.close()
    

    def put(
        self,
        config: Dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        保存一个 checkpoint 到 MySQL
        
        这个方法会在每个节点执行后被 LangGraph 自动调用。
        
        Args:
            config: 配置字典
                {
                    "configurable": {
                        "thread_id": "conv_123",      # 必须
                        "checkpoint_ns": "",           # 可选，默认空
                        "checkpoint_id": "uuid-111"    # 父checkpoint的ID
                    }
                }
            
            checkpoint: Checkpoint 对象（字典）
                {
                    "v": 1,                    # 版本号
                    "id": "uuid-222",          # 新checkpoint的ID（LangGraph生成）
                    "ts": "2024-01-15...",     # 时间戳
                    "channel_values": {        #  CausalAgentState
                        "messages": [...],
                        "analysis_parameters": {...},
                        ...
                    },
                    "channel_versions": {...},
                    "versions_seen": {...}
                }
            
            metadata: 元数据字典
                {
                    "source": "loop",
                    "step": 2,
                    "writes": {"fold": {...}}
                }
            
            new_versions: 新版本信息（LangGraph 内部使用）
        
        Returns:
            更新后的 config，包含新的 checkpoint_id
        """
        # 从 config 中提取关键信息
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        
        # parent_checkpoint_id：上一个 checkpoint 的 ID
        # 用于形成 checkpoint 链（支持时间旅行）
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")
        
        # 新 checkpoint 的 ID（由 LangGraph 在 checkpoint["id"] 中生成）
        new_checkpoint_id = checkpoint["id"]
        
        logger.info(
            f"保存 checkpoint: thread_id={thread_id}, "
            f"checkpoint_id={new_checkpoint_id}, "
            f"parent={parent_checkpoint_id}"
        )
        
        # 序列化 checkpoint 和 metadata
        # 使用 LangGraph typed serializer 将 Python 对象转为 bytes
        # 这样可以安全存储到 LONGBLOB 字段中
        try:
            checkpoint_blob = self._serialize_blob(checkpoint)
            metadata_json = json.dumps(metadata, ensure_ascii=False)
        except Exception as e:
            logger.error(f"序列化 checkpoint 失败: {e}")
            raise
        
        # 保存到数据库
        with get_write_connection() as conn:
            cursor = conn.cursor()
            
            # MySQL 语法：INSERT ... ON DUPLICATE KEY UPDATE
            # 含义：如果主键冲突（checkpoint已存在），则更新；否则插入
            # 为什么用这个：支持幂等性，重复调用不会出错
            cursor.execute("""
                INSERT INTO checkpoints (
                    thread_id,
                    checkpoint_ns,
                    checkpoint_id,
                    parent_checkpoint_id,
                    checkpoint,
                    metadata_data
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    checkpoint = VALUES(checkpoint),
                    metadata_data = VALUES(metadata_data),
                    parent_checkpoint_id = VALUES(parent_checkpoint_id)
            """, (
                thread_id,
                checkpoint_ns,
                new_checkpoint_id,
                parent_checkpoint_id,
                checkpoint_blob,  # bytes 类型，存到 LONGBLOB
                metadata_json     # JSON 字符串
            ))

            flushed_count = self._flush_deferred_writes(
                cursor,
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                checkpoint_id=new_checkpoint_id,
            )
            
            conn.commit()
            logger.info(f"Checkpoint {new_checkpoint_id} 保存成功，补写 pending writes={flushed_count}")
        
        # 返回新的 config
        # LangGraph 会用这个 config 作为下一个 checkpoint 的 parent_config
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": new_checkpoint_id,  # ← 关键：返回新ID
            }
        }
    
    def get_tuple(self, config: Dict[str, Any]) -> Optional[CheckpointTuple]:
        """
        获取一个 checkpoint
        
        这个方法会在 graph.invoke() 开始时被调用，
        用于检查是否有已保存的 checkpoint 可以恢复。
        
        Args:
            config: 配置字典
                场景1（获取最新）：
                {
                    "configurable": {
                        "thread_id": "conv_123"
                    }
                }
                
                场景2（获取特定）：
                {
                    "configurable": {
                        "thread_id": "conv_123",
                        "checkpoint_id": "uuid-111"
                    }
                }
        
        Returns:
            CheckpointTuple 对象，包含：
            - config: checkpoint 的配置
            - checkpoint: 反序列化后的 checkpoint 字典
            - metadata: 元数据
            - parent_config: 父 checkpoint 的 config
            - pending_writes: 待写入的数据（从 checkpoint_writes 表）
            
            如果没找到，返回 None
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"].get("checkpoint_id")
        
        logger.info(f"查询 checkpoint: thread_id={thread_id}, checkpoint_id={checkpoint_id}")
        
        with get_read_connection(consistency="strong") as conn:
            cursor = conn.cursor(dictionary=True)
            
            # 有 checkpoint_id，获取指定的 
            if checkpoint_id:
                cursor.execute("""
                    SELECT 
                        thread_id,
                        checkpoint_ns,
                        checkpoint_id,
                        parent_checkpoint_id,
                        checkpoint,
                        metadata_data,
                        created_at
                    FROM checkpoints
                    WHERE thread_id = %s 
                    AND checkpoint_ns = %s 
                    AND checkpoint_id = %s
                """, (thread_id, checkpoint_ns, checkpoint_id))
            
            # 没有 checkpoint_id，获取最新的 
            else:
                cursor.execute("""
                    SELECT 
                        thread_id,
                        checkpoint_ns,
                        checkpoint_id,
                        parent_checkpoint_id,
                        checkpoint,
                        metadata_data,
                        created_at
                    FROM checkpoints
                    WHERE thread_id = %s AND checkpoint_ns = %s
                    ORDER BY created_at DESC, checkpoint_id DESC
                    LIMIT 1
                """, (thread_id, checkpoint_ns))
            
            row = cursor.fetchone()
            
            # 如果没有找到任何 checkpoint
            if not row:
                logger.info(f"未找到 checkpoint，将从头开始执行")
                return None
            
            #  反序列化 checkpoint 数据 
            try:
                # 从 LONGBLOB 读取 bytes，反序列化为 Python 对象
                checkpoint_data = self._deserialize_blob(row["checkpoint"])
                
                # 解析 JSON 元数据
                metadata = json.loads(row["metadata_data"]) if row["metadata_data"] else {}
            except Exception as e:
                logger.error(f"反序列化 checkpoint 失败: {e}")
                raise
            
            # 查询 pending_writes（待写入数据
            # 这是容错机制的一部分
            cursor.execute("""
                SELECT task_id, channel, value
                FROM checkpoint_writes
                WHERE thread_id = %s 
                AND checkpoint_ns = %s 
                AND checkpoint_id = %s
                ORDER BY task_id, idx
            """, (thread_id, checkpoint_ns, row["checkpoint_id"]))
            
            write_rows = cursor.fetchall()
            
            # 反序列化每个 pending write
            pending_writes = []
            for write_row in write_rows:
                try:
                    value = self._deserialize_blob(write_row["value"]) if write_row["value"] else None
                    pending_writes.append((
                        write_row["task_id"],
                        write_row["channel"],
                        value
                    ))
                except Exception as e:
                    logger.warning(f"反序列化 pending write 失败: {e}")
            
            # 构建 parent_config（父 checkpoint 的引用）
            parent_config = None
            if row["parent_checkpoint_id"]:
                parent_config = {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": row["parent_checkpoint_id"],
                    }
                }
            
            # === 返回 CheckpointTuple 对象 ===
            logger.info(f"成功加载 checkpoint {row['checkpoint_id']}")
            
            return CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": row["checkpoint_id"],
                    }
                },
                checkpoint=checkpoint_data,  # 反序列化后的 checkpoint
                metadata=metadata,
                parent_config=parent_config,
                pending_writes=pending_writes,
            )
    
    def list(
        self,
        config: Optional[Dict[str, Any]],
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        """
        列出某个 thread 的所有 checkpoint 历史
        
        这个方法用于 graph.get_state_history(config) API
        
        Args:
            config: {"configurable": {"thread_id": "..."}}；若为 None，则列出所有 thread。
            filter: 过滤条件（暂未使用）
            before: 获取某个 checkpoint 之前的历史（暂未使用）
            limit: 限制返回数量
        
        Yields:
            CheckpointTuple 对象（按时间倒序）
            
        示例：
            config = {"configurable": {"thread_id": "conv_123"}}
            history = list(checkpointer.list(config, limit=10))
            # history[0] 是最新的
            # history[1] 是第2新的
            # ...
        """
        configurable = (config or {}).get("configurable", {})
        thread_id = configurable.get("thread_id")
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        
        logger.info(f"列出 checkpoint 历史: thread_id={thread_id or '*'}")
        
        with get_read_connection(consistency="strong") as conn:
            cursor = conn.cursor(dictionary=True)
            
            # 构建 SQL 查询
            query = """
                SELECT 
                    thread_id,
                    checkpoint_ns,
                    checkpoint_id,
                    parent_checkpoint_id,
                    checkpoint,
                    metadata_data,
                    created_at
                FROM checkpoints
            """
            params = []

            if thread_id:
                query += " WHERE thread_id = %s AND checkpoint_ns = %s"
                params.extend([thread_id, checkpoint_ns])

            query += " ORDER BY created_at DESC, checkpoint_id DESC"
            
            # 如果指定了 limit，添加到查询
            if limit:
                query += " LIMIT %s"
                params.append(limit)
            
            cursor.execute(query, params)
            
            # 遍历所有行，yield CheckpointTuple 
            for row in cursor:
                try:
                    # 反序列化
                    checkpoint_data = self._deserialize_blob(row["checkpoint"])
                    metadata = json.loads(row["metadata_data"]) if row["metadata_data"] else {}
                    
                    # 构建 parent_config
                    parent_config = None
                    if row["parent_checkpoint_id"]:
                        parent_config = {
                            "configurable": {
                                "thread_id": row["thread_id"],
                                "checkpoint_ns": row["checkpoint_ns"],
                                "checkpoint_id": row["parent_checkpoint_id"],
                            }
                        }
                    
                    # yield 返回
                    yield CheckpointTuple(
                        config={
                            "configurable": {
                                "thread_id": row["thread_id"],
                                "checkpoint_ns": row["checkpoint_ns"],
                                "checkpoint_id": row["checkpoint_id"],
                            }
                        },
                        checkpoint=checkpoint_data,
                        metadata=metadata,
                        parent_config=parent_config,
                        pending_writes=[],  # list() 不需要返回 pending_writes
                    )
                
                except Exception as e:
                    logger.error(f"处理 checkpoint 历史时出错: {e}")
                    continue
    
    def put_writes(
        self,
        config: Dict[str, Any],
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """
        保存 pending writes（待写入数据）
        
        容错机制：当节点执行到一半崩溃时，已完成的写操作会保存到这里。
        恢复时，LangGraph 会重新应用这些写操作。
        
        Args:
            config: {"configurable": {"thread_id": "...", "checkpoint_id": "..."}}
            
            writes: 写操作列表
                [
                    ("channel_name1", value1),  # 例如：("messages", [AIMessage(...)])
                    ("channel_name2", value2),  # 例如：("analysis_parameters", {...})
                    ...
                ]
            
            task_id: 任务ID（LangGraph 生成）
            task_path: 任务路径（LangGraph 内部使用，默认为空字符串）
        
        示例场景：
            fold_node 执行时：
            1. 准备写入 {"analysis_parameters": {...}}
            2. LangGraph 调用 put_writes() 保存
            3. 如果崩溃，下次恢复时会重新应用这个写入
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]
        
        logger.info(
            f"保存 {len(writes)} 个 pending writes: "
            f"thread_id={thread_id}, checkpoint_id={checkpoint_id}, task_id={task_id}"
        )
        
        with get_write_connection() as conn:
            cursor = conn.cursor()
            try:
                saved_count = self._insert_pending_writes(
                    cursor,
                    config=config,
                    writes=writes,
                    task_id=task_id,
                )
                conn.commit()
                logger.info(f"{saved_count} 个 pending writes 保存成功")
            except Exception as exc:
                if not is_missing_checkpoint_foreign_key_error(exc):
                    raise
                if hasattr(conn, "rollback"):
                    conn.rollback()
                self._defer_writes(config, writes, task_id, task_path)
                logger.warning(
                    "checkpoint_writes 外键父 checkpoint 暂不可用，已延迟写入: "
                    "thread_id=%s, checkpoint_ns=%s, checkpoint_id=%s, task_id=%s, writes=%s",
                    thread_id,
                    checkpoint_ns,
                    checkpoint_id,
                    task_id,
                    len(writes),
                )

    def _insert_pending_writes(
        self,
        cursor,
        config: Dict[str, Any],
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
    ) -> int:
        """按 LangGraph 特殊 write upsert、普通 write 忽略重复的语义写入。"""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]
        saved_count = 0

        upsert_known_writes = all(
            channel in WRITES_IDX_MAP
            for channel, _value in writes
        )
        insert_sql = """
            INSERT INTO checkpoint_writes (
                thread_id,
                checkpoint_ns,
                checkpoint_id,
                task_id,
                idx,
                channel,
                value,
                write_identity_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        if upsert_known_writes:
            insert_sql += """
                ON DUPLICATE KEY UPDATE
                    channel = VALUES(channel),
                    value = VALUES(value)
            """
        else:
            insert_sql = insert_sql.replace(
                "INSERT INTO checkpoint_writes",
                "INSERT IGNORE INTO checkpoint_writes",
                1,
            )

        for idx, (channel, value) in enumerate(writes):
            write_idx = WRITES_IDX_MAP.get(channel, idx)
            value_blob = self._serialize_blob(value)
            cursor.execute(insert_sql, (
                thread_id,
                checkpoint_ns,
                checkpoint_id,
                task_id,
                write_idx,
                channel,
                value_blob,
                _pending_write_identity_hash(
                    thread_id,
                    checkpoint_ns,
                    checkpoint_id,
                    task_id,
                    write_idx,
                ),
            ))
            if cursor.rowcount:
                saved_count += 1

        return saved_count

    def _defer_writes(
        self,
        config: Dict[str, Any],
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
        task_path: str,
    ) -> None:
        """Keep pending writes in memory when MySQL FK ordering rejects them temporarily."""
        self._deferred_writes.append((config, tuple(writes), task_id, task_path))

    def _flush_deferred_writes(
        self,
        cursor,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
    ) -> int:
        """Flush deferred writes that match a checkpoint just saved by put()."""
        flushed_count = 0
        remaining = []

        for config, writes, task_id, task_path in self._deferred_writes:
            configurable = config.get("configurable", {})
            matches_checkpoint = (
                configurable.get("thread_id") == thread_id
                and configurable.get("checkpoint_ns", "") == checkpoint_ns
                and configurable.get("checkpoint_id") == checkpoint_id
            )
            if not matches_checkpoint:
                remaining.append((config, writes, task_id, task_path))
                continue

            try:
                flushed_count += self._insert_pending_writes(
                    cursor,
                    config=config,
                    writes=writes,
                    task_id=task_id,
                )
            except Exception as exc:
                logger.warning(
                    "延迟 pending writes 补写失败，继续保留: checkpoint_id=%s, task_id=%s, error=%s",
                    checkpoint_id,
                    task_id,
                    exc,
                )
                remaining.append((config, writes, task_id, task_path))

        self._deferred_writes = remaining
        return flushed_count

    # ===== 异步方法实现（用于 ainvoke/astream） =====
    
    async def aget_tuple(self, config: Dict[str, Any]) -> Optional[CheckpointTuple]:
        """
        异步获取 checkpoint
        
        这个方法会在 graph.ainvoke() 或 graph.astream() 时被调用。
        使用 asyncio.to_thread() 将同步的 get_tuple() 方法在线程池中执行，
        避免阻塞事件循环。
        
        Args:
            config: 配置字典（与 get_tuple 相同）
        
        Returns:
            CheckpointTuple 或 None
        """
        # 在线程池中执行同步方法，避免阻塞事件循环
        return await asyncio.to_thread(self.get_tuple, config)
    
    async def aput(
        self,
        config: Dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        异步保存 checkpoint
        
        Args:
            config: 配置字典
            checkpoint: Checkpoint 对象
            metadata: 元数据
            new_versions: 新版本信息
        
        Returns:
            更新后的 config
        """
        # 在线程池中执行同步方法
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)
    
    async def alist(
        self,
        config: Optional[Dict[str, Any]],
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """
        异步列出 checkpoint 历史
        
        Args:
            config: 配置字典；若为 None，则列出所有 thread。
            filter: 过滤条件
            before: 获取某个 checkpoint 之前的历史
            limit: 限制返回数量
        
        Yields:
            CheckpointTuple 对象
        """
        # 在线程池中执行同步 list，然后异步 yield 结果
        # 由于 list() 返回一个生成器，我们需要先收集所有结果
        checkpoints = await asyncio.to_thread(
            lambda: list(self.list(config, filter=filter, before=before, limit=limit))
        )
        
        # 异步 yield 每个 checkpoint
        for checkpoint_tuple in checkpoints:
            yield checkpoint_tuple
    
    async def aput_writes(
        self,
        config: Dict[str, Any],
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """
        异步保存 pending writes
        
        Args:
            config: 配置字典
            writes: 写操作列表
            task_id: 任务ID
            task_path: 任务路径
        """
        # 在线程池中执行同步方法
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)


#辅助方法（可选，用于调试和管理）

    def delete_thread(self, thread_id: str) -> None:
        """
        删除某个 thread 的所有 checkpoints
        
        用途：
        - 用户删除对话历史时调用
        - 清理旧数据
        
        Args:
            thread_id: 要删除的 thread ID
        """
        logger.info(f"删除 thread: {thread_id}")
        
        with get_write_connection() as conn:
            cursor = conn.cursor()
            
            # MySQL 会自动级联删除（如果设置了外键）
            # 或者手动删除相关的 checkpoint_writes
            cursor.execute("""
                DELETE FROM checkpoint_writes
                WHERE thread_id = %s
            """, (thread_id,))
            
            cursor.execute("""
                DELETE FROM checkpoints
                WHERE thread_id = %s
            """, (thread_id,))
            
            conn.commit()
            logger.info(f" Thread {thread_id} 的所有 checkpoints 已删除")
    
    def get_checkpoint_count(self, thread_id: str) -> int:
        """
        获取某个 thread 的 checkpoint 数量（调试用）
        
        Args:
            thread_id: Thread ID
            
        Returns:
            checkpoint 数量
        """
        with get_read_connection(consistency="strong") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM checkpoints
                WHERE thread_id = %s
            """, (thread_id,))
            
            result = cursor.fetchone()
            count = result[0] if result else 0
            
            logger.info(f"Thread {thread_id} 有 {count} 个 checkpoints")
            return count



if __name__ == "__main__":
    """
    测试 MySQLSaver 的基本功能
    
    运行：python Database/mysql_checkpointer.py
    """
    
    # 配置数据库连接
    test_config = {
        'host': 'localhost',
        'port': 3306,
        'user': 'root',
        'password': 'your_password',
        'database': 'causalagent'
    }
    
    # 创建 checkpointer
    checkpointer = MySQLSaver(connection_config=test_config)
    
    # 初始化表（如果没用 Alembic）
    # checkpointer.setup()
    
    # 测试保存
    test_checkpoint = {
        "v": 1,
        "id": "test-checkpoint-123",
        "ts": "2024-01-15T10:00:00",
        "channel_values": {
            "messages": ["Hello", "World"],
            "count": 42
        }
    }
    
    test_metadata = {
        "source": "test",
        "step": 1
    }
    
    config = {
        "configurable": {
            "thread_id": "test-thread-1",
            "checkpoint_ns": ""
        }
    }
    
    # 保存
    new_config = checkpointer.put(config, test_checkpoint, test_metadata, {})
    print(f"保存成功！新 config: {new_config}")
    
    # 获取
    retrieved = checkpointer.get_tuple(config)
    if retrieved:
        print(f"恢复成功！Checkpoint ID: {retrieved.config['configurable']['checkpoint_id']}")
        print(f"State 内容: {retrieved.checkpoint['channel_values']}")
    
    # 查看历史
    print("\n=== Checkpoint 历史 ===")
    for idx, checkpoint_tuple in enumerate(checkpointer.list(config, limit=5)):
        print(f"{idx+1}. Checkpoint {checkpoint_tuple.config['configurable']['checkpoint_id']}")
        print(f"   Step: {checkpoint_tuple.metadata.get('step')}")
        print(f"   Time: {checkpoint_tuple.checkpoint.get('ts')}")
    
    print("\n测试完成！")

