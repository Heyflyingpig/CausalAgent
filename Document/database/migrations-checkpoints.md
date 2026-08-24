# 迁移与 Checkpoint

文档职责：记录 MySQL/Alembic/bootstrap、PostgreSQL checkpoint setup、cleanup outbox 以及具有破坏性的迁移事实。

适用范围：修改 `Database/bootstrap.py`、`Database/migrations/versions/`、checkpoint 配置、cleanup worker 或部署初始化顺序时使用；数据库危险操作的执行约束见 [`../../Database/AGENTS.md`](../../Database/AGENTS.md)。

## 初始化顺序

`Database/database_init.py` 只加载环境变量、确保 MySQL 数据库存在并执行连接检查。完整入口 `python -m Database.bootstrap` 按顺序执行：

1. MySQL 建库/连接准备。
2. 必要的旧库 schema-aware preflight；若 `b2c3d4e5f6a7` 前存在旧 Job 执行占用，则明确拒绝并要求先运行显式修复工具。
3. `alembic upgrade head` 维护 MySQL 业务 schema。
4. 官方 LangGraph PostgreSQL checkpointer schema setup。

Docker Compose 中 `db-bootstrap` 是一次性服务，`app`、worker、monitor 和 cleanup 依赖其成功退出后再启动。全新空库不需要先运行旧库 preflight；`Database/audit_before_db_upgrade.py` 只服务于已存在、尚未建立目标外键且即将执行相关迁移的旧库。程序化 bootstrap 会保留共享 JSON stderr handler，不让 Alembic 的 `fileConfig` 覆盖最终失败事件；直接运行 Alembic CLI 时仍使用 `alembic.ini` 的终端日志配置。

## 当前迁移链

当前 head 是 `c3d4e5f6a7b8`。迁移按职责演进如下，最终链路和 down revision 以文件内容为准：

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
| `a1b2c3d4e5f6` | 文件库替换、冻结文件快照、resume 输入账本和 Job 恢复字段 |
| `b2c3d4e5f6a7` | 取消后的执行占用、释放时间/原因和 worker fencing 状态 |
| `c3d4e5f6a7b8` | `analysis_jobs.request_id` 创建请求关联字段 |

`f8b9c0d1e2f3` 的 `down_revision` 声明为 `e4f5a6b7c8d9` 与 `e7a9b2c3d4f5`，随后由 `f9a0b1c2d3e4`、`a1b2c3d4e5f6`、`b2c3d4e5f6a7` 和 `c3d4e5f6a7b8` 继续。回退这类合并迁移必须指定明确目标 revision，不能用 `alembic downgrade -1` 代替。

## 破坏性事实

- `f8b9c0d1e2f3` 建立 `checkpoint_cleanup_outbox` 后直接删除 MySQL `checkpoint_writes` 和 `checkpoints` 表及其数据；PostgreSQL 才是运行时 checkpoint 真相。downgrade 只重建空的兼容表结构，不恢复数据。
- `a1b2c3d4e5f6` 直接 `DROP TABLE IF EXISTS uploaded_files`，创建 `file_objects`、`user_files` 和 Job 输入结构；不回填旧数据、不提供旧数据 fallback，也不增加旧数据拒绝迁移逻辑。downgrade 只恢复空的旧 `uploaded_files` 表结构。
- `c3d4e5f6a7b8` 为 `analysis_jobs` 增加可空的 `request_id VARCHAR(64)`；历史行不回填，创建请求由服务层保存首次请求 ID，幂等重放不覆盖该值。该字段没有索引，downgrade 只删除本字段。
- 迁移脚本属于高风险历史事实，不应为了让本地旧库“看起来能升级”而静默删除、回填或修改历史 migration。

## `b2c3d4e5f6a7` 旧 Job 兼容修复

旧版本可能在已经结束或尚未领取的 Job 上保留 `worker_id` / `locked_at`。`b2c3d4e5f6a7` 增加执行状态约束时会拒绝这些历史行；bootstrap 的只读 preflight 会在 Alembic 前停止，不会自动改数据。先确认 app、worker、monitor 和 cleanup 未运行，再执行默认 dry-run：

```bash
docker compose run --rm --no-deps db-bootstrap python -m Database.job_execution_upgrade_repair
```

dry-run 只返回 revision、目标迁移列、运行中 Job 数和可修复条数，不返回 Job ID、worker 标识或数据库连接信息。只有 `running_count=0` 时才能修复；实际执行必须把 dry-run 的 revision 和 `repairable_count` 原样带回，并精确确认当前数据库：

```bash
docker compose run --rm --no-deps db-bootstrap sh -c 'python -m Database.job_execution_upgrade_repair --apply --confirm-database "$MYSQL_DATABASE" --confirm-revision <CURRENT_REVISION> --expected-count <REPAIRABLE_COUNT>'
docker compose up --force-recreate db-bootstrap
```

修复在单个 `SERIALIZABLE` 主库事务中重新核对并锁定候选行，只把非运行 Job 的 `worker_id` 和 `locked_at` 置空；不删除任务，不改状态、结果、`heartbeat_at` 或业务正文。revision、候选条数、运行状态、目标列或提交后的复查任一变化都会回滚并拒绝执行。该工具不由 migration 自动调用，也不能用 `alembic stamp` 或清卷替代。

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
- [`../../Database/job_execution_upgrade_repair.py`](../../Database/job_execution_upgrade_repair.py)：`b2c3d4e5f6a7` 前旧 Job 执行占用的 dry-run 与显式修复。
