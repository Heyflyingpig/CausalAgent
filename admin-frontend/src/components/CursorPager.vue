<script setup lang="ts">
defineProps<{
  canPrevious: boolean
  hasMore: boolean
  loading?: boolean
}>()

defineEmits<{
  previous: []
  next: []
}>()
</script>

<template>
  <div class="cursor-pager">
    <span>每页最多 20 条，使用稳定游标翻页</span>
    <div>
      <el-button :disabled="!canPrevious || loading" @click="$emit('previous')">
        上一页
      </el-button>
      <el-button type="primary" plain :disabled="!hasMore || loading" @click="$emit('next')">
        下一页
      </el-button>
    </div>
  </div>
</template>
