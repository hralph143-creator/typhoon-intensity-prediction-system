import { apiClient } from './client'
import type { ApiResponse,DataSourceStatus,HealthStatus,RuntimeInfo } from '@/types/system'
export async function getHealth(){const r=await apiClient.get<ApiResponse<HealthStatus>>('/health');return r.data.data}
export async function getSystemInfo(){const r=await apiClient.get<ApiResponse<RuntimeInfo>>('/system/info');return r.data.data}
export async function getDataSourceStatuses(){const r=await apiClient.get<ApiResponse<DataSourceStatus[]>>('/data-sources/status');return r.data.data}
const get=async<T>(url:string,params?:object)=>(await apiClient.get<ApiResponse<T>>(url,{params})).data.data
export const getRuntimeStatus=()=>get<any>('/system/status')
export const getLogs=(params?:object)=>get<any[]>('/system/logs',params)
export const getBackups=()=>get<any[]>('/system/backups')
export const createBackup=async(name:string)=>(await apiClient.post<ApiResponse<any>>('/system/backups',{name})).data.data
export const verifyBackup=async(id:string)=>(await apiClient.post<ApiResponse<any>>(`/system/backups/${id}/verify`)).data.data
export const restoreBackup=async(id:string)=>(await apiClient.post<ApiResponse<any>>(`/system/backups/${id}/restore`,null,{params:{confirmed:true}})).data.data
export const deleteBackup=(id:string)=>apiClient.delete(`/system/backups/${id}`,{params:{confirmed:true}})
export const getMaintenance=()=>get<any>('/system/maintenance/preview')
export const cleanupTemporary=async()=>(await apiClient.post<ApiResponse<any>>('/system/maintenance/cleanup',null,{params:{confirmed:true}})).data.data
