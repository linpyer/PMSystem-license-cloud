<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { authApi } from '@/api/auth'
import { usersApi, type AdminEnrollment } from '@/api/users'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import { useAuthStore } from '@/stores/auth'
import type { AdminRole, AdminUser } from '@/types'
import { formatUtc } from '@/utils/date'
import { apiErrorMessage } from '@/utils/errors'

const auth = useAuthStore()
const passwordLoading = ref(false)
const usersLoading = ref(false)
const createVisible = ref(false)
const enrollment = ref<AdminEnrollment | null>(null)
const passwordForm = reactive({ currentPassword: '', newPassword: '', confirm: '' })
const createForm = reactive({ username: '', displayName: '', role: 'ADMIN' as AdminRole, password: '' })
const users = ref<AdminUser[]>([])
const isOwner = computed(() => auth.user?.role === 'OWNER')

async function savePassword() {
  if (passwordForm.newPassword !== passwordForm.confirm) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  passwordLoading.value = true
  try {
    await authApi.changePassword(passwordForm.currentPassword, passwordForm.newPassword)
    ElMessage.success('密码已修改，其他会话已退出')
    Object.assign(passwordForm, { currentPassword: '', newPassword: '', confirm: '' })
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    passwordLoading.value = false
  }
}

async function loadUsers() {
  if (!isOwner.value) return
  usersLoading.value = true
  try {
    users.value = (await usersApi.list()).data.items
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    usersLoading.value = false
  }
}

async function createUser() {
  if (!createForm.username || !createForm.displayName || createForm.password.length < 12) {
    ElMessage.warning('请完整填写账号信息，初始密码至少12位')
    return
  }
  try {
    enrollment.value = (await usersApi.create(createForm)).data
    createVisible.value = false
    Object.assign(createForm, { username: '', displayName: '', role: 'ADMIN', password: '' })
    await loadUsers()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  }
}

async function changeStatus(user: AdminUser) {
  const disabling = user.status === 'ACTIVE'
  try {
    const { value } = await ElMessageBox.prompt(
      disabling ? '禁用后该账号的现有会话会立即失效。' : '恢复后该账号可以重新登录。',
      disabling ? '禁用管理员' : '恢复管理员',
      { inputPlaceholder: '请输入操作原因', inputValidator: (value) => value.trim().length >= 3 || '原因至少3个字符' },
    )
    if (disabling) await usersApi.disable(user.id, value)
    else await usersApi.enable(user.id, value)
    ElMessage.success(disabling ? '管理员已禁用' : '管理员已恢复')
    await loadUsers()
  } catch (error: unknown) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(apiErrorMessage(error))
  }
}

async function copySecret() {
  if (!enrollment.value) return
  await navigator.clipboard.writeText(enrollment.value.totpSecret)
  ElMessage.success('TOTP密钥已复制')
}

onMounted(loadUsers)
</script>

<template>
  <div class="page">
    <PageHeader title="账号安全" description="修改当前密码并管理管理员访问权限" />
    <section class="surface form-panel">
      <h2>修改密码</h2>
      <el-form label-position="top">
        <el-form-item label="当前密码"><el-input v-model="passwordForm.currentPassword" type="password" show-password /></el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="passwordForm.newPassword" type="password" show-password />
          <div class="hint">至少12位，建议包含大小写字母、数字和符号</div>
        </el-form-item>
        <el-form-item label="确认新密码"><el-input v-model="passwordForm.confirm" type="password" show-password /></el-form-item>
        <el-button type="primary" :loading="passwordLoading" @click="savePassword">修改密码</el-button>
      </el-form>
    </section>

    <section v-if="isOwner" class="surface users-panel">
      <div class="section-heading">
        <div><h2>管理员账号</h2><p>OWNER 可创建账号并控制登录状态。</p></div>
        <el-button type="primary" @click="createVisible = true">创建管理员</el-button>
      </div>
      <el-table v-loading="usersLoading" :data="users" table-layout="fixed">
        <el-table-column prop="username" label="用户名" min-width="150" />
        <el-table-column prop="displayName" label="显示名称" min-width="150" />
        <el-table-column prop="role" label="角色" width="110" />
        <el-table-column label="状态" width="110"><template #default="scope"><StatusTag :status="scope.row.status" /></template></el-table-column>
        <el-table-column label="最后登录" min-width="170"><template #default="scope">{{ formatUtc(scope.row.lastLoginAt) }}</template></el-table-column>
        <el-table-column label="操作" width="110" align="right">
          <template #default="scope">
            <el-button v-if="scope.row.id !== auth.user?.id" link :type="scope.row.status === 'ACTIVE' ? 'danger' : 'primary'" @click="changeStatus(scope.row)">
              {{ scope.row.status === 'ACTIVE' ? '禁用' : '恢复' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="createVisible" title="创建管理员" width="520px">
      <el-form label-position="top">
        <el-form-item label="用户名"><el-input v-model="createForm.username" autocomplete="off" /></el-form-item>
        <el-form-item label="显示名称"><el-input v-model="createForm.displayName" /></el-form-item>
        <el-form-item label="角色"><el-select v-model="createForm.role"><el-option label="管理员" value="ADMIN" /><el-option label="审计员" value="AUDITOR" /></el-select></el-form-item>
        <el-form-item label="初始密码"><el-input v-model="createForm.password" type="password" show-password autocomplete="new-password" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="createVisible = false">取消</el-button><el-button type="primary" @click="createUser">创建</el-button></template>
    </el-dialog>

    <el-dialog :model-value="Boolean(enrollment)" title="绑定动态验证码" width="580px" :close-on-click-modal="false" @close="enrollment = null">
      <el-alert title="TOTP绑定信息仅显示一次，请立即录入验证器并妥善保管。" type="warning" :closable="false" show-icon />
      <dl v-if="enrollment" class="enrollment">
        <dt>管理员</dt><dd>{{ enrollment.user.username }}</dd>
        <dt>TOTP密钥</dt><dd class="secret"><code>{{ enrollment.totpSecret }}</code><el-button link type="primary" @click="copySecret">复制</el-button></dd>
        <dt>绑定URI</dt><dd class="uri">{{ enrollment.provisioningUri }}</dd>
      </dl>
      <template #footer><el-button type="primary" @click="enrollment = null">我已安全保存</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.form-panel{width:min(560px,100%);padding:22px}.users-panel{margin-top:18px;padding:20px}.section-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.section-heading h2,.form-panel h2{margin:0 0 12px;font-size:18px}.section-heading p{margin:4px 0 0;color:var(--text-muted);font-size:13px}.hint{font-size:12px;color:var(--text-muted)}.enrollment{display:grid;grid-template-columns:88px 1fr;gap:14px;margin:20px 0 0}.enrollment dt{color:var(--text-muted)}.enrollment dd{margin:0;min-width:0}.secret{display:flex;gap:12px;align-items:center}.uri{overflow-wrap:anywhere;font-family:ui-monospace,Consolas,monospace;font-size:12px}
</style>
