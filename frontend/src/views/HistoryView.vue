<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getStatistics, getTyphoons } from '@/api/typhoons'
import IbtracsManager from '@/components/IbtracsManager.vue'
import type { TyphoonEvent, TyphoonFilters } from '@/types/typhoon'
import { categoryNames, normalizeFilters, numberText, utc } from '@/utils/typhoon'

const router = useRouter()
const filters = reactive<TyphoonFilters>({ page: 1, page_size: 20, sort_by: 'season', sort_order: 'desc', source: 'ibtracs', include_spurs: false })
const items = ref<TyphoonEvent[]>([])
const total = ref(0)
const years = ref<number[]>(Array.from({ length: 12 }, (_, i) => 2025 - i))
const loading = ref(false)
const error = ref('')
const tab = ref('archive')
let requestId = 0
function openDetail(row: TyphoonEvent) { router.push(`/history/${row.id}`) }
async function load(reset = false) {
  if (reset) filters.page = 1
  const current = ++requestId
  loading.value = true
  error.value = ''
  try {
    const result = await getTyphoons(normalizeFilters(filters))
    if (current === requestId) { items.value = result.items; total.value = result.total }
  } catch { if (current === requestId) error.value = '无法获取历史台风，请确认后端服务运行正常。' }
  finally { if (current === requestId) loading.value = false }
}
function reset() {
  Object.assign(filters, { season: undefined, name: undefined, sid: undefined, min_wind: undefined, max_wind: undefined, category: undefined, source: 'ibtracs', sort_by: 'season', sort_order: 'desc', include_spurs: false })
  load(true)
}
onMounted(async () => {
  load()
  try { const stats = await getStatistics(); if (stats.years.length) years.value = stats.years.slice().sort((a, b) => b - a) } catch { /* 列表独立显示失败状态 */ }
})
</script>

<template>
  <section class="page-stack">
    <div class="page-heading"><h2>历史台风档案</h2><el-button @click="tab = tab === 'archive' ? 'source' : 'archive'">{{ tab === 'archive' ? '数据接入与任务' : '返回历史档案' }}</el-button></div>
    <el-tabs v-model="tab" @tab-change="tab === 'archive' && load()">
      <el-tab-pane label="台风档案" name="archive">
        <el-card shadow="never" class="data-card">
          <el-form class="filter-form" label-position="top" @submit.prevent="load(true)">
            <el-form-item label="年份"><el-select v-model="filters.season" clearable placeholder="全部年份"><el-option v-for="year in years" :key="year" :label="String(year)" :value="year" /></el-select></el-form-item>
            <el-form-item label="台风名称"><el-input v-model="filters.name" clearable placeholder="如 HAIYAN" @keyup.enter="load(true)" /></el-form-item>
            <el-form-item label="台风编号（SID）"><el-input v-model="filters.sid" clearable placeholder="输入编号片段" @keyup.enter="load(true)" /></el-form-item>
            <el-form-item label="最强 CMA 等级"><el-select v-model="filters.category" clearable placeholder="全部等级"><el-option v-for="(name, value) in categoryNames" :key="value" :label="name" :value="Number(value)" /></el-select></el-form-item>
            <el-form-item label="数据来源"><el-select v-model="filters.source"><el-option label="NOAA IBTrACS" value="ibtracs" /></el-select></el-form-item>
            <el-form-item label="最大风速下限（m/s）"><el-input-number v-model="filters.min_wind" :min="0" :max="150" :controls="false" placeholder="不限" /></el-form-item>
            <el-form-item label="最大风速上限（m/s）"><el-input-number v-model="filters.max_wind" :min="0" :max="150" :controls="false" placeholder="不限" /></el-form-item>
            <el-form-item label="排序"><el-select v-model="filters.sort_by"><el-option label="年份" value="season" /><el-option label="名称" value="name" /><el-option label="CMA 最大风速" value="maximum_wind" /><el-option label="起始时间" value="first_observation" /></el-select></el-form-item>
            <el-form-item label="顺序"><el-select v-model="filters.sort_order"><el-option label="降序" value="desc" /><el-option label="升序" value="asc" /></el-select></el-form-item>
            <el-form-item label="轨迹事件范围"><el-checkbox v-model="filters.include_spurs" @change="load(true)">包含临时轨迹和支轨事件</el-checkbox></el-form-item>
            <div class="filter-actions"><el-button type="primary" native-type="submit" :loading="loading">查询</el-button><el-button @click="reset">重置</el-button></div>
          </el-form>
        </el-card>
        <el-alert v-if="error" class="section-gap" :title="error" type="error" :closable="false" show-icon />
        <el-card shadow="never" class="data-card section-gap">
          <template #header><div class="card-header"><strong>台风列表 <span class="table-count">{{ total.toLocaleString() }} 个事件</span></strong><span>{{ filters.include_spurs ? '包含临时轨迹和支轨' : '默认仅展示有 MAIN 主轨迹的事件' }} · CMA 2 分钟平均 · m/s</span></div></template>
          <el-table v-loading="loading" :data="items" stripe @row-dblclick="openDetail">
            <template #empty><div class="empty-state"><strong>暂无符合条件的历史台风</strong><p>可调整筛选条件，或前往“数据接入与任务”导入真实 IBTrACS 文件。</p></div></template>
            <el-table-column prop="sid" label="IBTrACS 编号" min-width="155" />
            <el-table-column prop="name" label="名称" min-width="120" />
            <el-table-column prop="season" label="年份" width="76" />
            <el-table-column label="轨迹类型" min-width="160"><template #default="{row}"><el-tag v-for="type in row.track_types ?? []" :key="type" :type="type === 'MAIN' ? 'info' : 'warning'" size="small" class="track-type-tag">{{ type }}</el-tag></template></el-table-column>
            <el-table-column label="起止时间（UTC）" min-width="195"><template #default="{row}"><span>{{ utc(row.first_observation).replace(' UTC','') }}</span><br/><span class="muted-note">{{ utc(row.last_observation).replace(' UTC','') }}</span></template></el-table-column>
            <el-table-column prop="observation_count" label="观测点" width="90" />
            <el-table-column label="最大风速" width="104"><template #default="{row}">{{ numberText(row.maximum_wind) }}</template></el-table-column>
            <el-table-column label="最低气压" width="104"><template #default="{row}">{{ numberText(row.minimum_pressure, 0) }}</template></el-table-column>
            <el-table-column label="操作" width="86" fixed="right"><template #default="{row}"><el-button type="primary" link @click="router.push(`/history/${row.id}`)">查看详情</el-button></template></el-table-column>
          </el-table>
          <el-pagination v-model:current-page="filters.page" v-model:page-size="filters.page_size" :page-sizes="[10,20,50,100]" :total="total" layout="total, sizes, prev, pager, next" class="pagination" @current-change="load()" @size-change="load(true)" />
        </el-card>
      </el-tab-pane>
      <el-tab-pane label="数据接入与任务" name="source" lazy><el-card shadow="never" class="data-card"><IbtracsManager /></el-card></el-tab-pane>
    </el-tabs>
  </section>
</template>
