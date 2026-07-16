import axios from 'axios'
import { readCookie } from '@/utils/security'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  withCredentials: true,
  timeout: 10000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  if (config.method && !['get', 'head', 'options'].includes(config.method)) {
    const csrf = readCookie('pms_admin_csrf')
    if (csrf) config.headers['X-CSRF-Token'] = decodeURIComponent(csrf)
  }
  config.headers['X-Request-ID'] = crypto.randomUUID()
  return config
})

api.interceptors.response.use(undefined, async (error) => {
  if (error.response?.status === 401 && !location.pathname.startsWith('/login')) {
    location.assign('/login')
  }
  return Promise.reject(error)
})
