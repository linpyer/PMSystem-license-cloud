<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import { clientReleasesApi, type ClientRelease, type ClientReleaseDraft } from '@/api/client-releases'
import { useAuthStore } from '@/stores/auth'
import { apiErrorMessage } from '@/utils/errors'
import { formatUtc } from '@/utils/date'

const auth = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const visible = ref(false)
const items = ref<ClientRelease[]>([])
const total = ref(0)
const page = ref(1)
const canEdit = computed(() => ['OWNER', 'ADMIN'].includes(auth.user?.role || ''))
const isOwner = computed(() => auth.user?.role === 'OWNER')
const form = reactive({
  product: 'DDREC', version: '', buildNumber: 1, gitCommit: '', edition: 'standard',
  environment: 'production', architecture: 'x64', channel: 'stable', title: '',
  fileName: '', downloadPath: '', fileSize: 1, sha256: '', signature: '',
  mandatory: false, publishedAt: '',
})

function statusLabel(value: string) { return ({ draft: '草稿', published: '已发布', withdrawn: '已下架' } as Record<string,string>)[value] || value }
function statusType(value: string) { return value === 'published' ? 'success' : value === 'withdrawn' ? 'info' : 'warning' }
function formatSize(value: number) { return value >= 1048576 ? `${(value / 1048576).toFixed(1)} MB` : `${(value / 1024).toFixed(1)} KB` }

async function load() {
  loading.value = true
  try { const data = (await clientReleasesApi.list(page.value, 50)).data; items.value = data.items; total.value = data.total }
  catch (error) { ElMessage.error(apiErrorMessage(error)) }
  finally { loading.value = false }
}

function openCreate() {
  Object.assign(form, { product:'DDREC',version:'',buildNumber:1,gitCommit:'',edition:'standard',environment:'production',architecture:'x64',channel:'stable',title:'',fileName:'',downloadPath:'',fileSize:1,sha256:'',signature:'',mandatory:false,publishedAt:new Date().toISOString() })
  visible.value = true
}
async function save() {
  saving.value = true
  try {
    await clientReleasesApi.create({ ...form } as ClientReleaseDraft)
    ElMessage.success('客户端更新草稿已创建')
    visible.value = false; await load()
  } catch (error) { ElMessage.error(apiErrorMessage(error)) }
  finally { saving.value = false }
}
async function publish(row: ClientRelease) {
  try { await ElMessageBox.confirm('系统将重新校验文件、SHA-256和Ed25519签名。校验通过后客户端立即可见。', '确认发布', { type:'warning' }); await clientReleasesApi.publish(row.id); ElMessage.success('版本已发布'); await load() }
  catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(apiErrorMessage(error)) }
}
async function withdraw(row: ClientRelease) {
  try { await ElMessageBox.confirm('下架后客户端将立即停止获取此版本，历史记录会保留。', '确认下架', { type:'warning' }); await clientReleasesApi.withdraw(row.id); ElMessage.success('版本已下架'); await load() }
  catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(apiErrorMessage(error)) }
}
async function showIntegrity(row: ClientRelease) {
  await ElMessageBox.alert(`<p><b>Git Commit</b><br><code>${row.gitCommit}</code></p><p><b>SHA-256</b><br><code class="hash">${row.sha256}</code></p>`, '发布完整性', { dangerouslyUseHTMLString:true, confirmButtonText:'关闭' })
}
onMounted(load)
</script>

<template><div class="page">
  <PageHeader title="客户端更新" description="管理 iVRec 客户端安装包；正式发布前强制校验文件、哈希与签名">
    <el-button v-if="canEdit" type="primary" @click="openCreate">新建草稿</el-button>
  </PageHeader>
  <section class="surface table-wrap">
    <el-table v-loading="loading" :data="items">
      <el-table-column prop="version" label="版本" width="110"><template #default="s">V{{ s.row.version }}</template></el-table-column>
      <el-table-column prop="buildNumber" label="Build" width="80"/>
      <el-table-column prop="edition" label="Edition" width="100"/>
      <el-table-column prop="environment" label="环境" width="110"/>
      <el-table-column prop="architecture" label="架构" width="80"/>
      <el-table-column prop="channel" label="通道" width="90"/>
      <el-table-column label="状态" width="100"><template #default="s"><el-tag :type="statusType(s.row.status)">{{ statusLabel(s.row.status) }}</el-tag></template></el-table-column>
      <el-table-column label="安装包大小" width="120"><template #default="s">{{ formatSize(s.row.fileSize) }}</template></el-table-column>
      <el-table-column label="发布时间" min-width="170"><template #default="s">{{ formatUtc(s.row.publishedAt) }}</template></el-table-column>
      <el-table-column label="操作" width="210" fixed="right"><template #default="s">
        <el-button link @click="showIntegrity(s.row)">SHA / Commit</el-button>
        <el-button v-if="isOwner && s.row.status==='draft'" link type="success" @click="publish(s.row)">发布</el-button>
        <el-button v-if="isOwner && s.row.status==='published'" link type="warning" @click="withdraw(s.row)">下架</el-button>
      </template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page" :total="total" :page-size="50" layout="total, prev, pager, next" @change="load"/>
  </section>
  <el-dialog v-model="visible" title="新建客户端更新草稿" width="760px">
    <el-form label-position="top">
      <div class="grid">
        <el-form-item label="版本"><el-input v-model="form.version" placeholder="1.3.1"/></el-form-item><el-form-item label="Build"><el-input-number v-model="form.buildNumber" :min="1"/></el-form-item>
        <el-form-item label="正式版本"><el-select v-model="form.edition"><el-option label="Standard" value="standard"/><el-option label="License-Production" value="license"/></el-select></el-form-item>
        <el-form-item label="环境"><el-input model-value="production" disabled/></el-form-item>
        <el-form-item label="通道"><el-input model-value="stable" disabled/></el-form-item><el-form-item label="Git Commit"><el-input v-model="form.gitCommit"/></el-form-item>
        <el-form-item label="文件名"><el-input v-model="form.fileName"/></el-form-item><el-form-item label="文件大小（字节）"><el-input-number v-model="form.fileSize" :min="1"/></el-form-item>
        <el-form-item class="wide" label="下载路径"><el-input v-model="form.downloadPath" placeholder="/releases/stable/standard/1.3.1/DDREC-...exe"/></el-form-item>
        <el-form-item class="wide" label="SHA-256"><el-input v-model="form.sha256"/></el-form-item>
        <el-form-item class="wide" label="Ed25519签名"><el-input v-model="form.signature" type="textarea" :rows="2"/></el-form-item>
        <el-form-item label="Manifest发布时间"><el-input v-model="form.publishedAt"/></el-form-item>
      </div>
      <el-form-item label="标题"><el-input v-model="form.title" placeholder="iVRec V1.4.0"/></el-form-item>
    </el-form>
    <template #footer><el-button @click="visible=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存草稿</el-button></template>
  </el-dialog>
</div></template>

<style scoped>.table-wrap{padding:14px}.el-pagination{justify-content:flex-end;margin-top:14px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:0 18px}.wide{grid-column:1/-1}:deep(.hash){word-break:break-all}</style>
