export interface ApiResponse<T>{success:boolean;message:string;data:T}
export interface HealthStatus{status:string;database:string;timestamp:string}
export interface RuntimeInfo{software_name:string;brand:string;version:string;environment:string;python_version:string;platform:string;database_type:string;database_path:string;data_root:string}
export interface DataSourceStatus{code:'ibtracs'|'cma'|'era5';name:string;provider:string;connected:boolean;file_count:number;local_path:string;status_text:string;official_url:string}
