<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import {
  getModels,
  getPhase10Samples,
  getPhase10Summary,
  getSafnetInfo,
  getSafnetSamples,
  historicalPredict,
  phase10Predict,
  safnetPredict,
} from "@/api/ml";
import { getTrack, getTyphoon, getTyphoons } from "@/api/typhoons";
import type { BacktestResult, ModelArtifact } from "@/types/ml";
import type { Observation, TyphoonEvent } from "@/types/typhoon";
import { numberText, utc } from "@/utils/typhoon";
import AttentionHeatmap from "@/components/AttentionHeatmap.vue";
import DataChart from "@/components/DataChart.vue";
const route = useRoute(),
  models = ref<ModelArtifact[]>([]),
  events = ref<TyphoonEvent[]>([]),
  points = ref<Observation[]>([]),
  modelId = ref(""),
  eventId = ref<number>(),
  forecastTime = ref(""),
  result = ref<any>(),
  query = ref(""),
  loading = ref(false),
  safnetInfo = ref<any>(),
  safnetSamples = ref<any[]>([]),
  sampleId = ref("");
const selectedModel = computed(() =>
    models.value.find((m) => m.id === modelId.value),
  ),
  isSafnet = computed(() => selectedModel.value?.model_type === "safnet"),
  hasSafnet = computed(() =>
    models.value.some((m) => m.model_type === "safnet"),
  );
const attentionHead = ref(0),
  spatialStep = ref(3),
  spatialAttention = computed(
    () => result.value?.attention?.spatial?.[spatialStep.value] ?? [],
  ),
  temporalHeads = computed(() => result.value?.attention?.temporal?.[0] ?? []),
  temporalAttention = computed(
    () => temporalHeads.value[attentionHead.value] ?? [],
  );
const phase10 = ref<any>({ available: false }),
  multiSamples = ref<any[]>([]),
  multiSampleId = ref(""),
  multiResult = ref<any>(),
  multiLoading = ref(false);
const multiOption = computed(() => {
  const r = multiResult.value;
  if (!r) return {};
  const lower = r.p10,
    range = r.p90.map((v: number, i: number) => v - lower[i]);
  return {
    tooltip: { trigger: "axis" },
    legend: { data: ["P10–P90区间", "P50预测", "历史真实值"] },
    grid: { left: 55, right: 25, top: 45, bottom: 35 },
    xAxis: { type: "category", data: r.horizons.map((h: number) => `+${h}h`) },
    yAxis: { type: "value", name: "风速 (m/s)" },
    series: [
      {
        name: "P10",
        type: "line",
        stack: "interval",
        data: lower,
        lineStyle: { opacity: 0 },
        symbol: "none",
      },
      {
        name: "P10–P90区间",
        type: "line",
        stack: "interval",
        data: range,
        lineStyle: { opacity: 0 },
        symbol: "none",
        areaStyle: { color: "rgba(57,127,165,.28)" },
      },
      { name: "P50预测", type: "line", data: r.p50, symbolSize: 8 },
      {
        name: "历史真实值",
        type: "line",
        data: r.actual,
        connectNulls: false,
        symbolSize: 8,
      },
    ],
  };
});
const resultOption = computed(() => {
  const winds = result.value?.input_winds ?? [];
  return {
    tooltip: { trigger: "axis" },
    legend: { data: ["历史输入", "预测", "历史真实值"] },
    grid: { left: 55, right: 25, top: 45, bottom: 35 },
    xAxis: { type: "category", data: ["t-18h", "t-12h", "t-6h", "t", "t+6h"] },
    yAxis: { type: "value", name: "风速 (m/s)" },
    series: [
      { name: "历史输入", type: "line", data: [...winds, null], symbolSize: 7 },
      {
        name: "预测",
        type: "scatter",
        data: [null, null, null, null, result.value?.predicted_wind],
        symbolSize: 12,
        itemStyle: { color: "#d07832" },
      },
      {
        name: "历史真实值",
        type: "scatter",
        data: [null, null, null, null, result.value?.actual_wind],
        symbolSize: 12,
        itemStyle: { color: "#2d8a64" },
      },
    ],
  };
});
const candidates = computed(() => {
  const by = new Map(
    points.value.map((p) => [new Date(p.observation_time).getTime(), p]),
  );
  return points.value
    .filter((p) => {
      const t = new Date(p.observation_time).getTime();
      return [0, 6, 12, 18].every(
        (h) => by.get(t - h * 3600000)?.cma_wind_ms != null,
      );
    })
    .map((p) => p.observation_time);
});
async function search() {
  const response = await getTyphoons({
    page: 1,
    page_size: 100,
    sort_by: "season",
    sort_order: "desc",
    source: "ibtracs",
    include_spurs: false,
    name: query.value || undefined,
  });
  events.value = response.items;
}
async function loadTrack() {
  result.value = undefined;
  forecastTime.value = "";
  if (eventId.value) {
    const r = await getTrack(eventId.value, "MAIN");
    points.value = r.items;
  }
}
async function predict() {
  if (!modelId.value) return;
  loading.value = true;
  try {
    result.value = isSafnet.value
      ? await safnetPredict({
          model_id: modelId.value,
          sample_id: sampleId.value,
          include_attention: true,
        })
      : await historicalPredict({
          model_id: modelId.value,
          typhoon_id: eventId.value,
          forecast_time: forecastTime.value,
        });
    ElMessage.success("真实模型历史回测完成");
  } catch (e: any) {
    ElMessage.error(e.response?.data?.message || "无法构建有效历史输入");
  } finally {
    loading.value = false;
  }
}
function saveBlob(content: Blob, name: string) {
  const url = URL.createObjectURL(content),
    link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}
