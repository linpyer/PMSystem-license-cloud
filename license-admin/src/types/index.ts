export type AdminRole = 'OWNER' | 'ADMIN' | 'AUDITOR'
export interface AdminUser {
  id: string
  username: string
  displayName: string
  role: AdminRole
  status?: 'ACTIVE' | 'DISABLED'
  lastLoginAt?: string | null
  createdAt?: string | null
}
export interface ApiErrorBody { success: false; traceId?: string; error: { code: string; message: string; retryable: boolean } }
export interface LicenseItem {
  licenseId: string; maskedCode: string; licenseType: string; status: string;
  customerName?: string; customerContact?: string; activatedAt?: string; expiresAt?: string;
  createdAt: string; bindingId?: string; device?: string; lastVerifiedAt?: string;
}
export interface Paged<T> { items: T[]; page: number; pageSize: number; total: number }
export interface TrialItem {
  trialId: string; device: string; fingerprintVersion: string; deviceName?: string | null;
  status: 'ACTIVE' | 'EXPIRED' | 'CONVERTED' | 'DISABLED' | 'DELETED'; startedAt: string; expiresAt: string;
  lastSeenAt: string; convertedAt?: string | null; convertedLicenseId?: string | null;
  firstIp?: string | null; lastIp?: string | null; appVersion: string; osVersion?: string | null;
  resetCount: number; lastResetAt?: string | null; lastResetReason?: string | null;
  extensionCount: number; totalExtendedDays: number; lastExtendedAt?: string | null;
  lastExtensionDays?: number | null; lastExtensionReason?: string | null;
  deletedAt?: string | null; deleteReason?: string | null;
}
