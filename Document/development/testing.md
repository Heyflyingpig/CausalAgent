# 测试与验证

文档职责：定义后端、管理员前端、集成迁移和隔离主从/PostgreSQL 验收的验证矩阵与稳定命令。

适用范围：修改代码、迁移、管理员页面或文档中命令时使用；管理员专项测试补充说明见 [`../admin/testing.md`](../admin/testing.md)。

## 测试层级

| 层级 | 位置/入口 | 主要证明 |
| --- | --- | --- |
| 后端 unit | `tests/unit/` | 单模块状态机、权限、Job fencing、结构化输出和 monitor 逻辑 |
| 后端 integration | `tests/integration/` | 跨模块静态契约、日志政策、部署边界和 migration 链 |
| RAG/多模态与隔离评测 | `tests/test_multimodal_*.py`、`tests/test_rag_eval_*.py`、`tests/acceptance/` | 来源/索引/release 契约、隔离队列与评测矩阵的分层检查 |
| 管理员 Vue unit | `admin-frontend/tests/*.spec.ts` | API DTO、组件、看板/设置语义和 SQL digest 展示 |
| 管理员 Mock E2E | `admin-frontend` `test:e2e:mock` | 无真实数据库的页面导航、鉴权和交互 |
| Windows 桌面逻辑 | `windows-client/tests/test_config.py`、`test_navigation_policy.py`、`test_runtime.py`、`test_launcher.py` | 配置优先级、URL/origin 白名单、运行时错误和 Edge 事件策略，不创建真实窗口 |
| Windows 壳层 smoke | `windows-client/tests/run_windows_smoke.py`、`test_windows_smoke.py` | 隔离 HTTP stub、真实 WebView2 Edge Chromium 页面加载和窗口退出；只在 Windows 桌面会话执行 |
| 隔离 E2E | `tests/run_admin_31_e2e.ps1` / `run_admin_32_e2e.ps1` | 空库升级、migration 往返、主从、PostgreSQL checkpoint、受控写入/删除和普通用户回归 |

`tests/README.md` 是后端测试目录和 Docker 单元测试环境的补充入口；新增测试时先判断是否需要真实跨模块依赖，再选择 unit 或 integration。

## Windows 桌面客户端

桌面逻辑测试不启动窗口，也不连接 Flask、MySQL、模型或 WebView2 Runtime：

```powershell
.\.venv-desktop\Scripts\python.exe -m pip install -r .\windows-client\requirements-desktop-test.txt
.\.venv-desktop\Scripts\python.exe -m pytest windows-client/tests/test_config.py windows-client/tests/test_navigation_policy.py windows-client/tests/test_runtime.py windows-client/tests/test_launcher.py -q
```

桌面依赖验收使用独立虚拟环境；从仓库根目录执行兼容入口检查，必须确认 Python 3.12、Windows、`pywebview==5.4` 的完整依赖和 WebView2 Runtime：

```powershell
.\.venv-desktop\Scripts\python.exe .\Run_causal.py --check-environment
.\.venv-desktop\Scripts\python.exe -c "import webview; print('ok')"
```

真实壳层 smoke 不放入普通 pytest 默认执行范围。它会启动本地 stub（`/`、`/health`、`/external-link`）、创建真实 Edge Chromium 窗口，并使用测试专用自动关闭钩子验证窗口关闭和进程退出：

```powershell
.\.venv-desktop\Scripts\python.exe .\windows-client\tests\run_windows_smoke.py
```

也可以在已有 pytest 环境中显式运行 `test_windows_smoke.py`，但必须设置 `CAUSALAGENT_DESKTOP_RUN_SMOKE=1`；未设置时的 skip 不是 smoke 通过证据。壳层 smoke 通过只证明桌面壳与 stub 的加载/退出链路，不证明远程生产 origin、服务器 Session、真实 SSE、模型或后端 API 已验收。

## 后端 Docker 单元测试

RAG State 隔离和异常分流的单元测试位于 `tests/unit/agent/test_rag_subgraph_state.py`，覆盖 Planner 预检跳过 ToolNode、查询失败与协议错误标记、`success=False` Parser 路径、父 State 投影和取消/撤销传播。该测试使用 fake LLM、fake RAG tool 和导入桩，不覆盖真实模型、真实 MCP session、真实知识库向量检索或 PostgreSQL checkpoint。

测试镜像基于 Dockerfile 的 `test` target，安装 `requirements-test.txt`。`unit-test` 服务不依赖 app/worker/monitor/MySQL，关闭容器网络，只读挂载仓库，并通过 Compose `env_file` 注入 `tests/unit-test-env`；这些已注入环境变量优先于项目 `.env`：

```bash
docker compose -f docker-compose.test.yml build unit-test
docker compose -f docker-compose.test.yml run --rm unit-test
```

运行指定测试：

