# 测试与验证

文档职责：定义后端、管理员前端、集成迁移和隔离主从/PostgreSQL 验收的验证矩阵与稳定命令。

适用范围：修改代码、迁移、管理员页面或文档中命令时使用；管理员专项测试补充说明见 [`../admin/testing.md`](../admin/testing.md)。

## 测试层级

| 层级 | 位置/入口 | 主要证明 |
| --- | --- | --- |
| 后端 unit | `tests/unit/` | 单模块状态机、权限、Job fencing、结构化输出和 monitor 逻辑 |
| 后端 integration | `tests/integration/` | 跨模块静态契约、部署边界和 migration 链 |
| 管理员 Vue unit | `admin-frontend/tests/*.spec.ts` | API DTO、组件、看板/设置语义和 SQL digest 展示 |
| 管理员 Mock E2E | `admin-frontend` `test:e2e:mock` | 无真实数据库的页面导航、鉴权和交互 |
| 隔离 E2E | `tests/run_admin_31_e2e.ps1` / `run_admin_32_e2e.ps1` | 空库升级、migration 往返、主从、PostgreSQL checkpoint、受控写入/删除和普通用户回归 |

`tests/README.md` 是后端测试目录和 Docker 单元测试环境的补充入口；新增测试时先判断是否需要真实跨模块依赖，再选择 unit 或 integration。

## 后端 Docker 单元测试

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

## 文档重构验证

本轮不改应用行为和公开 API，不要求完整应用测试。必须执行文档静态检查、`git diff --check`、迁移链检查以及 `git diff -- README.md` 空检查；文档中的运行命令和路由已按当前代码/Compose/测试入口核对。
