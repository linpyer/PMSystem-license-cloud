import { api } from './client'
export interface DashboardRecent {
  createdLicenses: Array<{ id: string; maskedCode: string; customerName?: string; status: string; createdAt: string }>
  recentActivations: Array<{ id: string; maskedCode: string; customerName?: string; activatedAt: string }>
  adminOperations: Array<{ id: string; action: string; result: string; targetId?: string; createdAt: string }>
  abnormalEvents: Array<{ id: string; eventType: string; result: string; licenseId?: string; createdAt: string }>
}
export const dashboardApi = { summary: () => api.get<{ summary: Record<string, number>; recent: DashboardRecent }>('/admin/dashboard/summary') }
