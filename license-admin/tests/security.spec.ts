import { describe, expect, it } from 'vitest'
import { readCookie } from '@/utils/security'
import { formatUtc } from '@/utils/date'

describe('前端安全辅助', () => {
  it('读取CSRF Cookie而不存储会话令牌', () => { document.cookie='pms_admin_csrf=test-csrf; path=/';expect(readCookie('pms_admin_csrf')).toBe('test-csrf') })
  it('缺失Cookie返回undefined', () => expect(readCookie('missing')).toBeUndefined())
  it('UTC时间可本地化展示', () => expect(formatUtc('2026-07-15T00:00:00Z')).not.toBe('-'))
  it('无时间显示占位符', () => expect(formatUtc(null)).toBe('-'))
})
