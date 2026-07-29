<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { adminApi, loadIdentity } from './api'

const route = useRoute()
const username = ref('正在确认…')
const identityReady = ref(false)

onMounted(async () => {
  try {
    const identity = await loadIdentity()
    username.value = identity.username || '管理员'
    identityReady.value = true
  } catch {
    identityReady.value = false
  }
})
</script>

<template>
  <div class="admin-shell">
    <aside class="admin-sidebar" aria-label="后台导航">
      <div class="brand-block">
        <div class="brand-mark">CA</div>
        <div>
          <strong>CausalAgent</strong>
          <span>管理后台</span>
        </div>
      </div>

      <nav class="admin-nav">
        <p class="nav-label">数据库管理</p>
        <router-link class="nav-item" :class="{ active: route.path === '/database' }" to="/database">
          <span class="nav-dot" />
          数据库看板
        </router-link>
        <router-link class="nav-item" :class="{ active: route.path === '/database/settings' }" to="/database/settings">
          <span class="nav-dot" />
          采集配置
        </router-link>
        <p class="nav-note">当前阶段仅开放数据库看板与监控配置。</p>
      </nav>

      <div class="sidebar-footer">
        <div class="admin-identity">
          <span class="identity-label">当前管理员</span>
          <strong>{{ username }}</strong>
        </div>
        <el-button class="logout-button" type="success" :disabled="!identityReady" @click="adminApi.logout">
          退出登录
        </el-button>
      </div>
    </aside>

    <main class="admin-main">
      <router-view v-if="identityReady" />
      <div v-else class="page-loading">
        <el-skeleton :rows="8" animated />
      </div>
    </main>
  </div>
</template>
