<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Clock, Delete, Lock, RefreshRight, View } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { trialsApi } from '@/api/trials'
import type { TrialItem } from '@/types'
import type { TrialAction } from '@/utils/trials'
import { canExtendTrial, trialPermissions } from '@/utils/trials'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import TrialActionDialog from '@/components/TrialActionDialog.vue'
import { formatUtc } from '@/utils/date'
import { apiErrorMessage } from '@/utils/errors'

const auth = useAuthStore()
const router = useRouter()
const loading = ref(false)
const actionLoading = ref(false)
const items = ref<TrialItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const dialogVisible = ref(false)
const selected = ref<TrialItem | null>(null)
const action = ref<TrialAction>('extend')
const permissions = computed(() => trialPermissions(auth.user?.role))
const canDisable = computed(() => auth.user?.role === 'OWNER' || auth.user?.role === 'ADMIN')
const filters = reactive({
  deviceId: '', status: '', appVersion: '', converted: '', includeDeleted: false,
  startedRange: [] as string[], expiresRange: [] as string[],
})

function remaining(expiresAt: string, status: string): string {
  if (status === 'CONVERTED') return '已转正式'
  if (status === 'DELETED') return '已删除'
  const seconds = Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000))
  if (!seconds) return '已结束'
  return `${Math.floor(seconds / 86400)}天${Math.floor((seconds % 86400) / 3600)}小时`
}

async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      page: page.value,
      pageSize: pageSize.value,
      includeDeleted: filters.includeDeleted,
    }
    if (filters.deviceId) params.deviceId = filters.deviceId
    if (filters.status) params.status = filters.status
    if (filters.appVersion) params.appVersion = filters.appVersion
    if (filters.converted) params.converted = filters.converted === 'true'
    if (filters.startedRange.length === 2) [params.startedFrom, params.startedTo] = filters.startedRange
    if (filters.expiresRange.length === 2) [params.expiresFrom, params.expiresTo] = filters.expiresRange
    const data = (await trialsApi.list(params)).data
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  void load()
}

function openAction(item: TrialItem, nextAction: TrialAction) {
  selected.value = item
  action.value = nextAction
  dialogVisible.value = true
}

async function confirmAction(payload: { reason: string; days?: number }) {
  if (!selected.value) return
  actionLoading.value = true
  try {
    if (action.value === 'extend') await trialsApi.extend(selected.value.trialId, payload.days!, payload.reason)
    else if (action.value === 'reset') await trialsApi.reset(selected.value.trialId, payload.reason)
    else await trialsApi.delete(selected.value.trialId, payload.reason)
    dialogVisible.value = false
    ElMessage.success({ extend: '试用时间已延长', reset: '试用已重置为 7 天', delete: '试用设备已删除' }[action.value])
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    actionLoading.value = false
  }
}

async function disableTrial(item: TrialItem) {
  try {
    const { value } = await ElMessageBox.prompt(
      '禁用后该设备的试用许可证将在下次在线验证时失效。请输入操作原因。',
      '禁用试用',
      { type: 'warning', inputPlaceholder: '请输入禁用原因', inputValidator: value => value.length >= 3 || '原因至少3个字' },
    )
    await trialsApi.disable(item.trialId, value)
    ElMessage.success('试用已禁用')
    await load()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(apiErrorMessage(error))
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader title="试用设备" description="查看并管理设备免费试用，所有变更均保留审计记录" />
    <section class="surface filters">
      <el-input v-model="filters.deviceId" placeholder="设备编号" clearable @keyup.enter="search" />
      <el-select v-model="filters.status" placeholder="全部状态" clearable>
        <el-option label="试用中" value="ACTIVE" />
        <el-option label="已结束" value="EXPIRED" />
        <el-option label="已转正式" value="CONVERTED" />
        <el-option label="已禁用" value="DISABLED" />
        <el-option label="已删除" value="DELETED" />
      </el-select>
      <el-input v-model="filters.appVersion" placeholder="客户端版本" clearable @keyup.enter="search" />
      <el-select v-model="filters.converted" placeholder="是否转正式" clearable>
        <el-option label="已转正式" value="true" />
        <el-option label="未转正式" value="false" />
      </el-select>
      <el-date-picker v-model="filters.startedRange" type="datetimerange" value-format="YYYY-MM-DDTHH:mm:ssZ" start-placeholder="开始时间起" end-placeholder="开始时间止" />
      <el-date-picker v-model="filters.expiresRange" type="datetimerange" value-format="YYYY-MM-DDTHH:mm:ssZ" start-placeholder="到期时间起" end-placeholder="到期时间止" />
      <el-checkbox v-model="filters.includeDeleted">包含已删除</el-checkbox>
      <el-button type="primary" @click="search">查询</el-button>
    </section>
    <section class="surface table-wrap">
      <el-table v-loading="loading" :data="items">
        <el-table-column prop="device" label="设备编号" min-width="150" />
        <el-table-column prop="deviceName" label="设备名称" min-width="130" />
        <el-table-column label="状态" width="110"><template #default="scope"><StatusTag :status="`TRIAL_${scope.row.status}`" /></template></el-table-column>
        <el-table-column label="开始时间" width="178"><template #default="scope">{{ formatUtc(scope.row.startedAt) }}</template></el-table-column>
        <el-table-column label="截止时间" width="178"><template #default="scope">{{ formatUtc(scope.row.expiresAt) }}</template></el-table-column>
        <el-table-column label="剩余时间" width="120"><template #default="scope">{{ remaining(scope.row.expiresAt, scope.row.status) }}</template></el-table-column>
        <el-table-column label="最近在线" width="178"><template #default="scope">{{ formatUtc(scope.row.lastSeenAt) }}</template></el-table-column>
        <el-table-column prop="appVersion" label="客户端版本" width="110" />
        <el-table-column label="操作" width="310" fixed="right">
          <template #default="scope">
            <el-button link :icon="View" @click="router.push({ name: 'trial-detail', params: { id: scope.row.trialId } })">查看</el-button>
            <el-button v-if="permissions.canExtend && canExtendTrial(scope.row)" link type="primary" :icon="Clock" @click="openAction(scope.row, 'extend')">延长</el-button>
            <el-button v-if="permissions.canReset && scope.row.status !== 'DELETED'" link type="warning" :icon="RefreshRight" @click="openAction(scope.row, 'reset')">重置</el-button>
            <el-button v-if="canDisable && scope.row.status === 'ACTIVE'" link type="warning" :icon="Lock" @click="disableTrial(scope.row)">禁用</el-button>
            <el-button v-if="permissions.canDelete && scope.row.status !== 'DELETED'" link type="danger" :icon="Delete" @click="openAction(scope.row, 'delete')">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @change="load" />
    </section>
    <TrialActionDialog v-model="dialogVisible" :action="action" :trial="selected" :loading="actionLoading" @confirm="confirmAction" />
  </div>
</template>

<style scoped>
.filters { display: grid; grid-template-columns: minmax(180px, 1.4fr) 150px 140px 150px minmax(290px, 1fr) minmax(290px, 1fr) auto auto; align-items: center; gap: 10px; padding: 14px; margin-bottom: 14px; overflow-x: auto; }
.table-wrap { padding: 14px; }
.el-pagination { justify-content: flex-end; margin-top: 14px; }
</style>
