<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ApiError, adminApi } from '../api'
import CursorPager from '../components/CursorPager.vue'
import { formatDate } from '../lib/dashboard'
import type {
  AdminOperationResult,
  AdminUser,
  CursorPage,
  UserDeleteImpact,
  UserOperationAction,
  UserOperationPreview,
} from '../types'

const page = ref<CursorPage<AdminUser> | null>(null)
const loading = ref(false)
const error = ref('')
const q = ref('')
const role = ref('')
const active = ref('')
const cursors = ref<(string | undefined)[]>([undefined])
const detail = ref<AdminUser | null>(null)
const detailVisible = ref(false)
const detailLoading = ref(false)
const selectedUsers = ref<AdminUser[]>([])
const tableRef = ref<{ clearSelection: () => void } | null>(null)
const operationVisible = ref(false)
const operationLoading = ref(false)
const operationSubmitting = ref(false)
const operationAction = ref<UserOperationAction>('set_active')
const operationValue = ref<boolean | 'user' | 'admin' | undefined>(undefined)
const operationTargets = ref<AdminUser[]>([])
const operationPreview = ref<UserOperationPreview | null>(null)
const newPassword = ref('')
const reauthPassword = ref('')
const operationConfirmed = ref(false)
const operationIdempotencyKey = ref('')
const operationError = ref('')
const deleteVisible = ref(false)
const deleteLoading = ref(false)
const deleteSubmitting = ref(false)
const deleteImpact = ref<UserDeleteImpact | null>(null)
const deleteTarget = ref<AdminUser | null>(null)
const deleteConfirmation = ref('')
const deleteReauthPassword = ref('')
const deleteIdempotencyKey = ref('')
const deleteError = ref('')
const checkpointCleanupResult = ref<AdminOperationResult | null>(null)
const CHECKPOINT_CLEANUP_STORAGE_KEY = 'causalagent.admin.last-checkpoint-cleanup'

/** 尝试保留最近一次删除进度；浏览器禁用存储时不影响已提交的删除。 */
function persistCheckpointCleanupResult(result: AdminOperationResult): void {
  try {
    window.sessionStorage.setItem(CHECKPOINT_CLEANUP_STORAGE_KEY, JSON.stringify(result))
  } catch {
    // 页面内状态仍然可见，存储不可用不应覆盖成功结果。
  }
}

const currentCursor = computed(() => cursors.value[cursors.value.length - 1])

/** 把受控操作错误转换为弹窗内可直接处理的提示。 */
function dialogErrorMessage(caught: unknown): string {
  const apiError = caught as ApiError
  const message = apiError.code === 'reauth_failed'
    ? '当前管理员密码不正确，请重新输入。'
    : apiError.message
  return `${message}（请求 ID：${apiError.requestId || '未知'}）`
}

/** 按当前筛选和游标读取一页脱敏用户。 */
async function loadUsers(reset = false): Promise<void> {
  if (reset) cursors.value = [undefined]
  loading.value = true
  error.value = ''
  try {
    page.value = await adminApi.users({
      limit: 20,
      cursor: currentCursor.value,
      q: q.value,
      role: role.value,
      is_active: active.value === '' ? undefined : active.value === 'true',
    })
  } catch (caught) {
    const apiError = caught as ApiError
    error.value = `${apiError.message}（请求 ID：${apiError.requestId || '未知'}）`
  } finally {
    loading.value = false
  }
}

/** 使用服务端下一游标进入后一页。 */
function nextPage(): void {
  if (!page.value?.next_cursor) return
  cursors.value.push(page.value.next_cursor)
  void loadUsers()
}

/** 返回上一游标并重新读取。 */
function previousPage(): void {
  if (cursors.value.length <= 1) return
  cursors.value.pop()
  void loadUsers()
}

