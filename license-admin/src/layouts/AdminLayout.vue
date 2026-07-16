<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore, type ThemeMode } from '@/stores/theme'
import { DataAnalysis, Key, Plus, Document, Tickets, Setting, User, SwitchButton } from '@element-plus/icons-vue'

const route = useRoute(); const router = useRouter(); const auth = useAuthStore(); const theme = useThemeStore()
const active = computed(() => route.path)
const baseMenu = [
  ['/', '首页概览', DataAnalysis], ['/licenses', '授权管理', Key], ['/licenses/create', '创建授权', Plus],
  ['/license-events', '授权事件', Document], ['/admin-audit', '管理审计', Tickets], ['/version-policy', '版本策略', Setting], ['/account', '账号安全', User],
] as const
const menu = computed(() => baseMenu.filter(([path]) => path !== '/licenses/create' || auth.user?.role !== 'AUDITOR'))
async function logout() { await auth.logout(); await router.push('/login') }
</script>
<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand"><div class="brand-mark">PM</div><div><strong>PMSystem</strong><span>授权管理</span></div></div>
      <el-menu :default-active="active" router class="nav">
        <el-menu-item v-for="[path,label,icon] in menu" :key="path" :index="path"><el-icon><component :is="icon" /></el-icon><span>{{ label }}</span></el-menu-item>
      </el-menu>
      <div class="sidebar-bottom"><button class="logout" @click="logout"><el-icon><SwitchButton /></el-icon>退出登录</button></div>
    </aside>
    <main class="main">
      <header class="topbar">
        <span class="environment">开发环境</span>
        <div class="top-actions"><el-select :model-value="theme.mode" size="small" style="width:110px" @change="theme.setMode($event as ThemeMode)"><el-option label="跟随系统" value="system"/><el-option label="浅色" value="light"/><el-option label="深色" value="dark"/></el-select><span>{{ auth.user?.displayName }}</span><el-tag size="small" effect="plain">{{ auth.user?.role }}</el-tag></div>
      </header>
      <router-view />
    </main>
  </div>
</template>
<style scoped>.shell{display:grid;grid-template-columns:232px minmax(0,1fr);min-height:100vh}.sidebar{position:sticky;top:0;height:100vh;background:var(--sidebar);display:flex;flex-direction:column;color:#eef5f2}.brand{height:72px;display:flex;align-items:center;gap:12px;padding:0 20px;border-bottom:1px solid #ffffff18}.brand-mark{width:34px;height:34px;display:grid;place-items:center;background:#2d8b6d;border-radius:6px;font-weight:800}.brand strong,.brand span{display:block}.brand span{font-size:12px;color:#aab9b3;margin-top:2px}.nav{flex:1;border:0;background:transparent;padding:12px 8px;--el-menu-text-color:#aebbb6;--el-menu-hover-bg-color:#ffffff10;--el-menu-active-color:#fff;--el-menu-bg-color:transparent}.nav :deep(.el-menu-item){height:44px;border-radius:5px;margin:2px 0}.nav :deep(.el-menu-item.is-active){background:#2b765f}.sidebar-bottom{padding:14px;border-top:1px solid #ffffff18}.logout{width:100%;height:38px;display:flex;align-items:center;justify-content:center;gap:8px;border:0;background:transparent;color:#b9c4c0;cursor:pointer}.main{min-width:0;background:var(--app-bg)}.topbar{height:58px;display:flex;align-items:center;justify-content:space-between;padding:0 28px;background:var(--surface);border-bottom:1px solid var(--border)}.environment{font-size:12px;color:#8a5a10;background:#fff3d6;border:1px solid #e8cc90;border-radius:4px;padding:3px 8px}.top-actions{display:flex;align-items:center;gap:12px;font-size:13px}</style>
