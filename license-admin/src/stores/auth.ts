import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { authApi } from '@/api/auth'
import type { AdminUser } from '@/types'
import { setAuthenticationExpiredHandler } from '@/utils/auth-navigation'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AdminUser | null>(null)
  const challenge = ref('')
  const initialized = ref(false)
  const authenticated = computed(() => Boolean(user.value))

  function clearAuthentication() {
    user.value = null
    challenge.value = ''
    initialized.value = true
  }

  setAuthenticationExpiredHandler(clearAuthentication)

  async function restore() {
    try { user.value = (await authApi.me()).data.user } catch { user.value = null }
    initialized.value = true
  }
  async function login(username: string, password: string) {
    challenge.value = (await authApi.login(username, password)).data.challenge
  }
  async function verifyTotp(code: string) {
    const response = await authApi.verifyTotp(challenge.value, code)
    user.value = response.data.user
    challenge.value = ''
  }
  async function logout() {
    await authApi.logout()
    clearAuthentication()
  }
  return { user, challenge, initialized, authenticated, restore, login, verifyTotp, logout }
})
