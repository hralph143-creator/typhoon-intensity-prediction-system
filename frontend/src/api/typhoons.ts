import { apiClient } from './client'
import type { ApiResponse } from '@/types/system'
import type { IbtracsStatus, ImportJob, Observation, Page, Statistics, TrackResponse, TyphoonDetail, TyphoonEvent, TyphoonFilters } from '@/types/typhoon'

async function get<T>(path: string, params?: object) {
  return (await apiClient.get<ApiResponse<T>>(path, { params })).data.data
}
async function post<T>(path: string, data?: unknown) {
  return (await apiClient.post<ApiResponse<T>>(path, data)).data.data
}
export const getTyphoons = (params: TyphoonFilters) => get<Page<TyphoonEvent>>('/typhoons', params)
export const getStatistics = () => get<Statistics>('/typhoons/statistics')
export const getTyphoon = (id: number) => get<TyphoonDetail>(`/typhoons/${id}`)
export const getTrack = (id: number, track_type: string) => get<TrackResponse>(`/typhoons/${id}/track`, { track_type })
export const getIntensity = (id: number, track_type: string) => get<TrackResponse>(`/typhoons/${id}/intensity`, { track_type })
export const getObservations = (id: number, params: object) => get<Page<Observation>>(`/typhoons/${id}/observations`, params)
export const getIbtracsStatus = () => get<IbtracsStatus>('/ibtracs/status')
export const getImportJobs = () => get<{ items: ImportJob[]; total: number }>('/ibtracs/jobs')
export const downloadIbtracs = (force = false) => post<ImportJob>('/ibtracs/download', { force })
export const cancelJob = (id: string) => post<ImportJob>(`/ibtracs/jobs/${id}/cancel`)
export const reimportFile = (file_id: number) => post<ImportJob>('/ibtracs/reimport', { file_id })
export async function uploadIbtracs(file: File, onProgress: (percent: number) => void) {
  const data = new FormData()
  data.append('file', file)
  const response = await apiClient.post<ApiResponse<ImportJob>>('/ibtracs/import', data, {
    timeout: 0,
    onUploadProgress: event => onProgress(event.total ? Math.round(event.loaded / event.total * 100) : 0),
  })
  return response.data.data
}
