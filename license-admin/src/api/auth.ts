import { api } from './client'

export const authApi = {
  login: (username: string, password: string) => api.post('/admin/auth/login', { username, password }),
  verifyTotp: (challenge: string, code: string) => api.post('/admin/auth/totp/verify', { challenge, code }),
  me: () => api.get('/admin/auth/me'),
  logout: () => api.post('/admin/auth/logout'),
  changePassword: (currentPassword: string, newPassword: string) =>
    api.post('/admin/auth/change-password', { currentPassword, newPassword }),
}
