# 迁移与 Checkpoint

文档职责：记录 MySQL/Alembic/bootstrap、PostgreSQL checkpoint setup、cleanup outbox 以及具有破坏性的迁移事实。

适用范围：修改 `Database/bootstrap.py`、`Database/migrations/versions/`、checkpoint 配置、cleanup worker 或部署初始化顺序时使用；数据库危险操作的执行约束见 [`../../Database/AGENTS.md`](../../Database/AGENTS.md)。

## 初始化顺序

`Database/database_init.py` 只加载环境变量、确保 MySQL 数据库存在并执行连接检查。完整入口 `python -m Database.bootstrap` 按顺序执行：

1. MySQL 建库/连接准备。
2. 必要的旧库 schema-aware preflight。
3. `alembic upgrade head` 维护 MySQL 业务 schema。
4. 官方 LangGraph PostgreSQL checkpointer schema setup。

Docker Compose 中 `db-bootstrap` 是一次性服务，`app`、worker、monitor 和 cleanup 依赖其成功退出后再启动。全新空库不需要先运行旧库 preflight；`Database/audit_before_db_upgrade.py` 只服务于已存在、尚未建立目标外键且即将执行相关迁移的旧库。

## 当前迁移链

当前唯一 head 是 `s4d5e6f7a8b9`。develop 的 migration 作为主体链路，RAG 评测 DDL 使用独立且全仓唯一的 revision ID，最终由无 DDL 合流点统一；最终链路和 down revision 以文件内容为准：

| Revision | 当前作用 |
| --- | --- |
| `1a2b3c4d5e6f` | 核心用户、Session、消息、附件、旧文件和归档表 |
| `bae097eab4b3` | 早期 MySQL checkpoint 表 |
| `9359bc171e66` / `d876b980dc9a` | 附件可视化字段和内容容量调整 |
| `f6b8c9d0e1a2` | 移除聊天分区、重建主键/索引并补充业务外键 |
| `e7a9b2c3d4f5` | `analysis_jobs` 与 Job Event |
| `a8b9c0d1e2f3` / `b1c2d3e4f5a6` / `c2d3e4f5a6b7` | 用户角色、共享 monitor 快照、在线配置和管理员审计 |
| `d3e4f5a6b7c8` / `e4f5a6b7c8d9` | 管理员读取索引、受控写入、操作账本和 `auth_version` |
| `f8b9c0d1e2f3` | MySQL checkpoint -> PostgreSQL，建立 cleanup outbox |
| `f9a0b1c2d3e4` | Job 请求幂等键和请求指纹 |
| `a1b2c3d4e5f6` / `b2c3d4e5f6a7` / `c3d4e5f6a7b8` | develop 权威的文件库与 Job 恢复、执行释放、请求 ID |
| `1c2d3e4f5a6b` / `2d3e4f5a6b7c` / `a0b1c2d3e4f5` | develop 联网搜索字段、引用附件类型及其与 request ID 的合流 |
| `r1a2b3c4d5e6f` / `r2b3c4d5e6f7` | RAG 评测 profile 与持久 Job 队列 |
| `r3c4d5e6f7a8` / `g7c8d9e0f1a2` / `h8d9e0f1a2b3` / `i9e0f1a2b3c4` | RAG 评测与 PostgreSQL 合流、任务类型、数据集注册和队列优先级 |
| `s4d5e6f7a8b9` | develop `a0b1c2d3e4f5` 与 RAG 最终 head 的统一无 DDL head |

`f8b9c0d1e2f3` 的 `down_revision` 声明为 `e4f5a6b7c8d9` 与 `e7a9b2c3d4f5`；develop 主链随后经 `f9a0b1c2d3e4`、`a1b2c3d4e5f6`、`b2c3d4e5f6a7`、`c3d4e5f6a7b8` 和 `a0b1c2d3e4f5` 继续，RAG 分支经 `r1...`、`r2...`、`r3...`、`g7...`、`h8...`、`i9...` 继续，最终由 `s4d5e6f7a8b9` 合流。回退这类合并迁移必须指定明确目标 revision，不能用 `alembic downgrade -1` 代替。

## 破坏性事实

- `f8b9c0d1e2f3` 建立 `checkpoint_cleanup_outbox` 后直接删除 MySQL `checkpoint_writes` 和 `checkpoints` 表及其数据；PostgreSQL 才是运行时 checkpoint 真相。downgrade 只重建空的兼容表结构，不恢复数据。
- `a1b2c3d4e5f6` 直接 `DROP TABLE IF EXISTS uploaded_files`，创建 `file_objects`、`user_files` 和 Job 输入结构；不回填旧数据、不提供旧数据 fallback，也不增加旧数据拒绝迁移逻辑。downgrade 只恢复空的旧 `uploaded_files` 表结构。
- 迁移脚本属于高风险历史事实，不应为了让本地旧库“看起来能升级”而静默删除、回填或修改历史 migration。

## PostgreSQL checkpoint

`Database/checkpoint_setup.py` 调用官方 `AsyncPostgresSaver.setup()` 创建 checkpoint schema。worker 以 `analysis_jobs.job_id` 作为 `thread_id`，根 `checkpoint_ns` 为空；`config.metadata` 同时保存 `job_id` 和业务 `session_id`，供管理员安全摘要精确关联。

管理员和 monitor 的 quick integrity 只读检查连接、官方表集合和 setup migration 版本；deep audit 额外检查字段/主键、估算统计和最多 20 个跨库 `thread_id -> analysis_jobs.job_id` 关系样本。checkpoint API 不读取或返回状态正文、blob 或 pending writes，缺少 `metadata.job_id` 的历史记录不按时间猜测归属。

## Cleanup outbox

MySQL 删除 Session 或用户时，在同一个业务事务中为相关 Job 写入 `(thread_id)` 唯一的 `checkpoint_cleanup_outbox` 记录。cleanup worker 使用 `FOR UPDATE SKIP LOCKED` 领取，写入租约并调用 PostgreSQL `adelete_thread(job_id)`；租约过期可再次领取，最多执行有限次数，失败按退避重试。管理员用户删除操作通过 `operation_id` 聚合 outbox 状态为 `running`、`succeeded` 或 `failed`。

cleanup worker 按 `CHECKPOINT_CLEANUP_HEARTBEAT_INTERVAL_SECONDS` 发布脱敏心跳，默认 10 秒；运行快照只保存逻辑 worker 状态、计数、时间和安全错误结论，不保存 host、账号或原始 `last_error`。

## 相关入口

- [`../../alembic.ini`](../../alembic.ini)：Alembic script location。
- [`../../Database/bootstrap.py`](../../Database/bootstrap.py)：统一初始化编排。
- [`../../Database/checkpoint_setup.py`](../../Database/checkpoint_setup.py)：PostgreSQL setup。
- [`../../Database/checkpoint_cleanup_worker.py`](../../Database/checkpoint_cleanup_worker.py)：跨库清理 worker。
- [`../../Database/audit_before_db_upgrade.py`](../../Database/audit_before_db_upgrade.py)：旧库升级前 preflight。
