import type { AdminRole, TrialItem } from '@/types'

export type TrialAction = 'extend' | 'reset' | 'delete'

export function trialPermissions(role?: AdminRole) {
  return {
    canExtend: role === 'OWNER' || role === 'ADMIN',
    canReset: role === 'OWNER',
    canDelete: role === 'OWNER',
  }
}

export function canExtendTrial(trial: TrialItem): boolean {
  return !trial.deletedAt && (trial.status === 'ACTIVE' || trial.status === 'EXPIRED')
}

export function extensionPreview(trial: TrialItem, days: number, now = new Date()): Date | null {
  if (!Number.isInteger(days) || days < 1 || days > 365 || !canExtendTrial(trial)) return null
  const currentExpiry = new Date(trial.expiresAt)
  const base = trial.status === 'ACTIVE' && currentExpiry > now ? currentExpiry : now
  return new Date(base.getTime() + days * 86_400_000)
}
