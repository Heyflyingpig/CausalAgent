import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory('/admin/'),
  routes: [
    { path: '/', redirect: '/database' },
    {
      path: '/overview',
      component: () => import('./views/BusinessOverviewView.vue'),
    },
    {
      path: '/users',
      component: () => import('./views/UsersView.vue'),
    },
    {
      path: '/sessions',
      component: () => import('./views/SessionsView.vue'),
    },
    {
      path: '/jobs',
      component: () => import('./views/JobsView.vue'),
    },
    {
      path: '/files',
      component: () => import('./views/FilesView.vue'),
    },
    {
      path: '/database',
      component: () => import('./views/DatabaseDashboardView.vue'),
    },
    {
      path: '/database/settings',
      component: () => import('./views/MonitorSettingsView.vue'),
    },
    {
      path: '/database/audit',
      component: () => import('./views/DatabaseAuditView.vue'),
    },
    { path: '/:pathMatch(.*)*', redirect: '/database' },
  ],
})
