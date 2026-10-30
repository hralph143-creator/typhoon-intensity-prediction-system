<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref} from 'vue'
import {ElMessage,ElMessageBox} from 'element-plus'
import {createReport,deleteReport,getReports,getReportTypes,reportUrl,type ReportRecord} from '@/api/reports'
import {getTyphoons} from '@/api/typhoons'
import {getExperiments} from '@/api/ml'
const types=ref<any[]>([]),reports=ref<ReportRecord[]>([]),typhoons=ref<any[]>([]),experiments=ref<any[]>([]),loading=ref(false),preview=ref(''),previewOpen=ref(false)
const form=ref({report_type:'typhoon',title:'',typhoon_id:undefined as number|undefined,experiment_id:undefined as string|undefined,force:false})
const successfulExperiments=computed(()=>experiments.value.filter(x=>x.status==='succeeded'))
let timer:number|undefined
async function refresh(){reports.value=await getReports()}
async function submit(){loading.value=true;try{await createReport(form.value);ElMessage.success('报告任务已创建');await refresh()}finally{loading.value=false}}
async function remove(row:ReportRecord){await ElMessageBox.confirm('删除该报告及其生成文件？','二次确认',{type:'warning'});await deleteReport(row.id);await refresh()}
function show(row:ReportRecord){preview.value=reportUrl(row.id,'preview');previewOpen.value=true}
function statusType(status:string){return status==='succeeded'?'success':status==='failed'?'danger':'warning'}
onMounted(async()=>{loading.value=true;try{[types.value,reports.value,typhoons.value,experiments.value]=await Promise.all([getReportTypes(),getReports(),getTyphoons({page:1,page_size:100,sort_by:'maximum_wind',sort_order:'desc'}).then(x=>x.items),getExperiments()]);timer=window.setInterval(refresh,2500)}finally{loading.value=false}})
onBeforeUnmount(()=>timer&&clearInterval(timer))
</script>
<template><section v-loading="loading" class="page-stack"><div class="page-heading"><h2>科研分析报告中心</h2><el-button @click="refresh">刷新</el-button></div>
<el-card shadow="never"><template #header><strong>新建报告</strong></template><el-form label-position="top" class="report-form"><el-form-item label="报告类型"><el-select v-model="form.report_type"><el-option v-for="x in types" :key="x.code" :label="x.name" :value="x.code"/></el-select></el-form-item><el-form-item label="自定义标题"><el-input v-model="form.title" maxlength="200" placeholder="留空使用默认标题"/></el-form-item><el-form-item v-if="form.report_type==='typhoon'" label="历史台风"><el-select v-model="form.typhoon_id" filterable><el-option v-for="x in typhoons" :key="x.id" :label="`${x.sid} · ${x.name}`" :value="x.id"/></el-select></el-form-item><el-form-item v-if="form.report_type==='model'" label="正式实验"><el-select v-model="form.experiment_id" filterable><el-option v-for="x in successfulExperiments" :key="x.id" :label="`${x.name} · ${x.model_type.toUpperCase()}`" :value="x.id"/></el-select></el-form-item><el-form-item><el-checkbox v-model="form.force">即使数据未变化也重新生成</el-checkbox></el-form-item><el-form-item><el-button type="primary" @click="submit">生成报告</el-button></el-form-item></el-form></el-card>
<el-card shadow="never"><template #header><strong>报告记录</strong></template><el-table :data="reports"><el-table-column prop="report_title" label="标题" min-width="220"/><el-table-column prop="report_type" label="类型" width="120"/><el-table-column prop="created_at" label="创建时间" width="185"/><el-table-column label="状态" width="120"><template #default="{row}"><el-tag :type="statusType(row.report_status)">{{row.report_status}}</el-tag></template></el-table-column><el-table-column label="操作" width="290"><template #default="{row}"><el-button link :disabled="row.report_status!=='succeeded'" @click="show(row)">预览</el-button><el-link :href="reportUrl(row.id,'html')" :disabled="row.report_status!=='succeeded'">HTML</el-link><el-link :href="reportUrl(row.id,'pdf')" :disabled="row.report_status!=='succeeded'">PDF</el-link><el-button link type="danger" :disabled="['queued','generating'].includes(row.report_status)" @click="remove(row)">删除</el-button></template></el-table-column></el-table></el-card>
<el-dialog v-model="previewOpen" width="86%" title="报告预览" destroy-on-close><iframe class="report-preview" :src="preview" title="科研报告预览"/></el-dialog></section></template>
