import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

function sanitizeProductionDependencyFallbacks(mode: string) {
  return {
    name: 'sanitize-production-dependency-fallbacks',
    transform(code: string, id: string) {
      if (mode !== 'production' || !id.includes('node_modules')) return null
      const sanitized = code
        .replaceAll('"http://localhost"', '"https://license.aixcc.top"')
        .replaceAll("'http://localhost'", "'https://license.aixcc.top'")
        .replaceAll('localhost', 'license.aixcc.top')
      return sanitized === code ? null : { code: sanitized, map: null }
    },
  }
}

export default defineConfig(({ mode }) => ({
  base: process.env.VITE_BASE_PATH || '/admin/',
  plugins: [vue(), sanitizeProductionDependencyFallbacks(mode)],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: false } },
  },
  build: { outDir: 'dist', sourcemap: false },
}))
