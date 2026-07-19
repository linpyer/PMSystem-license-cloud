import { describe, expect, it } from 'vitest'
import type { TrialItem } from '@/types'
import { canExtendTrial, extensionPreview, trialPermissions } from '@/utils/trials'

const trial = (status: TrialItem['status'], expiresAt = '2026-07-20T00:00:00Z'): TrialItem => ({
  trialId: 'trial-1',
  device: '12345678...',
  fingerprintVersion: 'win-v1',
  status,
  startedAt: '2026-07-13T00:00:00Z',
  expiresAt,
  lastSeenAt: '2026-07-18T00:00:00Z',
  appVersion: '1.0.5',
  resetCount: 0,
  extensionCount: 0,
  totalExtendedDays: 0,
})

describe('试用管理权限', () => {
  it('OWNER 可以延长、重置和删除', () => {
    expect(trialPermissions('OWNER')).toEqual({ canExtend: true, canReset: true, canDelete: true })
  })

  it('ADMIN 只能延长', () => {
    expect(trialPermissions('ADMIN')).toEqual({ canExtend: true, canReset: false, canDelete: false })
  })

  it('AUDITOR 只读', () => {
    expect(trialPermissions('AUDITOR')).toEqual({ canExtend: false, canReset: false, canDelete: false })
  })
})

describe('试用延长预览', () => {
  it('ACTIVE 从当前截止时间继续增加', () => {
    expect(extensionPreview(trial('ACTIVE'), 2, new Date('2026-07-18T00:00:00Z'))?.toISOString())
      .toBe('2026-07-22T00:00:00.000Z')
  })

  it('EXPIRED 从服务器当前时间语义开始预览', () => {
    expect(extensionPreview(trial('EXPIRED'), 2, new Date('2026-07-18T00:00:00Z'))?.toISOString())
      .toBe('2026-07-20T00:00:00.000Z')
  })

  it('DISABLED、CONVERTED 和 DELETED 不能直接延长', () => {
    expect(canExtendTrial(trial('DISABLED'))).toBe(false)
    expect(canExtendTrial(trial('CONVERTED'))).toBe(false)
    expect(canExtendTrial({ ...trial('DELETED'), deletedAt: '2026-07-18T00:00:00Z' })).toBe(false)
  })

  it('拒绝范围外和非整数天数', () => {
    expect(extensionPreview(trial('ACTIVE'), 0)).toBeNull()
    expect(extensionPreview(trial('ACTIVE'), 366)).toBeNull()
    expect(extensionPreview(trial('ACTIVE'), 1.5)).toBeNull()
  })
})
