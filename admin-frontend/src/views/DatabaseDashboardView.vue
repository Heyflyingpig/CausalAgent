<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { adminApi } from '../api'
import SqlDigestTable from '../components/SqlDigestTable.vue'
import StatusCard from '../components/StatusCard.vue'
import {
  MANUAL_POLL_INTERVAL_MS,
  MANUAL_REFRESH_TIMEOUT_MS,
  REFRESH_GROUP_KEYS,
  SUCCESS_NOTICE_DURATION_MS,
  deriveBlockingCard,
  displayStatus,
  displayValue,
  formatBytes,
  formatDate,
  formatNumber,
  isObject,
  metaText,
  metricResult,
  metricValue,
  snapshotObservedRequest,
  statusLabel,
} from '../lib/dashboard'
import type { DashboardData, SnapshotMeta } from '../types'

const dashboard = ref<DashboardData | null>(null)
const loading = ref(true)
const pageNotice = ref('')
const noticeType = ref<'error' | 'warning' | 'info'>('error')
const refreshing = ref(false)
const auditing = ref(false)
let autoRefreshTimer: number | undefined
let noticeTimer: number | undefined
let dashboardRequest: Promise<DashboardData> | null = null

const failureMeta = computed<SnapshotMeta>(() => ({
  status: 'unknown',
  observed_at: null,
  source_alias: '共享监控快照',
  warning: pageNotice.value || '数据库看板尚未加载',
}))

/** 从聚合响应取得指定分层，并把未知值安全收敛为空元数据。 */
function group(name: keyof DashboardData): SnapshotMeta {
  const value = dashboard.value?.[name]
  return isObject(value) ? value as SnapshotMeta : {}
}

/** 把模板使用的未知嵌套值规范为普通对象。 */
function record(value: unknown): Record<string, unknown> {
  return isObject(value) ? value : {}
}

const realtime = computed(() => group('realtime'))
const capacity = computed(() => group('capacity'))
const sqlPerformance = computed(() => group('sql_performance'))
const integrity = computed(() => group('integrity'))
const policy = computed(() => record(dashboard.value?.refresh_policy))

const revisionMetric = computed(() => capacity.value.revision)
const revision = computed(() => record(metricValue(revisionMetric.value)))
const revisionMeta = computed(() => dashboard.value
  ? metricResult(revisionMetric.value, capacity.value)
  : failureMeta.value)
const revisionValue = computed(() => revision.value.matches === true
  ? '一致'
  : revision.value.matches === false ? '不一致' : '未知')
const revisionDetail = computed(() => {
  const repository = Array.isArray(revision.value.repository_heads) ? revision.value.repository_heads.join(', ') : ''
  const instance = Array.isArray(revision.value.instance_revisions) ? revision.value.instance_revisions.join(', ') : ''
  return `仓库 ${displayValue(repository)} · 实例 ${displayValue(instance)}`
})

const primaryMetric = computed(() => realtime.value.primary)
const primary = computed(() => record(metricValue(primaryMetric.value)))
const primaryMeta = computed(() => dashboard.value
  ? metricResult(primaryMetric.value, realtime.value)
  : failureMeta.value)
const primaryValue = computed(() => primary.value.connected === true
  ? '已连接'
  : primary.value.connected === false ? '不可用' : statusLabel(displayStatus(primaryMeta.value)))
const primaryDetail = computed(() => primary.value.version
  ? `MySQL ${primary.value.version}`
  : String(primaryMeta.value.warning || '暂无补充信息'))

const replicaMetric = computed(() => realtime.value.replica)
const replica = computed(() => record(metricValue(replicaMetric.value)))
const replicaMeta = computed(() => dashboard.value
  ? metricResult(replicaMetric.value, realtime.value)
  : failureMeta.value)
const replicaValue = computed(() => replica.value.configured === false
  ? '未配置'
  : replica.value.available === true
    ? `${displayValue(replica.value.lag_seconds, '?')} 秒延迟`
    : replica.value.available === false ? '不可用' : statusLabel(displayStatus(replicaMeta.value)))
