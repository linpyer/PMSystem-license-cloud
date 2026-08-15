import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AdminLayout from '@/layouts/AdminLayout.vue'
import { resolvePostLoginRedirect, safeInternalRedirect } from '@/utils/auth-navigation'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/auth/LoginView.vue'), meta: { public: true } },
    { path: '/totp', name: 'totp', component: () => import('@/views/auth/TotpVerifyView.vue'), meta: { public: true } },
    {
      path: '/', component: AdminLayout,
      children: [
        { path: '', name: 'dashboard', component: () => import('@/views/DashboardView.vue') },
        { path: 'licenses', name: 'licenses', component: () => import('@/views/licenses/LicenseListView.vue') },
        { path: 'licenses/create', name: 'license-create', component: () => import('@/views/licenses/LicenseCreateView.vue'), meta: { roles: ['OWNER', 'ADMIN'] } },
        { path: 'licenses/:id', name: 'license-detail', component: () => import('@/views/licenses/LicenseDetailView.vue') },
        { path: 'trials', name: 'trials', component: () => import('@/views/trials/TrialManagementView.vue') },
        { path: 'trials/:id', name: 'trial-detail', component: () => import('@/views/trials/TrialDetailView.vue') },
        { path: 'license-events', name: 'license-events', component: () => import('@/views/audit/LicenseEventsView.vue') },
        { path: 'admin-audit', name: 'admin-audit', component: () => import('@/views/audit/AdminAuditView.vue') },
        { path: 'version-policy', name: 'version-policy', component: () => import('@/views/versions/VersionPolicyView.vue') },
        { path: 'client-updates', name: 'client-updates', component: () => import('@/views/updates/ClientReleaseView.vue') },
        { path: 'account', name: 'account', component: () => import('@/views/account/AccountSecurityView.vue') },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.initialized) await auth.restore()
  if (!to.meta.public && !auth.authenticated) {
    return { name: 'login', query: { redirect: safeInternalRedirect(to.fullPath) || '/' } }
  }
  const roles = to.meta.roles as string[] | undefined
  if (roles && auth.user && !roles.includes(auth.user.role)) return { name: 'dashboard' }
  if (to.name === 'totp' && !auth.challenge) {
    return { name: 'login', query: { redirect: resolvePostLoginRedirect(to.query.redirect) } }
  }
  if (to.meta.public && auth.authenticated) return resolvePostLoginRedirect(to.query.redirect)
})

export default router
