import { expect, test } from '@playwright/test'

const username = process.env.PLAYWRIGHT_ADMIN_USERNAME
const password = process.env.PLAYWRIGHT_ADMIN_PASSWORD
const normalUsername = process.env.PLAYWRIGHT_USER_USERNAME
const normalPassword = process.env.PLAYWRIGHT_USER_PASSWORD

test.describe('管理员 Vue 与真实共享快照', () => {
  test.skip(
    !username || !password,
    '仅在隔离环境提供 PLAYWRIGHT_ADMIN_USERNAME/PASSWORD 后执行真实管理员写流程',
  )

  test('管理员直接访问、登录、看板刷新、审计与配置版本流程', async ({ page, context }) => {
    await page.goto('/admin/database')
    await expect(page).toHaveURL(/\/$/)

    await page.goto('/')
    await page.locator('#loginUsername').fill(username!)
    await page.locator('#loginPassword').fill(password!)
    await page.getByRole('button', { name: /登录/ }).click()
    await expect(page).toHaveURL(/\/admin\/database$/)
    await expect(page.getByRole('heading', { name: '数据库状态看板' })).toBeVisible()
    await expect(page.getByText('Revision', { exact: true })).toBeVisible()
    await expect(page.getByText('Worker / Job 快照')).toBeVisible()

    await page.getByRole('button', { name: '手动刷新' }).click()
    await expect(page.getByText('共享监控快照已刷新。')).toBeVisible({ timeout: 65_000 })

    await page.getByRole('button', { name: '执行完整性审计' }).click()
    await expect(page.getByText('完整性审计快照已更新。')).toBeVisible({ timeout: 65_000 })

    await page.getByRole('link', { name: '采集配置' }).click()
    await expect(page.getByRole('heading', { name: '采集配置' })).toBeVisible()
    await expect(page.getByText('数据库覆盖').first()).toBeVisible()
    await expect(page.getByRole('heading', { name: '配置变更记录' })).toBeVisible()

    const stalePage = await context.newPage()
    await stalePage.goto('/admin/database/settings')
    await expect(stalePage.getByRole('heading', { name: '采集配置' })).toBeVisible()

    await page.getByRole('button', { name: '保存配置' }).click()
    await expect(page.getByText(/配置已保存/)).toBeVisible()

    await stalePage.getByRole('button', { name: '保存配置' }).click()
    await expect(stalePage.getByText('版本冲突')).toBeVisible()
    await stalePage.getByRole('button', { name: '重新加载' }).click()

    await stalePage.getByRole('button', { name: '重置全部' }).click()
    await stalePage.getByRole('button', { name: '确认重置' }).click()
    await expect(stalePage.getByText(/全部数据库覆盖值已重置/)).toBeVisible()
  })

  test('普通用户仍进入原聊天页面', async ({ page }) => {
    test.skip(!normalUsername || !normalPassword, '未提供隔离环境普通用户凭据')
    await page.goto('/')
    await page.locator('#loginUsername').fill(normalUsername!)
    await page.locator('#loginPassword').fill(normalPassword!)
    await page.getByRole('button', { name: /登录/ }).click()

    await expect(page).not.toHaveURL(/\/admin\//)
    await expect(page.locator('#mainContainer')).toBeVisible()
  })

  test('管理员按已知主键核对 3.1 页面、延迟正文、文件副作用与 deep 审计', async ({ page }) => {
    await page.goto('/')
    await page.locator('#loginUsername').fill(username!)
    await page.locator('#loginPassword').fill(password!)
    await page.getByRole('button', { name: /登录/ }).click()
    await expect(page).toHaveURL(/\/admin\/database$/)

    await page.getByRole('link', { name: '业务概览' }).click()
    await expect(page.getByRole('heading', { name: '业务概览' })).toBeVisible()
    await expect(page.locator('img[alt="CausalAgent"]')).toHaveAttribute(
      'src',
      '/api/admin/brand/logo',
    )

    await page.getByRole('link', { name: '用户与权限' }).click()
    await expect(page.getByText('e2e-admin-31', { exact: true })).toBeVisible()
    await expect(page.getByText('e2e-user-31', { exact: true })).toBeVisible()

    await page.getByRole('link', { name: '会话与内容' }).click()
    await expect(page.getByText('31-user-session', { exact: true })).toBeVisible()
    await page.locator('tr', { hasText: '31-user-session' })
      .getByRole('button', { name: '查看详情' })
      .click()
    await expect(page.getByText('E2E_MESSAGE_BODY_MARKER_31')).toHaveCount(0)
    await page.locator('tr', { hasText: '3101' })
      .getByRole('button', { name: '查看正文' })
      .click()
    await expect(page.getByText('E2E_MESSAGE_BODY_MARKER_31', { exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
    const aiMessageRow = page.locator('tr', { hasText: '3102' })
    await aiMessageRow.getByRole('button', { name: '查看附件' }).click()
    await expect(page.getByText('causal_graph', { exact: true })).toBeVisible()
    await page.locator('tr', { hasText: 'causal_graph' })
      .getByRole('button', { name: '查看正文' })
      .click()
    await expect(page.getByText(/E2E_ATTACHMENT_RESULT_MARKER_31/)).toBeVisible()
    await page.keyboard.press('Escape')
    await page.keyboard.press('Escape')
    await page.keyboard.press('Escape')

    await page.getByRole('link', { name: '分析任务' }).click()
    await expect(page.getByText('31-job-succeeded', { exact: true })).toBeVisible()
    await expect(page.getByText('E2E_JOB_RESULT_MARKER_31')).toHaveCount(0)
    await page.locator('tr', { hasText: '31-job-succeeded' })
      .getByRole('button', { name: '查看详情' })
      .click()
    await page.getByRole('button', { name: '查看结果' }).click()
    await expect(page.getByText(/E2E_JOB_RESULT_MARKER_31/)).toBeVisible()
    await page.keyboard.press('Escape')
    await page.keyboard.press('Escape')

    await page.getByRole('link', { name: '文件资产' }).click()
    const fileRow = page.locator('tr', { hasText: '31-report.csv' })
    await expect(fileRow).toBeVisible()
    await fileRow.getByRole('button', { name: '安全预览' }).click()
    await expect(page.getByText('<script>alert(1)</script>', { exact: true })).toBeVisible()
    await expect(page.locator('.csv-preview-table script')).toHaveCount(0)
    await page.keyboard.press('Escape')
    const downloadPromise = page.waitForEvent('download')
    await fileRow.getByRole('button', { name: '下载' }).click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toBe('31-report.csv')

    await page.getByRole('link', { name: 'Schema 与审计' }).click()
    await page.getByRole('button', { name: '运行 deep 审计' }).click()
    await expect(page.getByText('deep 审计已由独立 monitor 完成。')).toBeVisible({
      timeout: 70_000,
    })
    await expect(page.getByText('Alembic revision')).toBeVisible()
  })

  test('普通用户对全部 3.1 管理页面/API 为 403，原 SSE 与附件恢复不变', async ({
    page,
  }) => {
    test.skip(!normalUsername || !normalPassword, '未提供隔离环境普通用户凭据')
    await page.goto('/')
    await page.locator('#loginUsername').fill(normalUsername!)
    await page.locator('#loginPassword').fill(normalPassword!)
    await page.getByRole('button', { name: /登录/ }).click()
    await expect(page.locator('#mainContainer')).toBeVisible()

    for (const path of [
      '/admin/overview',
      '/admin/users',
      '/admin/sessions',
      '/admin/jobs',
      '/admin/files',
      '/admin/database/audit',
    ]) {
      const response = await page.request.get(path)
      expect(response.status(), path).toBe(403)
    }
    for (const path of [
      '/api/admin/business/overview',
      '/api/admin/business/users',
      '/api/admin/business/sessions',
      '/api/admin/business/jobs',
      '/api/admin/business/files',
      '/api/admin/db/audit?mode=deep',
      '/api/admin/brand/logo',
    ]) {
      const response = await page.request.get(path)
      expect(response.status(), path).toBe(403)
    }

    const restored = await page.request.get('/api/load_session?session=31-user-session')
    expect(restored.status()).toBe(200)
    const restoredBody = await restored.json()
    expect(JSON.stringify(restoredBody)).toContain('E2E_ATTACHMENT_RESULT_MARKER_31')

    const sse = await page.request.get('/api/agent/jobs/31-job-succeeded/events')
    expect(sse.status()).toBe(200)
    const stream = await sse.text()
    expect(stream).toContain('event: final_result')
    expect(stream).toContain('E2E_JOB_RESULT_MARKER_31')
  })
})