const replicaDetail = computed(() => replica.value.available
  ? String(replica.value.last_io_error || replica.value.last_sql_error
      || `IO ${displayValue(replica.value.io_running)} · SQL ${displayValue(replica.value.sql_running)}`)
  : String(replicaMeta.value.warning || '暂无补充信息'))

const connectionsMetric = computed(() => realtime.value.connections)
const connections = computed(() => record(metricValue(connectionsMetric.value)))
const connectionsMeta = computed(() => dashboard.value
  ? metricResult(connectionsMetric.value, realtime.value)
  : failureMeta.value)
const connectionsValue = computed(() => (
  connections.value.utilization_percent === null
  || connections.value.utilization_percent === undefined
) ? '未知' : `${connections.value.utilization_percent}%`)
const connectionsDetail = computed(() =>
  `${formatNumber(connections.value.threads_connected)} / ${formatNumber(connections.value.max_connections)} 连接`
  + ` · Running ${formatNumber(connections.value.threads_running)}`
  + ` · 历史峰值 ${formatNumber(connections.value.max_used_connections)}`)

const blocking = computed(() => dashboard.value
  ? deriveBlockingCard(dashboard.value)
  : { status: 'unknown' as const, value: 0, detail: failureMeta.value.warning as string, meta: failureMeta.value })

const tablesMetric = computed(() => capacity.value.tables)
const tables = computed<Record<string, unknown>[]>(() => {
  const value = metricValue(tablesMetric.value)
  return Array.isArray(value) ? value.filter(isObject) : []
})
const tablesMeta = computed(() => dashboard.value
  ? metricResult(tablesMetric.value, capacity.value)
  : failureMeta.value)

const integrityChecks = computed<Record<string, unknown>[]>(() =>
  Array.isArray(integrity.value.checks) ? integrity.value.checks.filter(isObject) : [])

const statements = computed<Record<string, unknown>[]>(() => {
  const value = sqlPerformance.value.high_load_statements || sqlPerformance.value.top_statements
  return Array.isArray(value) ? value.filter(isObject) : []
})

const jobsMetric = computed(() => realtime.value.jobs)
const jobs = computed(() => record(metricValue(jobsMetric.value)))
const jobsSummary = computed(() => record(jobs.value.summary || jobs.value))
const jobRows = computed<Record<string, unknown>[]>(() => {
  const rows = jobs.value.data || jobs.value.jobs || jobs.value.active_jobs
  return Array.isArray(rows) ? rows.filter(isObject) : []
})
const jobsMeta = computed(() => dashboard.value
  ? metricResult(jobs.value.meta || jobsMetric.value, realtime.value)
  : failureMeta.value)

const lastObservedAt = computed(() => {
  const times = [
    realtime.value.observed_at,
    sqlPerformance.value.observed_at,
    capacity.value.observed_at,
    integrity.value.observed_at,
  ].filter(Boolean).map(value => new Date(String(value)).getTime()).filter(Number.isFinite)
  return times.length ? `最后采集：${formatDate(Math.max(...times))}` : '尚未生成监控快照'
})

const refreshPolicyText = computed(() => {
  if (policy.value.auto_refresh_enabled !== true) return '自动刷新已关闭 · 可手动刷新共享快照'
  const realtimeSeconds = Number(policy.value.realtime_interval_seconds)
  const sqlSeconds = Number(policy.value.sql_interval_seconds)
  const capacitySeconds = Number(policy.value.table_capacity_interval_seconds)
  return [realtimeSeconds, sqlSeconds, capacitySeconds].every(value => Number.isFinite(value) && value > 0)
    ? `自动读取 ${realtimeSeconds} 秒 · SQL ${sqlSeconds} 秒 · 容量 ${capacitySeconds} 秒`
    : '自动刷新策略不可用 · 可手动刷新共享快照'
})

