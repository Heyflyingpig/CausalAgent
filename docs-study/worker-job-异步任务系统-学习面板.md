# Worker/Job 异步任务系统学习面板

## 学习目标

理解 CausalAgent 最近与 worker、analysis job 直接相关及间接影响执行链的变更，掌握 Web 与长任务解耦、MySQL 持久化任务队列与事件日志、worker slot 资源隔离、LangGraph 执行、SSE 断线续传和 PostgreSQL checkpoint 之间的职责边界。最终应能根据代码预测任务状态变化，解释常见故障表现，并把这些机制迁移到一般的后台任务系统设计与排障中。

## 当前状态

- 当前阶段：阶段 1–3/9：初始化与认知诊断
- 当前主线：异步任务系统的整体知识地图
- 当前节点：近期演进范围与核心组件边界
- 下一步：根据用户对诊断问题的回答，进入 Web/worker 解耦和 Job 状态机，或直接下钻并发领取、故障恢复与 checkpoint 边界
- 用户自评：尚未提供
- 诊断状态：尚未验证
- 诊断证据：用户要求了解最近几次 worker、job 更改及其后的整体流程，但尚未展示对数据库队列、worker slot、SSE 与 checkpoint 边界的既有理解
- 阶段转换依据：学习主题、业务用途和本轮范围已经明确；知识地图将在本轮向用户展示；仍需用户回答诊断问题或明确要求跳过诊断
- 最终知识回顾路径：尚未指定；如后续明确要求生成知识回顾，将存放在 `docs-study/`

## 知识地图

```text
异步任务系统
├─ [进行中] 近期演进与核心组件边界
├─ [待学习] Web 与长任务解耦
│  ├─ 请求线程只负责鉴权、入队与事件转发
│  └─ 后台 worker 独立执行 Agent/RAG/MCP
├─ [待学习] Job 持久化与状态机
│  ├─ analysis_jobs 保存任务当前状态
│  ├─ analysis_job_events 保存可重放事件
│  ├─ 同一用户和会话只允许一个 active job
│  └─ queued、running、succeeded、failed、canceled
├─ [待学习] Worker 并发与资源所有权
│  ├─ 多 slot 轮询和事务领取
│  ├─ FOR UPDATE SKIP LOCKED 避免重复领取
│  ├─ 每个 slot 独占 MCP process/session/tools/graph
│  └─ heartbeat、stale 接管、attempt_count
├─ [待学习] LangGraph 执行与容错
│  ├─ 父图和 MCP/RAG 子图
│  ├─ 节点级超时、重试与恢复
│  └─ final_result、interrupt、error
└─ [待学习] 双持久化与端到端链路
   ├─ MySQL job/event 负责排队、状态和前端事件
   ├─ PostgreSQL checkpoint 负责图状态和中断恢复
   ├─ SSE 从 MySQL 强一致读取并支持 Last-Event-ID
   └─ 会话删除通过 cleanup outbox 异步清理 checkpoint
```

## 主线进度

| 主线 | 状态 | 已完成节点 | 待学习节点 |
| --- | --- | --- | --- |
| 近期演进 | 进行中 | 已定位相关提交并核对当前代码 | 根据用户认知深度解释演进因果 |
| Web 与 worker 解耦 | 待学习 | 无 | 入队、执行、事件转发的进程边界 |
| Job 状态机 | 待学习 | 无 | 创建互斥、领取、心跳、终态与重试边界 |
| Worker 资源模型 | 待学习 | 无 | slot、MCP session/process、compiled graph 与连接池 |
| LangGraph 与 checkpoint | 待学习 | 无 | 节点流、interrupt 恢复、PostgreSQL 持久化 |
| SSE 与故障边界 | 待学习 | 无 | 可重放事件、断线续传、终态和异常表现 |

## 用户标记的重点

当前无用户明确标记的重点。

## 疑点面板

- [Q-001][开放][认知诊断] 用户是否已经能区分 job 当前状态、job 事件历史和 LangGraph checkpoint 三种数据。
- [Q-002][开放][认知诊断] 用户希望以业务全链路为主，还是进一步掌握并发领取、故障恢复和幂等边界。
- [Q-003][待项目证据][故障恢复] 当前代码在普通执行异常时立即把 job 标记为 failed；`max_attempts` 主要用于 worker 崩溃后 stale running job 的重新领取，而不是所有业务异常的自动重试。后续教学时需明确区分节点级重试和 job 级接管。

