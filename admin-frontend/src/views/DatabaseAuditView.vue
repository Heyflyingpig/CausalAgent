<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError, adminApi } from '../api'
import { formatDate, isObject, statusLabel } from '../lib/dashboard'
import type { DeepAuditSnapshot } from '../types'

const quick = ref<Record<string, unknown> | null>(null)
const deep = ref<DeepAuditSnapshot | null>(null)
const loading = ref(true)
const running = ref(false)
const error = ref('')
const notice = ref('')
let pollTimer: number | undefined
let requestedAt = 0
let deadline = 0

const quickChecks = computed<Record<string, unknown>[]>(() => {
  const checks = quick.value?.checks
  return Array.isArray(checks) ? checks.filter(isObject) : []
})

/** 读取 quick 和最近一次 deep 共享审计快照。 */
async function loadAudits(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [quickResult, deepResult] = await Promise.all([
      adminApi.quickAudit(),
      adminApi.deepAudit(),
    ])
    quick.value = quickResult
    deep.value = deepResult
  } catch (caught) {
    showError(caught)
  } finally {
    loading.value = false
  }
}

/** 显示带 request ID 的审计页面错误。 */
function showError(caught: unknown): void {
  const apiError = caught as ApiError
  error.value = `${apiError.message}（请求 ID：${apiError.requestId || '未知'}）`
}

/** 判断 deep 快照是否已经覆盖本次手动请求。 */
function deepRequestCompleted(snapshot: DeepAuditSnapshot): boolean {
  const observed = Date.parse(snapshot.observed_at || '')
  return !snapshot.refresh_pending && Number.isFinite(observed) && observed >= requestedAt
}

/** 轮询共享快照，直到 monitor 完成本次 deep 请求或超时。 */
async function pollDeep(): Promise<void> {
  try {
    const snapshot = await adminApi.deepAudit()
    deep.value = snapshot
    if (deepRequestCompleted(snapshot)) {
      running.value = false
      notice.value = 'deep 审计已由独立 monitor 完成。'
      return
    }
    if (Date.now() >= deadline) {
      running.value = false
      error.value = 'deep 审计仍在排队，请稍后重新读取；Web 请求未执行现场审计。'
      return
    }
    pollTimer = window.setTimeout(pollDeep, 1500)
  } catch (caught) {
    running.value = false
    showError(caught)
  }
}

/** 登记手动 deep 审计请求并开始轮询共享结果。 */
async function runDeep(): Promise<void> {
  running.value = true
  error.value = ''
  notice.value = ''
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  try {
    const requested = await adminApi.runDeepAudit()
    requestedAt = Date.parse(requested.requested_at)
    deadline = Date.now() + 60_000
    await pollDeep()
  } catch (caught) {
    running.value = false
    showError(caught)
  }
}

/** 把 deep 检查详情稳定格式化为只读 JSON。 */
function formatDetails(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2)
}

onMounted(loadAudits)
onBeforeUnmount(() => {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
})
</script>

<template>
  <section>
    <header class="page-header">
      <div>
        <p class="eyebrow">数据库运维</p>
        <h1>Schema 与深度审计</h1>
        <p class="page-description">
          quick 读取现有完整性快照；deep 只允许手动登记，由 monitor 执行有超时、有样本上限的只读检查，不自动修复。
        </p>
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="loadAudits">重新读取</el-button>
        <el-button type="primary" :loading="running" @click="runDeep">运行 deep 审计</el-button>
      </div>
    </header>

    <el-alert v-if="error" class="page-notice" type="error" :closable="false" :title="error" />
    <el-alert v-if="notice" class="page-notice" type="success" :closable="false" :title="notice" />

    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>Quick 完整性</h2>
          <p>继续复用 2.5 的共享快照和轻量约束检查。</p>
        </div>
        <span class="source-meta">{{ formatDate(quick?.observed_at) }}</span>
      </div>
      <el-table v-loading="loading" :data="quickChecks" empty-text="尚无 quick 审计结果">
        <el-table-column prop="label" label="检查" min-width="220" />
        <el-table-column prop="status" label="状态" width="110" />
        <el-table-column prop="warning" label="说明" min-width="280" show-overflow-tooltip />
      </el-table>
    </section>

    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>Deep 审计</h2>
          <p>
            {{ deep?.query_timeout_ms || '—' }}ms 查询超时 ·
            异常样本最多 {{ deep?.sample_limit || '—' }} 条 · 永不自动调度
          </p>
        </div>
        <div class="source-meta">
          <el-tag :type="deep?.status === 'healthy' ? 'success' : deep?.status === 'error' ? 'danger' : 'warning'">
            {{ statusLabel(deep?.status || 'unknown') }}
          </el-tag>
          <span>{{ formatDate(deep?.observed_at) }}</span>
        </div>
      </div>

      <el-alert
        v-if="deep?.refresh_pending"
        class="page-notice"
        type="info"
        :closable="false"
        title="deep 审计请求已登记，正在等待独立 monitor 处理。"
      />

      <el-collapse v-loading="loading || running">
        <el-collapse-item
          v-for="check in deep?.checks || []"
          :key="check.key"
          :name="check.key"
        >
          <template #title>
            <div class="audit-check-title">
              <el-tag :type="check.status === 'healthy' ? 'success' : check.status === 'error' ? 'danger' : 'warning'">
                {{ statusLabel(check.status) }}
              </el-tag>
              <strong>{{ check.label }}</strong>
              <span>{{ check.summary }}</span>
            </div>
          </template>
          <pre class="audit-details" v-text="formatDetails(check.details)" />
        </el-collapse-item>
      </el-collapse>
      <el-empty v-if="!loading && !(deep?.checks || []).length" description="尚未运行 deep 审计" />
    </section>
  </section>
</template>
