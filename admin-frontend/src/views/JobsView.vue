<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ApiError, adminApi } from '../api'
import CursorPager from '../components/CursorPager.vue'
import SensitiveContentDialog from '../components/SensitiveContentDialog.vue'
import { formatDate } from '../lib/dashboard'
import type {
  AgentWorkerSummary,
  AdminCheckpointPage,
  AdminJob,
  AdminJobEvent,
  CursorPage,
  SensitiveContentChunk,
} from '../types'

const page = ref<CursorPage<AdminJob> | null>(null)
const loading = ref(false)
const error = ref('')
const q = ref('')
const status = ref('')
const userId = ref('')
const sessionId = ref('')
const cursors = ref<(string | undefined)[]>([undefined])
const workerSummary = ref<AgentWorkerSummary | null>(null)
const workerSummaryLoading = ref(false)
const workerSummaryError = ref('')

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<AdminJob | null>(null)
const events = ref<CursorPage<AdminJobEvent> | null>(null)
const eventLoading = ref(false)
const eventError = ref('')
const eventCursors = ref<(string | undefined)[]>([undefined])
const checkpoints = ref<AdminCheckpointPage | null>(null)
const checkpointLoading = ref(false)
const checkpointError = ref('')
const checkpointCursors = ref<(string | undefined)[]>([undefined])
type DetailPanel = 'events' | 'checkpoints'
const activeDetailPanel = ref<DetailPanel>('events')
const detailPanelOptions: Array<{ label: string; value: DetailPanel }> = [
  { label: '节点与任务事件', value: 'events' },
  { label: 'Checkpoint 状态', value: 'checkpoints' },
]
const contentVisible = ref(false)
const contentTitle = ref('')
const contentLoader = ref<(offset: number) => Promise<SensitiveContentChunk>>(
  async () => Promise.reject(new Error('正文加载器尚未初始化')),
)

const currentCursor = computed(() => cursors.value[cursors.value.length - 1])
const currentEventCursor = computed(
  () => eventCursors.value[eventCursors.value.length - 1],
)
const currentCheckpointCursor = computed(
  () => checkpointCursors.value[checkpointCursors.value.length - 1],
)

watch(activeDetailPanel, (panel) => {
  if (
    panel === 'checkpoints'
    && detail.value
    && !checkpoints.value
    && !checkpointLoading.value
  ) {
    void loadCheckpoints()
  }
})

/** 把 API 异常转换为带 request ID 的局部错误。 */
function errorText(caught: unknown): string {
  const apiError = caught as ApiError
  return `${apiError.message}（请求 ID：${apiError.requestId || '未知'}）`
}

/** 显示带 request ID 的统一页面错误。 */
function showError(caught: unknown): void {
  error.value = errorText(caught)
}

/** 按筛选和游标读取任务摘要。 */
async function loadJobs(reset = false): Promise<void> {
  if (reset) cursors.value = [undefined]
  loading.value = true
  error.value = ''
  try {
    page.value = await adminApi.jobs({
      limit: 20,
      cursor: currentCursor.value,
      q: q.value,
      status: status.value,
      user_id: userId.value ? Number(userId.value) : undefined,
      session_id: sessionId.value,
    })
  } catch (caught) {
    showError(caught)
  } finally {
    loading.value = false
  }
}

/** 从实时共享快照读取 Agent Worker 心跳和任务汇总。 */
async function loadWorkerSummary(): Promise<void> {
  workerSummaryLoading.value = true
  workerSummaryError.value = ''
  try {
    workerSummary.value = await adminApi.jobWorkersSummary()
  } catch (caught) {
    workerSummaryError.value = errorText(caught)
  } finally {
    workerSummaryLoading.value = false
  }
}

/** 进入任务后一页。 */
function nextPage(): void {
  if (!page.value?.next_cursor) return
  cursors.value.push(page.value.next_cursor)
  void loadJobs()
}

/** 返回任务上一页。 */
function previousPage(): void {
  if (cursors.value.length <= 1) return
  cursors.value.pop()
  void loadJobs()
}

/** 读取当前任务的一页事件时间线。 */
async function loadEvents(): Promise<void> {
  if (!detail.value) return
  eventLoading.value = true
  eventError.value = ''
  try {
    events.value = await adminApi.jobEvents(detail.value.job_id, {
      limit: 20,
      cursor: currentEventCursor.value,
    })
  } catch (caught) {
    eventError.value = errorText(caught)
  } finally {
    eventLoading.value = false
  }
}

/** 读取当前任务的一页 PostgreSQL checkpoint 摘要。 */
async function loadCheckpoints(): Promise<void> {
  if (!detail.value) return
  checkpointLoading.value = true
  checkpointError.value = ''
  try {
    checkpoints.value = await adminApi.jobCheckpoints(detail.value.job_id, {
      limit: 20,
      cursor: currentCheckpointCursor.value,
    })
  } catch (caught) {
    checkpointError.value = errorText(caught)
  } finally {
    checkpointLoading.value = false
  }
}

