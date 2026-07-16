<script setup lang="ts">
import { ElMessage } from 'element-plus'
const props = defineProps<{ items: Array<Record<string, string>> }>()
async function copy(code: string) { await navigator.clipboard.writeText(code); ElMessage.success('激活码已复制') }
function csv() {
  const header = ['序号','激活码','授权类型','到期规则','客户名称','备注']
  const lines = props.items.map((item, index) => [index + 1, item.licenseCode, item.licenseType, item.expiresAt || '首次激活后计算', item.customerName || '', item.remark || ''])
  const text = [header, ...lines].map((row) => row.map((cell) => `"${String(cell).replaceAll('"','""')}"`).join(',')).join('\r\n')
  const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob(['\ufeff' + text], { type: 'text/csv;charset=utf-8' }))
  link.download = `pmsystem-license-codes-${new Date().toISOString().replace(/[-:T]/g,'').slice(0,14)}.csv`; link.click(); URL.revokeObjectURL(link.href)
}
</script>
<template>
  <section class="result surface">
    <div class="notice"><strong>完整激活码仅显示一次</strong><span>离开本页后无法再次查看，请立即安全保存。</span></div>
    <el-table :data="items" max-height="420">
      <el-table-column type="index" label="序号" width="70" />
      <el-table-column prop="licenseCode" label="激活码" min-width="260"><template #default="scope"><span class="mono">{{ scope.row.licenseCode }}</span></template></el-table-column>
      <el-table-column prop="licenseType" label="类型" width="120" />
      <el-table-column label="操作" width="100"><template #default="scope"><el-button link type="primary" @click="copy(scope.row.licenseCode)">复制</el-button></template></el-table-column>
    </el-table>
    <div class="result-actions"><el-button v-if="items.length > 1" @click="csv">下载本次 CSV</el-button></div>
  </section>
</template>
<style scoped>.result{padding:18px}.notice{display:flex;gap:14px;align-items:center;padding:12px 14px;margin-bottom:14px;background:color-mix(in srgb,var(--accent) 10%,var(--surface));border-left:3px solid var(--accent)}.notice span{color:var(--text-muted)}.result-actions{text-align:right;margin-top:14px}</style>