/** 根据容量分层状态生成表容量的排队、过期、失败与空态提示。 */
function tableState(): { message: string; tone: 'warning' | 'error' | '' } {
  if (!dashboard.value) return { message: failureMeta.value.warning as string, tone: 'error' }
  if (capacity.value.refresh_pending) return { message: '表容量刷新请求已登记，正在等待 monitor 完成采集。', tone: 'warning' }
  if (capacity.value.is_stale) return { message: '表容量快照已过期，当前展示的是最近一次可用结果。', tone: 'warning' }
  if (capacity.value.warning || tablesMeta.value.warning) {
    return {
      message: String(capacity.value.warning || tablesMeta.value.warning),
      tone: displayStatus(capacity.value) === 'error' ? 'error' : 'warning',
    }
  }
  if (!tables.value.length) {
    return { message: capacity.value.observed_at ? '当前数据库没有可展示的表容量数据。' : '表容量快照尚未生成。', tone: '' }
  }
  return { message: '', tone: '' }
}

/** 根据完整性分层和定时策略生成审计状态提示。 */
function integrityState(): { message: string; tone: 'warning' | 'error' | '' } {
  if (!dashboard.value) return { message: failureMeta.value.warning as string, tone: 'error' }
  if (integrity.value.refresh_pending) return { message: '完整性审计请求已登记，正在等待 monitor 执行。', tone: 'warning' }
  if (!integrity.value.observed_at) {
    return {
      message: policy.value.integrity_enabled
        ? '完整性审计尚未执行，monitor 将按低频策略采集；也可立即手动执行。'
        : '完整性定时审计已关闭，尚无审计结果；可点击“执行完整性审计”。',
      tone: 'warning',
    }
  }
  if (integrity.value.is_stale) return { message: '完整性审计快照已过期，当前结果仅供参考；可手动重新执行。', tone: 'warning' }
  if (integrity.value.warning) {
    return { message: String(integrity.value.warning), tone: displayStatus(integrity.value) === 'error' ? 'error' : 'warning' }
  }
  if (!integrityChecks.value.length) return { message: '最近一次审计没有返回可展示的检查项。', tone: '' }
  if (!policy.value.integrity_enabled) return { message: '完整性定时审计已关闭；当前展示最近一次手动或迁移后审计结果。', tone: 'warning' }
  return { message: '', tone: '' }
}

/** 根据 SQL 快照生成排队、无快照、过期、降级和空态提示。 */
function sqlState(): { message: string; tone: 'warning' | 'error' | '' } {
  if (!dashboard.value) return { message: failureMeta.value.warning as string, tone: 'error' }
  if (sqlPerformance.value.refresh_pending) return { message: 'SQL 性能刷新请求已登记，正在等待 monitor 完成采集。', tone: 'warning' }
  if (!sqlPerformance.value.observed_at) return { message: 'SQL 性能快照尚未生成。', tone: 'warning' }
  if (sqlPerformance.value.is_stale) return { message: 'SQL 性能快照已过期，当前展示的是最近一次可用结果。', tone: 'warning' }
  if (sqlPerformance.value.warning) {
    return { message: String(sqlPerformance.value.warning), tone: displayStatus(sqlPerformance.value) === 'error' ? 'error' : 'warning' }
  }
  if (!statements.value.length) return { message: 'Performance Schema 当前没有可展示的高负载 SQL digest。', tone: '' }
  return { message: '', tone: '' }
}

/** 根据 realtime 与任务元数据生成 Worker/Job 状态提示。 */
function jobsState(): { message: string; tone: 'warning' | 'error' | '' } {
  if (!dashboard.value) return { message: failureMeta.value.warning as string, tone: 'error' }
  if (realtime.value.refresh_pending) return { message: '实时状态刷新请求已登记，正在等待 monitor 完成采集。', tone: 'warning' }
  if (realtime.value.is_stale) return { message: 'Worker / Job 快照已过期，monitor 可能未正常运行。', tone: 'warning' }
  if (realtime.value.warning || jobsMeta.value.warning) {
    return {
      message: String(realtime.value.warning || jobsMeta.value.warning),
      tone: displayStatus(realtime.value) === 'error' ? 'error' : 'warning',
    }
  }
  if (!jobRows.value.length) return { message: realtime.value.observed_at ? '当前没有 queued/running 任务。' : '实时状态快照尚未生成。', tone: '' }
  return { message: '', tone: '' }
}

