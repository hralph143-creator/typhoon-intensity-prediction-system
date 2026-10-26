import { computed,ref } from 'vue'
import { defineStore } from 'pinia'
import { getDataSourceStatuses,getHealth,getSystemInfo } from '@/api/system'
import type { DataSourceStatus,HealthStatus,RuntimeInfo } from '@/types/system'
export const useSystemStore=defineStore('system',()=>{const health=ref<HealthStatus|null>(null),info=ref<RuntimeInfo|null>(null),dataSources=ref<DataSourceStatus[]>([]),loading=ref(false),error=ref('');const backendOnline=computed(()=>health.value?.status==='healthy');async function refresh(){loading.value=true;error.value='';try{[health.value,info.value,dataSources.value]=await Promise.all([getHealth(),getSystemInfo(),getDataSourceStatuses()])}catch{health.value=null;info.value=null;dataSources.value=[];error.value='无法连接后端服务，请确认后端已在 8000 端口启动。'}finally{loading.value=false}}return{health,info,dataSources,loading,error,backendOnline,refresh}})
