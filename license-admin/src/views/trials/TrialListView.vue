<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { trialsApi } from '@/api/trials'
import type { TrialItem } from '@/types'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import { formatUtc } from '@/utils/date'
import { apiErrorMessage } from '@/utils/errors'

const auth = useAuthStore(); const loading = ref(false); const items = ref<TrialItem[]>([])
const total = ref(0); const page = ref(1); const pageSize = ref(20)
const filters = reactive({
  deviceId: '', status: '', appVersion: '', converted: '',
  startedRange: [] as string[], expiresRange: [] as string[],
})
const canDisable = computed(() => auth.user?.role === 'OWNER' || auth.user?.role === 'ADMIN')

function remaining(expiresAt: string, status: string): string {
  if (status === 'CONVERTED') return '已转正式'
  const seconds = Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000))
  if (!seconds) return '已结束'
  return `${Math.floor(seconds / 86400)}天${Math.floor((seconds % 86400) / 3600)}小时`
}
async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: page.value, pageSize: pageSize.value }
    if (filters.deviceId) params.deviceId = filters.deviceId
    if (filters.status) params.status = filters.status
    if (filters.appVersion) params.appVersion = filters.appVersion
    if (filters.converted) params.converted = filters.converted === 'true'
    if (filters.startedRange.length === 2) {
      params.startedFrom = filters.startedRange[0]
      params.startedTo = filters.startedRange[1]
    }
    if (filters.expiresRange.length === 2) {
      params.expiresFrom = filters.expiresRange[0]
      params.expiresTo = filters.expiresRange[1]
    }
    const data = (await trialsApi.list(params)).data; items.value = data.items; total.value = data.total
  } finally { loading.value = false }
}
async function disableTrial(item: TrialItem) {
  try {
    const { value } = await ElMessageBox.prompt('禁用后该设备的试用许可证将在下次在线验证时失效。此操作不会重置或延长试用。','禁用试用',{type:'warning',inputPlaceholder:'请输入禁用原因',inputValidator:value=>value.length>=3||'原因至少3个字'})
    await trialsApi.disable(item.trialId, value); ElMessage.success('试用已禁用'); await load()
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(apiErrorMessage(error)) }
}
function search(){ page.value=1; void load() }
onMounted(load)
</script>
<template>
  <div class="page">
    <PageHeader title="试用设备" description="查看并管理设备免费试用，所有变更均保留审计记录" />
    <section class="surface filters">
      <el-input v-model="filters.deviceId" placeholder="设备编号" clearable @keyup.enter="search" />
      <el-select v-model="filters.status" placeholder="全部状态" clearable><el-option label="试用中" value="ACTIVE"/><el-option label="已结束" value="EXPIRED"/><el-option label="已转正式" value="CONVERTED"/><el-option label="已禁用" value="DISABLED"/></el-select>
      <el-input v-model="filters.appVersion" placeholder="客户端版本" clearable @keyup.enter="search" />
      <el-select v-model="filters.converted" placeholder="是否转正式" clearable><el-option label="已转正式" value="true"/><el-option label="未转正式" value="false"/></el-select>
      <el-date-picker v-model="filters.startedRange" type="datetimerange" value-format="YYYY-MM-DDTHH:mm:ssZ" start-placeholder="开始时间起" end-placeholder="开始时间止" />
      <el-date-picker v-model="filters.expiresRange" type="datetimerange" value-format="YYYY-MM-DDTHH:mm:ssZ" start-placeholder="到期时间起" end-placeholder="到期时间止" />
      <el-button type="primary" @click="search">查询</el-button>
    </section>
    <section class="surface table-wrap">
      <el-table v-loading="loading" :data="items">
        <el-table-column prop="device" label="设备编号" min-width="150"/><el-table-column prop="deviceName" label="设备名称" min-width="130"/>
        <el-table-column label="状态" width="110"><template #default="scope"><StatusTag :status="`TRIAL_${scope.row.status}`"/></template></el-table-column>
        <el-table-column label="开始时间" width="178"><template #default="scope">{{ formatUtc(scope.row.startedAt) }}</template></el-table-column>
        <el-table-column label="截止时间" width="178"><template #default="scope">{{ formatUtc(scope.row.expiresAt) }}</template></el-table-column>
        <el-table-column label="剩余时间" width="120"><template #default="scope">{{ remaining(scope.row.expiresAt,scope.row.status) }}</template></el-table-column>
        <el-table-column label="最近在线" width="178"><template #default="scope">{{ formatUtc(scope.row.lastSeenAt) }}</template></el-table-column>
        <el-table-column prop="appVersion" label="客户端版本" width="110"/><el-table-column prop="convertedLicenseId" label="正式授权ID" min-width="180" show-overflow-tooltip/>
        <el-table-column v-if="canDisable" label="操作" width="90" fixed="right"><template #default="scope"><el-button v-if="scope.row.status==='ACTIVE'" link type="danger" @click="disableTrial(scope.row)">禁用</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20,50,100]" layout="total, sizes, prev, pager, next" @change="load" />
    </section>
  </div>
</template>
<style scoped>.filters{display:grid;grid-template-columns:minmax(180px,1.4fr) 160px 150px 160px minmax(300px,1fr) minmax(300px,1fr) auto;gap:10px;padding:14px;margin-bottom:14px;overflow-x:auto}.table-wrap{padding:14px}.el-pagination{justify-content:flex-end;margin-top:14px}</style>
