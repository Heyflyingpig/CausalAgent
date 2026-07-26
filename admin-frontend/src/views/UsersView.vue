<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError, adminApi } from '../api'
import CursorPager from '../components/CursorPager.vue'
import { formatDate } from '../lib/dashboard'
import type { AdminUser, CursorPage } from '../types'

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

const currentCursor = computed(() => cursors.value[cursors.value.length - 1])

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

onMounted(() => loadUsers())
</script>

<template>
  <section>
    <header class="page-header">
      <div>
        <p class="eyebrow">只读业务数据</p>
        <h1>用户与权限</h1>
        <p class="page-description">展示真实用户角色和启用状态；本阶段没有启停、角色修改或改密入口。</p>
      </div>
    </header>

    <section class="filter-bar">
      <el-input v-model="q" clearable placeholder="按用户名开头搜索" @keyup.enter="loadUsers(true)" />
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

    <section class="panel table-panel">
      <el-table v-loading="loading" :data="page?.items || []" empty-text="没有符合条件的用户">
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

    <el-drawer v-model="detailVisible" title="用户只读详情" size="min(520px, 100vw)">
      <div v-loading="detailLoading">
        <el-descriptions v-if="detail" :column="1" border>
          <el-descriptions-item label="用户 ID">{{ detail.id }}</el-descriptions-item>
          <el-descriptions-item label="用户名">{{ detail.username }}</el-descriptions-item>
          <el-descriptions-item label="角色">{{ detail.role }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ detail.is_active ? '已启用' : '已禁用' }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatDate(detail.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="最后登录">{{ formatDate(detail.last_login_at) }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </el-drawer>
  </section>
</template>
