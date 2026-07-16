import { api } from './client'

export const licensesApi = {
  list: (params: Record<string, unknown>) => api.get('/admin/licenses', { params }),
  detail: (id: string) => api.get(`/admin/licenses/${id}`),
  create: (data: Record<string, unknown>) => api.post('/admin/licenses', data),
  batch: (data: Record<string, unknown>) => api.post('/admin/licenses/batch', data),
  update: (id: string, data: Record<string, unknown>) => api.patch(`/admin/licenses/${id}`, data),
  disable: (id: string, reason: string) => api.post(`/admin/licenses/${id}/disable`, { reason }),
  enable: (id: string, reason: string) => api.post(`/admin/licenses/${id}/enable`, { reason }),
  revoke: (id: string, reason: string) => api.post(`/admin/licenses/${id}/revoke`, { reason }),
  deactivateBinding: (id: string, reason: string) => api.post(`/admin/bindings/${id}/deactivate`, { reason }),
}
