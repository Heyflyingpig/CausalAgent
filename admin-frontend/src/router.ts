import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory('/admin/'),
  routes: [
    { path: '/', redirect: '/database' },
    {
      path: '/database',
      component: () => import('./views/DatabaseDashboardView.vue'),
    },
    {
      path: '/database/settings',
      component: () => import('./views/MonitorSettingsView.vue'),
    },
    { path: '/:pathMatch(.*)*', redirect: '/database' },
  ],
})