function exportCsv() {
  if (!result.value) return;
  const r = result.value,
    lines = [
      "字段,数值",
      "台风," + r.name,
      "SID," + r.sid,
      "模型," + r.model_name,
      "起报时间," + r.forecast_time,
      "目标时间," + r.target_time,
      "预测风速(m/s)," + r.predicted_wind,
      "历史真实风速(m/s)," + (r.actual_wind ?? ""),
      "误差(m/s)," + (r.error ?? ""),
      '数据来源,"' + r.data_source + '"',
    ];
  saveBlob(
    new Blob(["\ufeff" + lines.join("\r\n")], {
      type: "text/csv;charset=utf-8",
    }),
    `prediction-${r.sid}.csv`,
  );
}
function exportCanvas(selector: string, name: string) {
  const canvas = document.querySelector<HTMLCanvasElement>(selector);
  if (!canvas) return ElMessage.warning("图表尚未完成渲染");
  canvas.toBlob((blob) => blob && saveBlob(blob, name), "image/png");
}
async function predictMulti() {
  if (!multiSampleId.value) return;
  multiLoading.value = true;
  try {
    multiResult.value = await phase10Predict(multiSampleId.value);
    ElMessage.success("6–24 小时概率历史回测完成");
  } catch (e: any) {
    ElMessage.error(e.response?.data?.message || "多时效推理失败");
  } finally {
    multiLoading.value = false;
  }
}
onMounted(async () => {
  [
    models.value,
    safnetInfo.value,
    safnetSamples.value,
    phase10.value,
    multiSamples.value,
  ] = await Promise.all([
    getModels(),
    getSafnetInfo(),
    getSafnetSamples(),
    getPhase10Summary(),
    getPhase10Samples("test"),
  ]);
  modelId.value = models.value[0]?.id ?? "";
  multiSampleId.value = multiSamples.value[0]?.id ?? "";
  await search();
  const fromRoute = Number(route.query.typhoon_id);
  if (fromRoute) {
    if (!events.value.some((e) => e.id === fromRoute)) {
      const detail = await getTyphoon(fromRoute);
      events.value.unshift(detail);
    }
    eventId.value = fromRoute;
    await loadTrack();
  }
});
</script>
<template>
  <section class="page-stack">
    <div class="page-heading">
      <div>
        <h2>强度预测</h2>
        <p>历史起报时刻回测 · 6–24 小时点预测与概率区间</p>
      </div>
    </div>
    <el-alert
      title="历史回测预测"
      description="仅使用起报时刻及之前四个连续时次；目标真实值不进入输入。ERA5 再分析回测不是实时业务预报。"
      type="warning"
      :closable="false"
      show-icon
    />
    <el-card v-if="phase10.available" shadow="never" class="data-card multi-card">
      <template #header><div class="card-header"><strong>多时效概率预测</strong><el-tag>数据版本 {{ phase10.dataset_version }}</el-tag></div></template>
      <div class="inline-controls">
        <el-select v-model="multiSampleId" filterable style="min-width: 360px"><el-option v-for="s in multiSamples" :key="s.id" :value="s.id" :label="`${s.sid} · ${utc(s.forecast_time)} · 测试集`" /></el-select>
        <el-button type="primary" :loading="multiLoading" @click="predictMulti">预测 6 / 12 / 18 / 24 小时</el-button>
        <el-link href="/api/ml/phase10/export.csv">导出全部 CSV</el-link>
      </div>
      <template v-if="multiResult">
        <DataChart :option="multiOption" label="多时效预测值、真实值和 P10 至 P90 区间" />
        <el-table :data="multiResult.horizons.map((h:number,i:number)=>({h,actual:multiResult.actual[i],p10:multiResult.p10[i],p50:multiResult.p50[i],p90:multiResult.p90[i]}))">
          <el-table-column prop="h" label="时效(h)" /><el-table-column label="真实值"><template #default="{ row }">{{ numberText(row.actual) }}</template></el-table-column><el-table-column label="P10"><template #default="{ row }">{{ numberText(row.p10) }}</template></el-table-column><el-table-column label="P50"><template #default="{ row }">{{ numberText(row.p50) }}</template></el-table-column><el-table-column label="P90"><template #default="{ row }">{{ numberText(row.p90) }}</template></el-table-column><el-table-column label="绝对误差"><template #default="{ row }">{{ row.actual == null ? "—" : numberText(Math.abs(row.p50 - row.actual)) }}</template></el-table-column>
        </el-table>
        <div class="settings-actions"><el-button @click="exportCanvas('.multi-card canvas', `phase10-${multiResult.sid}.png`)">导出图表 PNG</el-button></div>
      </template>
    </el-card>
    <el-alert
      v-if="!hasSafnet"
      title="SAF-Net 尚未完成真实数据训练。"
      type="info"
      :closable="false"
    /><el-card shadow="never" class="data-card"
      ><el-form label-position="top" class="prediction-form"
        ><el-form-item label="已训练模型"
          ><el-select v-model="modelId" placeholder="没有可用模型"
            ><el-option
              v-for="m in models"
              :key="m.id"
              :value="m.id"
              :label="`${m.name} · ${m.model_type.toUpperCase()}`" /><el-option
              v-if="!hasSafnet"
              label="SAF-Net · 尚无真实权重"
              value="safnet-unavailable"
              disabled /></el-select></el-form-item
        ><template v-if="isSafnet"
          ><el-form-item label="完整时空样本"
            ><el-select v-model="sampleId" filterable
              ><el-option
                v-for="s in safnetSamples"
                :key="s.id"
                :value="s.id"
                :label="`${s.sid} · ${utc(s.forecast_time)} · ${s.split}`" /></el-select></el-form-item></template
        ><template v-else
          ><el-form-item label="搜索历史台风"
            ><el-input
              v-model="query"
              placeholder="输入名称，如 MERANTI"
              @keyup.enter="search"
              ><template #append
                ><el-button @click="search">搜索</el-button></template
              ></el-input
            ></el-form-item
          ><el-form-item label="历史台风"
            ><el-select
              v-model="eventId"
              filterable
              placeholder="选择台风"
              @change="loadTrack"
              ><el-option
                v-for="e in events"
                :key="e.id"
                :value="e.id"
                :label="`${e.season} · ${e.name} · ${e.sid}`" /></el-select></el-form-item
          ><el-form-item label="有效起报时间（UTC）"
            ><el-select
              v-model="forecastTime"
              filterable
              placeholder="选择具备连续历史窗口的时刻"
              ><el-option
                v-for="t in candidates"
                :key="t"
                :value="t"
                :label="
                  utc(t)
                " /></el-select></el-form-item></template></el-form
      ><el-empty
        v-if="!models.length"
        description="尚无训练成功并保存的模型，请先在模型训练页面创建实验"
      /><el-alert
        v-else-if="!isSafnet && eventId && candidates.length === 0"
        title="该台风没有完整的四时次历史输入"
        type="info"
        :closable="false"
      /><el-button
        type="primary"
        :loading="loading"
        :disabled="
          !modelId || (isSafnet ? !sampleId : !eventId || !forecastTime)
        "
        @click="predict"
        >执行真实模型推理</el-button
      ></el-card
    ><el-card v-if="result" shadow="never" class="data-card result-card"
      ><template #header
        ><div class="card-header">
          <strong>{{ result.name }} · {{ result.sid }}</strong>
          <div>
            <el-button @click="exportCsv">导出 CSV</el-button
            ><el-button
              @click="
                exportCanvas(
                  '.result-card .data-chart canvas',
                  `prediction-${result.sid}.png`,
                )
              "
              >导出图表</el-button
            ><el-tag type="warning">历史回测</el-tag>
          </div>
        </div></template
      ><el-descriptions :column="3" border
        ><el-descriptions-item label="起报时间">{{
          utc(result.forecast_time)
        }}</el-descriptions-item
        ><el-descriptions-item label="目标时间">{{
          utc(result.target_time)
        }}</el-descriptions-item
        ><el-descriptions-item label="模型">{{
          result.model_name
        }}</el-descriptions-item
        ><el-descriptions-item label="预测风速"
          >{{ numberText(result.predicted_wind) }} m/s</el-descriptions-item
        ><el-descriptions-item label="历史真实风速">{{
          result.actual_wind == null
            ? "目标时次无可靠标签"
            : numberText(result.actual_wind) + " m/s"
        }}</el-descriptions-item
        ><el-descriptions-item label="预测误差">{{
          result.error == null ? "不可计算" : numberText(result.error) + " m/s"
        }}</el-descriptions-item
        ><el-descriptions-item
          v-if="result.input_winds"
          label="输入风速"
          :span="3"
          >{{
            result.input_winds.map((v: number) => numberText(v)).join(" → ")
          }}
          m/s</el-descriptions-item
        ><el-descriptions-item label="数据来源" :span="3"
          >{{ result.data_source
          }}<template v-if="result.quality_profile">
            · {{ result.quality_profile }}</template
          ></el-descriptions-item
        ></el-descriptions
      ><DataChart
        v-if="result.input_winds"
        :option="resultOption"
        label="四时次历史风速与六小时预测结果" /></el-card
    ><el-card
      v-if="result?.attention"
      class="data-card attention-card"
      shadow="never"
      ><template #header
        ><div class="card-header">
          <strong>SAF-Net 注意力</strong>
          <div class="inline-controls">
            <el-select v-model="spatialStep" style="width: 125px"
              ><el-option
                v-for="(label, index) in ['t-18h', 't-12h', 't-6h', 't']"
                :key="label"
                :value="index"
                :label="label" /></el-select
            ><el-select v-model="attentionHead" style="width: 130px"
              ><el-option
                v-for="(_, index) in temporalHeads"
                :key="index"
                :value="index"
                :label="`时间头 ${index + 1}`" /></el-select
            ><el-button
              @click="
                exportCanvas(
                  '.attention-card canvas',
                  `attention-${result.sid}.png`,
                )
              "
              >导出注意力图</el-button
            >
          </div>
        </div></template
      >
      <div class="attention-grid">
        <div>
          <h4>
            空间注意力 · {{ ["t-18h", "t-12h", "t-6h", "t"][spatialStep] }}
          </h4>
          <AttentionHeatmap
            :matrix="spatialAttention"
            label="空间注意力热力图"
          />
        </div>
        <div>
          <h4>时间注意力 · 4×4</h4>
          <AttentionHeatmap
            :matrix="temporalAttention"
            label="四时次多头注意力矩阵"
          />
        </div>
      </div>
      <p class="muted-note">
        注意力来自所选真实样本和已保存 SAF-Net
        权重，仅描述网络内部关注模式，不代表气象因果关系。
      </p></el-card
    >
  </section>
</template>
<style scoped>
.attention-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  max-width: 820px;
  margin: auto;
}
.attention-grid h4 {
  text-align: center;
}
.result-card .data-chart {
  margin-top: 18px;
}
@media (max-width: 900px) {
  .attention-grid {
    grid-template-columns: 1fr;
  }
}
</style>
