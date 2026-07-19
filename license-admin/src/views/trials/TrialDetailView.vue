<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Clock, Delete, RefreshRight } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { trialsApi } from '@/api/trials'
import type { TrialItem } from '@/types'
import type { TrialAction } from '@/utils/trials'
import { canExtendTrial, trialPermissions } from '@/utils/trials'
import { useAuthStore } from '@/stores/auth'
import { formatUtc } from '@/utils/date'
import { apiErrorMessage } from '@/utils/errors'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import TrialActionDialog from '@/components/TrialActionDialog.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const actionLoading = ref(false)
const detail = ref<TrialItem | null>(null)
const action = ref<TrialAction>('extend')
const dialogVisible = ref(false)
const permissions = computed(() => trialPermissions(auth.user?.role))

async function load() {
  loading.value = true
  try {
    detail.value = (await trialsApi.detail(String(route.params.id))).data.trial
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

function openAction(nextAction: TrialAction) {
  action.value = nextAction
  dialogVisible.value = true
}

async function confirmAction(payload: { reason: string; days?: number }) {
  if (!detail.value) return
  actionLoading.value = true
  try {
    if (action.value === 'extend') await trialsApi.extend(detail.value.trialId, payload.days!, payload.reason)
    else if (action.value === 'reset') await trialsApi.reset(detail.value.trialId, payload.reason)
    else await trialsApi.delete(detail.value.trialId, payload.reason)
    dialogVisible.value = false
    ElMessage.success({ extend: '试用时间已延长', reset: '试用已重置为 7 天', delete: '试用设备已删除' }[action.value])
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    actionLoading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page" v-loading="loading">
    <PageHeader title="试用设备详情" description="逻辑删除后的记录只读保留">
      <div class="actions">
        <el-button :icon="ArrowLeft" @click="router.push({ name: 'trials' })">返回列表</el-button>
        <el-button v-if="detail && permissions.canExtend && canExtendTrial(detail)" type="primary" plain :icon="Clock" @click="openAction('extend')">延长试用</el-button>
        <el-button v-if="detail && permissions.canReset && detail.status !== 'DELETED'" type="warning" plain :icon="RefreshRight" @click="openAction('reset')">重置试用</el-button>
        <el-button v-if="detail && permissions.canDelete && detail.status !== 'DELETED'" type="danger" plain :icon="Delete" @click="openAction('delete')">删除试用</el-button>
      </div>
    </PageHeader>
    <template v-if="detail">
      <section class="surface block">
        <div class="section-title"><h2>设备与试用状态</h2><StatusTag :status="`TRIAL_${detail.status}`" /></div>
        <el-descriptions :column="3" border>
          <el-descriptions-item label="设备编号"><span class="mono">{{ detail.device }}</span></el-descriptions-item>
          <el-descriptions-item label="设备名称">{{ detail.deviceName || '-' }}</el-descriptions-item>
          <el-descriptions-item label="指纹版本">{{ detail.fingerprintVersion }}</el-descriptions-item>
          <el-descriptions-item label="试用开始">{{ formatUtc(detail.startedAt) }}</el-descriptions-item>
          <el-descriptions-item label="试用截止">{{ formatUtc(detail.expiresAt) }}</el-descriptions-item>
          <el-descriptions-item label="最近在线">{{ formatUtc(detail.lastSeenAt) }}</el-descriptions-item>
          <el-descriptions-item label="客户端版本">{{ detail.appVersion }}</el-descriptions-item>
          <el-descriptions-item label="操作系统">{{ detail.osVersion || '-' }}</el-descriptions-item>
          <el-descriptions-item label="转正式授权">{{ detail.convertedLicenseId || '-' }}</el-descriptions-item>
        </el-descriptions>
      </section>
      <section class="surface block">
        <h2>管理记录</h2>
        <el-descriptions :column="3" border>
          <el-descriptions-item label="重置次数">{{ detail.resetCount }}</el-descriptions-item>
          <el-descriptions-item label="最后重置">{{ formatUtc(detail.lastResetAt) }}</el-descriptions-item>
          <el-descriptions-item label="重置原因">{{ detail.lastResetReason || '-' }}</el-descriptions-item>
          <el-descriptions-item label="延长次数">{{ detail.extensionCount }}</el-descriptions-item>
          <el-descriptions-item label="累计延长">{{ detail.totalExtendedDays }} 天</el-descriptions-item>
          <el-descriptions-item label="最后延长">{{ formatUtc(detail.lastExtendedAt) }}</el-descriptions-item>
          <el-descriptions-item label="删除时间">{{ formatUtc(detail.deletedAt) }}</el-descriptions-item>
          <el-descriptions-item label="删除原因" :span="2">{{ detail.deleteReason || '-' }}</el-descriptions-item>
        </el-descriptions>
      </section>
    </template>
    <TrialActionDialog v-model="dialogVisible" :action="action" :trial="detail" :loading="actionLoading" @confirm="confirmAction" />
  </div>
</template>

<style scoped>
.actions { display: flex; gap: 8px; flex-wrap: wrap; }
.block { padding: 18px; margin-bottom: 14px; }
.block h2, .section-title h2 { margin: 0 0 14px; font-size: 16px; }
.section-title { display: flex; align-items: start; justify-content: space-between; }
</style>
