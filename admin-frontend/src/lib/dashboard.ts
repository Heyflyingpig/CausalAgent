import type { DashboardData, HealthStatus, SnapshotMeta } from '../types'

export const REFRESH_GROUP_KEYS = ['realtime', 'sql_performance', 'capacity'] as const
export const MANUAL_REFRESH_TIMEOUT_MS = 60_000
export const MANUAL_POLL_INTERVAL_MS = 1_500
export const SUCCESS_NOTICE_DURATION_MS = 5_000

/** 判断未知值是否为可安全索引的普通对象。 */
export function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/** 把服务端健康状态映射为既定中文标签。 */
export function statusLabel(status?: string): string {
  return ({ healthy: '正常', warning: '警告', error: '异常', unknown: '未知' } as Record<string, string>)[status || ''] || '未知'
}

/** 统一处理空值展示，并保留非空的原始字符串语义。 */
export function displayValue(value: unknown, fallback = '—'): string {
  return value === null || value === undefined || value === '' ? fallback : String(value)
}

/** 把 ISO 时间转换为中文 24 小时本地时间。 */
export function formatDate(value: unknown): string {
  if (!value) return '时间未知'
  const parsed = value instanceof Date
    ? value
    : typeof value === 'number' ? new Date(value) : new Date(String(value))
  return Number.isNaN(parsed.getTime())
    ? String(value)
    : parsed.toLocaleString('zh-CN', { hour12: false })
}

/** 把字节数格式化为适合容量表展示的单位。 */
export function formatBytes(value: unknown): string {
  const bytes = Number(value || 0)
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / (1024 ** index)).toFixed(index === 0 ? 0 : 2)} ${units[index]}`
}

/** 对有效数值应用中文千分位，空值保持占位符。 */
export function formatNumber(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN') : String(value)
}

/** 兼容带 value 元数据包装和旧版直接值两种快照字段。 */
export function metricValue<T = unknown>(metric: unknown): T {
  if (isObject(metric) && Object.prototype.hasOwnProperty.call(metric, 'value')) {
    return metric.value as T
  }
  return metric as T
}

/** 合并分组与单指标元数据，单指标事实优先。 */
export function metricResult(metric: unknown, group: SnapshotMeta): SnapshotMeta {
  const metricObject = isObject(metric) ? metric : {}
  return {
    ...group,
    ...metricObject,
    observed_at: metricObject.observed_at || group.observed_at || null,
    source_alias: metricObject.source_alias || group.source_alias || '共享监控快照',
  } as SnapshotMeta
}

/** 组合来源、采集时间、估算、过期和排队提示。 */
export function metaText(result?: SnapshotMeta | null): string {
  if (!result) return '尚无快照'
  const suffixes: string[] = []
  if (result.is_estimate) suffixes.push('估算')
  if (result.is_stale) suffixes.push('已过期')
  if (result.refresh_pending) suffixes.push('刷新排队中')
  const suffix = suffixes.length ? ` · ${suffixes.join(' · ')}` : ''
  return `${displayValue(result.source_alias, '共享监控快照')} · ${formatDate(result.observed_at)}${suffix}`
}

/** 将已过期的 healthy 快照降级为 warning，避免伪装新鲜。 */
export function displayStatus(result?: SnapshotMeta | null): HealthStatus {
  if (!result) return 'unknown'
  if (result.is_stale && result.status === 'healthy') return 'warning'
  return result.status || 'unknown'
}

/** 从结构化或字符串阻塞项提取稳定提示。 */
export function issueMessage(issue: unknown): string {
  if (typeof issue === 'string') return issue
  if (isObject(issue)) return String(issue.message || issue.label || '发现未命名阻塞项')
  return '发现未命名阻塞项'
}

/** 综合 realtime、capacity 与 integrity 生成五卡中的阻塞卡。 */
export function deriveBlockingCard(data: Partial<DashboardData>): {
  status: HealthStatus
  value: number
  detail: string
  meta: SnapshotMeta
} {
  const realtime = data.realtime || {}
  const capacity = data.capacity || {}
  const integrity = data.integrity || {}
  const realtimeIssues = Array.isArray(realtime.blocking_issues) ? realtime.blocking_issues : []
  const capacityIssues = Array.isArray(capacity.blocking_issues) ? capacity.blocking_issues : []
  const issues = [...realtimeIssues, ...capacityIssues]
  const integrityCount = Number(integrity.blocking_count || 0)
  const count = issues.length + integrityCount
  const coreKnown = Boolean(realtime.observed_at && capacity.observed_at)
  const integrityKnown = Boolean(integrity.observed_at)
  const groupStatuses: Array<[string, HealthStatus]> = [
    ['实时状态', displayStatus(realtime)],
    ['容量状态', displayStatus(capacity)],
    ['完整性审计', displayStatus(integrity)],
  ]
  const errorGroup = groupStatuses.find(([, status]) => status === 'error')
  const uncertainGroup = groupStatuses.find(([, status]) => status === 'warning' || status === 'unknown')
  let status: HealthStatus = 'healthy'
  let detail = '未发现 revision、节点或完整性阻塞项'
  if (count > 0) {
    status = 'error'
    detail = issues.length ? issueMessage(issues[0]) : `完整性审计发现 ${integrityCount} 个阻塞项`
  } else if (errorGroup) {
    status = 'error'
    detail = `${errorGroup[0]}采集异常，当前不能确认不存在阻塞项`
  } else if (!coreKnown) {
    status = 'unknown'
    detail = '核心状态快照尚未生成，请确认 monitor 正常运行'
  } else if (!integrityKnown) {
    status = 'warning'
    detail = data.refresh_policy?.integrity_enabled
      ? '核心状态未发现阻塞；完整性审计尚未执行'
      : '核心状态未发现阻塞；完整性定时审计已关闭且尚未手动执行'
  } else if (integrity.is_stale) {
    status = 'warning'
    detail = '核心状态未发现阻塞；完整性审计快照已过期'
  } else if (uncertainGroup) {
    status = 'warning'
    detail = `${uncertainGroup[0]}结果不完整，当前不能确认不存在阻塞项`
  }
  const observedAt = [realtime.observed_at, capacity.observed_at, integrity.observed_at]
    .filter(Boolean)
    .sort()
    .at(-1) || null
  return {
    status,
    value: count,
    detail,
    meta: {
      status,
      observed_at: observedAt,
      source_alias: '共享监控快照',
      is_stale: Boolean(realtime.is_stale || capacity.is_stale),
      warning: detail,
    },
  }
}

/** 判断指定分层已经完成某次手动请求且不再排队。 */
export function snapshotObservedRequest(group: SnapshotMeta | undefined, requestedAt: string): boolean {
  if (!group || group.refresh_pending === true || !requestedAt) return false
  const observedTime = new Date(String(group.observed_at)).getTime()
  const requestedTime = new Date(requestedAt).getTime()
  return Number.isFinite(observedTime) && Number.isFinite(requestedTime) && observedTime >= requestedTime
}
