<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { cancelJob, downloadIbtracs, getIbtracsStatus, getImportJobs, reimportFile, uploadIbtracs } from '@/api/typhoons'
import type { IbtracsStatus, ImportJob } from '@/types/typhoon'
import { activeJob, formatBytes, jobLabel, utc } from '@/utils/typhoon'

const status = ref<IbtracsStatus | null>(null)
const jobs = ref<ImportJob[]>([])
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const uploadProgress = ref<number | null>(null)
const forceDownload = ref(false)
const fileInput = ref<HTMLInputElement>()
const active = computed(() => jobs.value.find(job => activeJob(job.status)))
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
const uploadLabel = (percent: number) => `正在上传 ${percent}%`

function errorMessage(err: unknown) {
  const failure = err as { response?: { data?: { message?: string } }; message?: string }
  return failure.response?.data?.message ?? failure.message ?? '操作失败，请检查后端服务。'
}
async function refresh(silent = false) {
  if (!silent) loading.value = true
  try {
    const [sourceData, jobData] = await Promise.all([getIbtracsStatus(), getImportJobs()])
    if (!disposed) { status.value = sourceData; jobs.value = jobData.items; error.value = '' }
  } catch (err) { if (!disposed) error.value = errorMessage(err) }
  finally {
    loading.value = false
    if (!disposed) { clearTimeout(timer); timer = setTimeout(() => refresh(true), active.value ? 1500 : 8000) }
  }
}
async function act(operation: () => Promise<unknown>) {
  busy.value = true
  try { await operation(); ElMessage.success('操作已受理'); await refresh(true) }
  catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
async function selectedFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  uploadProgress.value = 0
  await act(() => uploadIbtracs(file, value => { uploadProgress.value = value }))
  uploadProgress.value = null
  input.value = ''
}
onMounted(() => refresh())
onBeforeUnmount(() => { disposed = true; clearTimeout(timer) })
</script>

<template>
  <div v-loading="loading" class="page-stack source-manager">
    <div class="section-heading">
      <div><h3>IBTrACS 数据接入</h3><p>NOAA 官方西北太平洋子集 · v04r01 · 研究时段 2014—2025 年</p></div>
      <el-button @click="refresh()">刷新</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div class="source-toolbar">
      <el-button type="primary" :disabled="busy || !!active" @click="act(() => downloadIbtracs(forceDownload))">下载官方数据并导入</el-button>
      <el-button :disabled="busy || !!active" @click="fileInput?.click()">上传本地 CSV</el-button>
      <el-checkbox v-model="forceDownload" :disabled="busy || !!active">强制刷新官方文件</el-checkbox>
      <input ref="fileInput" class="visually-hidden" type="file" accept=".csv,text/csv" aria-label="选择 IBTrACS CSV 文件" @change="selectedFile" />
      <a :href="status?.official_url ?? 'https://www.ncei.noaa.gov/products/international-best-track-archive'" target="_blank" rel="noopener">官方数据说明 ↗</a>
    </div>
    <el-progress v-if="uploadProgress != null" :percentage="uploadProgress" :format="uploadLabel" />
    <div v-if="status" class="source-summary">
      <span>已入库台风 <strong>{{ status.typhoon_count }}</strong></span>
      <span>观测记录 <strong>{{ status.observation_count.toLocaleString() }}</strong></span>
      <span>最近导入 <strong>{{ utc(status.last_import_at) }}</strong></span>
    </div>
    <p class="muted-note">默认复用已校验缓存；勾选“强制刷新官方文件”可重新获取 NOAA 最新版本。仅筛选 2014—2025 年、BASIN=WP 的观测；CMA 和 ERA5 独立数据源尚未接入。</p>
    <el-table :data="jobs" empty-text="暂无下载或导入任务" size="small">
      <el-table-column prop="filename" label="最近任务" min-width="220" show-overflow-tooltip />
      <el-table-column label="状态" width="110"><template #default="{row}"><el-tag :type="row.status === 'failed' ? 'danger' : row.status === 'succeeded' ? 'success' : 'info'">{{ jobLabel(row.status) }}</el-tag></template></el-table-column>
      <el-table-column label="进度与结果" min-width="270"><template #default="{row}">
        <template v-if="row.status === 'downloading'">
          <el-progress v-if="row.progress != null" :percentage="Math.min(100, Math.round(row.progress))" />
          <span>{{ formatBytes(row.downloaded_bytes) }} / {{ formatBytes(row.total_bytes) }} · {{ formatBytes(row.speed_bps) }}/s</span>
        </template>
        <span v-else-if="row.status === 'importing'">正在解析与入库 · 已扫描 {{ row.total_records.toLocaleString() }} 行</span>
        <span v-else-if="row.status === 'succeeded'">有效 {{ row.valid_records.toLocaleString() }} · 跳过 {{ row.skipped_records.toLocaleString() }}</span>
        <span v-else>{{ row.error_message || row.phase || '等待执行' }}</span>
      </template></el-table-column>
      <el-table-column label="开始时间" min-width="185"><template #default="{row}">{{ utc(row.started_at) }}</template></el-table-column>
      <el-table-column label="操作" width="90"><template #default="{row}"><el-button v-if="activeJob(row.status)" link type="danger" :disabled="row.cancel_requested" @click="act(() => cancelJob(row.id))">{{ row.cancel_requested ? '取消中' : '取消' }}</el-button></template></el-table-column>
    </el-table>
    <el-collapse v-if="status?.imported_files.length">
      <el-collapse-item title="原始文件登记与可追溯信息" name="files">
        <article v-for="file in status.imported_files" :key="file.id" class="file-record">
          <div class="section-heading"><strong>{{ file.filename }}</strong><el-button size="small" :disabled="busy || !!active" @click="act(() => reimportFile(file.id))">重新导入</el-button></div>
          <div>{{ formatBytes(file.size_bytes) }} · {{ file.version }} · 获取时间 {{ utc(file.acquired_at) }}</div>
          <div class="hash-text">SHA-256：{{ file.sha256 }}</div>
          <div class="hash-text">来源：{{ file.source_url || '本地 CSV 上传（原始来源须由文件提供者确认）' }}</div>
          <details><summary>查看清洗统计</summary><pre class="statistics-json">{{ JSON.stringify(file.statistics, null, 2) }}</pre></details>
        </article>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>
