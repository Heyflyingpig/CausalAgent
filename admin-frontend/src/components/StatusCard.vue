<script setup lang="ts">
import { computed } from 'vue'
import { displayStatus, metaText, statusLabel } from '../lib/dashboard'
import type { SnapshotMeta } from '../types'

const props = defineProps<{
  label: string
  value: string | number
  detail: string
  meta: SnapshotMeta
}>()

const status = computed(() => displayStatus(props.meta))
const completeMetaText = computed(() => metaText(props.meta))
</script>

<template>
  <article class="status-card" :class="`status-${status}`">
    <div class="card-heading">
      <span>{{ label }}</span>
      <el-tag :type="status === 'healthy' ? 'success' : status === 'error' ? 'danger' : status === 'warning' ? 'warning' : 'info'" effect="light" round>
        {{ statusLabel(status) }}
      </el-tag>
    </div>
    <strong class="card-value">{{ value }}</strong>
    <p class="card-detail">{{ detail || meta.warning || '暂无补充信息' }}</p>
    <small class="card-meta" :title="completeMetaText">{{ completeMetaText }}</small>
  </article>
</template>
