# 后端测试说明

测试目录先按测试层级划分，再在层级内按业务模块划分：

```text
tests/
├── unit/               # 单个模块或最小 Flask 应用，外部依赖使用 fake/mock
│   ├── admin/
│   ├── agent/
│   ├── auth/
│   ├── chat/
│   └── database/
├── integration/        # 跨模块静态契约、部署边界和 migration 链路
│   ├── admin/
│   └── migrations/
├── e2e/admin/          # 隔离主从 E2E 的种子与数据库验收模块
├── run_admin_31_e2e.ps1
└── run_admin_32_e2e.ps1
```

`unit` 和 `integration` 表示依赖范围，`admin`、`auth`、`database` 等目录表示业务归属。新增测试时先判断是否需要真实跨模块依赖，再选择业务目录。仓库测试同时包含 pytest 风格函数与 `unittest.TestCase`，统一由 pytest 负责发现和执行。

## Docker 单元测试环境（推荐）

`docker-compose.test.yml` 提供独立的 `unit-test` 服务。Dockerfile 的 `test` 目标在共享 Python 项目依赖上安装 `requirements-test.txt`，不会把 `pytest` 临时安装到正在运行的应用容器。

该服务有以下边界：

- 不依赖 `app`、worker、monitor 或 MySQL 服务。
- 禁用容器网络，防止单元测试意外调用外部服务。
- 将当前仓库只读挂载到 `/app`，代码修改立即生效，测试不能改写工作区。
- 使用 `--rm` 时只删除本次测试容器；已经构建的测试镜像会继续复用。



```bash
docker compose -f docker-compose.test.yml build unit-test
```

运行全部单元测试：

```bash
docker compose -f docker-compose.test.yml run --rm unit-test
```

运行指定目录或文件时，在服务名后覆盖默认命令：

```bash
docker compose -f docker-compose.test.yml run --rm unit-test python -m pytest -p no:cacheprovider tests/unit/admin
docker compose -f docker-compose.test.yml run --rm unit-test python -m pytest -p no:cacheprovider tests/unit/agent/test_agent_state_routing.py
```

临时进入相同测试环境排查问题：

```bash
docker compose -f docker-compose.test.yml run --rm unit-test sh
```

退出 Shell 后容器自动删除。修改 Python 源码或测试文件后不需要重建镜像；只有依赖变化才需要重新构建。

## 本地 Python 回退方式

未使用 Docker 时，需要自行在当前 Python 环境安装项目依赖和 `pytest`，然后运行：

```bash
python -m pytest tests/unit
```

这条路径只作为环境受限时的回退，不应由 Codex 或开发者反复临时安装依赖来充当团队测试环境。



只有准备好隔离 Docker 主从、管理员前端生产构建和 Playwright 凭据后，才运行：

```powershell
powershell -ExecutionPolicy Bypass -File tests/run_admin_32_e2e.ps1
```

两个 PowerShell 文件是稳定的人工入口。E2E Python 辅助模块位于 `tests/e2e/admin/`，不应作为普通 pytest 测试自动执行，也不属于 `unit-test` 服务的执行范围。
