import { api } from './client'

export type ClientRelease = {
  id: string
  product: 'DDREC'
  version: string
  buildNumber: number
  gitCommit: string
  edition: 'standard' | 'license'
  environment: 'local' | 'production'
  architecture: 'x64'
  channel: 'stable' | 'dev'
  title: string
  releaseNotes: string
  fileName: string
  downloadPath: string
  fileSize: number
  sha256: string
  signature: string
  mandatory: false
  status: 'draft' | 'published' | 'withdrawn'
  publishedAt: string
  createdAt: string
}

export type ClientReleaseDraft = Omit<ClientRelease, 'id' | 'status' | 'createdAt'>

export const clientReleasesApi = {
  list: (page = 1, pageSize = 50) => api.get('/admin/client-releases', { params: { page, pageSize } }),
  create: (data: ClientReleaseDraft) => api.post('/admin/client-releases', data),
  edit: (id: string, data: { title: string; releaseNotes: string }) => api.patch(`/admin/client-releases/${id}`, data),
  publish: (id: string) => api.post(`/admin/client-releases/${id}/publish`),
  withdraw: (id: string) => api.post(`/admin/client-releases/${id}/withdraw`),
}
