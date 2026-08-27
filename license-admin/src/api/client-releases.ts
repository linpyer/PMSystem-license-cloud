import { api } from './client'

export type ClientRelease = {
  id: string
  product: 'DDREC' | 'iVRec'
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

// local/dev remain response-only so historical rows can still be displayed.
export type ClientReleaseDraft = Omit<ClientRelease, 'id' | 'status' | 'createdAt' | 'releaseNotes' | 'environment' | 'channel' | 'product'> & {
  product: 'iVRec'
  environment: 'production'
  channel: 'stable'
  releaseNotes?: string
}

export const clientReleasesApi = {
  list: (page = 1, pageSize = 50) => api.get('/admin/client-releases', { params: { page, pageSize } }),
  create: (data: ClientReleaseDraft) => api.post('/admin/client-releases', data),
  edit: (id: string, data: { title: string; releaseNotes: string }) => api.patch(`/admin/client-releases/${id}`, data),
  publish: (id: string) => api.post(`/admin/client-releases/${id}/publish`),
  withdraw: (id: string) => api.post(`/admin/client-releases/${id}/withdraw`),
}
