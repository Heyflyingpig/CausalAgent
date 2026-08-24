# 分析 Job API

文档职责：记录普通用户创建、查看、订阅、恢复和取消分析 Job 的 HTTP/SSE 契约。

适用范围：修改 `app/agent/routes.py`、`app/agent/job_service.py`、前端 Job 状态恢复或 `analysis_job_events` payload 时使用；内部 worker 执行机制见 [`../architecture/agent-runtime.md`](../architecture/agent-runtime.md)。

## 接口总览

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `POST` | `/api/agent/jobs` | 创建或按幂等键重放一个分析 Job |
| `GET` | `/api/agent/jobs/active` | 读取当前用户活动 Job，可用 `session_id` 过滤 |
| `GET` | `/api/agent/jobs/<job_id>/events` | 订阅该 Job 的 SSE 事件 |
| `POST` | `/api/agent/jobs/<job_id>/resume` | 提交 `waiting_input` Job 的恢复输入 |
| `POST` | `/api/agent/jobs/<job_id>/cancel` | 即时逻辑取消 `queued`、`running` 或 `waiting_input` Job |
| `POST` | `/api/send_stream` | 已废弃，固定返回 `410` 和迁移提示 |

所有路径都要求当前用户登录，并按 `job_id + user_id` 校验资源归属。Web 层不执行 Agent，只校验参数、持久化 Job 并入队。

## 创建 Job

请求 JSON 至少包含：

```json
{
  "message": "请分析这些变量之间的关系",
  "session_id": "session-uuid",
  "input_user_file_id": 123
}
```

`input_user_file_id` 可省略；消息必须是非空文本，长度受服务端限制。请求必须带标准 UUID v4 `Idempotency-Key`。服务端在一个 MySQL 事务中检查会话归属、活动 Job、文件归属，冻结文件快照，写入 Job、initial input、用户聊天消息和请求指纹。

- 新 Job 返回 `202`，`success=true`、`existing=false`、`job_id` 和 `status=queued`。
- 相同用户、相同幂等键和相同请求参数重放原 Job，返回 `200`、`existing=true`。
- 同一 `user_id + session_id` 已有 `queued`、`running` 或 `waiting_input` Job 时返回 `409`，错误码为 `active_job_conflict`。
- 同一个幂等键对应不同请求参数时返回 `409`。
- 缺少或非 UUID v4 幂等键、消息为空或文件/会话无权访问时返回 `400` 或 `403`。

## 活动 Job

`GET /api/agent/jobs/active` 返回当前用户的活动 Job 摘要，并附带当前公开事件最大 ID `last_event_id`。可传 `session_id` 只恢复指定会话。摘要包含状态、worker/lease 观测、尝试和恢复次数、冻结文件名以及等待输入的问题 ID/公开提示，但不返回内部 checkpoint 状态或文件正文。前端刷新时以会话历史实际回放到的 `rendered_event_id` 作为 SSE 游标，活动摘要中的最新 ID 不能覆盖它。

## SSE 订阅

`GET /api/agent/jobs/<job_id>/events` 返回 `text/event-stream`。客户端断线重连时使用上次收到的事件 ID：

```text
Last-Event-ID: 42
```

也兼容 `last_event_id=42` 查询参数。服务端从 `analysis_job_events.id > 42` 读取事件，返回标准 SSE 的 `id`、`event`、`data` 字段；没有新事件时按配置轮询并发送 heartbeat。事件 payload 按事件类型执行字段白名单清洗，worker 的 `attempt`、未知附加字段和内部对象不会对外可见。

收到 `interrupt` 后，前端应展示公开问题并等待恢复；收到 `final_result`、`error` 或 `canceled` 后连接结束。若 Job 已经进入终态，即使数据库查询时没有新的事件，服务端也会结束连接。

联网搜索成功且存在结果时，报告终态的 `final_result.data` 额外包含最多 5 条引用。引用只公开网页标题和 URL，不返回网页正文、搜索工具内部字段或完整搜索结果：

```json
{
  "type": "final_result",
  "data": {
    "type": "causal_graph",
    "summary": "报告正文",
    "references": [
      {
        "title": "网页标题",
        "url": "https://example.com/page"
      }
    ]
  }
}
```

引用随 assistant 消息独立持久化；重新加载会话时通过 `message.references` 返回相同的 `title + url` 数组。后端只提供该字段契约，不要求前端展示引用。报告、预处理和后处理节点不发送文字增量；公开 `text_delta` 仍只来自普通问答和报告追问节点。

## Resume 与 Cancel

恢复请求示例：

```json
{
  "question_id": "question-uuid",
  "answer": "补充信息"
}
```

`answer` 也兼容 `message` 字段，可以是文本或受限 JSON。恢复请求必须使用新的、可复用的 UUID v4 `Idempotency-Key`；服务端追加 `analysis_job_inputs.input_type='resume'`，然后重新排队同一个 Job。相同键重放返回原结果，不同问题或答案返回冲突。

取消请求支持 `queued`、`running` 和 `waiting_input`。事务提交后业务状态立即成为不可逆 `canceled`，同时写入稳定取消事件、assistant 投影并释放 Session 活动锁；`running` Job 的执行占用会暂时显示为内部 `draining`，普通用户不会看到该字段。请求同样需要 UUID v4 幂等键：首次取消返回 `202`，相同键重放返回 `200`，已由另一幂等键取消、或已经 `succeeded/failed` 时返回 `409 job_state_conflict`。取消不承诺终止已发出的远端调用；其结果不会进入 parser、router、error handler、重试或后续节点。

浏览器按 `job_id` 分别维护取消请求和 SSE 订阅：同一 Job 的网络重试复用同一个幂等键；收到 `409 job_state_conflict` 且状态已经是 `canceled` 时按成功对账，其他活动状态冲突则保留任务并恢复展示。取消成功或切换页面前会使旧订阅代次失效，迟到的 SSE 事件不得重新修改已取消 Job 的前端状态。

Job 状态、输入冻结、checkpoint identity 和旧 worker fencing 的完整关系见 [`../architecture/job-file-lifecycle.md`](../architecture/job-file-lifecycle.md)。
