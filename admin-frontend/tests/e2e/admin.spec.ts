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
})
