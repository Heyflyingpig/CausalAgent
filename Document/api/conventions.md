# API 通用约定

文档职责：记录普通用户 API、管理员 API 和 SSE 共同遵守的鉴权、请求关联、错误、分页与敏感数据边界。

适用范围：修改 Flask 路由、认证/CSRF、中间件、统一响应或事件协议时使用；管理员专属路径和业务 DTO 见 [`../admin/api.md`](../admin/api.md)。

## 身份与授权

普通用户接口通过当前 Cookie Session 找到用户，并每次从 MySQL 确认用户仍存在、`is_active` 为真且 `auth_version` 匹配。管理员接口额外要求主库强一致读取到 `role = 'admin'`；Session 中缓存的角色不能作为后端授权依据。

未登录或会话失效的 API 返回 `401`；已登录但不具备管理员权限的管理员 API 返回 `403`。管理员页面未登录时回到统一登录入口，普通用户访问管理页面先返回真实 `403` 再回普通首页。登录成功和 `check_auth` 会返回当前 Session 绑定的 CSRF token。

管理员写请求必须回传 `X-CSRF-Token`。管理员数据库刷新、完整性审计、在线配置写入以及 3.2 受控业务操作还分别受密码重新认证、预览、明确确认和 `Idempotency-Key` 等接口契约约束，不能把这些约束下沉为前端自律。

## Request ID 与错误

请求上下文从 `X-Request-ID` 接受符合 `[A-Za-z0-9._:-]{1,64}` 的上游值，否则生成 UUID；所有响应通过 `X-Request-ID` 返回该值。管理员统一响应还包含 `request_id` 字段，失败响应包含稳定 `code`，字段校验错误放在 `fields`。

Flask 在确定 request ID 后立即绑定运行日志上下文，只有主库确认用户有效和资源归属后才增加 `user_id/session_id/job_id`，teardown 在正常和异常路径都按逆序清理。分析 Job 首次创建时仍把当前 request ID 写入 `analysis_jobs.request_id`；幂等重放日志使用本次 HTTP request ID，worker 使用 Job 首次落库的 request ID，并通过同一 `job_id` 关联两次请求。

内部异常只能记录在服务端日志，不能把堆栈、数据库连接、凭据、原始 prompt 或工具结果直接返回给客户端。需要给用户展示的错误必须是稳定、有限且不泄露内部结构的消息。

未处理 500 由 Flask 的异常日志边界生成唯一 `web.request.unhandled`，已捕获并返回的 5xx 在最外层路由生成 `web.request.failed` 或专用 Job 事件；这不改变原响应。普通 400/401/403/404/409、字段校验、普通密码错误和会话自然过期不产生异常运行日志。只有已确认的禁用账号、已登录用户跨归属访问、CSRF 拒绝、高风险重认证失败或安全会话撤销进入 `security` 事件，且不记录用户名、请求正文或资源内容。

## 分页和内容读取

管理员列表默认 `limit=20`，硬上限为 50，使用不透明 cursor；不要把数据库主键排序值直接当作公开分页协议。管理员消息、附件和 Job 输入/结果/错误正文只有在明确点击的敏感读取接口中按源字节分块返回，单次最多 64 KiB，成功读取还必须能写入审计，否则拒绝返回正文。

文件预览是另一条受限路径：只允许文本化 CSV 预览，最多 256 KiB、100 行、50 列，每个单元格最多 1000 字符，不执行公式、HTML 或脚本。管理员列表 DTO 不得包含密码哈希、Cookie、Token、文件正文/哈希、数据库账号、host 或 grants。

## 幂等键边界

分析 Job 的创建、resume 和 cancel 请求必须提供标准 UUID v4 `Idempotency-Key`；管理员受控业务写入使用自己的操作幂等记录。相同身份、相同键和相同请求指纹可以重放原结果，不同参数必须返回冲突，不得静默覆盖第一次请求。

幂等落盘不等于外部 LLM、MCP 或 PostgreSQL 操作的分布式 exactly-once。Job 的 MySQL 状态、事件、assistant 消息和 worker fencing 负责本地持久化一致性；外部调用的重试边界必须在对应运行时文档中说明。

## SSE 公共协议

普通用户 Job SSE 使用 `text/event-stream`，事件由 MySQL `analysis_job_events` 按递增事件 ID 读取。客户端可通过 `Last-Event-ID` 或 `last_event_id` 查询参数续传；服务端发送 `id`、`event` 和 JSON `data`，定期发送 `heartbeat` 保活。

公共事件必须经过脱敏适配器：只暴露公开文字、阶段和稳定状态，移除内部 `attempt` 等字段，不暴露原始 prompt、ToolMessage、完整工具结果、图状态、文件内容或隐藏推理。终态事件或 `interrupt` 到达后连接结束，页面刷新后应通过活动 Job 接口和最后事件 ID恢复状态。
