import { api } from './client'
import type { Paged, TrialItem } from '@/types'

export const trialsApi = {
  list: (params: Record<string, unknown>) => api.get<Paged<TrialItem>>('/admin/trials', { params }),
  detail: (id: string) => api.get<{ trial: TrialItem }>(`/admin/trials/${id}`),
  disable: (id: string, reason: string) => api.post(`/admin/trials/${id}/disable`, { reason }),
  reset: (id: string, reason: string) => api.post(`/admin/trials/${id}/reset`, { reason }),
  extend: (id: string, days: number, reason: string) => api.post(`/admin/trials/${id}/extend`, { days, reason }),
  delete: (id: string, reason: string) => api.post(`/admin/trials/${id}/delete`, { reason, confirmation: 'DELETE' }),
}
