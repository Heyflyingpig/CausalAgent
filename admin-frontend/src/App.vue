<script setup lang="ts">
import {
  ClipboardCheck,
  Database,
  FolderOpen,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageCircle,
  MessagesSquare,
  PanelLeftClose,
  PanelLeftOpen,
  TimerReset,
  UsersRound,
  Workflow,
  X,
} from '@lucide/vue'
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { adminApi, loadIdentity } from './api'

const route = useRoute()
const username = ref('正在确认…')
const identityReady = ref(false)
const collapsed = ref(false)
const mobileOpen = ref(false)
const SIDEBAR_STORAGE_KEY = 'causalagent.admin.sidebar.collapsed'
const BRAND_LOGO_URL = '/api/admin/brand/logo'
const FLASK_ORIGIN = import.meta.env.VITE_FLASK_ORIGIN?.replace(/\/$/, '') || ''
const CHAT_URL = `${FLASK_ORIGIN}/`

const navigation = [
  {
    label: '业务数据',
    items: [
      { to: '/overview', label: '业务概览', icon: LayoutDashboard },
      { to: '/users', label: '用户与权限管理', icon: UsersRound },
      { to: '/sessions', label: '会话与内容管理', icon: MessagesSquare },
      { to: '/jobs', label: '分析任务管理', icon: Workflow },
      { to: '/files', label: '对话文件管理', icon: FolderOpen },
    ],
  },
  {
    label: '数据库管理',
    items: [
      { to: '/database', label: '数据库看板', icon: Database },
      { to: '/database/settings', label: '自动采集时间配置', icon: TimerReset },
      { to: '/database/audit', label: 'Schema与审计', icon: ClipboardCheck },
    ],
  },
]

/** 从浏览器恢复桌面侧栏偏好并确认实时管理员身份。 */
onMounted(async () => {
  collapsed.value = window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === 'true'
  try {
    const identity = await loadIdentity()
    username.value = identity.username || '管理员'
    identityReady.value = true
  } catch {
    identityReady.value = false
  }
})

/** 切换桌面侧栏并持久化到当前浏览器。 */
function toggleSidebar(): void {
  collapsed.value = !collapsed.value
  window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(collapsed.value))
}

/** 判断当前导航项是否精确匹配当前 Vue 路由。 */
function isActive(path: string): boolean {
  return route.path === path
}

watch(
  () => route.path,
  () => {
    mobileOpen.value = false
  },
)
</script>

<template>
  <div
    class="admin-shell"
    :class="{ 'sidebar-collapsed': collapsed }"
  >
    <header class="mobile-header">
      <button
        class="mobile-menu-button"
        type="button"
        aria-label="打开后台导航"
        :aria-expanded="mobileOpen"
        @click="mobileOpen = true"
      >
        <Menu :size="20" :stroke-width="2" aria-hidden="true" />
      </button>
      <div class="mobile-brand-icon" aria-hidden="true">
        <img :src="BRAND_LOGO_URL" alt="">
      </div>
      <strong>CausalAgent 管理后台</strong>
    </header>

    <button
      v-if="mobileOpen"
      class="sidebar-backdrop"
      type="button"
      aria-label="关闭后台导航"
      @click="mobileOpen = false"
    />

    <aside
      class="admin-sidebar"
      :class="{ collapsed, 'mobile-open': mobileOpen }"
      aria-label="后台导航"
    >
      <div class="brand-block">
        <div class="brand-image-wrap" :class="{ cropped: collapsed }">
          <img :src="BRAND_LOGO_URL" alt="CausalAgent">
        </div>
        <button
          class="sidebar-toggle"
          type="button"
          :aria-label="collapsed ? '展开左侧导航' : '收起左侧导航'"
          :aria-expanded="!collapsed"
          @click="toggleSidebar"
        >
          <PanelLeftOpen v-if="collapsed" :size="16" :stroke-width="2" aria-hidden="true" />
          <PanelLeftClose v-else :size="16" :stroke-width="2" aria-hidden="true" />
        </button>
        <button
          class="mobile-close-button"
          type="button"
          aria-label="关闭后台导航"
          @click="mobileOpen = false"
        >
          <X :size="20" :stroke-width="2" aria-hidden="true" />
        </button>
      </div>

      <nav class="admin-nav">
        <section v-for="group in navigation" :key="group.label" class="nav-group">
          <p class="nav-label">{{ group.label }}</p>
          <el-tooltip
            v-for="item in group.items"
            :key="item.to"
            :content="item.label"
            placement="right"
            :disabled="!collapsed"
          >
            <router-link
              class="nav-item"
              :class="{ active: isActive(item.to) }"
              :to="item.to"
            >
              <span class="nav-icon" aria-hidden="true">
                <component :is="item.icon" :size="18" :stroke-width="1.8" />
              </span>
              <span class="nav-text">{{ item.label }}</span>
            </router-link>
          </el-tooltip>
        </section>
      </nav>

      <div class="sidebar-footer">
        <div class="admin-identity">
          <span class="identity-label">当前管理员</span>
          <strong>{{ username }}</strong>
        </div>
        <el-tooltip content="进入聊天" placement="right" :disabled="!collapsed">
          <el-button
            class="chat-entry-button"
            tag="a"
            type="primary"
            :href="CHAT_URL"
            :disabled="!identityReady"
          >
            <span class="chat-entry-icon" aria-hidden="true">
              <MessageCircle :size="18" :stroke-width="1.8" />
            </span>
            <span class="chat-entry-text">进入聊天</span>
          </el-button>
        </el-tooltip>
        <el-tooltip content="退出登录" placement="right" :disabled="!collapsed">
          <el-button
            class="logout-button"
            type="success"
            :disabled="!identityReady"
            @click="adminApi.logout"
          >
            <span class="logout-icon" aria-hidden="true">
              <LogOut :size="18" :stroke-width="1.8" />
            </span>
            <span class="logout-text">退出登录</span>
          </el-button>
        </el-tooltip>
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
