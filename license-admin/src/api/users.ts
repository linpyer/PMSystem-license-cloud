import { api } from './client'
import type { AdminRole, AdminUser } from '@/types'

export interface AdminEnrollment {
  user: AdminUser
  totpSecret: string
  provisioningUri: string
  enrollmentVisibleOnce: boolean
}

export const usersApi = {
  list: () => api.get<{ items: AdminUser[] }>('/admin/users'),
  create: (payload: { username: string; displayName: string; role: AdminRole; password: string }) =>
    api.post<AdminEnrollment>('/admin/users', payload),
  disable: (id: string, reason: string) =>
    api.post<{ user: AdminUser }>(`/admin/users/${id}/disable`, { reason }),
  enable: (id: string, reason: string) =>
    api.post<{ user: AdminUser }>(`/admin/users/${id}/enable`, { reason }),
}
