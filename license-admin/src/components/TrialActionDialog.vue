<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { Clock, Delete, RefreshRight } from '@element-plus/icons-vue'
import type { TrialItem } from '@/types'
import type { TrialAction } from '@/utils/trials'
import { extensionPreview } from '@/utils/trials'
import { formatUtc } from '@/utils/date'

const props = defineProps<{
  modelValue: boolean
  action: TrialAction
  trial: TrialItem | null
  loading?: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: [payload: { reason: string; days?: number; confirmation?: 'DELETE' }]
}>()

const form = reactive({ reason: '', days: 7, confirmation: '' })
const title = computed(() => ({ extend: '延长试用', reset: '重置试用', delete: '删除试用设备' })[props.action])
const icon = computed(() => ({ extend: Clock, reset: RefreshRight, delete: Delete })[props.action])
const preview = computed(() => {
  if (!props.trial || props.action !== 'extend') return '-'
  const value = extensionPreview(props.trial, form.days)
  return value ? formatUtc(value.toISOString()) : '-'
})

watch(() => props.modelValue, (visible) => {
  if (visible) Object.assign(form, { reason: '', days: 7, confirmation: '' })
})

function submit() {
  const reason = form.reason.trim()
  if (!reason) return
  if (props.action === 'extend') {
    if (!Number.isInteger(form.days) || form.days < 1 || form.days > 365) return
    emit('confirm', { reason, days: form.days })
    return
  }
  if (props.action === 'delete') {
    if (form.confirmation !== 'DELETE' && form.confirmation !== '删除') return
    emit('confirm', { reason, confirmation: 'DELETE' })
    return
  }
  emit('confirm', { reason })
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="520px"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-if="trial" class="dialog-body">
      <el-alert
        v-if="action === 'delete'"
        title="删除后旧试用许可证和设备凭据将立即失效，历史记录与审计会继续保留。"
        type="error"
        :closable="false"
        show-icon
      />
      <el-alert
        v-else-if="action === 'reset'"
        title="重置会从当前服务器时间重新开始 7 天试用，并使旧试用凭据失效。"
        type="warning"
        :closable="false"
        show-icon
      />
      <div class="summary">
        <span>设备编号</span><strong class="mono">{{ trial.device }}</strong>
        <span>当前状态</span><strong>{{ trial.status }}</strong>
        <span>当前截止时间</span><strong>{{ formatUtc(trial.expiresAt) }}</strong>
        <template v-if="action === 'reset'">
          <span>重置后时长</span><strong>7 天（168 小时）</strong>
        </template>
      </div>
      <el-form label-position="top">
        <template v-if="action === 'extend'">
          <el-form-item label="延长天数" required>
            <el-input-number v-model="form.days" :min="1" :max="365" :step="1" />
          </el-form-item>
          <div class="preview"><span>延长后截止时间</span><strong>{{ preview }}</strong></div>
        </template>
        <el-form-item label="操作原因" required>
          <el-input
            v-model="form.reason"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
            placeholder="请输入操作原因"
          />
        </el-form-item>
        <el-form-item v-if="action === 'delete'" label="再次输入 DELETE 或 删除" required>
          <el-input v-model="form.confirmation" autocomplete="off" />
        </el-form-item>
      </el-form>
    </div>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button
        :type="action === 'delete' ? 'danger' : action === 'reset' ? 'warning' : 'primary'"
        :icon="icon"
        :loading="loading"
        :disabled="!form.reason.trim() || (action === 'delete' && form.confirmation !== 'DELETE' && form.confirmation !== '删除')"
        @click="submit"
      >
        {{ action === 'delete' ? '确认删除' : action === 'reset' ? '确认重置' : '确认延长' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.dialog-body { display: grid; gap: 18px; }
.summary { display: grid; grid-template-columns: 120px minmax(0, 1fr); gap: 9px 16px; padding: 14px; background: var(--surface-muted); border: 1px solid var(--border); }
.summary span, .preview span { color: var(--text-muted); }
.summary strong { overflow-wrap: anywhere; }
.preview { display: flex; justify-content: space-between; gap: 16px; margin: -4px 0 18px; padding: 10px 12px; border-left: 3px solid var(--accent); background: var(--surface-muted); }
</style>
