<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import DataChart from "@/components/DataChart.vue";
import {
  getCommonTestComparison,
  getComparisonDetail,
  getExperiment,
  getPhase10Summary,
  getPredictionRecords,
} from "@/api/ml";
import type { Experiment } from "@/types/ml";
const rows = ref<any[]>([]),
  common = ref<any>({ items: [] }),
  selected = ref<Experiment>(),
  loading = ref(false),
  formalRanking = ref(false),
  records = ref<any[]>([]),
  recordTotal = ref(0),
  filters = ref({
    sid: "",
    min_abs_error: undefined as number | undefined,
    page: 1,
    page_size: 20,
  });
const phase10 = ref<any>({ available: false }), horizon = ref("6");
const phase10Rows = computed(() => {
  if (!phase10.value.available) return [];
  const result = phase10.value.baselines;
  const values = ["persistence", "ridge", "gru"].map((name) => ({ name: name.toUpperCase(), ...result[name].test.by_horizon[horizon.value] }));
  values.push({ name: "候选 SAF-Net", ...phase10.value.selected_candidate.test.by_horizon[horizon.value] });
  return values;
});
const horizonOption = computed(() => ({
  tooltip: { trigger: "axis" }, legend: { data: ["Persistence", "Ridge", "GRU", "候选 SAF-Net"] }, grid: { left: 55, right: 20, top: 45, bottom: 35 },
  xAxis: { type: "category", data: ["6h", "12h", "18h", "24h"] }, yAxis: { type: "value", name: "MAE (m/s)" },
  series: ["persistence", "ridge", "gru"].map((name) => ({ name: name === "persistence" ? "Persistence" : name.toUpperCase(), type: "line", data: ["6", "12", "18", "24"].map((h) => phase10.value.baselines[name].test.by_horizon[h].mae) })).concat([{ name: "候选 SAF-Net", type: "line", data: ["6", "12", "18", "24"].map((h) => phase10.value.selected_candidate.test.by_horizon[h].mae) }]),
}));
const measured = computed(() => rows.value.filter((r) => r.mae != null)),
  commonItems = computed(() => common.value.items ?? []);
