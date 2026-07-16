<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { auditApi } from '@/api/audit'
import PageHeader from '@/components/PageHeader.vue'
import { formatUtc } from '@/utils/date'
const items=ref<any[]>([]);const total=ref(0);const page=ref(1);const loading=ref(false)
async function load(){loading.value=true;try{const data=(await auditApi.licenseEvents({page:page.value,pageSize:20})).data;items.value=data.items;total.value=data.total}finally{loading.value=false}}onMounted(load)
</script>
<template><div class="page"><PageHeader title="授权事件" description="激活、验证、解绑及异常请求记录"/><section class="surface"><el-table v-loading="loading" :data="items"><el-table-column prop="eventType" label="事件类型" width="220"/><el-table-column prop="result" label="结果" width="180"/><el-table-column prop="licenseId" label="License ID" min-width="260" show-overflow-tooltip/><el-table-column prop="requestId" label="请求 ID" min-width="220" show-overflow-tooltip/><el-table-column label="时间" width="180"><template #default="s">{{ formatUtc(s.row.createdAt) }}</template></el-table-column></el-table><el-pagination v-model:current-page="page" :total="total" :page-size="20" layout="total, prev, pager, next" class="pager" @change="load"/></section></div></template><style scoped>.pager{justify-content:flex-end;padding:14px}</style>
