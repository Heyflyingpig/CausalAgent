# 测试与验证

文档职责：定义后端、管理员前端、集成迁移和隔离主从/PostgreSQL 验收的验证矩阵与稳定命令。

适用范围：修改代码、迁移、管理员页面或文档中命令时使用；管理员专项测试补充说明见 [`../admin/testing.md`](../admin/testing.md)。

## 测试层级

| 层级 | 位置/入口 | 主要证明 |
| --- | --- | --- |
| 后端 unit | `tests/unit/` | 单模块状态机、权限、Job fencing、结构化输出和 monitor 逻辑 |
| 后端 integration | `tests/integration/` | 跨模块静态契约、日志政策、部署边界和 migration 链 |
| 管理员 Vue unit | `admin-frontend/tests/*.spec.ts` | API DTO、组件、看板/设置语义和 SQL digest 展示 |
| 管理员 Mock E2E | `admin-frontend` `test:e2e:mock` | 无真实数据库的页面导航、鉴权和交互 |
| 隔离 E2E | `tests/run_admin_31_e2e.ps1` / `run_admin_32_e2e.ps1` | 空库升级、migration 往返、主从、PostgreSQL checkpoint、受控写入/删除和普通用户回归 |

`tests/README.md` 是后端测试目录和 Docker 单元测试环境的补充入口；新增测试时先判断是否需要真实跨模块依赖，再选择 unit 或 integration。

## 后端 Docker 单元测试

RAG State 隔离和异常分流的单元测试位于 `tests/unit/agent/test_rag_subgraph_state.py`，覆盖 Planner 预检跳过 ToolNode、查询失败与协议错误标记、`success=False` Parser 路径、父 State 投影和取消/撤销传播。该测试使用 fake LLM、fake RAG tool 和导入桩，不覆盖真实模型、真实 MCP session、真实知识库向量检索或 PostgreSQL checkpoint。

测试镜像基于 Dockerfile 的 `test` target，安装 `requirements-test.txt`。`unit-test` 服务不依赖 app/worker/monitor/MySQL，关闭容器网络，只读挂载仓库，并用 `tests/unit-test-env` 屏蔽项目 `.env`：

```bash
docker compose -f docker-compose.test.yml build unit-test
docker compose -f docker-compose.test.yml run --rm unit-test
```

运行指定测试：

```bash
docker compose -f docker-compose.test.yml run --rm unit-test python -m pytest -p no:cacheprovider tests/unit/admin
docker compose -f docker-compose.test.yml run --rm unit-test python -m pytest -p no:cacheprovider tests/unit/agent/test_job_lifecycle.py
```

日志第二阶段的重点回归位于 `tests/unit/test_logging_runtime.py`、`test_event_catalog.py`、`test_noise_control.py`、`test_request_logging.py`、`tests/unit/agent/`、`tests/unit/database/test_database_logging.py` 和 `tests/integration/test_logging_policy.py`。它们覆盖事件目录和固定消息、非法合同安全降级、异常栈清理、请求/线程/异步任务/worker slot 上下文隔离、Job 终态、node 最终降级、RAG 计数日志、MCP 可信参数及 stdout/stderr、数据库/monitor/cleanup 转移，以及运行路径普通 logging 调用和敏感详情键的 AST 政策。

日志改造必须运行完整 `unit-test` 服务，不能只运行新增文件。测试通过只证明代码级合同，不证明 Docker 日志驱动、Alloy、Loki、Grafana、positions、查询标签或真实模型/MCP 链路。

环境受限时才使用本地回退：

```bash
python -m pytest tests/unit
```

## 管理员前端

```bash
cd admin-frontend
npm ci
npm run typecheck
npm run test:unit
npm run test:e2e:mock
npm run build
```

`npm run build` 会先执行 typecheck，再生成 `/admin/` base 的 Vite 产物。修改管理员 API 或页面后必须至少覆盖 loading、empty、error、401/403 和敏感内容边界；真实数据库写流程只能在隔离环境运行。

## 隔离管理员 E2E

完成管理员生产构建后，从仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File tests/run_admin_32_e2e.ps1
```

脚本通过 `docker-compose.admin-e2e.yml` 叠加固定的隔离容器名、端口和数据卷，不触碰开发库；覆盖空库 `alembic upgrade head`、3.2 migration downgrade/upgrade、PostgreSQL checkpoint 读取/清理、受控用户/文件写入、逐目标审计、主从追平和普通用户回归。需要 `PLAYWRIGHT_BASE_URL`、管理员/普通用户凭据；只有 Edge 时可设置 `PLAYWRIGHT_CHANNEL=msedge`。

脚本结束后会保留隔离容器和卷，不自动清理。物理删除用例会修改种子数据，不能用 `KeepSeededData` 重放。

## 日志链路与文档验证

第一阶段真实环境补验必须在隔离 Compose project、独立卷和合成凭据中执行：

```powershell
docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.yml pull loki alloy grafana
docker compose -f docker-compose.yml run --rm --no-deps alloy validate /etc/alloy/config.alloy
docker compose -f docker-compose.yml up -d
docker compose -f docker-compose.yml ps
```

随后验证五类 service 唯一事件、Alloy/Loki 重启和 positions 续读、暂停 Loki 时业务日志不阻塞、高基数字段不成为标签，以及 30 分钟代表性负载的行数、字节数、stream 数和事件排行。第二阶段还要逐项执行 Web 500、Job/node/RAG/MCP/monitor/副本/cleanup 故障矩阵，通过 request ID 和 job ID 检索完整关联链，检查并发无串值、正常流零 `WARNING/ERROR`，并用合成秘密、连接 URL、提示词、LLM 输出、CSV、SQL 参数和异常敏感文本做 stderr、Docker log 与 Loki 零命中抽样。

真实模型或知识库凭据不可用时，必须明确写为“未取得真实模型证据”，不能用 fake unit 测试替代。Docker daemon、Alloy validate、positions、上下文隔离、MCP stdout/可信参数或隐私检查任一失败时，不得标记第二阶段完成。

所有文档变更还必须检查相对链接、顶部职责声明、失效路径和 `git diff --check`；如果任务涉及根 README 的入口或部署说明，还必须核对 README 中的命令、链接和目录导航。只有用户明确要求时才修改根 README；完整验收通过前不追加完成态 CHANGELOG。
