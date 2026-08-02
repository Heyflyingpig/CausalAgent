# 管理员系统测试

后端测试的统一目录与执行顺序见 [`tests/README.md`](../../tests/README.md)。管理员系统同时包含 Python 后端测试、Vue 组件测试、Mock E2E 和隔离主从 E2E。

## 前端快速验证

```bash
cd admin-frontend
npm ci
npm run typecheck
npm run test:unit
npm run test:e2e:mock
npm run build
```

## 隔离主从 E2E

完成生产构建后，从仓库根目录运行稳定入口：

```powershell
powershell -ExecutionPolicy Bypass -File tests/run_admin_32_e2e.ps1
```

脚本使用 `docker-compose.yml` 和 `docker-compose.admin-e2e.yml`，不会迁移或写入当前开发库。它覆盖空库升级、migration 往返、受控用户/文件写入、逐目标审计、主从追平和普通用户回归。

真实 Playwright 流程需要提供 `PLAYWRIGHT_BASE_URL`、管理员和普通用户测试凭据。本机只有 Edge 时可设置 `PLAYWRIGHT_CHANNEL=msedge`；未设置时使用 Playwright Chromium。

脚本结束后会保留隔离数据库容器和卷，不会自动清理。物理删除用例会改变隔离种子，不能通过 `KeepSeededData` 重放。
