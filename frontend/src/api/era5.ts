import {apiClient} from './client'
export const era5Api={
  status:()=>apiClient.get('/era5/status').then(r=>r.data.data),
  publicSample:()=>apiClient.post('/era5/public-sample',null,{timeout:180000}).then(r=>r.data.data),
  test:()=>apiClient.post('/era5/connection-test').then(r=>r.data.data),
  plans:()=>apiClient.get('/era5/plans').then(r=>r.data.data),
  jobs:()=>apiClient.get('/era5/jobs').then(r=>r.data.data),
  createJob:(payload:any)=>apiClient.post('/era5/jobs',payload).then(r=>r.data.data),
  cancelJob:(id:string)=>apiClient.post(`/era5/jobs/${id}/cancel`).then(r=>r.data.data),
  retryJob:(id:string)=>apiClient.post(`/era5/jobs/${id}/retry`).then(r=>r.data.data),
  files:()=>apiClient.get('/era5/files').then(r=>r.data.data),
  statistics:()=>apiClient.get('/era5/samples/statistics').then(r=>r.data.data),
  build:(limit?:number)=>apiClient.post('/era5/samples/build',null,{params:{limit}}).then(r=>r.data.data),
  importFile:(file:File)=>{const form=new FormData();form.append('file',file);return apiClient.post('/era5/import',form,{timeout:120000}).then(r=>r.data.data)},
}
