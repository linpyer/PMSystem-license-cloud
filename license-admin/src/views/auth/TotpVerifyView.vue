<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { apiErrorMessage } from '@/utils/errors'
const code = ref(''); const loading = ref(false); const auth = useAuthStore(); const router = useRouter()
async function submit(){ if(!/^\d{6}$/.test(code.value)) return ElMessage.warning('请输入6位动态验证码'); loading.value=true; try{await auth.verifyTotp(code.value);await router.push('/')}catch(error){ElMessage.error(apiErrorMessage(error));code.value=''}finally{loading.value=false}}
</script>
<template><main class="auth-page"><section class="auth-panel"><h1>动态验证码</h1><p>请输入身份验证器当前显示的 6 位数字。</p><el-input v-model="code" maxlength="6" inputmode="numeric" size="large" class="code" @keyup.enter="submit"/><el-button type="primary" :loading="loading" class="submit" @click="submit">登录管理后台</el-button><el-button link @click="$router.push('/login')">返回密码登录</el-button></section></main></template>
<style scoped>.auth-page{min-height:100vh;display:grid;place-items:center}.auth-panel{width:410px;padding:32px;text-align:center;background:var(--surface);border:1px solid var(--border);border-radius:8px}.auth-panel h1{margin:0 0 8px;font-size:21px}.auth-panel p{color:var(--text-muted);font-size:13px}.code{margin:20px 0 16px}.code :deep(input){text-align:center;font:600 24px "Cascadia Mono",monospace;letter-spacing:8px}.submit{width:100%;height:40px;margin-bottom:10px}</style>
