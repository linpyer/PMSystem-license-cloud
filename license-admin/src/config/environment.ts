export function resolveEnvironmentLabel(environment: string, configuredLabel = ''): string {
  const explicit = configuredLabel.trim()
  if (explicit) return explicit

  switch (environment.trim().toLowerCase()) {
    case 'production':
      return '生产环境'
    case 'development':
      return '开发环境'
    case 'test':
      return '测试环境'
    default:
      return '环境未配置'
  }
}

export const appEnvironment = import.meta.env.VITE_APP_ENVIRONMENT || import.meta.env.MODE
export const appVersion = import.meta.env.VITE_APP_VERSION || '1.4.0'
export const environmentLabel = import.meta.env.PROD
  ? (import.meta.env.VITE_APP_ENV_LABEL || '环境未配置')
  : resolveEnvironmentLabel(appEnvironment, import.meta.env.VITE_APP_ENV_LABEL)
