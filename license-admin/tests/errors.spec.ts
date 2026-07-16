import { describe, expect, it } from 'vitest'
import { apiErrorMessage } from '@/utils/errors'

function error(status?: number, code?: string, message?: string) {
  return status ? { response: { status, data: { error: { code, message } } } } : {}
}

describe('API错误映射', () => {
  it('映射登录凭据错误', () => expect(apiErrorMessage(error(401, 'ADMIN_INVALID_CREDENTIALS'))).toContain('不正确'))
  it('映射无权限错误', () => expect(apiErrorMessage(error(403, 'ADMIN_FORBIDDEN'))).toContain('无权'))
  it('映射限流', () => expect(apiErrorMessage(error(429))).toContain('频繁'))
  it('映射服务器错误', () => expect(apiErrorMessage(error(500))).toContain('暂时异常'))
  it('映射断网', () => expect(apiErrorMessage(error())).toContain('网络连接失败'))
})
