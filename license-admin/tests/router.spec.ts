import { beforeEach, describe, expect, it, vi } from 'vitest'

const auth = {
  initialized: true,
  authenticated: false,
  user: null as { role: string } | null,
  challenge: '',
  restore: vi.fn(),
}

vi.mock('@/stores/auth', () => ({ useAuthStore: () => auth }))

import router from '@/router'

describe('管理端路由守卫', () => {
  beforeEach(async () => {
    auth.initialized = true
    auth.authenticated = false
    auth.user = null
    auth.challenge = ''
    vi.clearAllMocks()
    await router.replace({ name: 'login' })
  })

  it('createWebHistory使用Vite的/admin/基址', () => {
    expect(router.options.history.base).toBe('/admin')
  })

  it('未登录访问管理页会进入登录路由并保留目标', async () => {
    await router.replace('/licenses?page=2')
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/licenses?page=2')
  })

  it('非法外部redirect不会在已登录后开放跳转', async () => {
    auth.authenticated = true
    auth.user = { role: 'OWNER' }
    await router.replace({ name: 'login', query: { redirect: 'https://evil.example' } })
    expect(router.currentRoute.value.name).toBe('dashboard')
  })
})
