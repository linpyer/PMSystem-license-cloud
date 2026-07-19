<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ status: string }>()
const trialLabels: Record<string, string> = { TRIAL_ACTIVE: '试用中', TRIAL_EXPIRED: '已结束', TRIAL_CONVERTED: '已转正式', TRIAL_DISABLED: '已禁用', TRIAL_DELETED: '已删除' }
const labels: Record<string, string> = { ACTIVE: '有效', CREATED: '未激活', EXPIRED: '已过期', DISABLED: '已禁用', REVOKED: '已撤销', DEACTIVATED: '已解绑' }
const type = computed(() => ({
  ACTIVE: 'success', EXPIRED: 'warning', DISABLED: 'warning', REVOKED: 'danger',
  CREATED: 'info', DEACTIVATED: 'info', TRIAL_ACTIVE: 'success',
  TRIAL_EXPIRED: 'warning', TRIAL_CONVERTED: 'success', TRIAL_DISABLED: 'danger',
  TRIAL_DELETED: 'info',
}[props.status] || 'info'))
</script>
<template><el-tag :type="type" effect="light">{{ trialLabels[status] || labels[status] || status }}</el-tag></template>
