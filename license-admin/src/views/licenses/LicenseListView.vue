<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { licensesApi } from '@/api/licenses'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import { formatUtc } from '@/utils/date'
import type { LicenseItem } from '@/types'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const canWrite = computed(() => auth.user?.role === 'OWNER' || auth.user?.role === 'ADMIN')
const loading = ref(false)
const items = ref<LicenseItem[]>([])
const total = ref(0)
const createdRange = ref<[Date, Date] | null>(null)
const expiresRange = ref<[Date, Date] | null>(null)
const verifiedRange = ref<[Date, Date] | null>(null)
const query = reactive({ page: 1, pageSize: 20, keyword: '', licenseType: '', status: '', bound: '', sortBy: 'createdAt', sortOrder: 'desc' })

function appendRange(params: Record<string, unknown>, range: [Date, Date] | null, prefix: string) {
  if (!range) return
  const end = new Date(range[1]); end.setHours(23, 59, 59, 999)
  params[`${prefix}From`] = range[0].toISOString()
  params[`${prefix}To`] = end.toISOString()
}
async function load() {
  loading.value = true
  try {
    const params = Object.fromEntries(Object.entries(query).filter(([, value]) => value !== ''))
    appendRange(params, createdRange.value, 'created')
    appendRange(params, expiresRange.value, 'expires')
    appendRange(params, verifiedRange.value, 'verified')
    const data = (await licensesApi.list(params)).data
    items.value = data.items; total.value = data.total
  } finally { loading.value = false }
}
function search() { query.page = 1; load() }
function sortChanged({ prop, order }: { prop: string; order: string | null }) {
  query.sortBy = prop || 'createdAt'
  query.sortOrder = order === 'ascending' ? 'asc' : 'desc'
  search()
}
onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader title="授权管理" description="服务端筛选和分页，不返回完整激活码"><el-button v-if="canWrite" type="primary" @click="router.push('/licenses/create')">创建授权</el-button></PageHeader>
    <div class="toolbar surface filters">
      <el-input v-model="query.keyword" clearable placeholder="尾号、客户、联系方式或 License ID" style="width:290px" @keyup.enter="search" />
      <el-select v-model="query.licenseType" clearable placeholder="授权类型" style="width:140px"><el-option label="月卡" value="monthly" /><el-option label="年卡" value="yearly" /><el-option label="永久" value="permanent" /><el-option label="指定日期" value="fixed_date" /></el-select>
      <el-select v-model="query.status" clearable placeholder="状态" style="width:130px"><el-option v-for="status in ['CREATED','ACTIVE','EXPIRED','DISABLED','REVOKED']" :key="status" :label="status" :value="status" /></el-select>
      <el-select v-model="query.bound" clearable placeholder="设备绑定" style="width:130px"><el-option label="已绑定" :value="true" /><el-option label="未绑定" :value="false" /></el-select>
      <el-date-picker v-model="createdRange" type="daterange" range-separator="至" start-placeholder="创建开始" end-placeholder="创建结束" style="width:250px" />
      <el-date-picker v-model="expiresRange" type="daterange" range-separator="至" start-placeholder="到期开始" end-placeholder="到期结束" style="width:250px" />
      <el-date-picker v-model="verifiedRange" type="daterange" range-separator="至" start-placeholder="验证开始" end-placeholder="验证结束" style="width:250px" />
      <el-button type="primary" @click="search">查询</el-button>
    </div>
    <section class="surface table-wrap">
      <el-table v-loading="loading" :data="items" @row-click="(row: LicenseItem) => router.push(`/licenses/${row.licenseId}`)" @sort-change="sortChanged">
        <el-table-column prop="maskedCode" label="激活码" min-width="220"><template #default="scope"><span class="mono">{{ scope.row.maskedCode }}</span></template></el-table-column>
        <el-table-column prop="licenseType" label="类型" width="110" />
        <el-table-column label="状态" width="100"><template #default="scope"><StatusTag :status="scope.row.status" /></template></el-table-column>
        <el-table-column prop="customerName" label="客户" min-width="150" show-overflow-tooltip />
        <el-table-column prop="customerContact" label="联系方式" min-width="150" show-overflow-tooltip />
        <el-table-column prop="device" label="当前设备" width="130" />
        <el-table-column prop="activatedAt" label="首次激活" width="170" sortable="custom"><template #default="scope">{{ formatUtc(scope.row.activatedAt) }}</template></el-table-column>
        <el-table-column prop="expiresAt" label="到期时间" width="170" sortable="custom"><template #default="scope">{{ formatUtc(scope.row.expiresAt) }}</template></el-table-column>
        <el-table-column prop="lastVerifiedAt" label="最后验证" width="170" sortable="custom"><template #default="scope">{{ formatUtc(scope.row.lastVerifiedAt) }}</template></el-table-column>
        <el-table-column prop="createdAt" label="创建时间" width="170" sortable="custom"><template #default="scope">{{ formatUtc(scope.row.createdAt) }}</template></el-table-column>
        <el-table-column label="操作" width="85" fixed="right"><template #default="scope"><el-button link type="primary" @click.stop="router.push(`/licenses/${scope.row.licenseId}`)">详情</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="query.page" v-model:page-size="query.pageSize" :total="total" :page-sizes="[20,50,100]" layout="total, sizes, prev, pager, next" class="pagination" @change="load" />
    </section>
  </div>
</template>

<style scoped>
.filters{display:flex;flex-wrap:wrap}.table-wrap{overflow:hidden}.pagination{justify-content:flex-end;padding:14px}
</style>
