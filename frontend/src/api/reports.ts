import { apiClient } from './client'
import type { ApiResponse } from '@/types/system'
export interface ReportRecord { id:string; report_type:string; report_title:string; related_typhoon_id:number|null; related_experiment_id:string|null; source_metadata:Record<string,unknown>; report_status:string; phase:string; error_message:string|null; created_at:string; completed_at:string|null }
const get=async<T>(url:string,params?:object)=>(await apiClient.get<ApiResponse<T>>(url,{params})).data.data
export const getReportTypes=()=>get<Array<{code:string;name:string}>>('/reports/types')
export const getReports=()=>get<ReportRecord[]>('/reports')
export const createReport=async(payload:object)=>(await apiClient.post<ApiResponse<ReportRecord>>('/reports',payload)).data.data
export const deleteReport=(id:string)=>apiClient.delete(`/reports/${id}`,{params:{confirmed:true}})
export const reportUrl=(id:string,kind:'preview'|'html'|'pdf')=>kind==='preview'?`/api/reports/${id}/preview`:`/api/reports/${id}/download/${kind}`
