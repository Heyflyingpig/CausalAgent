import { expect, test } from '@playwright/test'

const observedAt = '2026-07-25T12:00:01.000Z'
const mappedDigestText = 'SELECT * FROM users WHERE id = ?'
const inferredDigestText = 'SELECT id, payload FROM custom_table WHERE tenant_id = ? AND archived_at IS NULL ORDER BY created_at DESC LIMIT ?'
const overrides = {
  auto_refresh_enabled: null,
  realtime_interval_seconds: null,
  sql_interval_seconds: null,
  table_capacity_interval_seconds: null,
  slow_query_warning_delta: null,
  integrity_enabled: null,
  integrity_interval_seconds: null,
}
const effective = {
  auto_refresh_enabled: true,
  realtime_interval_seconds: 10,
  sql_interval_seconds: 60,
  table_capacity_interval_seconds: 900,
  slow_query_warning_delta: 1,
  integrity_enabled: false,
  integrity_interval_seconds: 86400,
}

test('完整看板和在线配置在 Vue 生产路由语义下可交互', async ({ page }) => {
  let version = 1
  await page.route('**/api/check_auth', route => route.fulfill({
    json: {
      isLoggedIn: true,
      username: 'mock-admin',
      role: 'admin',
      csrf_token: 'mock-csrf',
    },
  }))
  await page.route('**/api/admin/db/dashboard', route => route.fulfill({
    json: {
      success: true,
      data: {
        realtime: {
          status: 'healthy',
          observed_at: observedAt,
          source_alias: 'primary',
          primary: {
            status: 'healthy',
            value: { connected: true, version: '8.0.42' },
          },
          replica: {
            status: 'healthy',
            value: {
              configured: true,
              available: true,
              lag_seconds: 0,
              io_running: 'Yes',
              sql_running: 'Yes',
            },
          },
          connections: {
            status: 'healthy',
            value: {
              utilization_percent: 12,
              threads_connected: 12,
              max_connections: 100,
              threads_running: 2,
              max_used_connections: 20,
            },
          },
          jobs: {
            status: 'healthy',
            value: {
              summary: { queued: 1, running: 2, stale: 0, max_attempts_running: 0 },
              data: [{
                job_id: 'job-1',
                status: 'running',
                worker_id: 'worker-1',
                attempt_count: 1,
                max_attempts: 3,
                heartbeat_at: observedAt,
                created_at: observedAt,
              }],
            },
          },
        },
        capacity: {
          status: 'healthy',
          observed_at: observedAt,
          source_alias: 'replica-1',
          is_estimate: true,
          revision: {
            status: 'healthy',
            value: {
              matches: true,
              repository_heads: ['c2d3e4f5a6b7'],
              instance_revisions: ['c2d3e4f5a6b7'],
            },
          },
          tables: {
            status: 'healthy',
            is_estimate: true,
            value: [{
              table_name: 'users',
              table_rows: 10,
              data_length: 1024,
              index_length: 512,
              total_length: 1536,
            }],
          },
        },
        integrity: {
          status: 'healthy',
          observed_at: observedAt,
          source_alias: 'primary',
          blocking_count: 0,
          checks: [{
            label: '关键外键',
            value: 0,
            status: 'healthy',
            source_alias: 'primary',
          }],
        },
        sql_performance: {
          status: 'warning',
          observed_at: observedAt,
          source_alias: 'primary',
          warning: 'performance_schema digest 无权限，其他指标仍可用',
          slow_query_log: 'ON',
          long_query_time: 10,
          slow_queries_delta: 2,
          window_seconds: 60,
          slow_queries_total: 20,
          slow_query_warning_threshold: 1,
          high_load_statements: [
            {
              digest_text: mappedDigestText,
              count_star: 10,
              total_seconds: 1.2,
              avg_seconds: 0.12,
              rows_examined: 10,
              rows_sent: 10,
            },
            {
              digest: inferredDigestText,
              execution_count: 3,
              total_seconds: 0.75,
              avg_seconds: 0.25,
              rows_examined: 30,
              rows_sent: 3,
            },
          ],
        },
        refresh_policy: {
          ...effective,
          configuration_version: 1,
          configuration_state: 'current',
          configuration_warning: null,
        },
      },
    },
  }))
  await page.route('**/api/admin/db/refresh', route => {
    expect(route.request().headers()['x-csrf-token']).toBe('mock-csrf')
    return route.fulfill({
      status: 202,
      json: {
        success: true,
        data: {
          groups: ['realtime', 'sql_performance', 'capacity'],
          requested_at: '2026-07-25T12:00:00.000Z',
        },
      },
    })
  })
  await page.route('**/api/admin/db/settings/history**', route => route.fulfill({
    json: { success: true, data: { items: [], next_before_id: null } },
  }))
  await page.route('**/api/admin/db/settings', route => {
    const isWrite = route.request().method() === 'PUT'
    if (isWrite) {
      expect(route.request().headers()['x-csrf-token']).toBe('mock-csrf')
      version += 1
    }
    return route.fulfill({
      json: {
        success: true,
        data: {
          version,
          overrides,
          effective,
          sources: Object.fromEntries(Object.keys(overrides).map(key => [key, 'default'])),
          limits: {
            auto_refresh_enabled: { type: 'boolean' },
            realtime_interval_seconds: { type: 'integer', minimum: 5, maximum: 10 },
            sql_interval_seconds: { type: 'integer', minimum: 30, maximum: 60 },
            table_capacity_interval_seconds: { type: 'integer', minimum: 300, maximum: 900 },
            slow_query_warning_delta: { type: 'integer', minimum: 1, maximum: 2147483647 },
            integrity_enabled: { type: 'boolean' },
            integrity_interval_seconds: { type: 'integer', minimum: 3600, maximum: 2147483647 },
          },
          updated_by: null,
          updated_at: null,
          state: 'current',
          warning: null,
        },
      },
    })
  })

  await page.goto('/admin/database')
  await expect(page.getByRole('heading', { name: '数据库状态看板' })).toBeVisible()
  for (const text of ['Revision', '主库', '第一从库', '阻塞项', '连接使用率']) {
    await expect(page.getByText(text, { exact: true })).toBeVisible()
  }
  await expect(page.getByText('users', { exact: true })).toBeVisible()
  await expect(page.getByText('performance_schema digest 无权限，其他指标仍可用')).toBeVisible()
  await expect(page.getByText('job-1', { exact: true })).toBeVisible()
  await expect(page.getByText(/最后采集：.*2026/)).toBeVisible()
  await expect(
    page.locator('.status-card').filter({ hasText: 'Revision' }).first().locator('.card-meta'),
  ).toHaveAttribute('title', /2026/)

  await expect(page.getByText('读取用户身份或权限', { exact: true })).toBeVisible()
  await expect(page.getByText('推断：查询 custom_table 数据', { exact: true })).toBeVisible()
  await expect(page.getByText(mappedDigestText, { exact: true })).toHaveCount(0)

  await page.setViewportSize({ width: 1180, height: 900 })
  await page.locator('.sql-business-table').getByRole('button', { name: '查看详情' }).first().click()
  await expect(page.getByRole('heading', { name: 'SQL 原始详情' })).toBeVisible()
  await expect(page.locator('.sql-detail-drawer').getByText('代码确认', { exact: true })).toBeVisible()
  await expect(page.getByText('判断依据', { exact: true })).toBeVisible()
  await expect(page.getByText(/app\/auth\/service\.py/)).toBeVisible()
  await expect(page.getByText(mappedDigestText, { exact: true })).toBeVisible()
  for (const label of [
    'Digest 模板（digest_text / digest）',
    '执行次数（count_star / execution_count）',
    '累计总耗时（total_seconds）',
    '平均耗时（avg_seconds）',
    '扫描行（rows_examined）',
    '返回行（rows_sent）',
  ]) {
    await expect(page.getByText(label, { exact: true })).toBeVisible()
  }
  await expect(page.getByText(/真实参数不会被 Performance Schema Digest 保存/)).toBeVisible()
  await page.getByRole('button', { name: '关闭详情' }).click()
  await expect(page.getByText(mappedDigestText, { exact: true })).toBeHidden()

  await page.setViewportSize({ width: 740, height: 900 })
  await page.locator('.sql-business-table').getByRole('button', { name: '查看详情' }).nth(1).click()
  const mobileDrawer = page.locator('.sql-detail-drawer')
  await expect(mobileDrawer).toBeVisible()
  await expect(mobileDrawer.getByText('推断', { exact: true })).toBeVisible()
  await expect(mobileDrawer.getByText(inferredDigestText, { exact: true })).toBeVisible()
  const drawerBox = await mobileDrawer.boundingBox()
  expect(drawerBox?.width).toBeGreaterThanOrEqual(739)
  expect(drawerBox?.width).toBeLessThanOrEqual(741)
  await page.getByRole('button', { name: '关闭详情' }).click()

  await page.getByRole('button', { name: '手动刷新' }).click()
  await expect(page.getByText('共享监控快照已刷新。')).toBeVisible()
  await expect(page.getByText('共享监控快照已刷新。')).toBeHidden({ timeout: 7_000 })

  await page.getByRole('link', { name: '采集配置' }).click()
  await expect(page).toHaveURL(/\/admin\/database\/settings$/)
  await expect(page.getByRole('heading', { name: '采集配置' })).toBeVisible()
  await expect(page.getByText('实时状态采集周期')).toBeVisible()
  await expect(page.getByText('代码默认').first()).toBeVisible()

  await page.getByRole('button', { name: '保存配置' }).click()
  await expect(page.getByText(/配置已保存/)).toBeVisible()
  expect(version).toBe(2)
})
