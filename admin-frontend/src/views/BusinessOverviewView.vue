<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError, adminApi } from '../api'
import { formatDate, formatNumber, statusLabel } from '../lib/dashboard'
import type { BusinessOverview } from '../types'

const overview = ref<BusinessOverview | null>(null)
const loading = ref(true)
const error = ref('')

/** 从 Flask 读取业务估算指标和共享快照摘要。 */
async function loadOverview(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    overview.value = await adminApi.businessOverview()
  } catch (caught) {
    const apiError = caught as ApiError
    error.value = `${apiError.message}（请求 ID：${apiError.requestId || '未知'}）`
  } finally {
    loading.value = false
  }
}

onMounted(loadOverview)
</script>

<template>
  <section>
    <header class="page-header">
      <div>
        <p class="eyebrow">只读业务后台</p>
        <h1>业务概览</h1>
        <p class="page-description">
          数量来自数据库表统计估算，具体记录请进入对应页面核对；数据库和 Worker 状态继续复用共享快照。
        </p>
      </div>
      <el-button type="primary" plain :loading="loading" @click="loadOverview">重新读取</el-button>
    </header>

    <el-alert v-if="error" class="page-notice" type="error" :closable="false" :title="error" />

    <div v-loading="loading" class="overview-grid">
      <article v-for="metric in overview?.metrics || []" :key="metric.key" class="overview-card">
        <span>{{ metric.label }}</span>
        <strong>{{ formatNumber(metric.value) }}</strong>
        <small>{{ metric.is_estimate ? '估算' : '精确' }} · {{ metric.source_alias }}</small>
      </article>
    </div>

    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>共享监控快照</h2>
          <p>展示快照类型、观测时间、刷新请求时间和对应健康摘要。</p>
        </div>
        <span class="source-meta">
          统计时间 {{ formatDate(overview?.observed_at) }}
        </span>
      </div>
      <el-table v-loading="loading" :data="overview?.snapshots || []" empty-text="暂无共享快照">
        <el-table-column prop="snapshot_key" label="快照类型" min-width="160" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.status === 'healthy' ? 'success' : row.status === 'error' ? 'danger' : 'warning'">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="观测时间" min-width="190">
          <template #default="{ row }">{{ formatDate(row.observed_at) }}</template>
        </el-table-column>
        <el-table-column label="刷新请求" min-width="190">
          <template #default="{ row }">{{ formatDate(row.refresh_requested_at) }}</template>
        </el-table-column>
        <el-table-column prop="source_alias" label="来源" min-width="180" />
        <el-table-column prop="warning" label="说明" min-width="220" show-overflow-tooltip />
      </el-table>
    </section>
  </section>
</template>