/** 点击后读取任务详情和首屏事件。 */
async function openDetail(row: AdminJob): Promise<void> {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  events.value = null
  eventError.value = ''
  eventCursors.value = [undefined]
  checkpoints.value = null
  checkpointError.value = ''
  checkpointCursors.value = [undefined]
  activeDetailPanel.value = 'events'
  try {
    detail.value = await adminApi.job(row.job_id)
    await loadEvents()
  } catch (caught) {
    showError(caught)
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

/** 进入事件后一页。 */
function nextEvents(): void {
  if (!events.value?.next_cursor) return
  eventCursors.value.push(events.value.next_cursor)
  void loadEvents()
}

/** 返回事件上一页。 */
function previousEvents(): void {
  if (eventCursors.value.length <= 1) return
  eventCursors.value.pop()
  void loadEvents()
}

/** 进入 checkpoint 后一页。 */
function nextCheckpoints(): void {
  if (!checkpoints.value?.next_cursor) return
  checkpointCursors.value.push(checkpoints.value.next_cursor)
  void loadCheckpoints()
}

/** 返回 checkpoint 上一页。 */
function previousCheckpoints(): void {
  if (checkpointCursors.value.length <= 1) return
  checkpointCursors.value.pop()
  void loadCheckpoints()
}

/** 明确点击后打开指定类别任务正文。 */
function reveal(kind: 'input' | 'result' | 'error'): void {
  if (!detail.value) return
  const labels = { input: '任务输入', result: '任务结果', error: '错误详情' }
  contentTitle.value = `${labels[kind]} · ${detail.value.job_id}`
  contentLoader.value = (offset) => adminApi.jobContent(detail.value!.job_id, kind, offset)
  contentVisible.value = true
}

/** 把任务状态映射为 Element Plus 标签类型。 */
function statusType(value: AdminJob['status']): 'success' | 'warning' | 'danger' | 'info' {
  if (value === 'succeeded') return 'success'
  if (value === 'failed' || value === 'canceled') return 'danger'
  if (value === 'running') return 'warning'
  return 'info'
}

onMounted(() => {
  void loadJobs()
  void loadWorkerSummary()
})
</script>

<template>
  <section>
    <header class="page-header">
      <div>
        <h1>分析任务管理</h1>
      </div>
    </header>

    <section class="panel worker-summary-panel" v-loading="workerSummaryLoading">
      <div class="panel-header">
        <div>
          <h2>Agent Worker</h2>
          <p>分析任务 Worker 心跳和当前队列摘要。</p>
        </div>
        <span class="source-meta">{{ workerSummary?.meta?.source_alias || '共享监控快照' }}</span>
      </div>
      <el-alert v-if="workerSummaryError" class="page-notice" type="warning" :closable="false" :title="workerSummaryError" />
      <div class="inline-metrics four-columns">
        <div><span>Queued</span><strong>{{ workerSummary?.summary.queued ?? '—' }}</strong></div>
        <div><span>Running</span><strong>{{ workerSummary?.summary.running ?? '—' }}</strong></div>
        <div><span>Stale</span><strong>{{ workerSummary?.summary.stale ?? '—' }}</strong></div>
        <div><span>达到最大尝试仍运行</span><strong>{{ workerSummary?.summary.max_attempts_running ?? '—' }}</strong></div>
      </div>
      <el-table v-if="workerSummary?.jobs?.length" :data="workerSummary.jobs" table-layout="auto">
        <el-table-column prop="job_id" label="Job ID" min-width="250" />
        <el-table-column prop="status" label="状态" min-width="100" />
        <el-table-column prop="worker_id" label="Worker" min-width="160" />
        <el-table-column label="尝试次数" min-width="110"><template #default="{ row }">{{ row.attempt_count }} / {{ row.max_attempts }}</template></el-table-column>
        <el-table-column label="心跳时间" min-width="180"><template #default="{ row }">{{ formatDate(row.heartbeat_at) }}</template></el-table-column>
      </el-table>
      <el-empty v-else description="当前没有 queued/running 任务" />
    </section>

    <section class="filter-bar">
      <el-input v-model="q" clearable placeholder="Job ID" @keyup.enter="loadJobs(true)" />
      <el-select v-model="status" clearable placeholder="全部状态">
        <el-option v-for="item in ['queued', 'running', 'succeeded', 'failed', 'canceled']" :key="item" :label="item" :value="item" />
      </el-select>
      <el-input v-model="userId" clearable placeholder="用户 ID" @keyup.enter="loadJobs(true)" />
      <el-input v-model="sessionId" clearable placeholder="会话 ID" @keyup.enter="loadJobs(true)" />
      <el-button type="primary" :loading="loading" @click="loadJobs(true)">筛选</el-button>
    </section>

    <el-alert v-if="error" class="page-notice" type="error" :closable="false" :title="error" />

    <section class="panel table-panel">
      <el-table v-loading="loading" :data="page?.items || []" empty-text="没有符合条件的任务">
        <el-table-column prop="job_id" label="Job ID" min-width="260" show-overflow-tooltip />
        <el-table-column prop="username" label="用户" min-width="130" />
        <el-table-column prop="session_id" label="会话" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="worker_id" label="Worker" min-width="170" show-overflow-tooltip />
        <el-table-column label="创建时间" min-width="180">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">查看详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      <CursorPager
        :can-previous="cursors.length > 1"
        :has-more="Boolean(page?.has_more)"
        :loading="loading"
        @previous="previousPage"
        @next="nextPage"
      />
    </section>

    <el-drawer v-model="detailVisible" title="任务详情" size="min(920px, 100vw)">
      <div v-loading="detailLoading">
        <el-descriptions v-if="detail" :column="2" border>
          <el-descriptions-item label="Job ID" :span="2">{{ detail.job_id }}</el-descriptions-item>
          <el-descriptions-item label="用户">{{ detail.username }} (#{{ detail.user_id }})</el-descriptions-item>
          <el-descriptions-item label="状态">{{ detail.status }}</el-descriptions-item>
          <el-descriptions-item label="会话" :span="2">{{ detail.session_id }}</el-descriptions-item>
          <el-descriptions-item label="Worker">{{ detail.worker_id || '未领取' }}</el-descriptions-item>
          <el-descriptions-item label="尝试次数">{{ detail.attempt_count }} / {{ detail.max_attempts }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatDate(detail.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="完成时间">{{ formatDate(detail.finished_at) }}</el-descriptions-item>
        </el-descriptions>

        <div v-if="detail" class="sensitive-actions">
          <span>查看会被读取并审计！</span>
          <el-button v-if="detail.has_input" @click="reveal('input')">查看输入</el-button>
          <el-button v-if="detail.has_result" @click="reveal('result')">查看结果</el-button>
          <el-button v-if="detail.has_error" type="danger" plain @click="reveal('error')">查看错误</el-button>
        </div>

        <div v-if="detail" class="job-state-selector">
          <div class="job-state-selector-copy">
            <strong>任务状态视图</strong>
            <span>选择查看 MySQL 任务事件或 PostgreSQL checkpoint 摘要</span>
          </div>
          <el-segmented
            v-model="activeDetailPanel"
            :options="detailPanelOptions"
            size="large"
            aria-label="选择任务状态视图"
          />
        </div>

        <section
          v-if="detail && activeDetailPanel === 'events'"
          v-loading="eventLoading"
          class="job-state-panel"
        >
          <h3 class="drawer-section-title">节点与任务事件（MySQL）</h3>
          <el-alert
            v-if="eventError"
            class="page-notice"
            type="error"
            :closable="false"
            :title="eventError"
          />
          <el-timeline v-if="events?.items.length">
            <el-timeline-item
              v-for="event in events.items"
              :key="event.id"
              :timestamp="formatDate(event.created_at)"
            >
              <strong>{{ event.node_name || event.event_type }}</strong>
              <span v-if="event.node_desc" class="event-meta">{{ event.node_desc }}</span>
              <span class="event-meta">
                {{ event.event_type }} · 事件 #{{ event.id }}
                <template v-if="event.duration_seconds !== null"> · {{ event.duration_seconds }} 秒</template>
              </span>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-else description="没有任务事件" />
          <CursorPager
            :can-previous="eventCursors.length > 1"
            :has-more="Boolean(events?.has_more)"
            :loading="eventLoading"
            @previous="previousEvents"
            @next="nextEvents"
          />
        </section>

        <section v-else-if="detail" v-loading="checkpointLoading" class="job-state-panel">
          <h3 class="drawer-section-title">Checkpoint 状态（PostgreSQL）</h3>
          <el-alert
            v-if="checkpointError"
            class="page-notice"
            type="error"
            :closable="false"
            :title="checkpointError"
          />
          <el-alert
            v-if="checkpoints?.legacy_unattributed"
            class="page-notice"
            type="warning"
            :closable="false"
            title="该会话存在迁移前 checkpoint，因缺少 job_id 无法可靠归属，本页不按时间猜测。"
          />
          <el-timeline v-if="checkpoints?.items.length">
            <el-timeline-item
              v-for="checkpoint in checkpoints.items"
              :key="`${checkpoint.checkpoint_ns}:${checkpoint.checkpoint_id}`"
              :timestamp="formatDate(checkpoint.created_at)"
            >
              <strong>Step {{ checkpoint.step ?? '未知' }} · {{ checkpoint.source || '未知来源' }}</strong>
              <span class="event-meta">ID {{ checkpoint.checkpoint_id }}</span>
              <span class="event-meta">父 ID {{ checkpoint.parent_checkpoint_id || '无' }} · namespace {{ checkpoint.checkpoint_ns || '(default)' }}</span>
              <span class="event-meta">更新通道 {{ checkpoint.updated_channels.join('、') || '无' }}</span>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-else-if="!checkpointError" description="没有可归属当前任务的 checkpoint" />
          <CursorPager
            :can-previous="checkpointCursors.length > 1"
            :has-more="Boolean(checkpoints?.has_more)"
            :loading="checkpointLoading"
            @previous="previousCheckpoints"
            @next="nextCheckpoints"
          />
        </section>
      </div>
    </el-drawer>

    <SensitiveContentDialog
      v-model="contentVisible"
      :title="contentTitle"
      :load-chunk="contentLoader"
    />
  </section>
</template>
