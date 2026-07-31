# 管理员 API 契约

管理员 API 统一使用 `/api/admin` 前缀。除特别说明外，接口只允许数据库中 `role = 'admin'` 且 `is_active = TRUE` 的用户访问；后端每次请求都会通过主库强一致读重新确认用户状态，不把浏览器 Session 中的角色缓存作为授权依据。

## 通用约定

- 未登录 API 请求返回 `401`，普通用户或已失效管理员返回 `403`。
- 所有响应都包含 `X-Request-ID`；格式合法的上游 request ID 会被沿用。
- 登录和 `check_auth` 返回 Session 绑定的 CSRF token。管理员写请求必须通过 `X-CSRF-Token` 回传。
- 受控业务写入还要求当前管理员密码重新认证、`Idempotency-Key`、影响预览和明确确认。
- 列表默认返回 20 条、最多 50 条，并使用不透明游标分页。

## 页面与品牌资源

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/admin/overview` | 业务概览页面 |
| `GET` | `/admin/users` | 用户管理页面 |
| `GET` | `/admin/sessions` | 会话与消息页面 |
| `GET` | `/admin/jobs` | 分析任务页面 |
| `GET` | `/admin/files` | 文件资产页面 |
| `GET` | `/admin/database` | 数据库看板与登录落点 |
| `GET` | `/admin/database/settings` | 采集配置页面 |
| `GET` | `/admin/database/audit` | 数据库审计页面 |
| `GET` | `/api/admin/brand/logo` | 受保护的品牌图片 |

未登录访问管理员页面时回到统一登录入口；普通登录用户访问返回 `403`。

## 数据库看板

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/admin/db/dashboard` | 聚合读取最近共享快照 |
| `GET` | `/api/admin/db/health` | 兼容的数据库健康响应 |
| `GET` | `/api/admin/db/overview` | 兼容的数据库概览响应 |
| `GET` | `/api/admin/db/integrity?mode=quick` | 读取最近 quick 完整性快照 |
| `GET` | `/api/admin/db/slow-queries` | 读取 SQL 性能摘要 |
| `GET` | `/api/admin/jobs/workers` | 读取 Worker/Job 快照 |
| `POST` | `/api/admin/db/refresh` | 登记实时、SQL 和容量刷新请求 |
| `POST` | `/api/admin/db/integrity/run` | 登记完整性审计请求 |
| `GET` | `/api/admin/db/audit` | 读取最近 deep audit 快照 |
| `POST` | `/api/admin/db/audit/run` | 登记 deep audit 请求 |

所有 GET 只读取 MySQL 中最近的共享快照，不在 Web 请求中执行完整采集。刷新接口只登记请求，实际采集由独立 monitor 完成。

SQL 性能摘要按 Performance Schema 的单次平均 `AVG_TIMER_WAIT` 降序选取和展示，平均耗时相同时按累计 `SUM_TIMER_WAIT` 降序次排序，不等同于单次查询超过 `long_query_time`。慢查询告警优先使用采集窗口内 `Slow_queries` 增量。

## 在线采集配置

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/admin/db/settings` | 读取当前有效值、覆盖值和版本 |
| `PUT` | `/api/admin/db/settings` | 使用乐观版本锁保存覆盖值 |
| `POST` | `/api/admin/db/settings/reset` | 重置数据库覆盖值 |
| `GET` | `/api/admin/db/settings/history` | 游标读取配置审计历史 |

有效值优先级是“数据库覆盖 > 环境变量 > 代码默认值”，数据库中的 `NULL` 表示继承。每个进程最多缓存 5 秒；数据库读取失败时优先使用最后有效值，再回退环境变量或代码默认值。

## 业务读取

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/admin/business/overview` | 业务聚合概览 |
| `GET` | `/api/admin/business/users` | 用户列表 |
| `GET` | `/api/admin/business/users/<id>` | 用户详情 |
| `GET` | `/api/admin/business/sessions` | 会话列表 |
| `GET` | `/api/admin/business/sessions/<id>` | 会话详情 |
| `GET` | `/api/admin/business/sessions/<id>/messages` | 会话消息列表 |
| `GET` | `/api/admin/business/messages/<id>/attachments` | 消息附件列表 |
| `GET` | `/api/admin/business/messages/<id>/content` | 分块读取消息正文 |
| `GET` | `/api/admin/business/attachments/<id>/content` | 分块读取附件正文 |
| `GET` | `/api/admin/business/jobs` | 分析任务列表 |
| `GET` | `/api/admin/business/jobs/<id>` | 分析任务详情 |
| `GET` | `/api/admin/business/jobs/<id>/events` | 任务事件列表 |
| `GET` | `/api/admin/business/jobs/<id>/content` | 分块读取任务内容 |
| `GET` | `/api/admin/business/files` | 文件列表 |
| `GET` | `/api/admin/business/files/<id>` | 文件详情 |
| `GET` | `/api/admin/business/files/<id>/preview` | 有界 CSV 文本预览 |
| `GET` | `/api/admin/business/files/<id>/download` | 下载文件 |

密码哈希、Cookie、Token、文件哈希、数据库账号、host 和 grants 不进入列表 DTO。消息、附件及任务内容最多按 64 KiB 源字节分块读取；成功的敏感读取要求审计可写。CSV 预览最多读取 256 KiB、100 行、50 列，单元格最多 1000 字符，并且只按文本渲染。

## 受控业务写入

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/admin/business/users/operations/preview` | 预览用户批量操作影响 |
| `POST` | `/api/admin/business/users/operations` | 执行用户启停、角色或密码操作 |
| `GET` | `/api/admin/business/users/<id>/delete-impact` | 预览用户删除影响 |
| `DELETE` | `/api/admin/business/users/<id>` | 物理删除用户 |
| `GET` | `/api/admin/business/files/<id>/delete-impact` | 预览文件删除影响 |
| `DELETE` | `/api/admin/business/files/<id>` | 物理删除文件和 BLOB |

操作者不能禁用、降级或删除自己，也不能移除最后一个启用管理员。角色、状态或密码实际变化会通过 `users.auth_version` 使目标用户旧 Session 失效。物理删除没有回收站，详细删除/保留矩阵见 [数据库治理文档](../../setting/database_governance.md)。
