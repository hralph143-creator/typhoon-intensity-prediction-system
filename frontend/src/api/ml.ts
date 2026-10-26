import { apiClient } from './client'
import type { ApiResponse } from '@/types/system'
import type { Audit, BacktestResult, Experiment, ModelArtifact, SampleStatistics } from '@/types/ml'
const get = async <T>(url:string, params?:object) => (await apiClient.get<ApiResponse<T>>(url,{params})).data.data
const post = async <T>(url:string, data?:unknown) => (await apiClient.post<ApiResponse<T>>(url,data)).data.data
export const getAudit = () => get<Audit>('/ml/audit')
export const getSampleStatistics = (quality_profile='strict') => get<SampleStatistics>('/ml/samples/statistics',{quality_profile})
export const getExperiments = (params?:object) => get<Experiment[]>('/ml/experiments',params)
export const getExperiment = (id:string) => get<Experiment>(`/ml/experiments/${id}`)
export const createExperiment = (data:object) => post<Experiment>('/ml/experiments',data)
export const cancelExperiment = (id:string) => post<Experiment>(`/ml/experiments/${id}/cancel`)
export const deleteExperiment = (id:string) => apiClient.delete(`/ml/experiments/${id}`,{params:{confirmed:true}})
export const getModels = () => get<ModelArtifact[]>('/ml/models')
export const getComparison = () => get<Array<{model_id:string;experiment_id:string;name:string;model_type:string;mae:number;rmse:number;bias:number;improvement_pct:number|null}>>('/ml/comparison')
export const historicalPredict = (data:object) => post<BacktestResult>('/ml/predict',data)
export async function downloadExperimentExport(format:'csv'|'xlsx') { const response=await apiClient.get(`/ml/export/experiments`,{params:{format},responseType:'blob'}); const url=URL.createObjectURL(response.data); const link=document.createElement('a'); link.href=url; link.download=`experiments.${format}`; link.click(); URL.revokeObjectURL(url) }
