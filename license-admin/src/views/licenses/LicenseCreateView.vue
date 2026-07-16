<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { licensesApi } from '@/api/licenses'
import PageHeader from '@/components/PageHeader.vue'
import LicenseCodeResult from '@/components/LicenseCodeResult.vue'
import { apiErrorMessage } from '@/utils/errors'
const loading=ref(false);const results=ref<Array<Record<string,string>>>([])
const form=reactive({licenseType:'monthly',quantity:1,expiresAt:'',customerName:'',customerContact:'',remark:''})
const isBatch=computed(()=>form.quantity>1)
async function submit(){loading.value=true;try{const body={requestId:crypto.randomUUID(),licenseType:form.licenseType,quantity:form.quantity,expiresAt:form.licenseType==='fixed_date'?new Date(form.expiresAt).toISOString():undefined,customerName:form.customerName||undefined,customerContact:form.customerContact||undefined,remark:form.remark||undefined};const response=isBatch.value?await licensesApi.batch(body):await licensesApi.create(Object.fromEntries(Object.entries(body).filter(([key])=>key!=='quantity')));results.value=response.data.items.map((item:Record<string,string>)=>({...item,customerName:form.customerName,remark:form.remark}));ElMessage.success('授权创建成功')}catch(error){ElMessage.error(apiErrorMessage(error))}finally{loading.value=false}}
onBeforeRouteLeave(async()=>{if(!results.value.length)return true;try{await ElMessageBox.confirm('完整激活码离开后无法再次查看，确认已安全保存？','离开创建结果',{type:'warning'});return true}catch{return false}})
</script>
<template><div class="page"><PageHeader title="创建授权" description="支持单个或批量创建，批量上限 100 个"/><LicenseCodeResult v-if="results.length" :items="results"/><section v-else class="form-panel surface"><el-form label-position="top"><div class="grid"><el-form-item label="授权类型"><el-select v-model="form.licenseType"><el-option label="月卡（首次激活后30天）" value="monthly"/><el-option label="年卡（首次激活后365天）" value="yearly"/><el-option label="永久授权" value="permanent"/><el-option label="指定UTC到期时间" value="fixed_date"/></el-select></el-form-item><el-form-item label="创建数量"><el-input-number v-model="form.quantity" :min="1" :max="100"/></el-form-item><el-form-item v-if="form.licenseType==='fixed_date'" label="到期时间"><el-date-picker v-model="form.expiresAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss"/></el-form-item><el-form-item label="客户名称"><el-input v-model="form.customerName" maxlength="160"/></el-form-item><el-form-item label="联系方式"><el-input v-model="form.customerContact" maxlength="240"/></el-form-item></div><el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="4" maxlength="2000" show-word-limit/></el-form-item><div class="actions"><el-button type="primary" :loading="loading" @click="submit">{{ isBatch?'批量创建':'创建授权' }}</el-button></div></el-form></section></div></template>
<style scoped>.form-panel{max-width:820px;padding:22px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:0 20px}.actions{text-align:right}</style>
