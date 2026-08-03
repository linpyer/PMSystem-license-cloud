import { describe, expect, it } from 'vitest'
import { resolveEnvironmentLabel } from '@/config/environment'

describe('environment label', () => {
  it('maps production builds to the production label', () => {
    expect(resolveEnvironmentLabel('production')).toBe('生产环境')
  })

  it('keeps development and test builds explicit', () => {
    expect(resolveEnvironmentLabel('development')).toBe('开发环境')
    expect(resolveEnvironmentLabel('test')).toBe('测试环境')
  })

  it('uses an explicitly configured deployment label', () => {
    expect(resolveEnvironmentLabel('production', '生产环境')).toBe('生产环境')
  })
})
