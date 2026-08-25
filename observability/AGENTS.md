# observability/AGENTS.md

生效目录：`observability/` 及其子目录。

负责约束的修改类型：共享 JSON 日志运行时、事件目录、上下文绑定、降噪、Alloy/Loki/Grafana 采集配置和日志仪表盘。

## 修改前必须阅读

- 必须阅读 [`Document/development/observability.md`](../Document/development/observability.md)、[`Document/development/deployment.md`](../Document/development/deployment.md) 和 [`Document/development/testing.md`](../Document/development/testing.md)。
- 必须检查 `observability/logging_runtime.py`、`event_catalog.py`、`noise_control.py`、`docker-compose.yml` 以及对应 unit/integration 测试；不能只修改配置字符串后假设采集链路有效。

## 日志合同

- 应用运行日志必须通过共享运行时和已注册事件目录写入单行 JSON stderr；事件级别、分类、固定消息和 `details` 键必须由目录约束。
- 必须保持 request、Job、worker slot、node 和 tool 上下文隔离；禁止记录用户输入、提示词、模型结果、ToolMessage、文件正文、SQL 参数、凭据、连接串、原始异常文本或隐藏推理。
- `request_id`、`user_id`、`session_id`、`job_id`、`worker_slot`、`node`、`tool` 和 `instance` 只能作为日志正文关联字段，禁止新增为 Loki 高基数标签；MCP stdout 只能承载协议消息。
- 修改 Alloy、Loki 或 Grafana 配置时，必须保持开发环境与生产环境边界，不得擅自把生产 Compose 接入开发日志卷或开放内部端口。

## 修改后验证

- 必须运行日志运行时、事件目录、降噪、请求/Agent/数据库日志和日志政策测试；配置变更必须执行 `docker compose -f docker-compose.yml config --quiet` 和 Alloy `validate`。
- 真实 Docker、Loki 查询、positions 续读、故障恢复、负载容量和真实模型/MCP 链路未执行时，最终说明必须明确列出，不能用静态测试代替。
