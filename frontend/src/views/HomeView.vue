<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { getStatistics } from '@/api/typhoons'
import DataChart from '@/components/DataChart.vue'
import StatusIndicator from '@/components/StatusIndicator.vue'
import { useSystemStore } from '@/stores/system'
import type { Statistics } from '@/types/typhoon'
import { jobLabel, utc } from '@/utils/typhoon'

const system = useSystemStore()
const statistics = ref<Statistics | null>(null)
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
  try { statistics.value = await getStatistics() } catch { statistics.value = null; error.value = '历史数据统计暂不可用。' }
}
onMounted(refresh)
</script>

<template>
  <section v-loading="system.loading" class="page-stack">
    <div class="page-heading"><div><h2>系统运行概览</h2><p>实际运行状态与真实历史数据统计</p></div><el-button :icon="Refresh" @click="refresh">刷新状态</el-button></div>
    <el-alert v-if="system.error || error" :title="system.error || error" type="error" :closable="false" show-icon />
    <div class="status-grid">
      <article class="status-card"><span class="card-label">后端服务与数据库</span><StatusIndicator :active="system.backendOnline && system.health?.database === 'connected'" active-text="运行正常" inactive-text="连接失败"/><strong>{{ system.info?.version ? `版本 ${system.info.version}` : '等待服务响应' }}</strong></article>
      <article class="status-card"><span class="card-label">MAIN 主轨迹事件</span><strong class="stat-value">{{ statistics?.typhoon_count.toLocaleString() ?? '—' }}<small> 个事件</small></strong><span class="muted-note">全部轨迹事件 {{ statistics?.all_event_count?.toLocaleString() ?? '—' }} 个</span><RouterLink to="/history">打开历史档案 →</RouterLink></article>
      <article class="status-card"><span class="card-label">观测记录</span><strong class="stat-value">{{ statistics?.observation_count.toLocaleString() ?? '—' }}<small> 条</small></strong><span class="muted-note">主轨迹观测 {{ statistics?.main_observation_count.toLocaleString() ?? '—' }} 条</span></article>
      <article class="status-card"><span class="card-label">数据覆盖年份</span><strong>{{ statistics?.years.length ? `${Math.min(...statistics.years)}—${Math.max(...statistics.years)}` : '暂无数据' }}</strong><span class="muted-note">仅统计已入库数据</span></article>
    </div>
    <el-card v-if="statistics?.typhoon_count" shadow="never" class="data-card"><template #header><div class="card-header"><strong>年度 MAIN 主轨迹事件数量</strong><span>BASIN=WP · 包括资料中的热带低压等事件</span></div></template><DataChart :option="yearlyOption" label="已导入真实台风的年度 MAIN 主轨迹事件统计" /><p class="muted-note">仅统计有 MAIN 主轨迹的事件。临时轨迹、支轨另行保存；2025 年主轨迹资料可能尚未完备，可在历史档案勾选“包含临时轨迹和支轨事件”查询。</p></el-card>
    <el-alert v-else-if="statistics" title="尚无历史台风数据" description="请在“历史台风数据 → 数据接入与任务”下载 NOAA 官方数据，或上传真实 IBTrACS CSV 文件。" type="info" :closable="false" show-icon />
    <el-card shadow="never" class="data-card"><template #header><div class="card-header"><strong>数据源接入状态</strong><RouterLink to="/settings">数据源管理 →</RouterLink></div></template><el-table :data="system.dataSources" empty-text="后端未返回数据源状态"><el-table-column prop="name" label="数据源" min-width="210"/><el-table-column prop="provider" label="提供机构" min-width="150"/><el-table-column label="状态" width="160"><template #default="{row}"><StatusIndicator :active="row.connected" :active-text="row.status_text" :inactive-text="row.status_text"/></template></el-table-column><el-table-column prop="file_count" label="本地文件" width="100"/><el-table-column prop="local_path" label="存储位置" min-width="260" show-overflow-tooltip/></el-table></el-card>
    <el-card v-if="statistics" shadow="never" class="data-card"><template #header><strong>最近数据处理</strong></template><el-descriptions :column="2"><el-descriptions-item label="最近成功导入">{{ utc(statistics.last_import_at) }}</el-descriptions-item><el-descriptions-item label="最近任务">{{ statistics.latest_job ? jobLabel(statistics.latest_job.status) : '暂无任务' }}</el-descriptions-item><el-descriptions-item label="CMA 风速缺测／特殊编码">{{ statistics.missing_cma_wind_count.toLocaleString() }} 条</el-descriptions-item><el-descriptions-item label="模型与实验"><RouterLink to="/evaluation">查看真实评估 →</RouterLink></el-descriptions-item></el-descriptions></el-card>
  </section>
</template>
