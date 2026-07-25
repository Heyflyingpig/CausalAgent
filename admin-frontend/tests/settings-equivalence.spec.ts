import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const settingsSource = readFileSync(
  resolve(process.cwd(), 'src/views/MonitorSettingsView.vue'),
  'utf8',
)

describe('在线监控配置页契约', () => {
  it.each([
    ['auto_refresh_enabled', '自动采集总开关'],
    ['realtime_interval_seconds', '实时状态采集周期'],
    ['sql_interval_seconds', 'SQL 性能采集周期'],
    ['table_capacity_interval_seconds', '表容量采集周期'],
    ['slow_query_warning_delta', '慢查询增量告警阈值'],
    ['integrity_enabled', '完整性定时审计开关'],
    ['integrity_interval_seconds', '完整性审计周期'],
  ])('展示并编辑 %s', (field, label) => {
    expect(settingsSource).toContain(field)
    expect(settingsSource).toContain(label)
  })

  it.each(['数据库覆盖', '环境变量', '代码默认'])('显示逐项来源 %s', source => {
    expect(settingsSource).toContain(source)
  })

  it.each([
    '继承环境/默认',
    '开启',
    '关闭',
    '保存配置',
    '重置全部',
    '版本冲突',
    '变更记录',
    '变更内容',
    '其他进程将在 5 秒内热加载',
  ])('保留配置操作语义：%s', text => {
    expect(settingsSource).toContain(text)
  })
})
