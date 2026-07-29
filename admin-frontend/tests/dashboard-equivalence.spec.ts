import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  MANUAL_POLL_INTERVAL_MS,
  MANUAL_REFRESH_TIMEOUT_MS,
  SUCCESS_NOTICE_DURATION_MS,
  deriveBlockingCard,
  displayStatus,
  formatDate,
  metaText,
  snapshotObservedRequest,
  statusLabel,
} from '../src/lib/dashboard'
import type { SnapshotMeta } from '../src/types'

const dashboardSource = [
  'src/views/DatabaseDashboardView.vue',
  'src/components/SqlDigestTable.vue',
].map(path => readFileSync(resolve(process.cwd(), path), 'utf8')).join('\n')

const equivalenceMatrix = {
  core: ['Revision', '主库', '第一从库', '阻塞项', '连接使用率'],
  capacity: ['表容量', '估算行数', '数据量', '索引量', '总大小'],
  integrity: ['完整性审计', '执行完整性审计', '检查项', '数量', '结果', '来源'],
  sql: [
    'SQL 性能摘要',
    'slow_query_log',
    'long_query_time',
    '周期内 Slow_queries 增量',
    '采集窗口',
    '累计 Slow_queries',
    '高负载 SQL（Digest）',
    '累计总耗时',
    '平均耗时',
    '扫描行',
    '返回行',
    '业务模块',
    '功能',
    '业务说明',
    '识别方式',
    '代码确认',
    '判断依据',
    '查看详情',
    'Digest 模板',
    '执行次数',
  ],
  jobs: [
    'Worker / Job 快照',
    'Queued',
    'Running',
    'Stale',
    '达到最大尝试仍运行',
    'Job ID',
    'Worker',
    '尝试次数',
    '心跳时间',
    '创建时间',
  ],
  operations: ['手动刷新', 'realtime、SQL 性能和表容量', '完整性审计请求已登记'],
  states: [
    '数据库看板加载失败',
    '尚未生成监控快照',
    '刷新请求已登记',
    '正在等待 monitor',
    '快照已过期',
    '当前数据库没有可展示的表容量数据',
    '没有返回可展示的检查项',
    '没有可展示的高负载 SQL digest',
    '当前没有 queued/running 任务',
    '自动刷新已关闭',
    '在线监控配置读取失败',
  ],
}

describe('旧看板到 Vue 的数据驱动等价矩阵', () => {
  for (const [section, requiredTexts] of Object.entries(equivalenceMatrix)) {
    it(`${section} 区块保留全部既定字段、提示或操作`, () => {
      for (const text of requiredTexts) {
        expect(dashboardSource, `缺少等价项：${section}/${text}`).toContain(text)
      }
    })
  }

  it.each([
    ['healthy', '正常'],
    ['warning', '警告'],
    ['error', '异常'],
    ['unknown', '未知'],
    [undefined, '未知'],
  ])('状态 %s 保持中文语义', (status, label) => {
    expect(statusLabel(status)).toBe(label)
  })

  it('来源元数据同时保留估算、过期和排队状态', () => {
    expect(metaText({
      source_alias: 'primary',
      observed_at: '2026-07-25T00:00:00.000Z',
      is_estimate: true,
      is_stale: true,
      refresh_pending: true,
    })).toContain('primary')
    expect(metaText({
      source_alias: 'primary',
      observed_at: '2026-07-25T00:00:00.000Z',
      is_estimate: true,
      is_stale: true,
      refresh_pending: true,
    })).toContain('估算 · 已过期 · 刷新排队中')
  })

  it('已过期的健康快照降级为警告，而真实错误保持异常', () => {
    expect(displayStatus({ status: 'healthy', is_stale: true })).toBe('warning')
    expect(displayStatus({ status: 'error', is_stale: true })).toBe('error')
  })

  it('阻塞卡覆盖已知阻塞、无核心快照和完整性未执行', () => {
    const blocked = deriveBlockingCard({
      realtime: {
        observed_at: '2026-07-25T00:00:00Z',
        blocking_issues: [{ message: 'revision 不一致' }],
      },
      capacity: { observed_at: '2026-07-25T00:00:00Z' },
      integrity: { observed_at: '2026-07-25T00:00:00Z', blocking_count: 0 },
    })
    expect(blocked.status).toBe('error')
    expect(blocked.value).toBe(1)
    expect(blocked.detail).toBe('revision 不一致')

    const missing = deriveBlockingCard({
      realtime: {},
      capacity: {},
      integrity: {},
      refresh_policy: {},
    })
    expect(missing.status).toBe('unknown')

    const unaudited = deriveBlockingCard({
      realtime: { observed_at: '2026-07-25T00:00:00Z', status: 'healthy' as const },
      capacity: { observed_at: '2026-07-25T00:00:00Z', status: 'healthy' as const },
      integrity: {},
      refresh_policy: { integrity_enabled: false },
    })
    expect(unaudited.status).toBe('warning')
    expect(unaudited.detail).toContain('定时审计已关闭')
  })

  it('手动刷新维持 1.5 秒轮询、60 秒超时并按请求时间判定完成', () => {
    expect(MANUAL_POLL_INTERVAL_MS).toBe(1_500)
    expect(MANUAL_REFRESH_TIMEOUT_MS).toBe(60_000)
    const settled: SnapshotMeta = {
      observed_at: '2026-07-25T00:00:01Z',
      refresh_pending: false,
    }
    expect(snapshotObservedRequest(settled, '2026-07-25T00:00:00Z')).toBe(true)
    expect(snapshotObservedRequest(
      { ...settled, refresh_pending: true },
      '2026-07-25T00:00:00Z',
    )).toBe(false)
  })

  it('最后采集时间支持毫秒时间戳，并让成功提示在 5 秒后消失', () => {
    const timestamp = Date.parse('2026-07-25T12:00:01.000Z')
    expect(formatDate(timestamp)).not.toBe(String(timestamp))
    expect(formatDate(timestamp)).toContain('2026')
    expect(SUCCESS_NOTICE_DURATION_MS).toBe(5_000)
    expect(dashboardSource).toContain('scheduleNoticeDismiss()')
  })
})
