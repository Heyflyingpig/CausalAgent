# Database/AGENTS.md

生效目录：`Database/` 及其子目录。

负责约束的修改类型：Alembic migration、bootstrap、MySQL 主从连接、PostgreSQL checkpoint、monitor、cleanup worker、数据库审计和任何可能改变数据/结构的操作。

## 修改前必须核对

- 必须阅读 [`Document/database/overview.md`](../Document/database/overview.md)、[`consistency.md`](../Document/database/consistency.md)、[`migrations-checkpoints.md`](../Document/database/migrations-checkpoints.md) 和 [`monitoring.md`](../Document/database/monitoring.md)。
- 必须检查当前 `alembic heads`、相关 migration 的 `revision/down_revision`、`Database/bootstrap.py`、`app/db.py`、当前 Compose 拓扑和对应测试。
- 修改表结构时必须检查所有 SQL 读写、`check_database_readiness()`、管理员/Job/File 服务和测试种子；不能只检查 migration 文件。

## Schema 与迁移规则

- 业务表结构必须通过 `Database/migrations/versions/` 维护；禁止把业务建表逻辑重新放入 `database_init.py`。
- 禁止修改已形成事实的历史 migration 来掩盖旧库问题；需要兼容旧库时必须新增 migration，并明确升级、降级和数据风险。
- 破坏性迁移必须明确说明是否删除数据、是否回填、downgrade 是否只恢复空结构；禁止静默删除、隐式 fallback 或在 migration 中调用自动修复 CLI，由修改任务定义
- 全新空库必须直接走 bootstrap；`audit_before_db_upgrade.py` 只用于满足其前置条件的旧库外键升级 preflight。
- 修改迁移 head、Compose 启动顺序或数据库初始化方式时，必须同步检查 `Document/` 和根 `AGENTS.md`；本轮文档重构不得修改根 `README.md`。

## 一致性与危险操作

- 必须按 strong/eventual 语义选择读连接；授权、Job 队列/事件、所有权校验、删除和计数更新不得为了“读写分离”改走未确认健康的副本。
- 复制状态异常或延迟超阈值只能回退主库，禁止在应用内擅自实现自动切主。
- MySQL 与 PostgreSQL 之间禁止伪造分布式事务；业务删除必须和 cleanup outbox 在同一 MySQL 事务落盘，再由 cleanup worker 异步执行 checkpoint 删除。
- 禁止在 SQL、日志、快照或 API 中输出密码、账号、host、连接串、grants、文件 BLOB 或原始 `last_error`。
- 删除表、数据卷、历史 migration、checkpoint 或用户数据属于高风险操作；执行前必须有明确范围和隔离环境验证，不能用 `down -v` 代替数据管理。

## 修改后验证

- 必须运行与变更直接相关的 unit/integration 测试；迁移变更至少检查 `alembic heads`、空库 upgrade、指定目标 downgrade/upgrade 和 `git diff --check`。
- checkpoint、主从或 monitor 变更必须在 Docker 拓扑中验证；unit 结果不能替代真实数据库证据。
- 必须检查快照的 `source_role/source_alias`、`observed_at`、estimate/warning 语义和脱敏边界。
- 不能验证真实数据库时，必须在最终说明中明确未验证的迁移、主从、checkpoint 或容量风险。
