<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { dashboardApi, type DashboardRecent } from '@/api/dashboard'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import { formatUtc } from '@/utils/date'

const loading = ref(false)
const summary = ref<Record<string, number>>({})
const recent = ref<DashboardRecent>({ createdLicenses: [], recentActivations: [], adminOperations: [], abnormalEvents: [] })
const metrics = [
  ['trialTotal','试用设备总数'],['trialActive','当前试用中'],['trialStartedToday','今日新增试用'],
  ['trialExpiring3Days','3天内到期试用'],['trialExpired','已过期试用'],['trialConverted','已转正式'],
  ['trialConversionRateBasisPoints','试用转正式比例'],
  ['total','授权总数'],['activated','已激活'],['unactivated','未激活'],['active','当前有效'],
  ['expiring7Days','7天内到期'],['expiring30Days','30天内到期'],['expired','已过期'],
  ['disabled','已禁用'],['revoked','已撤销'],['activeBindings','当前设备绑定'],
  ['verified24Hours','24小时在线'],['created7Days','7天新增'],['activated7Days','7天激活'],
]
function metricValue(key: string): string | number {
  const value = summary.value[key] ?? 0
  return key === 'trialConversionRateBasisPoints' ? `${(value / 100).toFixed(2)}%` : value
}
async function load() {
  loading.value = true
  try {
    const data = (await dashboardApi.summary()).data
    summary.value = data.summary
    recent.value = data.recent || { createdLicenses: [], recentActivations: [], adminOperations: [], abnormalEvents: [] }
  } finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader title="首页概览" description="授权规模、状态和设备在线情况" />
    <section v-loading="loading" class="metrics">
      <article v-for="[key,label] in metrics" :key="key" class="metric surface"><span>{{ label }}</span><strong>{{ metricValue(key) }}</strong></article>
    </section>
    <section class="activity-grid">
      <article class="surface activity"><h2>最近创建授权</h2><ul><li v-for="item in recent.createdLicenses" :key="item.id"><div><b>{{ item.maskedCode }}</b><span>{{ item.customerName || '未填写客户' }}</span></div><time>{{ formatUtc(item.createdAt) }}</time></li><li v-if="!recent.createdLicenses.length" class="empty">暂无记录</li></ul></article>
      <article class="surface activity"><h2>最近激活</h2><ul><li v-for="item in recent.recentActivations" :key="item.id"><div><b>{{ item.maskedCode }}</b><span>{{ item.customerName || '未填写客户' }}</span></div><time>{{ formatUtc(item.activatedAt) }}</time></li><li v-if="!recent.recentActivations.length" class="empty">暂无记录</li></ul></article>
      <article class="surface activity"><h2>最近管理员操作</h2><ul><li v-for="item in recent.adminOperations" :key="item.id"><div><b>{{ item.action }}</b><span>{{ item.targetId || '系统' }}</span></div><time>{{ formatUtc(item.createdAt) }}</time></li><li v-if="!recent.adminOperations.length" class="empty">暂无记录</li></ul></article>
      <article class="surface activity"><h2>异常验证事件</h2><ul><li v-for="item in recent.abnormalEvents" :key="item.id"><div><b>{{ item.eventType }}</b><StatusTag :status="item.result" /></div><time>{{ formatUtc(item.createdAt) }}</time></li><li v-if="!recent.abnormalEvents.length" class="empty">暂无异常</li></ul></article>
    </section>
  </div>
</template>

<style scoped>
.metrics{display:grid;grid-template-columns:repeat(4,minmax(180px,1fr));gap:12px}.metric{padding:18px 20px}.metric span{display:block;color:var(--text-muted);font-size:13px}.metric strong{display:block;margin-top:9px;font-size:30px;font-weight:650}.activity-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:16px}.activity{padding:18px 20px}.activity h2{margin:0 0 10px;font-size:16px}.activity ul{list-style:none;margin:0;padding:0}.activity li{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:48px;border-top:1px solid var(--border)}.activity li:first-child{border-top:0}.activity li div{min-width:0;display:flex;align-items:center;gap:10px}.activity li span{color:var(--text-muted);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.activity time{flex:none;color:var(--text-muted);font-size:12px}.activity .empty{justify-content:center;color:var(--text-muted)}@media(max-width:1280px){.metrics{grid-template-columns:repeat(3,minmax(180px,1fr))}}
</style>
