import { describe, expect, it } from 'vitest'
import type { Observation } from '@/types/typhoon'
import { clampSelection, normalizeFilters, unwrapTrack, utc, windValue } from './typhoon'
import { intensityOption } from './chartOptions'

function point(longitude: number, time = '2020-01-01T00:00:00Z'): Observation {
  return { id: 1, longitude, latitude: 18, observation_time: time, basin: 'WP', track_type: 'MAIN', cma_wind: null, cma_wind_ms: null, cma_pressure: null, cma_category: null, wmo_wind_ms: 20, wmo_pressure: 990, wmo_agency: 'tokyo', usa_wind_ms: 30, tokyo_wind_ms: 25, quality_flags: [], source_file_id: 1 }
}
describe('历史路径与指标', () => {
  it('跨日期变更线保持轨迹连续', () => {
    expect(unwrapTrack([point(179), point(-179), point(-175)])).toEqual([[18, 179], [18, 181], [18, 185]])
  })
  it('反向越过日期变更线不跨越全球', () => {
    expect(unwrapTrack([point(-179), point(179)])).toEqual([[18, -179], [18, -181]])
  })
  it('空轨迹不会生成坐标', () => expect(unwrapTrack([])).toEqual([]))
  it('CMA 缺测保持缺测，不静默采用 USA 风速', () => {
    expect(windValue(point(130), 'cma')).toBeNull()
    expect(windValue(point(130), 'usa')).toBe(30)
  })
  it('曲线保留空值并禁止连接缺测点', () => {
    const option = intensityOption([point(130)], 'cma', 'cma', 0)
    const series = option.series as { data: unknown[]; connectNulls: boolean }[]
    expect(series[0].data).toEqual([null])
    expect(series[0].connectNulls).toBe(false)
    expect(series[1].data).toEqual([null])
  })
  it('地图、时间轴和曲线索引限定于真实观测范围', () => {
    expect(clampSelection(100, 3)).toBe(2)
    expect(clampSelection(-1, 3)).toBe(0)
    expect(clampSelection(0, 0)).toBe(0)
  })
  it('筛选去除空格，保留分页和年份条件', () => {
    const filters = normalizeFilters({ name: '  RAMMASUN  ', sid: ' ', season: 2014, page: 2, page_size: 20, sort_by: 'season', sort_order: 'desc' })
    expect(filters.name).toBe('RAMMASUN')
    expect(filters.sid).toBeUndefined()
    expect(filters.season).toBe(2014)
    expect(filters.page).toBe(2)
  })
  it('时间明确使用 UTC 并支持缺测', () => {
    expect(utc('2020-01-01T00:00:00Z')).toBe('2020-01-01 00:00:00 UTC')
    expect(utc(null)).toBe('—')
  })
})