```bash
docker compose -f docker-compose.test.yml run --rm unit-test python -m pytest -p no:cacheprovider tests/unit/admin
docker compose -f docker-compose.test.yml run --rm unit-test python -m pytest -p no:cacheprovider tests/unit/agent/test_job_lifecycle.py
```

## RAG、多模态与隔离评测

多模态来源、staged index、release publish/rollback、便携 embedding 配置、隔离来源与持久评测队列的 focused tests 位于 `tests/test_multimodal_*.py`、`tests/test_rag_release_portable_embedding.py`、`tests/test_isolated_rag_eval_routes.py` 和 `tests/test_rag_eval_*.py`；RAG 子图 State 隔离与不可用降级由 `tests/unit/agent/test_rag_subgraph_state.py` 覆盖。它们使用 fixture/fake 或静态契约，不代表真实模型、远程 VLM、向量库、SearXNG 或生产数据已执行。

正式多模态 embedding 默认使用 `EMBEDDING_API_KEY` 与 `EMBEDDING_BASE_URL`；缺少配置时相关运行只应报告 embedding 不可用。需要测试本地 embedding 时必须在隔离测试中显式传入配置，生产 defaults 的 `local_embedding.enabled` 当前为 `false`。

声明式验收矩阵位于 `Document/rag_eval_production_acceptance_matrix.json`，安全 runner 位于 `tests/acceptance/run_rag_eval_production_acceptance.py`。从仓库根目录运行：

```bash
# 只列出 contract 检查，不执行检查或写入报告
python tests/acceptance/run_rag_eval_production_acceptance.py --layer contract --list

# 执行非变更 contract 检查
python tests/acceptance/run_rag_eval_production_acceptance.py --layer contract

# integration 层按矩阵执行静态/隔离检查
python tests/acceptance/run_rag_eval_production_acceptance.py --layer integration

# production 层必须显式确认，且仅做只读 readiness
python tests/acceptance/run_rag_eval_production_acceptance.py --layer production --confirm-production-readiness
```

production 层不会摄取资料、调用外部 VLM/模型、运行完整评测、冻结题集、发布索引或切换 active pointer；contract、integration、静态 Compose、迁移 head 或 readiness 结果都不能写成真实生产验收通过。RAG 评测使用独立 `rag-eval-worker`、队列任务和产物目录，不等同于独立数据库或安全域。当前测试入口只保留新的 acceptance runner，不应重新添加已移除的旧入口。

## 迁移链验证

空库升级和 migration graph 检查必须确认唯一 head 为 `s4d5e6f7a8b9`：

```bash
python -m alembic heads
```

迁移 downgrade/upgrade 仅在隔离数据库执行，并指定明确 revision；不能用 `alembic downgrade -1` 代替合并迁移的回退验证。

## SearXNG 部署验证

SearXNG 初始化脚本的纯脚本行为由 `tests/unit/deployment/test_searxng_init_settings.py` 覆盖，包含生成、幂等、缺失 example 和生成中断不发布半成品。Compose 部署契约由 `tests/integration/deployment/test_searxng_compose.py` 静态检查，确认镜像不是 `latest`、存在 `/healthz` healthcheck，且默认 `app`/`worker` 不依赖 SearXNG。

需要 Docker Engine 才能执行真实容器验证：

```bash
docker compose -f docker-compose.yml config
docker compose -f docker-compose.yml up -d searxng
docker compose -f docker-compose.yml ps searxng searxng-init valkey
```

容器验证应另外确认 `/healthz` 返回成功、JSON 搜索格式可用，以及停止 SearXNG 后开启 `web_search_enabled` 的 Job 仍按运行期重试和统一降级协议收敛。该真实网络证据不能由 unit 或静态 Compose 测试替代。

可使用隔离临时配置目录执行 init、healthcheck 和幂等性验证；脚本结束时只清理本次生成的 Compose project 和临时目录，不触碰开发环境现有配置：

```powershell
powershell -ExecutionPolicy Bypass -File tests/run_searxng_docker_validation.ps1
```

## 日志与可观测性验证

日志第二阶段的重点回归位于 `tests/unit/test_event_catalog.py`、`tests/unit/test_request_context_contract.py`、`tests/unit/agent/` 和 `tests/integration/test_logging_policy.py`。它们覆盖事件目录和固定消息、请求/线程/异步任务/worker slot 上下文隔离、Job 终态、node 最终降级、RAG 计数日志、MCP 可信参数及 stdout/stderr、数据库/monitor/cleanup 转移，以及运行路径普通 logging 调用和敏感详情键的 AST 政策。

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

所有文档变更还必须检查相对链接、顶部职责声明、失效路径和旧 acceptance 入口引用，以及 `git diff --check`；如果任务涉及根 README 的入口或部署说明，还必须核对 README 中的命令、链接和目录导航。只有用户明确要求时才修改根 README；完整验收通过前不追加完成态 CHANGELOG。
