import { ref } from 'vue'
import { defineStore } from 'pinia'

export type ThemeMode = 'light' | 'dark' | 'system'

export const useThemeStore = defineStore('theme', () => {
  const mode = ref<ThemeMode>('system')
  let media: MediaQueryList | undefined
  const apply = () => {
    const dark = mode.value === 'dark' || (mode.value === 'system' && media?.matches)
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
  }
  const initialize = () => {
    mode.value = (localStorage.getItem('pms-admin-theme') as ThemeMode) || 'system'
    media = matchMedia('(prefers-color-scheme: dark)')
    media.addEventListener('change', apply)
    apply()
  }
  const setMode = (value: ThemeMode) => {
    mode.value = value
    localStorage.setItem('pms-admin-theme', value)
    apply()
  }
  return { mode, initialize, setMode }
})
