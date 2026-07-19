<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { apiErrorMessage } from '@/utils/errors'
import { resolvePostLoginRedirect } from '@/utils/auth-navigation'

const route = useRoute(); const router = useRouter(); const auth = useAuthStore(); const loading = ref(false)
const form = reactive({ username: '', password: '' })
async function submit() {
  if (!form.username || !form.password) return ElMessage.warning('请输入用户名和密码')
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    await router.push({ name: 'totp', query: { redirect: resolvePostLoginRedirect(route.query.redirect) } })
  }
  catch (error) { ElMessage.error(apiErrorMessage(error)) } finally { loading.value = false }
}
</script>
<template>
  <main class="auth-page"><section class="auth-panel"><div class="auth-brand"><div class="mark">PM</div><div><h1>PMSystem 授权管理</h1><p>管理员安全登录</p></div></div><el-form label-position="top" @submit.prevent="submit"><el-form-item label="用户名"><el-input v-model="form.username" autocomplete="username" /></el-form-item><el-form-item label="密码"><el-input v-model="form.password" type="password" show-password autocomplete="current-password" @keyup.enter="submit" /></el-form-item><el-button type="primary" :loading="loading" class="submit" @click="submit">继续验证</el-button></el-form><p class="security">登录后仍需输入动态验证码。连续失败将临时锁定账号。</p></section></main>
</template>
<style scoped>.auth-page{min-height:100vh;display:grid;place-items:center;background:var(--app-bg)}.auth-panel{width:410px;padding:32px;background:var(--surface);border:1px solid var(--border);border-radius:8px}.auth-brand{display:flex;gap:14px;align-items:center;margin-bottom:28px}.mark{width:44px;height:44px;display:grid;place-items:center;background:var(--accent);color:white;border-radius:7px;font-weight:800}.auth-brand h1{font-size:20px;margin:0}.auth-brand p,.security{color:var(--text-muted);font-size:13px}.auth-brand p{margin:4px 0 0}.submit{width:100%;height:40px}.security{margin:18px 0 0;line-height:1.6}</style>
