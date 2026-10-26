import type { EChartsCoreOption } from 'echarts/core'
import type { Observation } from '@/types/typhoon'
import { agencyLabels, type Agency, utc, windValue } from './typhoon'

export function intensityOption(points: Observation[], agency: Agency, pressureAgency: 'cma' | 'wmo', selected: number): EChartsCoreOption {
  const selection = points[selected]?.observation_time
  return {
    animation: false,
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0, textStyle: { color: '#66788a' } },
    grid: { left: 58, right: 64, top: 28, bottom: 82 },
    xAxis: { type: 'category', data: points.map(point => utc(point.observation_time).replace(' UTC', '')), axisLabel: { color: '#748396', hideOverlap: true } },
    yAxis: [
      { type: 'value', name: '风速 m/s', axisLabel: { color: '#52758f' }, splitLine: { lineStyle: { color: '#edf0f4' } } },
      { type: 'value', name: '气压 hPa', scale: true, axisLabel: { color: '#8c7185' }, splitLine: { show: false } },
    ],
    dataZoom: [{ type: 'inside' }],
    series: [
      { name: agencyLabels[agency], type: 'line', data: points.map(point => windValue(point, agency)), connectNulls: false, symbolSize: 5, lineStyle: { width: 2, color: '#2778b5' }, itemStyle: { color: '#2778b5' },
        markLine: selection ? { symbol: 'none', silent: true, label: { show: false }, lineStyle: { color: '#7e8c9a', type: 'dashed' }, data: [{ xAxis: utc(selection).replace(' UTC', '') }] } : undefined },
      { name: `${pressureAgency.toUpperCase()} 中心气压`, type: 'line', yAxisIndex: 1, data: points.map(point => point[`${pressureAgency}_pressure`]), connectNulls: false, symbolSize: 4, itemStyle: { color: '#a0778b' }, lineStyle: { width: 1.5 } },
    ],
  }
}
