import type { AxiosError } from 'axios'
import type { ApiErrorBody } from '@/types'

const messages: Record<string, string> = {
  ADMIN_INVALID_CREDENTIALS: '用户名、密码或动态验证码不正确。',
  ADMIN_ACCOUNT_LOCKED: '登录失败次数过多，请稍后再试。',
  ADMIN_FORBIDDEN: '当前账号无权执行此操作。',
  CSRF_FAILED: '安全上下文已失效，请重新登录。',
  INVALID_STATE: '当前状态不允许执行此操作。',
}

export function apiErrorMessage(error: unknown): string {
  const axiosError = error as AxiosError<ApiErrorBody>
  const code = axiosError.response?.data?.error?.code
  if (code && messages[code]) return messages[code]
  if (!axiosError.response) return '网络连接失败，请检查授权服务。'
  if (axiosError.response.status === 429) return '操作过于频繁，请稍后再试。'
  if (axiosError.response.status >= 500) return '服务暂时异常，请稍后重试。'
  return axiosError.response.data?.error?.message || '请求未能完成。'
}
