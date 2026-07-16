import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

vi.mock('@/api/auth', () => ({ authApi: { login: vi.fn(), verifyTotp: vi.fn(), me: vi.fn(), logout: vi.fn() } }))

describe('管理员会话状态', () => {
  beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks() })
  it('密码登录只保存短期TOTP挑战', async () => { vi.mocked(authApi.login).mockResolvedValue({data:{challenge:'challenge'}} as never);const store=useAuthStore();await store.login('owner','password');expect(store.challenge).toBe('challenge');expect(store.authenticated).toBe(false) })
  it('TOTP成功后建立前端用户状态', async () => { vi.mocked(authApi.verifyTotp).mockResolvedValue({data:{user:{id:'1',username:'owner',displayName:'Owner',role:'OWNER'}}} as never);const store=useAuthStore();store.challenge='challenge';await store.verifyTotp('123456');expect(store.authenticated).toBe(true);expect(store.challenge).toBe('') })
  it('会话恢复失败时保持未登录', async () => { vi.mocked(authApi.me).mockRejectedValue(new Error('401'));const store=useAuthStore();await store.restore();expect(store.initialized).toBe(true);expect(store.user).toBeNull() })
  it('退出清空本地用户状态', async () => { vi.mocked(authApi.logout).mockResolvedValue({} as never);const store=useAuthStore();store.user={id:'1',username:'owner',displayName:'Owner',role:'OWNER'};await store.logout();expect(store.user).toBeNull() })
})
