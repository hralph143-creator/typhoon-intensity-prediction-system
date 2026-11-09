<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Refresh,Search,DataAnalysis,Aim,TrendCharts,Document } from '@element-plus/icons-vue'
import { getStatistics } from '@/api/typhoons'
import { getExperiments,getModels } from '@/api/ml'
import { getReports } from '@/api/reports'
import { era5Api } from '@/api/era5'
import DataChart from '@/components/DataChart.vue'
import StatusIndicator from '@/components/StatusIndicator.vue'
import { useSystemStore } from '@/stores/system'
import type { Statistics } from '@/types/typhoon'
import { jobLabel, utc } from '@/utils/typhoon'

const system = useSystemStore()
const statistics = ref<Statistics | null>(null),cmaStatistics=ref<Statistics|null>(null),era5=ref<any>(),models=ref<any[]>([]),experiments=ref<any[]>([]),reports=ref<any[]>([])
const error = ref('')
const yearlyOption = computed(() => ({
  tooltip: { trigger: 'axis' }, grid: { left: 45, right: 20, top: 30, bottom: 35 },
  xAxis: { type: 'category', data: statistics.value?.yearly.map(item => String(item.year)), axisLabel: { color: '#6a7b8d' } },
  yAxis: { type: 'value', name: '事件数', minInterval: 1, splitLine: { lineStyle: { color: '#edf0f4' } } },
  series: [{ name: '台风事件', type: 'bar', data: statistics.value?.yearly.map(item => item.count), barMaxWidth: 32, itemStyle: { color: '#457da6' } }],
}))
async function refresh() {
  error.value = ''
  await system.refresh()
  try { [statistics.value,cmaStatistics.value,era5.value,models.value,experiments.value,reports.value]=await Promise.all([getStatistics('ibtracs'),getStatistics('cma'),era5Api.statistics(),getModels(),getExperiments(),getReports()]) } catch { statistics.value = null; error.value = '系统概览暂不可用，请稍后刷新。' }
}
const latestExperiment=computed(()=>experiments.value[0]),latestReport=computed(()=>reports.value[0])
const shortcuts=[['/history','查询历史台风',Search],['/wind-field','查看 ERA5 风场',DataAnalysis],['/prediction','执行强度预测',Aim],['/evaluation','查看模型评估',TrendCharts],['/reports','生成分析报告',Document]] as const
onMounted(refresh)
</script>

<template>
  <section v-loading="system.loading" class="page-stack">
    <div class="page-heading"><h2>系统运行概览</h2><el-button :icon="Refresh" @click="refresh">刷新状态</el-button></div>
    <el-alert v-if="system.error || error" :title="system.error || error" type="error" :closable="false" show-icon />
    <div class="status-grid overview-grid"><article class="status-card"><span class="card-label">IBTrACS 台风事件</span><strong class="stat-value">{{statistics?.all_event_count?.toLocaleString()??'—'}}</strong><span>观测 {{statistics?.observation_count?.toLocaleString()??'—'}} 条</span></article><article class="status-card"><span class="card-label">CMA 独立台风事件</span><strong class="stat-value">{{cmaStatistics?.all_event_count?.toLocaleString()??'—'}}</strong><span>观测 {{cmaStatistics?.observation_count?.toLocaleString()??'—'}} 条</span></article><article class="status-card"><span class="card-label">ERA5 四时次样本</span><strong class="stat-value">{{era5?.spatiotemporal_samples??'—'}}</strong><span>{{era5?.processing_version??'等待数据'}}</span></article><article class="status-card"><span class="card-label">可用模型</span><strong class="stat-value">{{models.length}}</strong><span>历史实验 {{experiments.length}} 项</span></article></div>
    <el-card shadow="never" class="data-card quick-card"><template #header><strong>快捷操作</strong></template><div class="quick-actions"><RouterLink v-for="item in shortcuts" :key="item[0]" :to="item[0]"><el-icon><component :is="item[2]"/></el-icon><span>{{item[1]}}</span></RouterLink></div></el-card>
    <el-card v-if="statistics?.typhoon_count" shadow="never" class="data-card"><template #header><strong>年度 MAIN 主轨迹事件数量</strong></template><DataChart :option="yearlyOption" label="已导入真实台风的年度 MAIN 主轨迹事件统计" /></el-card>
    <el-alert v-else-if="statistics" title="尚无历史台风数据" description="请在“历史台风数据 → 数据接入与任务”下载 NOAA 官方数据，或上传真实 IBTrACS CSV 文件。" type="info" :closable="false" show-icon />
    <div class="home-bottom"><el-card shadow="never" class="data-card"><template #header><strong>系统状态</strong></template><el-descriptions :column="1"><el-descriptions-item label="后端与数据库"><StatusIndicator :active="system.backendOnline&&system.health?.database==='connected'" active-text="运行正常" inactive-text="连接失败"/></el-descriptions-item><el-descriptions-item label="最近数据导入">{{utc(statistics?.last_import_at)}}</el-descriptions-item><el-descriptions-item label="最近处理任务">{{statistics?.latest_job?jobLabel(statistics.latest_job.status):'暂无任务'}}</el-descriptions-item></el-descriptions></el-card><el-card shadow="never" class="data-card"><template #header><strong>最近模型实验</strong></template><el-empty v-if="!latestExperiment" description="尚无实验记录" :image-size="56"/><el-descriptions v-else :column="1"><el-descriptions-item label="实验">{{latestExperiment.name}}</el-descriptions-item><el-descriptions-item label="模型">{{latestExperiment.model_type.toUpperCase()}}</el-descriptions-item><el-descriptions-item label="完成时间">{{utc(latestExperiment.finished_at)}}</el-descriptions-item></el-descriptions></el-card><el-card shadow="never" class="data-card"><template #header><strong>最近科研报告</strong></template><el-empty v-if="!latestReport" description="尚无报告记录" :image-size="56"/><el-descriptions v-else :column="1"><el-descriptions-item label="报告">{{latestReport.report_title}}</el-descriptions-item><el-descriptions-item label="状态">{{latestReport.report_status}}</el-descriptions-item><el-descriptions-item label="生成时间">{{utc(latestReport.completed_at)}}</el-descriptions-item></el-descriptions></el-card></div>
  </section>
</template>
<style scoped>.overview-grid{grid-template-columns:repeat(4,minmax(180px,1fr))}.quick-actions{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}.quick-actions a{display:flex;align-items:center;gap:10px;padding:15px;border:1px solid var(--app-border);background:#f8fafc;color:#29445f;border-radius:4px}.quick-actions a:hover{border-color:#8cb4d2;text-decoration:none;background:#f1f7fb}.home-bottom{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}@media(max-width:1180px){.quick-actions{grid-template-columns:repeat(3,1fr)}.home-bottom{grid-template-columns:1fr}.overview-grid{grid-template-columns:repeat(2,1fr)}}</style>
