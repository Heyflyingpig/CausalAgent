<script setup lang="ts">
import { computed, ref } from 'vue'
import { displayValue, formatNumber } from '../lib/dashboard'
import { toSqlDigestView, type SqlDigestView } from '../lib/sqlSemantics'

const props = defineProps<{
  statements: Record<string, unknown>[]
}>()

const detailVisible = ref(false)
const selectedStatement = ref<SqlDigestView | null>(null)
const rows = computed(() => props.statements.map(toSqlDigestView))

/** 打开指定 SQL 摘要的业务解释和原始字段详情。 */
function openDetails(row: SqlDigestView): void {
  selectedStatement.value = row
  detailVisible.value = true
}

/** 在抽屉关闭动画完成后清理当前行，避免残留不可见详情状态。 */
function clearDetails(): void {
  selectedStatement.value = null
}
</script>

<template>
  <el-table class="sql-business-table" :data="rows" table-layout="auto">
    <el-table-column label="业务模块" min-width="150" align="center">
      <template #default="{ row }">
        <el-tag effect="plain" round>{{ row.meaning.module }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column label="功能" min-width="240">
      <template #default="{ row }">
        <strong class="sql-business-action">{{ row.meaning.action }}</strong>
      </template>
    </el-table-column>
    <el-table-column label="业务说明" min-width="360">
      <template #default="{ row }">
        <span class="sql-business-description">{{ row.meaning.description }}</span>
      </template>
    </el-table-column>
    <el-table-column label="识别方式" min-width="110">
      <template #default="{ row }">
        <el-tag
          :type="row.meaning.confidence === 'confirmed' ? 'success' : 'warning'"
          effect="light"
          round
        >
          {{ row.meaning.confidence === 'confirmed' ? '代码确认' : '推断' }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column label="操作" fixed="right" width="112">
      <template #default="{ row }">
        <el-button type="primary" link @click="openDetails(row)">查看详情</el-button>
      </template>
    </el-table-column>
  </el-table>

  <el-drawer
    v-model="detailVisible"
    class="sql-detail-drawer"
    direction="rtl"
    size="min(720px, 100vw)"
    destroy-on-close
    @closed="clearDetails"
  >
    <template #header>
      <div>
        <h3>SQL详情</h3>
      </div>
    </template>

    <div v-if="selectedStatement" class="sql-detail-content">
      <section class="sql-detail-business">
        <div class="sql-detail-tags">
          <el-tag effect="plain" round>{{ selectedStatement.meaning.module }}</el-tag>
          <el-tag
            :type="selectedStatement.meaning.confidence === 'confirmed' ? 'success' : 'warning'"
            effect="light"
            round
          >
            {{ selectedStatement.meaning.confidence === 'confirmed' ? '代码确认' : '推断' }}
          </el-tag>
        </div>
        <strong>{{ selectedStatement.meaning.action }}</strong>
        <p>{{ selectedStatement.meaning.description }}</p>
        <div class="sql-detail-evidence">
          <span>判断依据</span>
          <code>{{ selectedStatement.meaning.evidence }}</code>
        </div>
      </section>

      <section class="sql-detail-section">
        <h4>Digest 模板</h4>
        <pre class="sql-detail-digest">{{ selectedStatement.digestText || '—' }}</pre>
      </section>

      <section class="sql-detail-section">
        <h4>统计信息</h4>
        <dl class="sql-raw-metrics">
          <div>
            <dt>执行次数</dt>
            <dd>{{ formatNumber(selectedStatement.countStar) }}</dd>
          </div>
          <div>
            <dt>累计总耗时</dt>
            <dd>{{ displayValue(selectedStatement.totalSeconds) }} 秒</dd>
          </div>
          <div>
            <dt>平均耗时</dt>
            <dd>{{ displayValue(selectedStatement.averageSeconds) }} 秒</dd>
          </div>
          <div>
            <dt>扫描行</dt>
            <dd>{{ formatNumber(selectedStatement.rowsExamined) }}</dd>
          </div>
          <div>
            <dt>返回行</dt>
            <dd>{{ formatNumber(selectedStatement.rowsSent) }}</dd>
          </div>
        </dl>
      </section>

      <div class="sql-detail-actions">
        <el-button @click="detailVisible = false">关闭详情</el-button>
      </div>
    </div>
  </el-drawer>
</template>
