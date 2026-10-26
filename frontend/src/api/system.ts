import { apiClient } from './client'
import type { ApiResponse,DataSourceStatus,HealthStatus,RuntimeInfo } from '@/types/system'
export async function getHealth(){const r=await apiClient.get<ApiResponse<HealthStatus>>('/health');return r.data.data}
export async function getSystemInfo(){const r=await apiClient.get<ApiResponse<RuntimeInfo>>('/system/info');return r.data.data}
export async function getDataSourceStatuses(){const r=await apiClient.get<ApiResponse<DataSourceStatus[]>>('/data-sources/status');return r.data.data}
