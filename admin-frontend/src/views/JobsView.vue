<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError, adminApi } from '../api'
import CursorPager from '../components/CursorPager.vue'
import SensitiveContentDialog from '../components/SensitiveContentDialog.vue'
import { formatDate } from '../lib/dashboard'
import type {
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

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<AdminJob | null>(null)
const events = ref<CursorPage<AdminJobEvent> | null>(null)
const eventCursors = ref<(string | undefined)[]>([undefined])
const contentVisible = ref(false)
const contentTitle = ref('')
const contentLoader = ref<(offset: number) => Promise<SensitiveContentChunk>>(
  async () => Promise.reject(new Error('正文加载器尚未初始化')),
)

const currentCursor = computed(() => cursors.value[cursors.value.length - 1])
const currentEventCursor = computed(
  () => eventCursors.value[eventCursors.value.length - 1],
)

/** 显示带 request ID 的统一页面错误。 */
function showError(caught: unknown): void {
  const apiError = caught as ApiError
  error.value = `${apiError.message}（请求 ID：${apiError.requestId || '未知'}）`
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
  detailLoading.value = true
  try {
    events.value = await adminApi.jobEvents(detail.value.job_id, {
      limit: 20,
      cursor: currentEventCursor.value,
    })
  } catch (caught) {
    showError(caught)
  } finally {
    detailLoading.value = false
  }
}

/** 点击后读取任务详情和首屏事件。 */
async function openDetail(row: AdminJob): Promise<void> {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  events.value = null
  eventCursors.value = [undefined]
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

onMounted(() => loadJobs())
</script>

<template>
  <section>
    <header class="page-header">
      <div>
        <h1>分析任务管理</h1>
      </div>
    </header>

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

        <h3 class="drawer-section-title">事件时间线</h3>
        <el-timeline v-if="events?.items.length">
          <el-timeline-item
            v-for="event in events.items"
            :key="event.id"
            :timestamp="formatDate(event.created_at)"
          >
            <strong>{{ event.event_type }}</strong>
            <span class="event-meta">事件 #{{ event.id }} · payload {{ event.has_payload ? '已记录' : '为空' }}</span>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="没有任务事件" />
        <CursorPager
          :can-previous="eventCursors.length > 1"
          :has-more="Boolean(events?.has_more)"
          :loading="detailLoading"
          @previous="previousEvents"
          @next="nextEvents"
        />
      </div>
    </el-drawer>

    <SensitiveContentDialog
      v-model="contentVisible"
      :title="contentTitle"
      :load-chunk="contentLoader"
    />
  </section>
</template>
