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

`unit` 和 `integration` 表示依赖范围，`admin`、`auth`、`database` 等目录表示业务归属。新增测试时先判断是否需要真实跨模块依赖，再选择业务目录。

运行前需要在当前 Python 环境中安装项目依赖和 `pytest`。仓库测试同时包含 pytest 风格函数与 `unittest.TestCase`，统一由 pytest 负责发现和执行。

## 推荐执行顺序

1. 运行快速单元测试：

```bash
python -m pytest tests/unit
```

2. 运行集成契约测试：

```bash
python -m pytest tests/integration
```

3. 一次运行全部无外部副作用的后端测试：

```bash
python -m pytest tests/unit tests/integration
```

4. 只有准备好隔离 Docker 主从、管理员前端生产构建和 Playwright 凭据后，才运行：

```powershell
powershell -ExecutionPolicy Bypass -File tests/run_admin_32_e2e.ps1
```

两个 PowerShell 文件是稳定的人工入口。E2E Python 辅助模块位于 `tests/e2e/admin/`，不应作为普通 pytest 测试自动执行。
