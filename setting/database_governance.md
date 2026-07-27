# 阶段一 3.2 数据库治理与受控写入说明

本文冻结阶段一结束时的业务写入、数据生命周期、读写一致性、事务和连接容量口径。管理员后台仍不提供任意 SQL、迁移、数据库账号授权、复制控制或任务强制控制。

## 1. 受控管理员写入

管理员用户写操作只通过现有 `/api/admin/business/*` 命名空间开放：

- `POST /users/operations/preview`：预览单个或批量启停、角色切换、改密。
- `POST /users/operations`：执行预览后的用户操作。
- `GET /users/<id>/delete-impact`、`DELETE /users/<id>`：预览并物理删除用户。
- `GET /files/<id>/delete-impact`、`DELETE /files/<id>`：预览并物理删除文件行与 BLOB。

执行接口统一要求有效管理员 Session、Session 绑定的 CSRF、`Idempotency-Key`、当前管理员密码重新认证和明确确认。批量默认最多 20、硬上限 50 个目标。密码只出现在 HTTPS JSON 请求体和内存中；同密码批量设置会为每个目标分别调用 bcrypt 生成独立盐值哈希，响应、日志、操作记录和审计均不保存明文或哈希。

受控改密采用长度优先规则：15～64 个字符且不超过 bcrypt 可安全处理的 72 UTF-8 bytes，不强制大小写/数字/符号组合。该口径遵循 [NIST SP 800-63B](https://pages.nist.gov/800-63-4/sp800-63b.html) 与 [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html) 的长口令方向，并按 [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) 明确处理 bcrypt 输入上限。

`users.auth_version` 是服务端会话版本。角色、状态或密码实际变化时递增；后续任意受保护请求发现 Cookie Session 版本不一致会清空会话。操作者不能禁用、降级或删除自己；事务会锁定全部启用管理员，再判断变更后是否至少保留一个启用管理员。

`admin_operations` 保存幂等操作主记录和去敏结果，`admin_operation_items` 保存逐目标结果；成功业务变更与逐目标 `admin_audit_events` 在同一个主库事务提交。相同操作者、相同幂等键、相同请求返回原结果；同键异参返回 `idempotency_conflict`。

## 2. 删除与保留矩阵

| 入口 | 事务内删除 | 保留 | 阻断条件 |
| --- | --- | --- | --- |
| 普通用户删除会话 | 对应 checkpoint；pending writes 由 checkpoint 外键级联；随后删除 session，消息和附件按外键级联 | 用户、文件、其他会话、历史审计 | 会话有 `queued/running` job |
| 管理员删除用户 | 该用户 session 对应 checkpoint、归档会话、用户行；session/message/attachment/file/job/event 依赖现有外键级联 | 去敏管理员操作、逐项操作和审计；操作者外键按 `SET NULL` 保留历史 | 删除自己、最后启用管理员、活动 job、关联行超过同步阈值 |
| 管理员删除文件 | `uploaded_files` 单行及同一行 BLOB | 用户、会话、job、审计 | 因文件与 job 无稳定直接关系，只要归属用户有活动 job 就保守阻断 |
| 管理员改角色/状态/密码 | 不删除业务数据；实际变化时递增 `auth_version` | 全部业务数据与去敏审计 | 操作者自我禁用/降级、最后启用管理员 |

文件删除不提供回收站，必须在影响预览中完整输入原始文件名。用户删除默认同步关联行上限为 10000，超过后不在 Web 请求中处理。

代码与当前实例均证明 LangGraph `thread_id` 使用 `session_id`。由于两列定义并不完全一致，3.2 不冒险增加 `checkpoints.thread_id → sessions.id` 外键；会话和用户删除继续显式先删 checkpoint，pending writes 由既有复合外键级联。

历史孤立数据不能由 migration 静默删除。以下命令默认只输出每类最多 100 个主键/复合键，不读取正文：

```bash
python -m Database.lifecycle_repair
python -m Database.lifecycle_repair --limit 100
```

只有维护者核对清单后，才能显式执行有限批次：

```bash
python -m Database.lifecycle_repair --limit 100 --apply --confirm-database <MYSQL_DATABASE>
```

## 3. 读写一致性矩阵

| 数据路径 | 一致性 | 原因 |
| --- | --- | --- |
| 登录、Session 恢复、管理员授权、CSRF 后写入前复核 | 主库强一致读 | 角色、启用状态和认证版本不能读取旧值 |
| 用户写入/删除预览、文件删除预览 | 主库强一致读 | 预览必须基于最新安全状态；执行时仍会加锁重算 |
| 用户启停、角色、改密、用户/文件删除、访问计数、任务状态、SSE 事件、checkpoint | 主库写 | 都参与事务、幂等或实时顺序 |
| 管理列表与敏感详情 | 主库强一致读 | 管理员必须看到已提交结果和精确目标 |
| 普通用户历史会话、历史文件列表等允许短暂延迟的列表 | `eventual` | 副本健康且延迟不超过阈值时读副本，否则回退主库 |
| Job 创建、领取、心跳、终态与事件读取 | 主库或强一致读 | 不能因副本延迟重复领取或漏读实时事件 |
| 容量估算 | `eventual` | 允许估算并明确标记来源 |
| revision、约束、完整性、权限和复制状态 | 主库或专用观测连接 | 不使用业务副本结果代替事实判断 |

从库状态按 host 在进程内缓存 2 秒，失败结果也短时缓存；缓存失效后重新检查。任一状态账号缺失、复制线程异常、延迟未知/超阈值或副本连接失败都会安全回退主库，不自动切主或故障转移。

## 4. 事务与幂等边界

高风险管理员事务固定使用 `READ COMMITTED`，锁等待默认 5 秒。锁顺序为：操作者用户 → 全部启用管理员（用户批量/用户删除）→ 目标用户（按 ID 排序）→ 子记录。文件删除先锁操作者，再锁文件归属用户、文件行和归属用户的活动 job。

执行前会再次检查管理员密码、角色、状态、目标存在性、明确确认、最后管理员、活动 job 和同步删除规模；受影响行数不符合预期时整体回滚。死锁或锁等待超时返回 `transaction_retryable`，调用方必须复用原 `Idempotency-Key`。并发相同请求在取得操作者锁后会回读已提交结果，不会重复删除。

`checkpoint_writes` 的真实幂等键是 `(thread_id, checkpoint_ns, checkpoint_id, task_id, idx)`。四个 `utf8mb4 VARCHAR(255)` 直接联合索引会超过 InnoDB 索引字节上限，因此应用按完整长度前缀编码计算 SHA-256 `BINARY(32)` 摘要，migration 对既有行使用相同表达式回填后建立唯一索引，不截断任何 LangGraph 标识。这里不能使用 `STORED` 生成列，因为其基列属于带 `ON DELETE CASCADE` 的 checkpoint 复合外键，MySQL 明确限制这类组合。已知特殊 channel 使用 upsert 更新，普通 pending write 使用 insert-ignore；最新 checkpoint 固定按 `created_at DESC, checkpoint_id DESC` 排序。

技术依据：MySQL 8.0 官方文档说明默认 16 KiB page 下 InnoDB 索引键上限为 [3072 bytes](https://dev.mysql.com/doc/refman/8.0/en/innodb-limits.html)，并在 [Generated Columns](https://dev.mysql.com/doc/refman/8.0/en/create-table-generated-columns.html) 中明确限制带级联动作外键的基列；`UNHEX(SHA2(...))` 以 `BINARY(32)` 存储摘要符合官方的二进制存储建议（[Encryption and Compression Functions](https://dev.mysql.com/doc/refman/8.0/en/encryption-functions.html)）。

## 5. 连接容量与超时依据

2026-07-27 对当前非生产主从实例只读核对：MySQL `8.0.46`，`max_connections=151`，`Max_used_connections=31`，`Threads_connected=31`，`Threads_running=3`；从库 IO/SQL 均为 `Yes`，观测延迟为 0 秒。核对时 revision 为 `d3e4f5a6b7c8`，3.2 migration 尚未执行。该快照会漂移，发布前必须重新测量。

每个 OS 进程的池上限公式是：

```text
write_pool + read_pool * (1 + replica_count)
```

默认一主一从为 `5 + 5 * 2 = 15`。当前一个 Web worker 进程、一个 worker 进程和一个 monitor 进程理论共 45 个池连接；worker slot 共享所在进程的全局池，不按 `JOB_WORKERS` 再乘。复制状态观测、migration 和运维连接是短时额外连接。45 距 70% warning 线（约 105）仍有 60 个连接余量；当前历史峰值 31 距 warning 线有 74 个。扩大 Web worker、后台进程或副本数前必须按公式重算。

单池大小被限制在 MySQL Connector/Python 支持的最大值 32。默认连接建立超时 5 秒、池获取超时 3 秒、获取重试间隔 50 毫秒、管理员锁等待 5 秒、复制状态缓存 2 秒；池耗尽和锁冲突都有限失败，不无限等待。

## 6. 发布与恢复

`Database/database_init.py` 仍只确保数据库存在并检查连接，结构升级唯一入口是 Alembic。发布顺序：

```bash
python Database/database_init.py
python Database/audit_before_db_upgrade.py
alembic upgrade head
```

空库不先执行 preflight。现有库升级前使用 `Database/audit_before_db_upgrade.py` 按当前 revision 只读确认仍待建立的外键和 pending write 业务键无异常；若发现重复，停止 migration，先用专用清单和人工决策处理，禁止在 migration 内删除。升级后的 deep 审计通过管理员手动请求并由独立 monitor 执行，不直接运行 `Database/deep_audit.py`。

生产发布前必须在隔离数据库分别完成空库升级、现有结构升级、`downgrade -1` 后重新升级，或完成可还原备份的恢复演练。迁移前先备份，应用、worker、monitor 应在同一维护窗口升级，避免新代码读取旧 schema。当前开发数据库没有因本次实现被迁移。

阶段三并发设计交接见 `setting/phase3_concurrency_handoff.md`；3.2 没有启用 fencing token、事件 UUID、heartbeat 监督或任务终态新协议。
