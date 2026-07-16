<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { auditApi } from '@/api/audit'
import PageHeader from '@/components/PageHeader.vue'
import { formatUtc } from '@/utils/date'

const items = ref<any[]>([])
const total = ref(0)
const loading = ref(false)
const dateRange = ref<[Date, Date] | null>(null)
const query = reactive({ page: 1, pageSize: 20, action: '', targetId: '', adminUserId: '' })
async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = Object.fromEntries(Object.entries(query).filter(([, value]) => value !== ''))
    if (dateRange.value) {
      const end = new Date(dateRange.value[1]); end.setHours(23, 59, 59, 999)
      params.createdFrom = dateRange.value[0].toISOString(); params.createdTo = end.toISOString()
    }
    const data = (await auditApi.adminEvents(params)).data
    items.value = data.items; total.value = data.total
  } finally { loading.value = false }
}
function search() { query.page = 1; load() }
onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader title="管理审计" description="管理员高风险操作不可由普通管理流程删除" />
    <div class="toolbar surface filters">
      <el-input v-model="query.action" clearable placeholder="操作类型" style="width:190px" />
      <el-input v-model="query.targetId" clearable placeholder="目标 ID" style="width:250px" />
      <el-input v-model="query.adminUserId" clearable placeholder="管理员 ID" style="width:250px" />
      <el-date-picker v-model="dateRange" type="daterange" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" style="width:260px" />
      <el-button type="primary" @click="search">查询</el-button>
    </div>
    <section class="surface">
      <el-table v-loading="loading" :data="items">
        <el-table-column prop="action" label="操作" width="220" />
        <el-table-column prop="result" label="结果" width="100" />
        <el-table-column prop="adminUserId" label="管理员 ID" min-width="240" show-overflow-tooltip />
        <el-table-column prop="targetType" label="目标类型" width="150" />
        <el-table-column prop="targetId" label="目标 ID" min-width="240" show-overflow-tooltip />
        <el-table-column label="时间" width="180"><template #default="scope">{{ formatUtc(scope.row.createdAt) }}</template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="query.page" v-model:page-size="query.pageSize" :total="total" :page-sizes="[20,50,100]" layout="total, sizes, prev, pager, next" class="pager" @change="load" />
    </section>
  </div>
</template>

<style scoped>
.filters{display:flex;flex-wrap:wrap}.pager{justify-content:flex-end;padding:14px}
</style>
