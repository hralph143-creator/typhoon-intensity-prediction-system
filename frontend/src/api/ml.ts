import { apiClient } from './client'
import type { ApiResponse } from '@/types/system'
import type { Audit, BacktestResult, Experiment, ModelArtifact, SampleStatistics } from '@/types/ml'
const get = async <T>(url:string, params?:object) => (await apiClient.get<ApiResponse<T>>(url,{params})).data.data
const post = async <T>(url:string, data?:unknown) => (await apiClient.post<ApiResponse<T>>(url,data)).data.data
export const getAudit = async () => (await apiClient.get<ApiResponse<Audit>>('/ml/audit',{timeout:60000})).data.data
export const getSampleStatistics = async (quality_profile='strict') => (await apiClient.get<ApiResponse<SampleStatistics>>('/ml/samples/statistics',{params:{quality_profile},timeout:60000})).data.data
export const getExperiments = (params?:object) => get<Experiment[]>('/ml/experiments',params)
export const getExperiment = (id:string) => get<Experiment>(`/ml/experiments/${id}`)
export const createExperiment = (data:object) => post<Experiment>('/ml/experiments',data)
export const cancelExperiment = (id:string) => post<Experiment>(`/ml/experiments/${id}/cancel`)
export const deleteExperiment = (id:string) => apiClient.delete(`/ml/experiments/${id}`,{params:{confirmed:true}})
export const getModels = () => get<ModelArtifact[]>('/ml/models')
export const getComparison = () => get<Array<{model_id:string;experiment_id:string;name:string;model_type:string;mae:number;rmse:number;bias:number;improvement_pct:number|null}>>('/ml/comparison')
export const getComparisonDetail = () => get<any>('/ml/comparison/detail')
export const getCommonTestComparison = () => get<any>('/ml/comparison/common-test')
export const getPredictionRecords = (params?:object) => get<any>('/ml/predictions',params)
export const historicalPredict = (data:object) => post<BacktestResult>('/ml/predict',data)
export const getSafnetInfo = () => get<any>('/ml/safnet/info')
export const getSafnetSamples = () => get<any[]>('/ml/safnet/samples')
export const safnetPredict = (data:object) => post<any>('/ml/safnet/predict',data)
export const getPhase10Summary = () => get<any>('/ml/phase10/summary')
export const getPhase10Audit = () => get<any>('/ml/phase10/audit')
export const getPhase10Samples = (split?:'train'|'validation'|'test') => get<any[]>('/ml/phase10/samples',split?{split}:undefined)
export const phase10Predict = (sample_id:string) => post<any>('/ml/phase10/predict',{sample_id})
export async function downloadExperimentExport(format:'csv'|'xlsx') { const response=await apiClient.get(`/ml/export/experiments`,{params:{format},responseType:'blob'}); const url=URL.createObjectURL(response.data); const link=document.createElement('a'); link.href=url; link.download=`experiments.${format}`; link.click(); URL.revokeObjectURL(url) }
