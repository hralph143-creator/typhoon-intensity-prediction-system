export interface SplitSummary { sample_count:number; event_count:number; years:number[]; wind_min:number|null; wind_max:number|null; wind_mean:number|null }
export interface SampleStatistics { quality_profile:string; dataset_version:string; total:number; splits:Record<string, SplitSummary | Record<string,string[]> | boolean> }
export interface Metric { sample_count:number; mae:number; rmse:number; bias:number; persistence_mae?:number|null; improvement_pct?:number|null }
export interface Experiment {
  id:string; name:string; model_type:string; quality_profile:string; status:string; phase:string; progress:number; current_epoch:number; max_epochs:number
  config:Record<string,unknown>; dataset_version:string|null; split_statistics:Record<string,unknown>; training_curve:Array<Record<string,number>>
  metrics:Record<string,{overall:Metric; groups?:Record<string,Record<string,Metric>>; points?:PredictionPoint[]; extreme_errors?:PredictionPoint[]}>; device:string|null
  error_message:string|null; created_at:string; started_at:string|null; finished_at:string|null; model?:ModelArtifact|null
}
export interface ModelArtifact { id:string; experiment_id:string; name:string; model_type:string; model_path:string; metadata_path:string; dataset_version:string; feature_names:string[]; metrics:Experiment['metrics']; created_at:string }
export interface PredictionPoint { sid:string; season:number; forecast_time:string; target_time:string; actual:number; predicted:number; persistence:number; error:number }
export interface BacktestResult { id:string; sid:string; name:string; forecast_time:string; target_time:string; predicted_wind:number; actual_wind:number|null; error:number|null; model_name:string; model_type:string; model_created_at:string; data_source:string; quality_profile:string; input_winds:number[]; historical_backtest:true }
export interface Audit { observation_count:number; valid_cma_wind_count:number; missing_cma_wind_count:number; missing_cma_wind_ratio:number; special_cma_17_count:number; abnormal_wind_count:number; strict_sample_count:number; extended_sample_count:number; cma_iflag_count:Record<string,number>; track_type_count:Record<string,number>; yearly_valid_cma_wind:Record<string,number> }
