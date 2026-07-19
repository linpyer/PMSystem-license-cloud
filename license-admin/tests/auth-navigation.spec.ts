import { describe, expect, it } from 'vitest'
import {
  ADMIN_BASE_PATH,
  browserPathForRoute,
  currentInternalRoute,
  isCredentialSubmission,
  resolvePostLoginRedirect,
  safeInternalRedirect,
  unauthorizedRedirectTarget,
} from '@/utils/auth-navigation'

const locationAt = (pathname: string, search = '', hash = '') => ({ pathname, search, hash })

describe('管理端认证导航', () => {
  it('使用Vite提供的/admin/基址', () => {
    expect(ADMIN_BASE_PATH).toBe('/admin/')
    expect(browserPathForRoute('/login')).toBe('/admin/login')
  })

  it('将管理端浏览器地址还原为Router内部地址', () => {
    expect(currentInternalRoute(locationAt('/admin/licenses', '?page=2'))).toBe('/licenses?page=2')
  })

  it('API返回401时跳转到基址内登录页并保留目标', () => {
    expect(unauthorizedRedirectTarget('/licenses', locationAt('/admin/licenses')))
      .toBe('/admin/login?redirect=%2Flicenses')
  })

  it('已在登录页时401不会循环跳转', () => {
    expect(unauthorizedRedirectTarget('/admin/auth/me', locationAt('/admin/login'))).toBeNull()
  })

  it('密码错误不会触发全页登录跳转', () => {
    expect(isCredentialSubmission('/admin/auth/login')).toBe(true)
    expect(unauthorizedRedirectTarget('/admin/auth/login', locationAt('/admin/login'))).toBeNull()
  })

  it('TOTP错误不会跳出登录流程', () => {
    expect(isCredentialSubmission('/admin/auth/totp/verify')).toBe(true)
    expect(unauthorizedRedirectTarget('/admin/auth/totp/verify', locationAt('/admin/totp'))).toBeNull()
  })

  it('登录成功后返回原管理端页面', () => {
    expect(resolvePostLoginRedirect('/licenses/abc?tab=bindings')).toBe('/licenses/abc?tab=bindings')
  })

  it('无redirect时回到管理首页', () => {
    expect(resolvePostLoginRedirect(undefined)).toBe('/')
  })

  it('拒绝外部和协议相对redirect', () => {
    expect(safeInternalRedirect('https://evil.example')).toBeNull()
    expect(safeInternalRedirect('//evil.example/path')).toBeNull()
    expect(safeInternalRedirect('/%2F%2Fevil.example')).toBeNull()
  })

  it('退出后的命名登录路由解析在管理端基址内', () => {
    expect(browserPathForRoute('/login', '/admin/')).toBe('/admin/login')
  })
})
