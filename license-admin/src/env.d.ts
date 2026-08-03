/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_APP_ENVIRONMENT?: string
  readonly VITE_APP_ENV_LABEL?: string
  readonly VITE_APP_TITLE?: string
  readonly VITE_BASE_PATH?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