## 项目事实与证据

- [E-001][项目事实] 2026-05-18 的 `709ed01` 新增 `analysis_jobs` 与 `analysis_job_events`，分别承载任务当前状态和事件日志。
- [E-002][项目事实] 2026-05-18 的 `30ac01d` 新增 job service 和独立 worker，并把旧 Web 请求内长任务执行替换为“创建 job + SSE 读取数据库事件”。
- [E-003][项目事实] 当前 worker 按 `JOB_WORKERS` 创建 slot；每个 slot 独占 MCP client 资源和 compiled graph，但同一进程内共享数据库连接池及 PostgreSQL checkpoint pool。
- [E-004][项目事实] 当前领取 SQL 使用 `FOR UPDATE SKIP LOCKED`，可领取 queued 或心跳过期且尝试次数未耗尽的 running job。
- [E-005][项目事实] 当前 SSE 路由从 MySQL `analysis_job_events` 强一致轮询，并使用事件自增 id 支持 `Last-Event-ID` 断线续传；它不直接订阅 worker 内存。
- [E-006][项目事实] 2026-05-30 至 2026-05-31 的变更把 worker 使用的工具阶段重构为 MCP/RAG 子图和 LangChain 工具协议，并将 MCP session/process/tools/graph 的所有权固定到 slot。
- [E-007][项目事实] 2026-08-02 的 `e1487b3` 把 LangGraph checkpoint 迁到 PostgreSQL；worker 启动时必须打开并验证 checkpoint pool/schema，再构建 graph。
- [E-008][项目事实] 2026-08-03 的 `de9003a` 给 checkpoint 写入附加 `metadata.job_id`，使管理员可按 job 精确查看安全摘要；`thread_id` 仍是 `session_id`。
- [E-009][项目事实] 2026-08-01 的 `48922a3` 要求 job 创建前 session 已在主库存在并属于当前用户，取消未知 session ID 的隐式补建。

## 原理与项目实现映射

| 原理节点 | 项目实现或证据 | 用于解释什么 | 项目未采用或尚未验证的边界 |
| --- | --- | --- | --- |
| 持久化任务队列 | `analysis_jobs`、`claim_next_job()` | Web 与执行进程解耦，进程重启后任务仍可观察和接管 | 不是 Kafka、Redis 或专用消息队列 |
| 竞争消费者 | `FOR UPDATE SKIP LOCKED`、多个 slot | 多个执行单元并发领取而不阻塞、不重复领取同一行 | 不代表任意失败都自动重试 |
| 可重放事件日志 | `analysis_job_events`、事件自增 id | SSE 断线后从最后事件继续读取 | 当前是数据库轮询，不是数据库主动推送 |
| 租约式故障检测 | `heartbeat_at`、stale 阈值 | worker 崩溃后其他 slot 可接管 | 长节点阻塞事件循环时可能影响心跳，需要结合实际执行方式判断 |
| 图状态持久化 | PostgreSQL `AsyncPostgresSaver` | 会话连续状态、interrupt/resume 和图执行恢复 | 不代替 MySQL job 状态与 SSE 事件表 |
| 资源隔离 | 每 slot 独占 MCP process/session/tools/graph | 避免并发共享有状态 MCP 会话带来的冲突 | slot 并非 OS 进程；多个 slot 位于同一 worker 进程 |

## 已纠正误区

当前尚未记录用户误区。

## 已证明掌握

当前尚无；需通过用户解释、预测或诊断回答验证。

## 关键图表

- [V-001][双持久化与端到端链路] 前端、Web、MySQL job/event、worker slot、LangGraph/MCP/RAG 与 PostgreSQL checkpoint 的整体时序图。
- [V-002][Job 状态机] queued、running、succeeded、failed、canceled 及 stale 接管路径。

## 任务谱系

- 当前任务：用户指定 `learn-business-deeply`，询问最近几次 worker/job 更改及之后的整体流程
- 父任务：无可用父任务
- 已读取范围：技能说明与面板/Mermaid 规范；仓库 `AGENTS.md`；Git 相关提交历史；当前 routes、job service、worker、core、graph、migration、前端调用点、配置与 checkpoint 只读实现
- 完整性状态：对当前仓库和可见 Git 历史完整；未读取运行中数据库或容器日志，因此不把运行态健康状况当作已验证事实