/** 清理当前页面的自动读取定时器。 */
function clearAutoRefresh(): void {
  if (autoRefreshTimer !== undefined) window.clearTimeout(autoRefreshTimer)
  autoRefreshTimer = undefined
}

/** 清理成功提示的自动隐藏定时器。 */
function clearNoticeTimer(): void {
  if (noticeTimer !== undefined) window.clearTimeout(noticeTimer)
  noticeTimer = undefined
}

/** 仅让当前成功提示在固定时间后消失，不覆盖后续警告或错误。 */
function scheduleNoticeDismiss(): void {
  const currentNotice = pageNotice.value
  clearNoticeTimer()
  noticeTimer = window.setTimeout(() => {
    if (pageNotice.value === currentNotice) pageNotice.value = ''
    noticeTimer = undefined
  }, SUCCESS_NOTICE_DURATION_MS)
}

/** 按服务端有效 realtime 周期安排下一次聚合快照读取。 */
function scheduleAutoRefresh(): void {
  clearAutoRefresh()
  if (policy.value.auto_refresh_enabled !== true) return
  const seconds = Number(policy.value.realtime_interval_seconds)
  if (!Number.isFinite(seconds) || seconds <= 0) return
  autoRefreshTimer = window.setTimeout(() => {
    void loadDashboard(true)
  }, seconds * 1000)
}

/** 去重读取聚合快照，并统一维护加载、失败与下一轮调度。 */
async function loadDashboard(quiet = false): Promise<DashboardData> {
  if (dashboardRequest) return dashboardRequest
  dashboardRequest = adminApi.dashboard()
    .then(data => {
      dashboard.value = data
      if (!quiet) {
        clearNoticeTimer()
        pageNotice.value = ''
      }
      return data
    })
    .catch(error => {
      pageNotice.value = `数据库看板加载失败：${error instanceof Error ? error.message : String(error)}`
      noticeType.value = 'error'
      throw error
    })
    .finally(() => {
      dashboardRequest = null
      loading.value = false
      scheduleAutoRefresh()
    })
  return dashboardRequest
}

/** 以 1.5 秒间隔轮询，最长 60 秒等待指定分层完成请求。 */
async function pollUntilSettled(keys: readonly string[], requestedAt: string): Promise<boolean> {
  const deadline = Date.now() + MANUAL_REFRESH_TIMEOUT_MS
  while (Date.now() < deadline) {
    const data = await loadDashboard(true)
    if (keys.every(key => snapshotObservedRequest(data[key as keyof DashboardData] as SnapshotMeta, requestedAt))) return true
    await new Promise(resolve => window.setTimeout(resolve, MANUAL_POLL_INTERVAL_MS))
  }
  return false
}

/** 登记 realtime、SQL、capacity 共享刷新并等待分层完成。 */
async function requestSharedRefresh(): Promise<void> {
  clearAutoRefresh()
  clearNoticeTimer()
  refreshing.value = true
  try {
    const response = await adminApi.refresh()
    pageNotice.value = '普通刷新请求已登记，正在等待 realtime、SQL 性能和表容量快照更新。'
    noticeType.value = 'info'
    const completed = await pollUntilSettled(REFRESH_GROUP_KEYS, response.requested_at)
    pageNotice.value = completed ? '共享监控快照已刷新。' : '刷新仍在后台进行，请确认 monitor 是否正常运行。'
    noticeType.value = completed ? 'info' : 'warning'
    if (completed) scheduleNoticeDismiss()
  } catch (error) {
    pageNotice.value = `手动刷新失败：${error instanceof Error ? error.message : String(error)}`
    noticeType.value = 'error'
  } finally {
    refreshing.value = false
    scheduleAutoRefresh()
  }
}

