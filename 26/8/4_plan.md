一、数据库看板布局
页面顶部保留标题、最后采集时间和手动刷新按钮，在标题下增加胶囊式三段滑块：
数据库状态看板                         最后采集时间  [手动刷新]

┌──────────────────────────────────────────────┐
│ [ 数据库运行状态 ] [ Cleanup Worker ] [ Outbox 队列 ] │
└──────────────────────────────────────────────┘

                当前选中视图内容
使用三段式分段选择器，不使用普通的开关组件。切换时只显示一个视图。
选中状态写入 URL：
/admin/database?view=database
/admin/database?view=cleanup-worker
/admin/database?view=outbox
这样刷新页面、浏览器前进后退，以及从用户删除结果跳转时，都能保持正确视图。
二、数据库运行状态
这里保留当前数据库看板的内容：
Revision
主库
第一从库
阻塞项
连接使用率
表容量
完整性审计
SQL 性能摘要
现有“Worker / Job 快照”从这里移出，避免数据库状态、分析任务和清理任务混在一起。
三、Cleanup Worker
这个视图只回答一个问题：
PostgreSQL checkpoint 清理进程是否正常工作？

展示内容：
Worker 状态：空闲、处理中、失联、已停止、未知
Worker 逻辑别名
启动时间
最近心跳
当前处理的 Outbox ID
本次启动成功数量
本次启动失败数量
心跳周期
当前处理耗时
状态规则：
正常：心跳新鲜，Worker 为 idle 或 processing
警告：心跳超过阈值、最近处理出现失败
异常：存在到期任务，但 Worker 已失联
未知：从未收到心跳
cleanup worker 每约 10 秒把心跳写入独立共享快照键 checkpoint_cleanup_runtime。当前部署只有一个 cleanup worker，因此暂时不新增 Worker 注册表或数据库迁移。
四、Outbox 队列
这个视图回答：
当前有哪些 checkpoint 清理任务，它们是否积压或失败？

顶部摘要：
Pending
已到执行时间
Processing
租约已过期
Failed
最近完成时间
最早待处理时间
下方展示最多100条待处理或异常记录：
Outbox ID
Thread ID
Operation ID
状态
尝试次数，例如 2 / 3
可领取时间
租约到期时间
创建时间
完成时间
是否存在错误
默认优先展示：
Failed
租约过期
Processing
到期 Pending
其他 Pending
不直接返回 last_error 原文，避免暴露数据库地址、账号或内部连接信息。页面只显示安全错误结论，详细异常保留在服务端日志。
五、用户与权限管理
用户删除完成后增加一个持续可见的“Checkpoint 清理进度”结果区，不在用户列表下放完整 Worker 或 Outbox 看板。
展示：
MySQL 用户数据：已删除
PostgreSQL checkpoint：等待清理、清理中、成功或失败
总任务数、成功数、失败数、待处理数
Operation ID
“查看全局清理状态”按钮
按钮跳转：
/admin/database?view=outbox&operation_id=<operation_id>
Outbox 视图自动按该 operation_id 高亮或过滤，让管理员从业务操作自然进入系统级排查。
六、分析任务管理
不增加 Agent/Cleanup 滑块。
这里只管理：
Agent Worker
analysis_jobs
Job 事件
PostgreSQL checkpoint 安全摘要
将原数据库看板中的 Agent Worker 汇总移到分析任务列表上方，继续展示：
Queued
Running
Stale
达到最大尝试仍运行
Agent Worker ID和心跳
现有 /api/admin/jobs/workers 可以继续复用。
七、数据流保持不变
用户或会话删除
  → MySQL 事务写入 checkpoint_cleanup_outbox
  → Cleanup Worker 持续心跳并领取任务
  → PostgreSQL adelete_thread()
  → 回写 Outbox 终态
  → monitor 采集安全摘要
  → 数据库看板共享快照
GET /api/admin/db/dashboard 仍然只读取共享快照，不在 Web 请求里现场扫描数据库。
实施批次
建议分成三个提交批次，但不主动提交：
feat(checkpoint):增加cleanup worker心跳与outbox监控快照
feat(admin):增加数据库看板三段式清理视图
feat(admin):关联用户删除进度与全局清理看板
验证范围包括Python 编译、Vue typecheck、Vitest 等价矩阵。