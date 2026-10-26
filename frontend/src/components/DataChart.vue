<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init, use, type ECharts, type EChartsCoreOption } from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import { GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, DataZoomComponent } from 'echarts/components'

use([BarChart, LineChart, CanvasRenderer, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, DataZoomComponent])
const props = defineProps<{ option: EChartsCoreOption; selectedIndex?: number; label: string }>()
const emit = defineEmits<{ select: [index: number] }>()
const root = ref<HTMLDivElement>()
let chart: ECharts | undefined
let resizeObserver: ResizeObserver | undefined
function render() { chart?.setOption(props.option, { notMerge: true }) }
onMounted(() => {
  chart = init(root.value!)
  render()
  chart.on('click', params => { if (typeof params.dataIndex === 'number') emit('select', params.dataIndex) })
  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(root.value!)
})
watch(() => props.option, render, { deep: true })
watch(() => props.selectedIndex, index => {
  if (index != null) chart?.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: index })
})
onBeforeUnmount(() => { resizeObserver?.disconnect(); chart?.dispose() })
</script>

<template><div ref="root" class="data-chart" role="img" :aria-label="label" /></template>

<style scoped>.data-chart { width: 100%; height: 290px; }</style>
