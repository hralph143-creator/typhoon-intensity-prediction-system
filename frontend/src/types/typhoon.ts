export interface Page<T> { items: T[]; total: number; page: number; page_size: number }
export interface TyphoonEvent {
  id: number
  source: string
  sid: string
  season: number
  number: number | null
  name: string
  first_observation: string
  last_observation: string
  observation_count: number
  maximum_wind: number | null
  minimum_pressure: number | null
  maximum_category: number | null
  track_types?: string[]
}
export interface SourceFile {
  id: number
  filename: string
  size_bytes: number
  sha256: string
  version: string
  source_url: string | null
  acquired_at: string
  imported_at: string | null
  status: string
  statistics: Record<string, unknown>
}
export interface ImportJob {
  id: string
  kind: string
  filename: string
  status: string
  phase: string
  total_records: number
  valid_records: number
  skipped_records: number
  failed_records: number
  downloaded_bytes: number
  total_bytes: number | null
  speed_bps: number
  progress: number | null
  cancel_requested: boolean
  started_at: string
  finished_at: string | null
  error_message: string | null
  statistics: Record<string, unknown>
}
export interface Observation {
  id: number
  observation_time: string
  latitude: number
  longitude: number
  basin: string
  track_type: string
  cma_wind: number | null
  cma_wind_ms: number | null
  cma_pressure: number | null
  cma_category: number | null
  wmo_wind_ms: number | null
  wmo_pressure: number | null
  wmo_agency: string | null
  usa_wind_ms: number | null
  tokyo_wind_ms: number | null
  quality_flags: string[]
  source_file_id: number
}
export interface TyphoonDetail extends TyphoonEvent { source_files: SourceFile[]; track_types: string[] }
export interface TrackResponse { items: Observation[]; total: number; track_type: string }
export interface Statistics {
  typhoon_count: number
  all_event_count?: number
  observation_count: number
  main_observation_count: number
  years: number[]
  yearly: { year: number; count: number }[]
  yearly_all?: { year: number; count: number }[]
  provisional_observation_count?: number
  missing_cma_wind_count: number
  last_import_at: string | null
  latest_job: ImportJob | null
}
export interface IbtracsStatus {
  source: string
  official_url: string
  download_url: string
  connected: boolean
  file_count: number
  imported_files: SourceFile[]
  typhoon_count: number
  observation_count: number
  last_import_at: string | null
  active_job: ImportJob | null
}
export interface TyphoonFilters {
  include_spurs?: boolean
  season?: number
  name?: string
  sid?: string
  min_wind?: number
  max_wind?: number
  category?: number
  source?: string
  page: number
  page_size: number
  sort_by: string
  sort_order: string
}