/** 点击后读取并审计单个用户详情。 */
async function openDetail(row: AdminUser): Promise<void> {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await adminApi.user(row.id)
  } catch (caught) {
    const apiError = caught as ApiError
    error.value = `${apiError.message}（请求 ID：${apiError.requestId || '未知'}）`
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

/** 生成在一次确认对话框生命周期内保持稳定的幂等键。 */
function newIdempotencyKey(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return `admin-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

/** 轮询跨库 cleanup 操作，避免把 MySQL 已完成误报成 PostgreSQL 已完成。 */
async function waitForCheckpointCleanup(operationId: string): Promise<void> {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    await new Promise(resolve => window.setTimeout(resolve, 1000))
    try {
      const operation = await adminApi.operation(operationId)
      checkpointCleanupResult.value = operation
      persistCheckpointCleanupResult(operation)
      if (operation.status === 'succeeded') {
        ElMessage.success('用户删除及 checkpoint 清理已完成')
        return
      }
      if (operation.status === 'failed') {
        ElMessage.error('用户业务数据已删除，但 checkpoint 清理失败，请查看操作状态')
        return
      }
    } catch {
      // 短暂读取失败不改变已提交的删除结果，下一轮继续查询。
    }
  }
  ElMessage.warning('用户业务数据已删除，checkpoint 仍在后台清理')
}

/** 把 cleanup 聚合状态转换成不含内部异常的管理员文案。 */
function checkpointCleanupStatusLabel(result: AdminOperationResult | null): string {
  const status = result?.checkpoint_cleanup?.status || result?.status
  if (status === 'succeeded') return '成功'
  if (status === 'failed') return '失败'
  if (status === 'running' || status === 'pending') return '清理中'
  return '等待清理'
}

/** 把统一用户操作转换为管理员可读标签。 */
function operationLabel(action = operationAction.value): string {
  if (action === 'set_password') return '设置同一新密码'
  if (action === 'set_role') {
    return operationValue.value === 'admin' ? '设为管理员' : '设为普通用户'
  }
  return operationValue.value === true ? '启用用户' : '禁用用户'
}

/** 打开单个或批量用户操作预览，执行按钮在预览完成前保持禁用。 */
async function openOperation(
  action: UserOperationAction,
  targets: AdminUser[],
  value?: boolean | 'user' | 'admin',
): Promise<void> {
  if (!targets.length) return
  operationVisible.value = true
  operationLoading.value = true
  operationPreview.value = null
  operationAction.value = action
  operationValue.value = value
  operationTargets.value = [...targets]
  newPassword.value = ''
  reauthPassword.value = ''
  operationConfirmed.value = false
  operationIdempotencyKey.value = newIdempotencyKey()
  operationError.value = ''
  error.value = ''
  try {
    operationPreview.value = await adminApi.previewUserOperation(
      action,
      targets.map(item => item.id),
      value,
    )
  } catch (caught) {
    const apiError = caught as ApiError
    error.value = `${apiError.message}（请求 ID：${apiError.requestId || '未知'}）`
    operationVisible.value = false
  } finally {
    operationLoading.value = false
  }
}

/** 提交已预览并重新认证的用户操作；失败重试继续使用同一幂等键。 */
async function submitOperation(): Promise<void> {
  if (!operationPreview.value?.can_execute) return
  operationSubmitting.value = true
  operationError.value = ''
  error.value = ''
  try {
    const body = {
      action: operationAction.value,
      target_ids: operationTargets.value.map(item => item.id),
      value: operationValue.value,
      new_password: operationAction.value === 'set_password' ? newPassword.value : undefined,
      reauth_password: reauthPassword.value,
      confirmed: true as const,
    }
    const result: AdminOperationResult = await adminApi.executeUserOperation(
      body,
      operationIdempotencyKey.value,
    )
    ElMessage.success(
      `${operationLabel()}已完成${result.replayed ? '（幂等重放）' : ''}`,
    )
    operationVisible.value = false
    selectedUsers.value = []
    tableRef.value?.clearSelection()
    await loadUsers(true)
  } catch (caught) {
    const apiError = caught as ApiError
    operationError.value = dialogErrorMessage(caught)
    if (apiError.code === 'reauth_failed' || apiError.code === 'reauth_required') {
      reauthPassword.value = ''
    }
  } finally {
    operationSubmitting.value = false
  }
}

/** 打开用户删除影响预览；此时不会执行任何删除。 */
async function openDelete(row: AdminUser): Promise<void> {
  deleteVisible.value = true
  deleteLoading.value = true
  deleteImpact.value = null
  deleteTarget.value = row
  deleteConfirmation.value = ''
  deleteReauthPassword.value = ''
  deleteIdempotencyKey.value = newIdempotencyKey()
  deleteError.value = ''
  error.value = ''
  try {
    deleteImpact.value = await adminApi.userDeleteImpact(row.id)
  } catch (caught) {
    const apiError = caught as ApiError
    error.value = `${apiError.message}（请求 ID：${apiError.requestId || '未知'}）`
    deleteVisible.value = false
  } finally {
    deleteLoading.value = false
  }
}

/** 在用户名确认、重新认证和影响预览均通过后物理删除用户。 */
async function submitDelete(): Promise<void> {
  if (!deleteTarget.value || !deleteImpact.value?.can_delete) return
  deleteSubmitting.value = true
  deleteError.value = ''
  error.value = ''
  try {
    const result = await adminApi.deleteUser(
      deleteTarget.value.id,
      {
        confirm_username: deleteConfirmation.value,
        reauth_password: deleteReauthPassword.value,
        confirmed: true,
      },
      deleteIdempotencyKey.value,
    )
    checkpointCleanupResult.value = result
    persistCheckpointCleanupResult(result)
    if (result.status === 'running') {
      ElMessage.info('用户业务数据已删除，checkpoint 正在后台清理')
      void waitForCheckpointCleanup(result.operation_id)
    } else {
      ElMessage.success(`用户已删除${result.replayed ? '（幂等重放）' : ''}`)
    }
    deleteVisible.value = false
    selectedUsers.value = []
    tableRef.value?.clearSelection()
    await loadUsers(true)
  } catch (caught) {
    const apiError = caught as ApiError
    deleteError.value = dialogErrorMessage(caught)
    if (apiError.code === 'reauth_failed' || apiError.code === 'reauth_required') {
      deleteReauthPassword.value = ''
    }
  } finally {
    deleteSubmitting.value = false
  }
}

onMounted(() => {
  let stored: string | null = null
  try {
    stored = window.sessionStorage.getItem(CHECKPOINT_CLEANUP_STORAGE_KEY)
  } catch {
    stored = null
  }
  if (stored) {
    try {
      checkpointCleanupResult.value = JSON.parse(stored) as AdminOperationResult
    } catch {
      try {
        window.sessionStorage.removeItem(CHECKPOINT_CLEANUP_STORAGE_KEY)
      } catch {
        // 忽略不可用的浏览器存储。
      }
    }
  }
  void loadUsers()
})
</script>

<template>
  <section>
    <header class="page-header">
      <div>
        <h1>用户与权限管理</h1>
      </div>
    </header>

    <section class="filter-bar">
      <el-input v-model="q" clearable placeholder="用户名" @keyup.enter="loadUsers(true)" />
      <el-select v-model="role" placeholder="全部角色" clearable>
        <el-option label="普通用户" value="user" />
        <el-option label="管理员" value="admin" />
      </el-select>
      <el-select v-model="active" placeholder="全部状态" clearable>
        <el-option label="已启用" value="true" />
        <el-option label="已禁用" value="false" />
      </el-select>
      <el-button type="primary" :loading="loading" @click="loadUsers(true)">筛选</el-button>
    </section>

    <el-alert v-if="error" class="page-notice" type="error" :closable="false" :title="error" />

    <section v-if="checkpointCleanupResult" class="panel checkpoint-cleanup-result">
      <div class="panel-header">
        <div>
          <h2>Checkpoint 清理进度</h2>
          <p>用户业务数据已删除；PostgreSQL checkpoint 由后台 worker 异步清理。</p>
        </div>
        <el-tag
          :type="checkpointCleanupStatusLabel(checkpointCleanupResult) === '成功' ? 'success' : checkpointCleanupStatusLabel(checkpointCleanupResult) === '失败' ? 'danger' : 'warning'"
          round
        >
          {{ checkpointCleanupStatusLabel(checkpointCleanupResult) }}
        </el-tag>
      </div>
      <div class="inline-metrics four-columns">
        <div><span>MySQL 用户数据</span><strong>已删除</strong></div>
        <div><span>PostgreSQL checkpoint</span><strong>{{ checkpointCleanupStatusLabel(checkpointCleanupResult) }}</strong></div>
        <div><span>总任务数</span><strong>{{ checkpointCleanupResult.checkpoint_cleanup?.total ?? 0 }}</strong></div>
        <div><span>成功数</span><strong>{{ checkpointCleanupResult.checkpoint_cleanup?.succeeded ?? 0 }}</strong></div>
        <div><span>失败数</span><strong>{{ checkpointCleanupResult.checkpoint_cleanup?.failed ?? 0 }}</strong></div>
        <div><span>待处理数</span><strong>{{ checkpointCleanupResult.checkpoint_cleanup?.pending ?? 0 }}</strong></div>
        <div><span>Operation ID</span><strong class="break-anywhere">{{ checkpointCleanupResult.operation_id }}</strong></div>
      </div>
      <router-link
        class="checkpoint-cleanup-link"
        :to="{ path: '/database', query: { view: 'outbox', operation_id: checkpointCleanupResult.operation_id } }"
      >
        查看全局清理状态
      </router-link>
    </section>

    <section class="panel table-panel">
      <div class="controlled-action-bar">
        <span>已选择 {{ selectedUsers.length }} / 20 个用户</span>
        <el-button
          :disabled="!selectedUsers.length"
          @click="openOperation('set_active', selectedUsers, true)"
        >
          批量启用
        </el-button>
        <el-button
          :disabled="!selectedUsers.length"
          @click="openOperation('set_active', selectedUsers, false)"
        >
          批量禁用
        </el-button>
        <el-button
          :disabled="!selectedUsers.length"
          @click="openOperation('set_role', selectedUsers, 'admin')"
        >
          批量设为管理员
        </el-button>
        <el-button
          :disabled="!selectedUsers.length"
          @click="openOperation('set_role', selectedUsers, 'user')"
        >
          批量设为普通用户
        </el-button>
        <el-button
          type="warning"
          :disabled="!selectedUsers.length"
          @click="openOperation('set_password', selectedUsers)"
        >
          设置同一新密码
        </el-button>
      </div>
      <el-table
        ref="tableRef"
        v-loading="loading"
        :data="page?.items || []"
        row-key="id"
        empty-text="没有符合条件的用户"
        @selection-change="selectedUsers = $event"
      >
        <el-table-column type="selection" width="48" />
        <el-table-column prop="id" label="ID" width="90" />
        <el-table-column prop="username" label="用户名" min-width="180" />
        <el-table-column label="角色" width="120">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'primary' : 'info'">
              {{ row.role === 'admin' ? '管理员' : '普通用户' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'">
              {{ row.is_active ? '已启用' : '已禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="180">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="最后登录" min-width="180">
          <template #default="{ row }">{{ formatDate(row.last_login_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="350" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <el-button
              link
              :type="row.is_active ? 'warning' : 'success'"
              @click="openOperation('set_active', [row], !row.is_active)"
            >
              {{ row.is_active ? '禁用' : '启用' }}
            </el-button>
            <el-button
              link
              type="primary"
              @click="openOperation('set_role', [row], row.role === 'admin' ? 'user' : 'admin')"
            >
              {{ row.role === 'admin' ? '降为用户' : '升为管理员' }}
            </el-button>
            <el-button link type="warning" @click="openOperation('set_password', [row])">改密</el-button>
            <el-button link type="danger" @click="openDelete(row)">删除</el-button>
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

    <el-drawer v-model="detailVisible" title="用户详情" size="min(520px, 100vw)">
      <div v-loading="detailLoading">
        <el-descriptions v-if="detail" :column="1" border>
          <el-descriptions-item label="用户 ID">{{ detail.id }}</el-descriptions-item>
          <el-descriptions-item label="用户名">{{ detail.username }}</el-descriptions-item>
          <el-descriptions-item label="角色">{{ detail.role }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ detail.is_active ? '已启用' : '已禁用' }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatDate(detail.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="最后登录">{{ formatDate(detail.last_login_at) }}</el-descriptions-item>
          <el-descriptions-item label="认证版本">{{ detail.auth_version ?? 1 }}</el-descriptions-item>
          <el-descriptions-item label="最近改密">
            {{ formatDate(detail.password_changed_at) }}
          </el-descriptions-item>
        </el-descriptions>
      </div>
    </el-drawer>

    <el-dialog v-model="operationVisible" :title="operationLabel()" width="min(760px, 96vw)">
      <div v-loading="operationLoading">
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          title="提交后目标用户旧登录会话将会立即失效！"
        />
        <el-alert
          v-if="operationError"
          class="dialog-error"
          type="error"
          :closable="false"
          show-icon
          :title="operationError"
        />
        <el-table
          v-if="operationPreview"
          class="operation-preview-table"
          :data="operationPreview.items"
          max-height="280"
        >
          <el-table-column prop="id" label="ID" width="80" />
          <el-table-column prop="username" label="用户名" min-width="150" />
          <el-table-column label="当前值" min-width="150">
            <template #default="{ row }">
              {{ row.current.role }} / {{ row.current.is_active ? '启用' : '禁用' }}
            </template>
          </el-table-column>
          <el-table-column label="执行后" min-width="150">
            <template #default="{ row }">
              <template v-if="operationAction === 'set_password'">密码更新、会话失效</template>
              <template v-else-if="operationAction === 'set_role'">
                {{ row.next.role }} / 会话失效
              </template>
              <template v-else>
                {{ row.next.is_active ? '启用' : '禁用' }} / 会话失效
              </template>
            </template>
          </el-table-column>
          <el-table-column label="阻断原因" min-width="230">
            <template #default="{ row }">
              {{ row.blockers.join('；') || '无' }}
            </template>
          </el-table-column>
        </el-table>
        <el-alert
          v-if="operationPreview && !operationPreview.can_execute"
          class="page-notice"
          type="error"
          :closable="false"
          title="预览发现安全阻断，本次操作不能提交。"
        />
        <el-form v-if="operationPreview" label-position="top" class="reauth-form">
          <el-form-item v-if="operationAction === 'set_password'" label="同一个新密码">
            <el-input
              v-model="newPassword"
              aria-label="同一新密码"
              type="password"
              show-password
              autocomplete="new-password"
              placeholder="至少 15 个字符，最多 64 个字符且不超过 72 UTF-8 字节"
            />
          </el-form-item>
          <el-form-item label="当前管理员密码（重新认证）">
            <el-input
              v-model="reauthPassword"
              aria-label="当前管理员密码（重新认证）"
              type="password"
              show-password
              autocomplete="current-password"
              placeholder="请输入当前登录管理员的密码"
            />
          </el-form-item>
          <label class="operation-confirmation">
            <input v-model="operationConfirmed" type="checkbox" />
            <span>我已核对预览，并确认执行 {{ operationLabel() }}</span>
          </label>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="operationVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="operationSubmitting"
          :disabled="
            !operationPreview?.can_execute ||
              !operationConfirmed ||
              !reauthPassword ||
              (operationAction === 'set_password' && newPassword.length < 15)
          "
          @click="submitOperation"
        >
          确认执行
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="deleteVisible" title="删除用户" width="min(720px, 96vw)">
      <div v-loading="deleteLoading">
        <el-alert
          type="error"
          :closable="false"
          show-icon
          title="删除不可恢复；MySQL 业务数据先提交，PostgreSQL checkpoint 随后由后台任务清理。"
        />
        <el-alert
          v-if="deleteError"
          class="dialog-error"
          type="error"
          :closable="false"
          show-icon
          :title="deleteError"
        />
        <template v-if="deleteImpact">
          <el-descriptions :column="2" border class="impact-grid">
            <el-descriptions-item
              v-for="(count, key) in deleteImpact.impact"
              :key="key"
              :label="String(key)"
            >
              {{ count }}
            </el-descriptions-item>
          </el-descriptions>
          <el-alert
            v-if="deleteImpact.blockers.length"
            class="page-notice"
            type="error"
            :closable="false"
            :title="deleteImpact.blockers.join('；')"
          />
          <div class="danger-confirmation-form">
            <div class="danger-confirmation-field">
              <label for="user-delete-confirmation">
                第一步：输入用户名以确认删除
              </label>
              <el-input
                id="user-delete-confirmation"
                v-model="deleteConfirmation"
                :aria-label="`输入用户名 ${deleteImpact.requires_confirmation} 确认`"
                autocomplete="off"
                :placeholder="`请输入完整用户名：${deleteImpact.requires_confirmation}`"
              />
              <p>请完整输入“{{ deleteImpact.requires_confirmation }}”，防止误删其他用户。</p>
            </div>
            <div class="danger-confirmation-field">
              <label for="user-delete-reauth-password">
                第二步：输入当前管理员登录密码
              </label>
              <el-input
                id="user-delete-reauth-password"
                v-model="deleteReauthPassword"
                aria-label="当前管理员密码（重新认证）"
                type="password"
                show-password
                autocomplete="current-password"
                placeholder="请输入当前管理员密码"
              />
            </div>
          </div>
        </template>
      </div>
      <template #footer>
        <el-button @click="deleteVisible = false">取消</el-button>
        <el-button
          type="danger"
          :loading="deleteSubmitting"
          :disabled="
            !deleteImpact?.can_delete ||
              deleteConfirmation !== deleteImpact?.requires_confirmation ||
              !deleteReauthPassword
          "
          @click="submitDelete"
        >
          确认删除
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.controlled-action-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.controlled-action-bar > span {
  margin-right: auto;
  color: #64748b;
}

.operation-preview-table,
.impact-grid,
.reauth-form {
  margin-top: 16px;
}

.dialog-error {
  margin-top: 12px;
}

.danger-confirmation-form {
  display: grid;
  gap: 16px;
  margin-top: 16px;
}

.danger-confirmation-field label {
  display: block;
  margin-bottom: 8px;
  color: #1f2937;
  font-weight: 600;
}

.danger-confirmation-field p {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
}

.operation-confirmation {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #334155;
  cursor: pointer;
}

.operation-confirmation input {
  width: 16px;
  height: 16px;
  accent-color: #2563eb;
}
</style>