const maeOption = computed(() => ({
  tooltip: { trigger: "axis" },
  grid: { left: 55, right: 20, top: 30, bottom: 35 },
  xAxis: {
    type: "category",
    data: commonItems.value.map((r: any) => r.model_type.toUpperCase()),
  },
  yAxis: { type: "value", name: "MAE (m/s)" },
  series: [
    {
      type: "bar",
      data: commonItems.value.map((r: any) => r.mae),
      itemStyle: { color: "#397fa5" },
    },
  ],
}));
const rmseOption = computed(() => ({
  tooltip: { trigger: "axis" },
  grid: { left: 55, right: 20, top: 30, bottom: 35 },
  xAxis: {
    type: "category",
    data: commonItems.value.map((r: any) => r.model_type.toUpperCase()),
  },
  yAxis: { type: "value", name: "RMSE (m/s)" },
  series: [
    {
      type: "bar",
      data: commonItems.value.map((r: any) => r.rmse),
      itemStyle: { color: "#d28745" },
    },
  ],
}));
const comparisonOption = computed(() => {
  const p = selected.value?.metrics.test?.points ?? [];
  return {
    tooltip: { trigger: "axis" },
    legend: { data: ["真实风速", "预测风速"] },
    xAxis: {
      type: "category",
      data: p.map((v) => v.target_time.slice(0, 10)),
      axisLabel: { show: false },
    },
    yAxis: { type: "value", name: "m/s" },
    series: [
      {
        name: "真实风速",
        type: "line",
        showSymbol: false,
        data: p.map((v) => v.actual),
      },
      {
        name: "预测风速",
        type: "line",
        showSymbol: false,
        data: p.map((v) => v.predicted),
      },
    ],
  };
});
const errorOption = computed(() => {
  const p = selected.value?.metrics.test?.points ?? [];
  const bins = Array.from({ length: 13 }, (_, i) => i - 6);
  return {
    xAxis: { type: "category", data: bins.map((v) => `${v}~${v + 1}`) },
    yAxis: { type: "value", name: "样本" },
    series: [
      {
        type: "bar",
        data: bins.map(
          (v) => p.filter((x) => x.error >= v && x.error < v + 1).length,
        ),
      },
    ],
  };
});
async function select(row: any) {
  if (row.experiment_id)
    selected.value = await getExperiment(row.experiment_id);
}
async function loadRecords() {
  const result = await getPredictionRecords(filters.value);
  records.value = result.items;
  recordTotal.value = result.total;
}
function download(path: string) {
  window.location.href = path;
}
onMounted(async () => {
  loading.value = true;
  const [detail, fair, p10] = await Promise.all([
    getComparisonDetail(),
    getCommonTestComparison(),
    getPhase10Summary(),
  ]);
  rows.value = detail.items;
  common.value = fair;
  phase10.value = p10;
  formalRanking.value = detail.formal_ranking_allowed;
  if (measured.value.length) await select(measured.value[0]);
  await loadRecords();
  loading.value = false;
});
</script>
<template>
  <section v-loading="loading" class="page-stack">
    <div class="page-heading">
      <div>
        <h2>预测性能评估</h2>
        <p>独立事件测试集 · 所有指标来自已保存模型</p>
      </div>
      <div class="settings-actions">
        <el-button @click="download('/api/exports/model-comparison.png')"
          >导出 PNG</el-button
        ><el-button @click="download('/api/exports/workbook')"
          >导出科研工作簿</el-button
        >
      </div>
    </div>
    <el-alert
      title="公平比较口径"
      :description="
        common.reason ||
        '五模型使用相同 SID、起报时间、目标时间、标签单位和质量规则。'
      "
      :type="common.formal_ranking_allowed ? 'success' : 'warning'"
      :closable="false"
      show-icon
    />
    <template v-if="phase10.available">
      <el-alert title="第十阶段结论" description="候选模型仅按验证集选择；当前测试结果没有超过持续性基线，P10–P90 区间存在欠校准，不作性能优势声明。" type="warning" :closable="false" show-icon />
      <div class="chart-grid">
        <el-card shadow="never"><DataChart :option="horizonOption" label="四类模型多时效 MAE 曲线" /></el-card>
        <el-card shadow="never">
          <template #header><div class="card-header"><strong>分时效指标</strong><el-select v-model="horizon" style="width: 120px"><el-option v-for="h in ['6','12','18','24']" :key="h" :value="h" :label="`${h} 小时`" /></el-select></div></template>
          <el-table :data="phase10Rows"><el-table-column prop="name" label="模型" /><el-table-column label="MAE"><template #default="{ row }">{{ row.mae.toFixed(3) }}</template></el-table-column><el-table-column label="RMSE"><template #default="{ row }">{{ row.rmse.toFixed(3) }}</template></el-table-column><el-table-column label="Bias"><template #default="{ row }">{{ row.bias.toFixed(3) }}</template></el-table-column></el-table>
          <p><strong>候选区间：</strong>覆盖率 {{ (phase10.selected_candidate.test.probability.by_horizon[horizon].coverage_p10_p90 * 100).toFixed(1) }}% · 宽度 {{ phase10.selected_candidate.test.probability.by_horizon[horizon].mean_interval_width.toFixed(3) }} m/s · Pinball {{ phase10.selected_candidate.test.probability.by_horizon[horizon].pinball_loss.toFixed(3) }}</p>
        </el-card>
      </div>
      <el-card shadow="never"><template #header><strong>六组消融实验（验证集选择后一次性测试）</strong></template><el-table :data="phase10.selected_ablations"><el-table-column prop="variant" label="结构" min-width="180" /><el-table-column prop="seed" label="种子" /><el-table-column prop="parameters" label="参数量" /><el-table-column prop="best_epoch" label="最佳 Epoch" /><el-table-column label="验证 MAE"><template #default="{ row }">{{ row.validation.overall.mae.toFixed(3) }}</template></el-table-column><el-table-column label="测试 MAE"><template #default="{ row }">{{ row.test.overall.mae.toFixed(3) }}</template></el-table-column></el-table></el-card>
    </template>
    <el-card shadow="never"
      ><template #header
        ><div class="card-header">
          <strong>五模型共同测试集</strong
          ><el-tag :type="common.status === 'formal' ? 'success' : 'warning'">{{
            common.status === "formal" ? "正式" : "小样本试验"
          }}</el-tag>
        </div></template
      >
      <p>
        共同样本 {{ common.sample_count || 0 }} 条 · 独立事件
        {{ common.event_count || 0 }} 个 · 预测时效
        {{ common.forecast_horizon_hours || 6 }} 小时
      </p>
      <el-table :data="common.items"
        ><el-table-column prop="model_type" label="模型" /><el-table-column
          prop="sample_count"
          label="样本"
        /><el-table-column label="MAE"
          ><template #default="{ row }">{{
            row.mae.toFixed(3)
          }}</template></el-table-column
        ><el-table-column label="RMSE"
          ><template #default="{ row }">{{
            row.rmse.toFixed(3)
          }}</template></el-table-column
        ><el-table-column label="Bias"
          ><template #default="{ row }">{{
            row.bias.toFixed(3)
          }}</template></el-table-column
        ><el-table-column label="相对持续性"
          ><template #default="{ row }">{{
            row.improvement_pct == null
              ? "—"
              : row.improvement_pct.toFixed(1) + "%"
          }}</template></el-table-column
        ></el-table
      ></el-card
    >
    <el-card v-if="common.safnet_selection" shadow="never"
      ><template #header><strong>SAF-Net 正式选择与不确定性</strong></template>
      <p>
        最终权重仅按验证集 MAE 选择：{{
          common.safnet_selection.validation_mae.toFixed(3)
        }}
        m/s；测试集未参与选模。
      </p>
      <p v-if="common.bootstrap_safnet_minus_persistence?.reliable">
        事件级 Bootstrap（SAF-Net MAE − Persistence MAE）：{{
          common.bootstrap_safnet_minus_persistence.estimate.toFixed(3)
        }}
        m/s，95% CI [{{
          common.bootstrap_safnet_minus_persistence.ci95[0].toFixed(3)
        }},
        {{ common.bootstrap_safnet_minus_persistence.ci95[1].toFixed(3) }}]。
      </p></el-card
    >
    <div class="chart-grid">
      <el-card shadow="never"
        ><DataChart
          :option="maeOption"
          label="原第三阶段正式模型 MAE 对比" /></el-card
      ><el-card shadow="never"
        ><DataChart :option="rmseOption" label="原第三阶段正式模型 RMSE 对比"
      /></el-card>
    </div>
    <el-card shadow="never"
      ><template #header
        ><strong>历史实验记录（不同数据版本不混合排名）</strong></template
      ><el-table :data="rows" highlight-current-row @row-click="select"
        ><el-table-column
          prop="name"
          label="实验"
          min-width="220"
        /><el-table-column
          prop="model_type"
          label="模型"
          width="100"
        /><el-table-column
          prop="dataset_version"
          label="数据版本"
          min-width="210"
          show-overflow-tooltip
        /><el-table-column
          prop="test_count"
          label="测试样本"
          width="95"
        /><el-table-column label="MAE" width="95"
          ><template #default="{ row }">{{
            row.mae == null ? "—" : row.mae.toFixed(3)
          }}</template></el-table-column
        ><el-table-column label="RMSE" width="95"
          ><template #default="{ row }">{{
            row.rmse == null ? "—" : row.rmse.toFixed(3)
          }}</template></el-table-column
        ><el-table-column label="Bias" width="95"
          ><template #default="{ row }">{{
            row.bias == null ? "—" : row.bias.toFixed(3)
          }}</template></el-table-column
        ><el-table-column label="同组可比" width="100"
          ><template #default="{ row }"
            ><el-tag :type="row.comparable ? 'success' : 'info'">{{
              row.comparable ? "是" : "否"
            }}</el-tag></template
          ></el-table-column
        ></el-table
      ></el-card
    >
    <template v-if="selected"
      ><div class="chart-grid">
        <el-card shadow="never"
          ><DataChart
            :option="comparisonOption"
            label="真实与预测风速对比" /></el-card
        ><el-card shadow="never"
          ><DataChart :option="errorOption" label="预测误差分布"
        /></el-card></div
    ></template>
    <el-card shadow="never"
      ><template #header
        ><div class="card-header">
          <strong>已保存预测记录</strong
          ><el-button @click="download('/api/exports/predictions.csv')"
            >导出筛选结果 CSV</el-button
          >
        </div></template
      >
      <div class="settings-actions">
        <el-input
          v-model="filters.sid"
          clearable
          placeholder="SID"
          style="width: 180px"
        /><el-input-number
          v-model="filters.min_abs_error"
          :min="0"
          placeholder="最小绝对误差"
        /><el-button @click="loadRecords">查询</el-button>
      </div>
      <el-table :data="records"
        ><el-table-column prop="model_name" label="模型" /><el-table-column
          prop="sid"
          label="SID"
          width="130" /><el-table-column
          prop="forecast_time"
          label="起报时间"
          width="190" /><el-table-column
          prop="predicted_wind"
          label="预测 m/s" /><el-table-column
          prop="actual_wind"
          label="真实 m/s" /><el-table-column
          prop="absolute_error"
          label="绝对误差" /></el-table
      ><el-pagination
        class="pagination"
        v-model:current-page="filters.page"
        :page-size="filters.page_size"
        :total="recordTotal"
        @current-change="loadRecords"
    /></el-card>
  </section>
</template>
<style scoped></style>
