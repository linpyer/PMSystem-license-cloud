const DEFAULT_ADMIN_BASE_PATH = '/admin/'

type LocationSnapshot = Pick<Location, 'pathname' | 'search' | 'hash'>

let authenticationExpiredHandler: (() => void) | undefined

export const ADMIN_BASE_PATH = normalizeBasePath(
  import.meta.env.BASE_URL || DEFAULT_ADMIN_BASE_PATH,
)

export function normalizeBasePath(basePath: string): string {
  const normalized = `/${basePath.trim().replace(/^\/+|\/+$/g, '')}/`
  return normalized === '//' ? '/' : normalized
}

export function safeInternalRedirect(value: unknown): string | null {
  if (Array.isArray(value)) value = value[0]
  if (typeof value !== 'string') return null

  const candidate = value.trim()
  if (!candidate.startsWith('/') || candidate.startsWith('//') || candidate.includes('\\')) {
    return null
  }

  try {
    const parsed = new URL(candidate, 'https://ddrec-admin.invalid')
    if (parsed.origin !== 'https://ddrec-admin.invalid') return null
    const decodedPath = decodeURIComponent(parsed.pathname)
    if (decodedPath.startsWith('//') || decodedPath.includes('\\')) return null
    return `${parsed.pathname}${parsed.search}${parsed.hash}`
  } catch {
    return null
  }
}

export function resolvePostLoginRedirect(value: unknown): string {
  const target = safeInternalRedirect(value)
  return target && !['/login', '/totp'].includes(target.split(/[?#]/, 1)[0]) ? target : '/'
}

export function browserPathForRoute(
  routePath: string,
  basePath: string = ADMIN_BASE_PATH,
): string {
  const base = normalizeBasePath(basePath)
  const internalPath = safeInternalRedirect(routePath) || '/'
  return internalPath === '/' ? base : `${base}${internalPath.slice(1)}`
}

export function currentInternalRoute(
  current: LocationSnapshot,
  basePath: string = ADMIN_BASE_PATH,
): string {
  const base = normalizeBasePath(basePath)
  const baseWithoutSlash = base === '/' ? '/' : base.slice(0, -1)
  let internalPath: string

  if (current.pathname === base || current.pathname === baseWithoutSlash) {
    internalPath = '/'
  } else if (current.pathname.startsWith(base)) {
    internalPath = `/${current.pathname.slice(base.length)}`
  } else {
    return '/'
  }

  return safeInternalRedirect(`${internalPath}${current.search}${current.hash}`) || '/'
}

export function isCredentialSubmission(requestUrl: unknown): boolean {
  if (typeof requestUrl !== 'string') return false
  try {
    const path = new URL(requestUrl, 'https://ddrec-admin.invalid').pathname
    return ['/api/v1/admin/auth/login', '/api/v1/admin/auth/totp/verify'].some(
      (endpoint) => path === endpoint || path.endsWith(endpoint.replace('/api/v1', '')),
    )
  } catch {
    return false
  }
}

export function unauthorizedRedirectTarget(
  requestUrl: unknown,
  current: LocationSnapshot,
  basePath: string = ADMIN_BASE_PATH,
): string | null {
  if (isCredentialSubmission(requestUrl)) return null

  const loginPath = browserPathForRoute('/login', basePath)
  const currentRoute = currentInternalRoute(current, basePath)
  if (currentRoute.split(/[?#]/, 1)[0] === '/login') return null

  const redirect = resolvePostLoginRedirect(currentRoute)
  return `${loginPath}?redirect=${encodeURIComponent(redirect)}`
}

export function setAuthenticationExpiredHandler(handler: () => void): void {
  authenticationExpiredHandler = handler
}

export function handleUnauthorized(requestUrl: unknown): boolean {
  const target = unauthorizedRedirectTarget(requestUrl, window.location)
  if (!target) return false

  authenticationExpiredHandler?.()
  window.location.assign(target)
  return true
}
