# admin-frontend/AGENTS.md

生效目录：`admin-frontend/` 及其子目录。

负责约束的修改类型：Vue/TypeScript 页面、Router、管理员 API 客户端、Vite 构建、组件测试和浏览器 E2E。

## 修改前必须阅读

- 必须阅读 [`Document/admin/architecture.md`](../Document/admin/architecture.md)、[`Document/admin/api.md`](../Document/admin/api.md)、[`Document/admin/testing.md`](../Document/admin/testing.md) 和 [`Document/development/deployment.md`](../Document/development/deployment.md)。
- 必须检查 `src/api.ts`、`src/types.ts`、router、对应 view/component、Flask 路由和现有 Vitest/Playwright 用例；不能凭页面文字猜 API。
- 修改 database dashboard、monitor settings、Job 或敏感内容组件时，必须阅读对应 `Document/database/` 或 `Document/architecture/` 权威事实。

## TypeScript 与 API 规则

- 必须保持严格 TypeScript 和当前 `/admin/` Vite base；路由、API 客户端、类型定义和页面状态必须一起修改。
- 管理员前端只能调用 Flask API，禁止直接连接 MySQL/PostgreSQL、在浏览器保存密钥或自行实现授权。
- 必须保留 401/403、loading、empty、error、分页、CSRF、request ID、敏感读取上限和脱敏 DTO 的处理；不能因为 UI 方便而显示密码哈希、文件 hash/BLOB、checkpoint 正文或原始错误。
- monitor/数据库页面必须消费共享快照和服务端返回的来源/时间/estimate 语义；禁止在前端硬编码采集周期、数据库 host 或阈值。
- 修改受控写入页面时必须保留预览、密码重新认证、明确确认、幂等键和操作状态查询流程。

## 构建与浏览器验证

- 修改后至少运行 `npm run typecheck`、相关 `npm run test:unit`、`npm run test:e2e:mock` 和 `npm run build`；不要只依赖编辑器类型提示。
- 修改页面导航、鉴权回跳或真实 API 交互时，必须在可用条件下运行 Playwright；截图/浏览器验证应覆盖桌面和移动布局中的文字溢出、遮挡、空态和错误态。
- 真实数据库写操作只能使用隔离 E2E 环境；不要在开发库执行物理删除验收。
