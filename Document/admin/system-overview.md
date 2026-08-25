# 管理员系统结构说明

文档职责：以架构图和功能地图概览管理员系统当前组成、安全边界及运维交接要点；详细实现由管理员模块权威文档负责。

适用范围：面向管理员前后端、数据库治理和后台进程的整体理解；接口、部署和测试细节分别以 [API 契约](api.md)、[开发说明](development.md) 和 [测试说明](testing.md) 为准。

> 当前事实基线：阶段一管理员后台及截至 2026-08-24 的后续修复；历史来源包括 PR [#23](https://github.com/Heyflyingpig/CausalAgent/pull/23)、[#27](https://github.com/Heyflyingpig/CausalAgent/pull/27) 和 [#28](https://github.com/Heyflyingpig/CausalAgent/pull/28)。

## 一、定位与架构

管理员系统是独立于普通聊天页面的治理面：前端位于 `admin-frontend/`，采用 Vue 3、TypeScript、Vue Router、Element Plus 和 Vite；Flask 负责页面鉴权、API 与生产静态资源托管。Node 只参与镜像构建，生产运行时不启动 Vite。

```mermaid
flowchart LR
  Admin["管理员浏览器"]
  subgraph Web["Web 层"]
    Vue["Vue 3 管理端<br>Flask 托管构建产物"]
    Gate["Flask 鉴权门<br>实时授权 + CSRF + Request ID"]
    Read["业务只读服务"]
    Write["受控写入服务"]
    Snap["看板 API<br>读取快照 / 登记刷新"]
  end
  subgraph Runtime["后台进程"]
    Monitor["Monitor<br>分层采集与 deep audit"]
    Worker["Agent Worker<br>任务与事件"]
  end
  subgraph Data["MySQL 数据层"]
    Primary[("Primary<br>业务、审计、操作与快照")]
    Replica[("Replica<br>最终一致读")]
    Perf[("Performance Schema<br>SQL Digest")]
  end

  Admin --> Vue --> Gate
  Gate --> Read
  Gate --> Write
  Gate --> Snap
  Gate -->|"实时角色与状态"| Primary
  Read -->|"强一致读取"| Primary
  Write -->|"主库事务与审计"| Primary
  Snap -->|"快照与刷新请求"| Primary
  Monitor -->|"采集并写快照"| Primary
  Monitor -->|"容量读取"| Replica
  Monitor -->|"性能摘要"| Perf
  Worker -->|"任务与事件"| Primary
  Primary -->|"异步复制"| Replica
```

[可编辑 draw.io 架构图](admin-system-architecture.drawio)

## 二、功能地图

| 模块 | 主要能力 |
| --- | --- |
| 业务概览 | 汇总用户、会话、消息、任务和文件规模，并展示最近监控状态。 |
| 用户与权限 | 查询用户；受控启停、切换 `user/admin`、重设密码；预览并物理删除用户。 |
| 会话与任务 | 筛选会话、消息、附件、Job 和事件；正文仅在明确点击后分块读取。 |
| 文件资产 | 查询详情、安全预览 CSV、下载文件、查看删除影响并物理删除 BLOB。 |
| 数据库治理 | 查看主从、连接、容量、完整性、Worker/Job 和 SQL Digest；配置七项采集参数；执行 quick/deep 审计。PR #28 后 Digest 按平均耗时降序展示，同值再按累计耗时排序。 |

## 三、关键机制

每次管理请求都从主库重新确认 `role`、`is_active` 与 `auth_version`，未登录返回 `401`，非管理员返回 `403`。普通管理写请求要求 Session CSRF；用户和文件写入还必须经过主库影响预览、明确确认、当前管理员密码重认证和 `Idempotency-Key`。成功变更、`admin_operations`、逐目标 `admin_operation_items` 与审计事件在同一事务提交；系统禁止操作者禁用、降级或删除自己，并通过事务锁保护最后一个启用管理员。

敏感正文单次最多读取 64 KiB，成功读取要求审计可写，审计不保存正文。CSV 仅按文本预览，限制 256 KiB、100 行、50 列。文件与用户删除均为物理删除且没有回收站；存在活动任务或关联量超过阈值时会阻断。

看板 GET 不现场执行重采集，只读取 `database_monitor_snapshots`。手动刷新仅登记请求，独立 monitor 通过 MySQL 命名锁采集 `realtime`、`sql_performance`、`capacity`、`integrity` 和仅手动触发的 `deep_audit`，再写回主库共享快照。默认开发拓扑包含 Web、Job worker、monitor、checkpoint cleanup、统一 bootstrap、MySQL 主从、PostgreSQL checkpoint 及独立可观测组件；副本异常时读路径回退主库，不提供自动故障切换。

## 四、边界与维护

当前只有 `user/admin` 两级角色，不是完整 RBAC；后台不提供任意 SQL、迁移、自动修复、数据库授权、复制控制或任务控制。结构变更必须通过 Alembic，并同步检查 `app/db.py` 就绪检查。管理员前端源码变更后需更新 `admin-frontend/dist/`，并执行 Python 测试、TypeScript/Vitest、Mock E2E 与生产构建；高风险写入应在隔离主从 E2E 中验收。
