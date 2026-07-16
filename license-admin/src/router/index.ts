import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AdminLayout from '@/layouts/AdminLayout.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('@/views/auth/LoginView.vue'), meta: { public: true } },
    { path: '/totp', component: () => import('@/views/auth/TotpVerifyView.vue'), meta: { public: true } },
    {
      path: '/', component: AdminLayout,
      children: [
        { path: '', name: 'dashboard', component: () => import('@/views/DashboardView.vue') },
        { path: 'licenses', name: 'licenses', component: () => import('@/views/licenses/LicenseListView.vue') },
        { path: 'licenses/create', name: 'license-create', component: () => import('@/views/licenses/LicenseCreateView.vue'), meta: { roles: ['OWNER', 'ADMIN'] } },
        { path: 'licenses/:id', name: 'license-detail', component: () => import('@/views/licenses/LicenseDetailView.vue') },
        { path: 'license-events', name: 'license-events', component: () => import('@/views/audit/LicenseEventsView.vue') },
        { path: 'admin-audit', name: 'admin-audit', component: () => import('@/views/audit/AdminAuditView.vue') },
        { path: 'version-policy', name: 'version-policy', component: () => import('@/views/versions/VersionPolicyView.vue') },
        { path: 'account', name: 'account', component: () => import('@/views/account/AccountSecurityView.vue') },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.initialized) await auth.restore()
  if (!to.meta.public && !auth.authenticated) return '/login'
  const roles = to.meta.roles as string[] | undefined
  if (roles && auth.user && !roles.includes(auth.user.role)) return '/'
  if (to.path === '/totp' && !auth.challenge) return '/login'
  if (to.meta.public && auth.authenticated) return '/'
})

export default router
