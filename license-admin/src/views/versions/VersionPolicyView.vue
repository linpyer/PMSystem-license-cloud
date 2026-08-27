<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { versionsApi } from '@/api/versions'
import PageHeader from '@/components/PageHeader.vue'
import { useAuthStore } from '@/stores/auth'
import { apiErrorMessage } from '@/utils/errors'
const auth=useAuthStore();const loading=ref(false);const form=reactive({recommendedVersion:'',minimumSupportedVersion:'',downloadUrl:'',updatedAt:''})
async function load(){Object.assign(form,(await versionsApi.get()).data.policy)}async function save(){loading.value=true;try{await versionsApi.save({recommendedVersion:form.recommendedVersion,minimumSupportedVersion:form.minimumSupportedVersion,downloadUrl:form.downloadUrl||null});ElMessage.success('版本策略已保存');await load()}catch(e){ElMessage.error(apiErrorMessage(e))}finally{loading.value=false}}onMounted(load)
</script>
<template><div class="page"><PageHeader title="版本策略" description="语义版本比较；最低版本会影响客户端授权验证"/><section class="surface form-panel"><el-alert title="推荐版本允许用户继续使用并返回升级建议；低于最低支持版本的客户端将被拒绝验证。" type="warning" :closable="false"/><el-form label-position="top" class="form"><div class="grid"><el-form-item label="推荐版本"><el-input v-model="form.recommendedVersion" placeholder="1.4.0"/></el-form-item><el-form-item label="最低支持版本"><el-input v-model="form.minimumSupportedVersion" placeholder="1.4.0"/></el-form-item></div><el-form-item label="下载地址"><el-input v-model="form.downloadUrl" placeholder="https://..."/></el-form-item><el-button v-if="auth.user?.role==='OWNER'" type="primary" :loading="loading" @click="save">保存版本策略</el-button><span v-else class="muted">仅 OWNER 可以修改版本策略</span></el-form></section></div></template><style scoped>.form-panel{max-width:820px;padding:20px}.form{margin-top:20px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}</style>
