import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useThemeStore } from '@/stores/theme'

describe('主题状态', () => {
  beforeEach(() => { localStorage.clear(); setActivePinia(createPinia()) })
  it('默认跟随系统', () => { const store=useThemeStore(); store.initialize(); expect(store.mode).toBe('system') })
  it('切换深色并持久化', () => { const store=useThemeStore(); store.initialize(); store.setMode('dark'); expect(document.documentElement.dataset.theme).toBe('dark'); expect(localStorage.getItem('pms-admin-theme')).toBe('dark') })
  it('切换浅色', () => { const store=useThemeStore(); store.initialize(); store.setMode('light'); expect(document.documentElement.dataset.theme).toBe('light') })
})
