import { api } from './client'
export const versionsApi = {
  get: () => api.get('/admin/version-policy'),
  save: (data: Record<string, unknown>) => api.put('/admin/version-policy', data),
}
