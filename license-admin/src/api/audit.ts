import { api } from './client'
export const auditApi = {
  licenseEvents: (params: Record<string, unknown>) => api.get('/admin/license-events', { params }),
  adminEvents: (params: Record<string, unknown>) => api.get('/admin/audit-events', { params }),
}
