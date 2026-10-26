<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getTrack, getTyphoon } from '@/api/typhoons'
import DataChart from '@/components/DataChart.vue'
import TyphoonMap from '@/components/TyphoonMap.vue'
import type { Observation, TyphoonDetail } from '@/types/typhoon'
import { agencyLabels, type Agency, categoryNames, clampSelection, numberText, qualityLabel, utc, windValue } from '@/utils/typhoon'
import { intensityOption } from '@/utils/chartOptions'

const route = useRoute(), router = useRouter()
const detail = ref<TyphoonDetail | null>(null)
const points = ref<Observation[]>([])
const loading = ref(false), trackLoading = ref(false), error = ref('')
const trackType = ref('MAIN'), agency = ref<Agency>('cma'), pressureAgency = ref<'cma' | 'wmo'>('cma')
const selectedIndex = ref(0), page = ref(1), pageSize = ref(15)
const selected = computed(() => points.value[selectedIndex.value])
const tablePoints = computed(() => points.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const chartOption = computed(() => intensityOption(points.value, agency.value, pressureAgency.value, selectedIndex.value))
const tableRef = ref<{ setCurrentRow: (row: Observation | undefined) => void }>()
let requestId = 0
function selectPoint(index: number) {
  selectedIndex.value = clampSelection(index, points.value.length)
  page.value = Math.floor(selectedIndex.value / pageSize.value) + 1
}
function selectRow(row: Observation) { selectPoint(points.value.findIndex(point => point.id === row.id)) }
function selectSlider(value: number | number[]) { selectPoint(Number(value)) }
async function loadTrack() {
  const current = ++requestId
  trackLoading.value = true
  error.value = ''
  points.value = []
  try {
    const result = await getTrack(Number(route.params.id), trackType.value)
    if (current === requestId) { points.value = result.items; selectedIndex.value = 0; page.value = 1 }
  } catch { if (current === requestId) error.value = '轨迹数据加载失败，请稍后重试。' }
  finally { if (current === requestId) trackLoading.value = false }
}
async function load() {
  loading.value = true; error.value = ''
  try {
    detail.value = await getTyphoon(Number(route.params.id))
    const types = detail.value.track_types
    trackType.value = types.includes('MAIN') ? 'MAIN' : (types[0] ?? 'MAIN')
    await loadTrack()
  } catch { detail.value = null; error.value = '未找到该台风或后端连接失败。' }
  finally { loading.value = false }
}
watch(selected, point => tableRef.value?.setCurrentRow(point), { flush: 'post' })
watch(() => route.params.id, load)
onMounted(load)
</script>

<template>
  <section v-loading="loading" class="page-stack">
    <div class="page-heading"><div><el-button link type="primary" @click="router.push('/history')">← 返回历史档案</el-button><h2 class="detail-title">{{ detail?.name || '台风详情' }} <span>{{ detail?.sid }}</span></h2><p>真实历史观测 · 统一使用 UTC 时间</p></div></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="detail">
      <el-card shadow="never" class="data-card backtest-entry"><div><strong>历史强度回测</strong><p class="muted-note">选择已保存模型和有效起报时刻，预测未来6小时风速。</p></div><el-button type="primary" @click="router.push({path:'/prediction',query:{typhoon_id:detail.id}})">前往历史回测预测</el-button></el-card>
      <el-card shadow="never" class="data-card">
        <el-descriptions :column="3" border>
          <el-descriptions-item label="年份">{{ detail.season }}</el-descriptions-item>
          <el-descriptions-item label="数据来源">NOAA IBTrACS</el-descriptions-item>
          <el-descriptions-item label="观测点数量">{{ detail.observation_count }}</el-descriptions-item>
          <el-descriptions-item label="CMA 最大风速">{{ numberText(detail.maximum_wind) }} m/s</el-descriptions-item>
          <el-descriptions-item label="CMA 最低气压">{{ numberText(detail.minimum_pressure, 0) }} hPa</el-descriptions-item>
          <el-descriptions-item label="最强 CMA 等级">{{ detail.maximum_category == null ? '缺测' : categoryNames[detail.maximum_category] }}</el-descriptions-item>
          <el-descriptions-item label="观测起止" :span="3">{{ utc(detail.first_observation) }} — {{ utc(detail.last_observation) }}</el-descriptions-item>
        </el-descriptions>
      </el-card>
    <el-alert title="统计口径" description="风速默认采用 CMA 2 分钟平均，缺测不替换。CMA 的 17 kn 为“低于 10 m/s”特殊编码，仅保留原值。记录可能包括 IBTrACS 插值时次；仅纳入 BASIN=WP 观测。相同时次有冲突版本时，路径与曲线选用最近导入版本；原始冲突记录及来源仍保存在数据库中。" type="info" :closable="false" show-icon />
      <el-card v-loading="trackLoading" shadow="never" class="data-card">
        <template #header><div class="card-header"><strong>历史路径</strong><div class="inline-controls"><span>轨迹类型</span><el-select v-model="trackType" style="width:190px" @change="loadTrack"><el-option v-for="type in detail.track_types" :key="type" :label="type" :value="type" /></el-select></div></div></template>
        <template v-if="points.length">
          <TyphoonMap :points="points" :selected-index="selectedIndex" @select="selectPoint" />
          <div class="map-legend"><span><i style="background:#4692bb"/>热带低压以下</span><span><i style="background:#3ca778"/>热带风暴</span><span><i style="background:#d5a130"/>强热带风暴</span><span><i style="background:#d88034"/>台风</span><span><i style="background:#cb5861"/>强台风</span><span><i style="background:#8c5cb1"/>超强台风</span><span><i style="background:#8995a4"/>缺测／特殊编码</span></div>
          <div class="timeline-controls"><el-button size="small" :disabled="selectedIndex === 0" @click="selectPoint(selectedIndex - 1)">上一时次</el-button><el-slider :model-value="selectedIndex" :min="0" :max="Math.max(1, points.length - 1)" :show-tooltip="false" @update:model-value="selectSlider" /><el-button size="small" :disabled="selectedIndex === points.length - 1" @click="selectPoint(selectedIndex + 1)">下一时次</el-button></div>
          <div v-if="selected" class="selected-observation"><strong>{{ utc(selected.observation_time) }}</strong><span>{{ numberText(selected.latitude, 2) }}°N，{{ numberText(selected.longitude, 2) }}°E</span><span>{{ agencyLabels[agency] }}：{{ numberText(windValue(selected, agency)) }} m/s</span><span>{{ pressureAgency.toUpperCase() }} 气压：{{ numberText(selected[`${pressureAgency}_pressure`], 0) }} hPa</span><span v-if="agency === 'wmo'">负责机构：{{ selected.wmo_agency || '缺测' }}</span></div>
        </template>
        <el-empty v-else description="该轨迹类型暂无有效观测点" />
      </el-card>
      <el-card shadow="never" class="data-card">
        <template #header><div class="card-header"><strong>风速与中心气压变化</strong><div class="inline-controls"><el-select v-model="agency" style="width:245px"><el-option v-for="(label, value) in agencyLabels" :key="value" :value="value" :label="label" /></el-select><el-select v-model="pressureAgency" style="width:155px"><el-option label="CMA 中心气压" value="cma" /><el-option label="WMO 中心气压" value="wmo" /></el-select></div></div></template>
        <DataChart v-if="points.length" :option="chartOption" :selected-index="selectedIndex" label="真实历史风速与中心气压变化曲线" @select="selectPoint" />
        <el-empty v-else description="暂无可绘制数据" />
        <p class="muted-note">缺测点以断线表示。不同机构的风速分别查看；WMO 平均时段依实际负责机构而异。点击曲线观测点可联动历史路径。</p>
      </el-card>
      <el-card shadow="never" class="data-card">
        <template #header><div class="card-header"><strong>历史观测记录</strong><span>当前轨迹 {{ trackType }} · {{ points.length }} 个观测点</span></div></template>
        <el-table ref="tableRef" :data="tablePoints" highlight-current-row row-key="id" @row-click="selectRow">
          <el-table-column label="时间（UTC）" min-width="180"><template #default="{row}">{{ utc(row.observation_time).replace(' UTC','') }}</template></el-table-column>
          <el-table-column label="纬度／经度" min-width="145"><template #default="{row}">{{ numberText(row.latitude, 2) }} / {{ numberText(row.longitude, 2) }}</template></el-table-column>
          <el-table-column label="CMA 原始风速 kn" min-width="130"><template #default="{row}">{{ numberText(row.cma_wind) }}</template></el-table-column>
          <el-table-column label="CMA 风速 m/s" min-width="115"><template #default="{row}">{{ numberText(row.cma_wind_ms) }}</template></el-table-column>
          <el-table-column label="CMA 气压 hPa" min-width="120"><template #default="{row}">{{ numberText(row.cma_pressure, 0) }}</template></el-table-column>
          <el-table-column label="来源文件" width="100"><template #default="{row}">#{{ row.source_file_id }}</template></el-table-column>
          <el-table-column label="质量标记" min-width="190"><template #default="{row}"><span v-if="!row.quality_flags.length" class="muted-note">无附加标记</span><el-tooltip v-else :content="row.quality_flags.join('，')"><span class="quality-text">{{ row.quality_flags.map(qualityLabel).join('，') }}</span></el-tooltip></template></el-table-column>
        </el-table>
        <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="points.length" :page-sizes="[15,30,50]" layout="total, sizes, prev, pager, next" class="pagination" />
      </el-card>
      <el-card shadow="never" class="data-card"><template #header><strong>数据版本与来源</strong></template><article v-for="file in detail.source_files" :key="file.id" class="file-record"><strong>#{{ file.id }} · {{ file.filename }}</strong><p>{{ file.version }} · 导入时间 {{ utc(file.imported_at) }}</p><div class="hash-text">SHA-256：{{ file.sha256 }}</div><div class="hash-text">来源：{{ file.source_url || '本地上传文件' }}</div></article></el-card>
    </template>
  </section>
</template>
