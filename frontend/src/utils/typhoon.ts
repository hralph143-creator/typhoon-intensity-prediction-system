import type { Observation, TyphoonFilters } from '@/types/typhoon'

export const categoryNames: Record<number, string> = {
  0: '弱于热带低压／未知', 1: '热带低压', 2: '热带风暴', 3: '强热带风暴',
  4: '台风', 5: '强台风', 6: '超强台风', 9: '温带气旋',
}
export const agencyLabels = {
  cma: 'CMA · 2 分钟平均', usa: 'USA · 1 分钟平均', tokyo: 'JMA / TOKYO · 10 分钟平均',
  wmo: 'WMO · 平均时段依负责机构',
}
export type Agency = keyof typeof agencyLabels
export function windValue(point: Observation, agency: Agency): number | null {
  return point[`${agency}_wind_ms`]
}
export function utc(value: string | null | undefined): string {
  return value ? `${value.replace('T', ' ').replace(/(?:\.\d+)?(?:Z|\+00:00)$/, '')} UTC` : '—'
}
export function numberText(value: number | null | undefined, digits = 1) {
  return value == null ? '—' : value.toFixed(digits)
}
export function formatBytes(value: number | null | undefined) {
  if (value == null) return '未知'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}
export function unwrapTrack(points: Observation[]): [number, number][] {
  let previous: number | null = null
  return points.map(point => {
    let longitude = point.longitude
    if (previous != null) {
      while (longitude - previous > 180) longitude -= 360
      while (longitude - previous < -180) longitude += 360
    }
    previous = longitude
    return [point.latitude, longitude]
  })
}
export function windColor(wind: number | null) {
  if (wind == null) return '#8995a4'
  if (wind < 17.2) return '#4692bb'
  if (wind < 24.5) return '#3ca778'
  if (wind < 32.7) return '#d5a130'
  if (wind < 41.5) return '#d88034'
  if (wind < 51) return '#cb5861'
  return '#8c5cb1'
}
export function normalizeFilters(filters: TyphoonFilters): TyphoonFilters {
  return { ...filters, name: filters.name?.trim() || undefined, sid: filters.sid?.trim() || undefined }
}
export function clampSelection(index: number, count: number) {
  return Math.max(0, Math.min(index, Math.max(0, count - 1)))
}
export function jobLabel(status: string) {
  return ({ queued: '等待执行', downloading: '正在下载', importing: '正在导入', succeeded: '已完成', failed: '失败', cancelled: '已取消', interrupted: '已中断' } as Record<string, string>)[status] ?? status
}
export function activeJob(status: string) { return ['queued', 'downloading', 'importing'].includes(status) }

const qualityLabels: Record<string, string> = {
  non_main_track: '非主轨迹', provisional_track: '临时轨迹',
  non_six_hour_time: '非六小时整点', cma_interpolated: 'CMA 插值记录',
  cma_wind_below_10: 'CMA 风速低于 10 m/s（特殊编码）',
  missing_cma_wind: 'CMA 风速缺测', missing_cma_pressure: 'CMA 气压缺测',
  duplicate_observation: '重复观测', conflicting_observation: '冲突观测',
  conflict: '同一时次存在冲突版本',
}
const fieldLabels: Record<string, string> = {
  cma_wind: 'CMA 风速', cma_pres: 'CMA 气压', cma_pressure: 'CMA 气压',
  cma_lat: 'CMA 纬度', cma_lon: 'CMA 经度', cma_cat: 'CMA 等级',
  wmo_wind: 'WMO 风速', wmo_pres: 'WMO 气压',
  usa_wind: 'USA 风速', usa_pres: 'USA 气压',
  tokyo_wind: 'JMA 风速', tokyo_pres: 'JMA 气压', number: '台风序号',
}
export function qualityLabel(flag: string) {
  if (qualityLabels[flag]) return qualityLabels[flag]
  if (flag.startsWith('invalid_')) return `${fieldLabels[flag.slice(8)] ?? '字段'}异常`
  return '其他质量标记'
}