/** 单独登记完整性审计请求并等待 integrity 分层完成。 */
async function requestIntegrityAudit(): Promise<void> {
  clearAutoRefresh()
  clearNoticeTimer()
  auditing.value = true
  try {
    const response = await adminApi.runIntegrity()
    pageNotice.value = '完整性审计请求已登记，正在等待 monitor 完成审计。'
    noticeType.value = 'info'
    const completed = await pollUntilSettled(['integrity'], response.requested_at)
    pageNotice.value = completed ? '完整性审计快照已更新。' : '审计仍在后台进行，请确认 monitor 是否正常运行。'
    noticeType.value = completed ? 'info' : 'warning'
    if (completed) scheduleNoticeDismiss()
  } catch (error) {
    pageNotice.value = `完整性审计请求失败：${error instanceof Error ? error.message : String(error)}`
    noticeType.value = 'error'
  } finally {
    auditing.value = false
    scheduleAutoRefresh()
  }
}

onMounted(() => void loadDashboard())
onBeforeUnmount(() => {
  clearAutoRefresh()
  clearNoticeTimer()
})
</script>

<template>
  <header class="page-header">
    <div>
      <h1>数据库状态看板</h1>
    </div>
    <div class="header-actions">
      <div class="header-status">
        <span>{{ lastObservedAt }}</span>
        <span>{{ refreshPolicyText }}</span>
      </div>
      <el-button type="primary" :loading="refreshing" @click="requestSharedRefresh">手动刷新</el-button>
    </div>
  </header>

  <el-alert
    v-if="pageNotice"
    class="page-notice"
    :title="pageNotice"
    :type="noticeType"
    show-icon
    :closable="false"
  />
  <el-alert
    v-if="policy.configuration_state === 'degraded'"
    class="page-notice"
    :title="String(policy.configuration_warning || '在线监控配置读取失败，当前继续展示已有快照')"
    type="warning"
    show-icon
    :closable="false"
  />

  <section class="status-grid" aria-label="核心状态">
    <StatusCard label="Revision" :value="revisionValue" :detail="revisionDetail" :meta="revisionMeta" />
    <StatusCard label="主库" :value="primaryValue" :detail="primaryDetail" :meta="primaryMeta" />
    <StatusCard label="第一从库" :value="replicaValue" :detail="replicaDetail" :meta="replicaMeta" />
    <StatusCard label="阻塞项" :value="blocking.value" :detail="blocking.detail" :meta="blocking.meta" />
    <StatusCard label="连接使用率" :value="connectionsValue" :detail="connectionsDetail" :meta="connectionsMeta" />
  </section>

  <section class="panel">
    <div class="panel-header">
      <div>
        <h2>表容量</h2>
      </div>
      <span class="source-meta">{{ metaText(tablesMeta) }}</span>
    </div>
    <div v-if="tableState().message" class="section-state" :class="tableState().tone">{{ tableState().message }}</div>
    <el-table v-if="tables.length" :data="tables" v-loading="loading" table-layout="auto">
      <el-table-column prop="table_name" label="表名" min-width="180" />
      <el-table-column label="估算行数" min-width="120"><template #default="{ row }">{{ formatNumber(row.table_rows) }}</template></el-table-column>
      <el-table-column label="数据量" min-width="120"><template #default="{ row }">{{ formatBytes(row.data_length) }}</template></el-table-column>
      <el-table-column label="索引量" min-width="120"><template #default="{ row }">{{ formatBytes(row.index_length) }}</template></el-table-column>
      <el-table-column label="总大小" min-width="120"><template #default="{ row }">{{ formatBytes(row.total_length) }}</template></el-table-column>
    </el-table>
  </section>

  <section class="panel">
    <div class="panel-header">
      <div>
        <h2>完整性审计</h2>
      </div>
      <div class="panel-actions">
        <span class="source-meta">{{ metaText(integrity) }}</span>
        <el-button plain type="primary" :loading="auditing" @click="requestIntegrityAudit">执行完整性审计</el-button>
      </div>
    </div>
    <div v-if="integrityState().message" class="section-state" :class="integrityState().tone">{{ integrityState().message }}</div>
    <el-table v-if="integrityChecks.length" :data="integrityChecks" table-layout="auto">
      <el-table-column label="检查项" min-width="240"><template #default="{ row }">{{ row.label || row.name }}</template></el-table-column>
      <el-table-column label="数量" min-width="100"><template #default="{ row }">{{ formatNumber(row.value) }}</template></el-table-column>
      <el-table-column label="结果" min-width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'healthy' ? 'success' : row.status === 'error' ? 'danger' : 'warning'" round>{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="来源" min-width="150"><template #default="{ row }">{{ row.source_alias || integrity.source_alias || '共享监控快照' }}</template></el-table-column>
    </el-table>
  </section>

  <section class="panel">
    <div class="panel-header">
      <div>
        <h2>SQL 性能摘要</h2>
      </div>
      <span class="source-meta">
        {{ metaText(sqlPerformance) }}
        <template v-if="sqlPerformance.slow_query_warning_threshold !== null && sqlPerformance.slow_query_warning_threshold !== undefined">
        </template>
      </span>
    </div>
    <div class="inline-metrics five-columns">
      <div><span>slow_query_log</span><strong>{{ displayValue(sqlPerformance.slow_query_log) }}</strong></div>
      <div><span>long_query_time</span><strong>{{ sqlPerformance.long_query_time == null ? '—' : `${sqlPerformance.long_query_time} 秒` }}</strong></div>
      <div class="metric-emphasis"><span>周期内 Slow_queries 增量</span><strong>{{ sqlPerformance.slow_queries_delta == null ? (sqlPerformance.baseline_reset ? '基线重建中' : '—') : formatNumber(sqlPerformance.slow_queries_delta) }}</strong></div>
      <div><span>采集窗口</span><strong>{{ sqlPerformance.window_seconds == null ? '—' : `${formatNumber(sqlPerformance.window_seconds)} 秒` }}</strong></div>
      <div><span>累计 Slow_queries</span><strong>{{ formatNumber(sqlPerformance.slow_queries_total ?? sqlPerformance.Slow_queries) }}</strong></div>
    </div>
    <div v-if="sqlState().message" class="section-state" :class="sqlState().tone">{{ sqlState().message }}</div>
    <template v-if="statements.length">
      <div class="sql-business-heading">
        <strong>高负载 SQL（Digest）</strong>
        <span>点击“查看详情”可核对完整原始摘要字段。</span>
      </div>
      <SqlDigestTable :statements="statements" />
    </template>
  </section>

  <section class="panel">
    <div class="panel-header">
      <div>
        <h2>Worker / Job 快照</h2>
        <p>明细最多展示 100 条。</p>
      </div>
      <span class="source-meta">{{ metaText(jobsMeta) }}</span>
    </div>
    <div class="inline-metrics four-columns">
      <div><span>Queued</span><strong>{{ formatNumber(jobsSummary.queued) }}</strong></div>
      <div><span>Running</span><strong>{{ formatNumber(jobsSummary.running) }}</strong></div>
      <div><span>Stale</span><strong>{{ formatNumber(jobsSummary.stale) }}</strong></div>
      <div><span>达到最大尝试仍运行</span><strong>{{ formatNumber(jobsSummary.max_attempts_running) }}</strong></div>
    </div>
    <div v-if="jobsState().message" class="section-state" :class="jobsState().tone">{{ jobsState().message }}</div>
    <el-table v-if="jobRows.length" :data="jobRows" table-layout="auto">
      <el-table-column prop="job_id" label="Job ID" min-width="250" />
      <el-table-column prop="status" label="状态" min-width="100" />
      <el-table-column prop="worker_id" label="Worker" min-width="160" />
      <el-table-column label="尝试次数" min-width="100"><template #default="{ row }">{{ formatNumber(row.attempt_count) }} / {{ formatNumber(row.max_attempts) }}</template></el-table-column>
      <el-table-column label="心跳时间" min-width="180"><template #default="{ row }">{{ formatDate(row.heartbeat_at) }}</template></el-table-column>
      <el-table-column label="创建时间" min-width="180"><template #default="{ row }">{{ formatDate(row.created_at) }}</template></el-table-column>
    </el-table>
  </section>
</template>
