export type AbuDhabiModelId = 'geosos_flus' | 'geospatial_kernel' | 'paper58';
export type AbuDhabiTrack = 'historical' | 'planning';

export interface HistoricalMetrics {
  change_f1?: number | null;
  change_fom?: number | null;
  macro_f1?: number | null;
  overall_accuracy?: number | null;
  demand_total_variation?: number | null;
  constraint_violation_rate?: number | null;
  high_confidence_change_fom?: number | null;
}

export interface PlanningCandidate {
  candidate_id?: string;
  model_id?: string;
  scenario_id?: string;
  built_gain_pixels?: number | null;
  green_gain_pixels?: number | null;
  removed_built_pixels?: number | null;
  demand_total_variation?: number | null;
  ecological_conversion_rate?: number | null;
  new_built_neighbor_fraction?: number | null;
  new_built_mean_prior_built_distance_m?: number | null;
  new_built_mean_major_road_distance_m?: number | null;
  constraint_violation_rate?: number | null;
  pareto?: boolean;
}

export interface ModelPresentation {
  id: AbuDhabiModelId;
  label: string;
  family: string;
  mechanism: string;
  state: string;
  action: string;
  runtime: string;
  inputs: string[];
  caveats: string[];
  historical?: Record<string, HistoricalMetrics>;
  planning?: PlanningCandidate[];
  pareto_scenarios?: string[];
}

export interface LegendItem {
  value: number;
  label: string;
  color: string;
}

export interface AbuDhabiOverview {
  schema: string;
  status: string;
  benchmark_id: string;
  title: string;
  scope: {
    city: string;
    boundary: string;
    crs: string;
    resolution_m: number;
    width: number;
    height: number;
    valid_pixels: number;
    area_km2: number;
    observed_years: number[];
  };
  data_quality: {
    status: string;
    mean_low_confidence_fraction: number;
    median_one_year_reversion_fraction: number;
    interpretation: string;
  };
  output_audit: {
    status: string;
    prediction_count: number;
    failure_count: number;
    track_counts: Record<string, number>;
  };
  input_sources: Array<{ name: string; source: string; years: string; role: string }>;
  models: ModelPresentation[];
  interpretation: string[];
  pareto_frontier: string[];
  claim_boundary: {
    supports: string[];
    does_not_support: string[];
    planning: string[];
  };
  required_controls: string[];
  figures: string[];
  legend: LegendItem[];
}

export interface AbuDhabiModelPayload {
  schema: string;
  status: string;
  benchmark_id: string;
  model: ModelPresentation;
  state_writeback: boolean;
  test_label_access_during_fit: boolean;
  historical: Record<string, HistoricalMetrics>;
  training_runs: Array<{ seed: number; training: Record<string, unknown> }>;
  planning: PlanningCandidate[];
  options: {
    historical_years: number[];
    planning_years: number[];
    scenarios: string[];
    seeds: string[];
  };
  legend: LegendItem[];
}

export interface AbuDhabiRun {
  schema: string;
  run_id: string;
  status: 'queued' | 'running' | 'complete' | 'failed';
  stage: string;
  model_id: AbuDhabiModelId;
  model_label: string;
  track: AbuDhabiTrack;
  seed: number;
  scenario?: string | null;
  requested_at: string;
  started_at?: string;
  completed_at?: string;
  years: number[];
  output_count?: number;
  error?: string;
}

export const API_BASE = '/api/benchmarks/abu-dhabi-land-use';

export const MODEL_LABELS: Record<AbuDhabiModelId, string> = {
  geosos_flus: 'GeoSOS-FLUS',
  geospatial_kernel: 'Geospatial Kernel',
  paper58: 'Paper58',
};

export const SCENARIO_LABELS: Record<string, string> = {
  compact: '紧凑增长',
  ecological_priority: '生态优先',
  outward_growth: '外延增长',
};

export function rasterUrl(
  modelId: AbuDhabiModelId | 'observed',
  track: AbuDhabiTrack,
  year: number,
  seed = 'ensemble',
  scenario?: string,
) {
  const params = new URLSearchParams({ track, year: String(year), seed });
  if (scenario) params.set('scenario', scenario);
  return `${API_BASE}/rasters/${modelId}?${params.toString()}`;
}

export function figureUrl(figureId: string) {
  return `${API_BASE}/figures/${figureId}`;
}

export function runtimeRasterUrl(runId: string, year: number) {
  return `${API_BASE}/runs/${runId}/rasters/${year}`;
}

export function formatMetric(value: number | null | undefined, digits = 4) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '-';
}

export function formatPercent(value: number | null | undefined, digits = 2) {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(digits)}%` : '-';
}

export function formatCount(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? Math.round(value).toLocaleString('zh-CN') : '-';
}
