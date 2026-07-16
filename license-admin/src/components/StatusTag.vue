<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ status: string }>()
const labels: Record<string, string> = { ACTIVE: '有效', CREATED: '未激活', EXPIRED: '已过期', DISABLED: '已禁用', REVOKED: '已撤销', DEACTIVATED: '已解绑' }
const type = computed(() => ({ ACTIVE: 'success', EXPIRED: 'warning', DISABLED: 'warning', REVOKED: 'danger', CREATED: 'info', DEACTIVATED: 'info' }[props.status] || 'info'))
</script>
<template><el-tag :type="type" effect="light">{{ labels[status] || status }}</el-tag></template>
