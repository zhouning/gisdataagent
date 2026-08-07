import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, BarChart3, CheckCircle2, Layers, ListChecks, Map, PlayCircle, RefreshCw, ShieldCheck } from 'lucide-react';
import AbuDhabiLandUseModelTab from './AbuDhabiLandUseModelTab';

type MetricValue = string | number | null | undefined;
type MetricValueRecord = Record<string, MetricValue>;

interface VisualizationArea {
  area: string;
  display_name?: string;
  start_year?: number;
  end_year?: number;
  n_pixels?: number;
  paper58_change_f1?: number | null;
  baseline_change_f1?: number | null;
  paper58_delta_change_f1?: number | null;
  paper58_wins?: boolean;
}

interface MethodSummary {
  method?: string | null;
  n?: number | null;
  mean_change_f1?: number | null;
  mean_fom?: number | null;
  mean_transition_accuracy?: number | null;
  mean_allocation_disagreement?: number | null;
}

interface Paper58Visualization {
  schema?: string;
  status?: string;
  source_dir?: string | null;
  selected_area?: string | null;
  selected_method?: string | null;
  baseline_method?: string | null;
  years?: number[];
  areas: VisualizationArea[];
  method_summary: MethodSummary[];
  selected_area_metrics?: {
    paper58?: MetricValueRecord;
    baseline?: MetricValueRecord;
    deltas?: Record<string, number | null | undefined>;
    winner_by_metric?: Record<string, string | null | undefined>;
  };
  visualization?: {
    map_action?: string;
    available_layers?: string[];
    class_legend?: Record<string, string>;
    difference_legend?: Record<string, string>;
    display_crs?: string;
    georeferenced?: boolean;
    georef_source?: string | null;
  };
  source_files?: Record<string, string | null | undefined>;
  missing?: string[];
  error?: string;
}

interface Paper58Evidence {
  schema?: string;
  status?: 'missing' | 'supporting_evidence' | 'review' | 'blocked' | string;
  provided?: boolean;
  missing?: string[];
  read_errors?: Array<{ path?: string; error?: string }>;
  source_files?: Record<string, string | null | undefined>;
  metric_summary?: {
    best_paper58_method?: string | null;
    baseline_method?: string | null;
    area_count?: number | null;
    paper58_vs_baseline_wins?: number | null;
    best_paper58_metrics?: MetricValueRecord;
    baseline_metrics?: MetricValueRecord;
    deltas?: Record<string, number | null | undefined>;
  };
  manifest_summary?: Record<string, unknown>;
  claim_scope?: string;
  runtime_dependency?: string;
  geofm_runtime_allowed?: boolean;
  twm_generator_role?: string;
  primary_twm_route?: string;
  blocks_validation?: boolean;
  can_promote_claim_ladder?: boolean;
  claim_boundary?: string;
  error?: string;
}

interface RuntimeCase {
  area: string;
  display_name?: string;
  start_year?: number;
  end_year?: number;
  valid_pixels?: number;
  changed_pixels?: number;
  methods?: string[];
}

interface RuntimeCatalog {
  schema?: string;
  status?: string;
  cases: RuntimeCase[];
  engines?: {
    paper58?: { available?: boolean; path?: string };
    geosos_flus?: { available?: boolean; path?: string };
  };
  missing?: string[];
  error?: string;
}

interface RuntimeRun {
  schema?: string;
  run_id?: string;
  status?: string;
  case?: RuntimeCase;
  paper58_method?: string;
  output_dir?: string;
  stages?: Array<{ key?: string; label?: string; status?: string; message?: string }>;
  metrics?: Record<string, MetricValueRecord>;
  layers?: Array<{ name?: string; geojson?: string; type?: string; visible?: boolean }>;
  error?: string;
}

const areaMetricLabels: Record<string, string> = {
  change_f1: '变化 F1',
  fom: 'FoM',
  transition_accuracy: '转换准确率',
  allocation_disagreement: '分配分歧',
};

const methodMetricLabels: Record<string, string> = {
  mean_change_f1: '变化 F1',
  mean_fom: 'FoM',
  mean_transition_accuracy: '转换准确率',
  mean_allocation_disagreement: '分配分歧',
};

const BOUNDARY_DEFAULTS: Paper58Evidence = {
  status: 'missing',
  claim_scope: '仅支持外部基准证据',
  runtime_dependency: '无运行依赖',
  geofm_runtime_allowed: false,
  twm_generator_role: '不是运行时生成器',
  primary_twm_route: '世界模型原生生成与规划流程',
  blocks_validation: false,
  can_promote_claim_ladder: false,
  claim_boundary: 'Paper58 仅作为外部基准证据，不作为世界模型运行时生成器。',
};

const EMPTY_VISUALIZATION: Paper58Visualization = {
  status: 'missing',
  selected_area: null,
  selected_method: null,
  baseline_method: 'geosos_flus_console',
  years: [2020, 2021],
  areas: [],
  method_summary: [],
  selected_area_metrics: { paper58: {}, baseline: {}, deltas: {}, winner_by_metric: {} },
  visualization: {
    map_action: 'POST /api/twm/paper58-visualization/map',
    available_layers: [
      'Paper58 土地利用 2020',
      'Paper58 土地利用 2021',
      'GeoSOS-FLUS 土地利用 2021',
      'Paper58 与 GeoSOS-FLUS 差异 2021',
    ],
    display_crs: 'local_same_grid_normalized',
    georeferenced: false,
    georef_source: null,
  },
  missing: [],
};

const EMPTY_RUNTIME_CATALOG: RuntimeCatalog = {
  status: 'missing',
  cases: [],
  engines: {
    paper58: { available: false },
    geosos_flus: { available: false },
  },
  missing: [],
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function normalizedString(value: unknown) {
  return typeof value === 'string' ? value : undefined;
}

function normalizedNullableString(value: unknown) {
  if (typeof value === 'string' || value === null) return value;
  return undefined;
}

function normalizedBoolean(value: unknown) {
  return typeof value === 'boolean' ? value : undefined;
}

function normalizedNullableNumber(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (value === null) return null;
  return undefined;
}

function normalizeSourceFiles(value: unknown) {
  const sourceFiles: Record<string, string | null | undefined> = {};
  if (!isRecord(value)) return sourceFiles;

  Object.entries(value).forEach(([key, sourcePath]) => {
    if (typeof sourcePath === 'string' || sourcePath === null || typeof sourcePath === 'undefined') {
      sourceFiles[key] = sourcePath;
    }
  });

  return sourceFiles;
}

function normalizeDeltas(value: unknown) {
  const deltas: Record<string, number | null | undefined> = {};
  if (!isRecord(value)) return deltas;

  Object.entries(value).forEach(([key, delta]) => {
    if (typeof delta === 'number' && Number.isFinite(delta)) {
      deltas[key] = delta;
    } else if (delta === null || typeof delta === 'undefined') {
      deltas[key] = delta;
    }
  });

  return deltas;
}

function normalizeMetricRecord(value: unknown) {
  const metrics: MetricValueRecord = {};
  if (!isRecord(value)) return metrics;

  Object.entries(value).forEach(([key, metricValue]) => {
    if (typeof metricValue === 'number' && Number.isFinite(metricValue)) {
      metrics[key] = metricValue;
    } else if (typeof metricValue === 'string' || metricValue === null || typeof metricValue === 'undefined') {
      metrics[key] = metricValue;
    }
  });

  return metrics;
}

function normalizeWinnerMap(value: unknown): Record<string, string | null | undefined> {
  const winners: Record<string, string | null | undefined> = {};
  if (!isRecord(value)) return winners;

  Object.entries(value).forEach(([key, winner]) => {
    if (typeof winner === 'string' || winner === null || typeof winner === 'undefined') {
      winners[key] = winner;
    }
  });

  return winners;
}

function normalizeReadErrors(value: unknown): Array<{ path?: string; error?: string }> {
  if (!Array.isArray(value)) return [];

  return value
    .filter(isRecord)
    .map(item => ({
      path: normalizedString(item.path),
      error: normalizedString(item.error),
    }))
    .filter(item => item.path || item.error);
}

function normalizeEvidence(raw: unknown): Paper58Evidence {
  const evidence: Paper58Evidence = {
    ...BOUNDARY_DEFAULTS,
    missing: [],
    read_errors: [],
    source_files: {},
  };

  if (!isRecord(raw)) return evidence;

  return {
    ...evidence,
    schema: normalizedString(raw.schema),
    status: normalizedString(raw.status) || evidence.status,
    provided: normalizedBoolean(raw.provided),
    missing: Array.isArray(raw.missing) ? raw.missing.filter((item): item is string => typeof item === 'string') : [],
    read_errors: normalizeReadErrors(raw.read_errors),
    source_files: normalizeSourceFiles(raw.source_files),
    metric_summary: isRecord(raw.metric_summary) ? {
      best_paper58_method: normalizedNullableString(raw.metric_summary.best_paper58_method),
      baseline_method: normalizedNullableString(raw.metric_summary.baseline_method),
      area_count: normalizedNullableNumber(raw.metric_summary.area_count),
      paper58_vs_baseline_wins: normalizedNullableNumber(raw.metric_summary.paper58_vs_baseline_wins),
      best_paper58_metrics: normalizeMetricRecord(raw.metric_summary.best_paper58_metrics),
      baseline_metrics: normalizeMetricRecord(raw.metric_summary.baseline_metrics),
      deltas: normalizeDeltas(raw.metric_summary.deltas),
    } : undefined,
    manifest_summary: isRecord(raw.manifest_summary) ? raw.manifest_summary : undefined,
    claim_scope: BOUNDARY_DEFAULTS.claim_scope,
    runtime_dependency: BOUNDARY_DEFAULTS.runtime_dependency,
    geofm_runtime_allowed: BOUNDARY_DEFAULTS.geofm_runtime_allowed,
    twm_generator_role: BOUNDARY_DEFAULTS.twm_generator_role,
    primary_twm_route: BOUNDARY_DEFAULTS.primary_twm_route,
    blocks_validation: BOUNDARY_DEFAULTS.blocks_validation,
    can_promote_claim_ladder: BOUNDARY_DEFAULTS.can_promote_claim_ladder,
    claim_boundary: BOUNDARY_DEFAULTS.claim_boundary,
    error: normalizedString(raw.error),
  };
}

function normalizeArea(value: unknown): VisualizationArea | null {
  if (!isRecord(value) || typeof value.area !== 'string') return null;
  return {
    area: value.area,
    display_name: normalizedString(value.display_name),
    start_year: normalizedNullableNumber(value.start_year) ?? undefined,
    end_year: normalizedNullableNumber(value.end_year) ?? undefined,
    n_pixels: normalizedNullableNumber(value.n_pixels) ?? undefined,
    paper58_change_f1: normalizedNullableNumber(value.paper58_change_f1),
    baseline_change_f1: normalizedNullableNumber(value.baseline_change_f1),
    paper58_delta_change_f1: normalizedNullableNumber(value.paper58_delta_change_f1),
    paper58_wins: normalizedBoolean(value.paper58_wins),
  };
}

function normalizeMethodSummary(value: unknown): MethodSummary | null {
  if (!isRecord(value)) return null;
  return {
    method: normalizedNullableString(value.method),
    n: normalizedNullableNumber(value.n),
    mean_change_f1: normalizedNullableNumber(value.mean_change_f1),
    mean_fom: normalizedNullableNumber(value.mean_fom),
    mean_transition_accuracy: normalizedNullableNumber(value.mean_transition_accuracy),
    mean_allocation_disagreement: normalizedNullableNumber(value.mean_allocation_disagreement),
  };
}

function normalizeRuntimeCase(value: unknown): RuntimeCase | null {
  if (!isRecord(value) || typeof value.area !== 'string') return null;
  return {
    area: value.area,
    display_name: normalizedString(value.display_name),
    start_year: normalizedNullableNumber(value.start_year) ?? undefined,
    end_year: normalizedNullableNumber(value.end_year) ?? undefined,
    valid_pixels: normalizedNullableNumber(value.valid_pixels) ?? undefined,
    changed_pixels: normalizedNullableNumber(value.changed_pixels) ?? undefined,
    methods: Array.isArray(value.methods) ? value.methods.filter((item): item is string => typeof item === 'string') : [],
  };
}

function normalizeRuntimeCatalog(raw: unknown): RuntimeCatalog {
  if (!isRecord(raw)) return { ...EMPTY_RUNTIME_CATALOG };
  const engines = isRecord(raw.engines) ? raw.engines : {};
  const paper58 = isRecord(engines.paper58) ? engines.paper58 : {};
  const geososFlus = isRecord(engines.geosos_flus) ? engines.geosos_flus : {};
  return {
    ...EMPTY_RUNTIME_CATALOG,
    schema: normalizedString(raw.schema),
    status: normalizedString(raw.status) || EMPTY_RUNTIME_CATALOG.status,
    cases: Array.isArray(raw.cases) ? raw.cases.map(normalizeRuntimeCase).filter((item): item is RuntimeCase => !!item) : [],
    engines: {
      paper58: {
        available: normalizedBoolean(paper58.available),
        path: normalizedString(paper58.path),
      },
      geosos_flus: {
        available: normalizedBoolean(geososFlus.available),
        path: normalizedString(geososFlus.path),
      },
    },
    missing: Array.isArray(raw.missing) ? raw.missing.filter((item): item is string => typeof item === 'string') : [],
    error: normalizedString(raw.error),
  };
}

function normalizeRuntimeRun(raw: unknown): RuntimeRun {
  if (!isRecord(raw)) return {};
  return {
    schema: normalizedString(raw.schema),
    run_id: normalizedString(raw.run_id),
    status: normalizedString(raw.status),
    case: normalizeRuntimeCase(raw.case) ?? undefined,
    paper58_method: normalizedString(raw.paper58_method),
    output_dir: normalizedString(raw.output_dir),
    stages: Array.isArray(raw.stages)
      ? raw.stages.filter(isRecord).map(stage => ({
        key: normalizedString(stage.key),
        label: normalizedString(stage.label),
        status: normalizedString(stage.status),
        message: normalizedString(stage.message),
      }))
      : [],
    metrics: isRecord(raw.metrics)
      ? Object.fromEntries(Object.entries(raw.metrics).map(([key, value]) => [key, normalizeMetricRecord(value)]))
      : {},
    layers: Array.isArray(raw.layers)
      ? raw.layers.filter(isRecord).map(layer => ({
        name: normalizedString(layer.name),
        geojson: normalizedString(layer.geojson),
        type: normalizedString(layer.type),
        visible: normalizedBoolean(layer.visible),
      }))
      : [],
    error: normalizedString(raw.error),
  };
}

function normalizeVisualization(raw: unknown): Paper58Visualization {
  if (!isRecord(raw)) return { ...EMPTY_VISUALIZATION };

  const selectedAreaMetrics = isRecord(raw.selected_area_metrics) ? raw.selected_area_metrics : {};
  const visualization = isRecord(raw.visualization) ? raw.visualization : {};
  return {
    ...EMPTY_VISUALIZATION,
    schema: normalizedString(raw.schema),
    status: normalizedString(raw.status) || EMPTY_VISUALIZATION.status,
    source_dir: normalizedNullableString(raw.source_dir),
    selected_area: normalizedNullableString(raw.selected_area),
    selected_method: normalizedNullableString(raw.selected_method),
    baseline_method: normalizedNullableString(raw.baseline_method),
    years: Array.isArray(raw.years) ? raw.years.filter((item): item is number => typeof item === 'number') : EMPTY_VISUALIZATION.years,
    areas: Array.isArray(raw.areas) ? raw.areas.map(normalizeArea).filter((item): item is VisualizationArea => !!item) : [],
    method_summary: Array.isArray(raw.method_summary)
      ? raw.method_summary.map(normalizeMethodSummary).filter((item): item is MethodSummary => !!item)
      : [],
    selected_area_metrics: {
      paper58: normalizeMetricRecord(selectedAreaMetrics.paper58),
      baseline: normalizeMetricRecord(selectedAreaMetrics.baseline),
      deltas: normalizeDeltas(selectedAreaMetrics.deltas),
      winner_by_metric: normalizeWinnerMap(selectedAreaMetrics.winner_by_metric),
    },
    visualization: {
      map_action: normalizedString(visualization.map_action) || EMPTY_VISUALIZATION.visualization?.map_action,
      available_layers: Array.isArray(visualization.available_layers)
        ? visualization.available_layers.filter((item): item is string => typeof item === 'string')
        : EMPTY_VISUALIZATION.visualization?.available_layers,
      class_legend: isRecord(visualization.class_legend) ? Object.fromEntries(Object.entries(visualization.class_legend).filter(([, value]) => typeof value === 'string')) as Record<string, string> : {},
      difference_legend: isRecord(visualization.difference_legend) ? Object.fromEntries(Object.entries(visualization.difference_legend).filter(([, value]) => typeof value === 'string')) as Record<string, string> : {},
      display_crs: normalizedString(visualization.display_crs),
      georeferenced: normalizedBoolean(visualization.georeferenced),
      georef_source: normalizedNullableString(visualization.georef_source),
    },
    source_files: normalizeSourceFiles(raw.source_files),
    missing: Array.isArray(raw.missing) ? raw.missing.filter((item): item is string => typeof item === 'string') : [],
    error: normalizedString(raw.error),
  };
}

function formatValue(value: unknown) {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '-';
    return value.toFixed(4);
  }
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (value === null || typeof value === 'undefined' || value === '') return '-';
  return String(value);
}

function formatCount(value: unknown) {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '-';
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  return formatValue(value);
}

function statusBadgeClass(status?: string) {
  if (status === 'ready' || status === 'supporting_evidence') return 'status-badge success';
  if (status === 'review') return 'status-badge warning';
  if (status === 'blocked' || status === 'error') return 'status-badge error';
  return 'status-badge dismissed';
}

function statusText(status?: string) {
  const labels: Record<string, string> = {
    ready: '就绪',
    missing: '缺少数据',
    supporting_evidence: '证据可用',
    review: '需复核',
    blocked: '已阻断',
    error: '错误',
  };
  return labels[status || ''] || status || '未知';
}

function formatMethodLabel(value: unknown) {
  if (typeof value !== 'string' || !value) return formatValue(value);
  const labels: Record<string, string> = {
    paper58_spatial_demand_ratio_claim_robustness_v4: 'Paper58 空间需求比例（稳健性 v4）',
    geosos_flus_console: 'GeoSOS-FLUS 控制台基线',
  };
  return labels[value] || value;
}

function MetricValueText({ value }: { value: unknown }) {
  return (
    <strong className="v11-value-text">
      {formatValue(value)}
    </strong>
  );
}

function LegacyWorldModelV11Tab() {
  const [viewMode, setViewMode] = useState<'results' | 'runtime'>('results');
  const [visualization, setVisualization] = useState<Paper58Visualization>(() => normalizeVisualization(null));
  const [evidence, setEvidence] = useState<Paper58Evidence>(() => normalizeEvidence(null));
  const [runtimeCatalog, setRuntimeCatalog] = useState<RuntimeCatalog>(() => normalizeRuntimeCatalog(null));
  const [runtimeRun, setRuntimeRun] = useState<RuntimeRun | null>(null);
  const [selectedArea, setSelectedArea] = useState('');
  const [selectedMethod, setSelectedMethod] = useState('');
  const [selectedRuntimeArea, setSelectedRuntimeArea] = useState('');
  const [selectedRuntimeMethod, setSelectedRuntimeMethod] = useState('paper58_spatial_demand_ratio_claim_robustness_v4');
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [pushingMap, setPushingMap] = useState(false);
  const [runningRuntime, setRunningRuntime] = useState(false);
  const [pushingRuntimeMap, setPushingRuntimeMap] = useState(false);
  const [error, setError] = useState('');
  const [mapMessage, setMapMessage] = useState('');

  const areaMetricRows = useMemo(() => {
    const paper58 = visualization.selected_area_metrics?.paper58 || {};
    const baseline = visualization.selected_area_metrics?.baseline || {};
    const deltas = visualization.selected_area_metrics?.deltas || {};
    return Object.keys(areaMetricLabels).map(key => ({
      key,
      label: areaMetricLabels[key],
      paper58: paper58[key],
      baseline: baseline[key],
      delta: deltas[key],
    }));
  }, [visualization]);

  const selectedAreaRecord = useMemo(
    () => visualization.areas.find(area => area.area === selectedArea) || visualization.areas[0],
    [visualization.areas, selectedArea],
  );

  const selectedRuntimeCase = useMemo(
    () => runtimeCatalog.cases.find(area => area.area === selectedRuntimeArea) || runtimeCatalog.cases[0],
    [runtimeCatalog.cases, selectedRuntimeArea],
  );

  const runtimeMetricRows = useMemo(() => {
    const paper58 = runtimeRun?.metrics?.paper58 || {};
    const geososFlus = runtimeRun?.metrics?.geosos_flus || {};
    return Object.keys(areaMetricLabels).map(key => ({
      key,
      label: areaMetricLabels[key],
      paper58: paper58[key],
      geososFlus: geososFlus[key],
    }));
  }, [runtimeRun]);

  const loadVisualization = async (area = selectedArea, method = selectedMethod) => {
    setLoading(true);
    setError('');
    setMapMessage('');
    try {
      const params = new URLSearchParams();
      if (area) params.set('area', area);
      if (method) params.set('method', method);
      const suffix = params.toString() ? `?${params.toString()}` : '';
      const resp = await fetch(`/api/twm/paper58-visualization${suffix}`, { credentials: 'include' });
      const data = normalizeVisualization(await resp.json());
      if (!resp.ok || data.error) {
        const message = data.error || 'Paper58 可视化加载失败';
        setVisualization(normalizeVisualization({ error: message }));
        setError(message);
        return;
      }
      setVisualization(data);
      if (data.selected_area) setSelectedArea(data.selected_area);
      if (data.selected_method) setSelectedMethod(data.selected_method);
    } catch (err: unknown) {
      setVisualization(normalizeVisualization(null));
      setError(err instanceof Error ? err.message : 'Paper58 可视化加载失败');
    } finally {
      setLoading(false);
    }
  };

  const loadEvidence = async () => {
    try {
      const resp = await fetch('/api/twm/paper58-benchmark', { credentials: 'include' });
      const data = normalizeEvidence(await resp.json());
      setEvidence(data);
    } catch {
      setEvidence(normalizeEvidence(null));
    }
  };

  const loadRuntimeCases = async () => {
    try {
      const resp = await fetch('/api/twm/world-model-v11/runtime/cases', { credentials: 'include' });
      const data = normalizeRuntimeCatalog(await resp.json());
      setRuntimeCatalog(data);
      if (data.cases[0] && !selectedRuntimeArea) setSelectedRuntimeArea(data.cases[0].area);
      const firstMethod = data.cases[0]?.methods?.find(method => method.includes('paper58_spatial_demand_ratio')) || data.cases[0]?.methods?.[0];
      if (firstMethod && !selectedRuntimeMethod) setSelectedRuntimeMethod(firstMethod);
    } catch {
      setRuntimeCatalog(normalizeRuntimeCatalog(null));
    }
  };

  const refreshEvidence = async () => {
    setRefreshing(true);
    setError('');
    try {
      const resp = await fetch('/api/twm/paper58-benchmark/refresh', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const data = normalizeEvidence(await resp.json());
      if (!resp.ok || data.error) {
        const message = data.error || 'Paper58 证据刷新失败';
        setError(message);
        return;
      }
      setEvidence(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Paper58 证据刷新失败');
    } finally {
      setRefreshing(false);
    }
  };

  const pushVisualizationToMap = async () => {
    setPushingMap(true);
    setError('');
    setMapMessage('');
    try {
      const resp = await fetch('/api/twm/paper58-visualization/map', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ area: selectedArea, method: selectedMethod }),
      });
      const data = await resp.json();
      if (!resp.ok || data.error || data.map_update_queued === false) {
        setError(data.error || 'Paper58 地图更新失败');
        return;
      }
      const mapResp = await fetch('/api/map/pending', { credentials: 'include' });
      const mapData = await mapResp.json();
      const mapUpdate = mapData.map_update || data.map_update;
      (window as any).__twmLastMapUpdate = mapUpdate;
      if (mapUpdate && (window as any).__handleMapUpdate) {
        (window as any).__handleMapUpdate(mapUpdate);
      }
      setMapMessage('已发送 Paper58 与 GeoSOS-FLUS 对比图层到地图。');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Paper58 地图更新失败');
    } finally {
      setPushingMap(false);
    }
  };

  const startRuntimeRun = async () => {
    const area = selectedRuntimeArea || selectedRuntimeCase?.area;
    if (!area) {
      setError('请选择样本区域后再运行。');
      return;
    }
    setRunningRuntime(true);
    setError('');
    setMapMessage('');
    try {
      const resp = await fetch('/api/twm/world-model-v11/runtime/runs', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ area, method: selectedRuntimeMethod }),
      });
      const data = normalizeRuntimeRun(await resp.json());
      if (!resp.ok || data.error) {
        setError(data.error || '全流程运行失败');
        setRuntimeRun(data);
        return;
      }
      setRuntimeRun(data);
      setMapMessage('全流程运行已完成，可以加载运行结果到地图。');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '全流程运行失败');
    } finally {
      setRunningRuntime(false);
    }
  };

  const pushRuntimeRunToMap = async () => {
    if (!runtimeRun?.run_id) {
      setError('没有可加载的运行结果。');
      return;
    }
    setPushingRuntimeMap(true);
    setError('');
    setMapMessage('');
    try {
      const resp = await fetch(`/api/twm/world-model-v11/runtime/runs/${runtimeRun.run_id}/map`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const data = await resp.json();
      if (!resp.ok || data.error || data.map_update_queued === false) {
        setError(data.error || '运行结果地图加载失败');
        return;
      }
      const mapResp = await fetch('/api/map/pending', { credentials: 'include' });
      const mapData = await mapResp.json();
      const mapUpdate = mapData.map_update || data.map_update;
      (window as any).__twmLastMapUpdate = mapUpdate;
      if (mapUpdate && (window as any).__handleMapUpdate) {
        (window as any).__handleMapUpdate(mapUpdate);
      }
      setMapMessage('已加载全流程运行结果到地图。');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '运行结果地图加载失败');
    } finally {
      setPushingRuntimeMap(false);
    }
  };

  useEffect(() => {
    loadVisualization();
    loadEvidence();
    loadRuntimeCases();
  }, []);

  const sourceFiles = isRecord(evidence.source_files) ? evidence.source_files : {};
  const readErrors = Array.isArray(evidence.read_errors) ? evidence.read_errors : [];
  const missingEvidence = Array.isArray(evidence.missing) ? evidence.missing : [];
  const visualLayers = visualization.visualization?.available_layers || EMPTY_VISUALIZATION.visualization?.available_layers || [];
  const status = visualization.status || 'missing';
  const georeferenced = visualization.visualization?.georeferenced === true;
  const displayCrs = visualization.visualization?.display_crs || '-';
  const georefSource = visualization.visualization?.georef_source;

  return (
    <div className="datapanel-section world-model-v11-tab">
      <div className="datapanel-section-header">
        <div>
          <h3>世界模型 v1.1</h3>
          <p>Paper58 与 GeoSOS-FLUS 同栅格结果</p>
        </div>
        <span className={statusBadgeClass(status)}>{statusText(status)}</span>
      </div>

      {error && (
        <div className="v11-message error">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      {mapMessage && (
        <div className="v11-message success">
          <CheckCircle2 size={16} />
          <span>{mapMessage}</span>
        </div>
      )}

      <div className="v11-mode-switch" aria-label="世界模型 v1.1 模式">
        <button
          type="button"
          className={viewMode === 'results' ? 'active' : ''}
          onClick={() => setViewMode('results')}
        >
          <BarChart3 size={14} />
          结果查看
        </button>
        <button
          type="button"
          className={viewMode === 'runtime' ? 'active' : ''}
          onClick={() => setViewMode('runtime')}
        >
          <PlayCircle size={14} />
          全流程运行
        </button>
      </div>

      {viewMode === 'runtime' && (
        <>
          <section className="v11-panel v11-control-panel">
            <div className="v11-panel-header">
              <ListChecks size={16} />
              <strong>Paper58 与 GeoSOS-FLUS 全流程运行</strong>
            </div>
            <div className="v11-controls">
              <label className="v11-field">
                <span>样本区域</span>
                <select
                  value={selectedRuntimeArea}
                  disabled={runningRuntime || runtimeCatalog.cases.length === 0}
                  onChange={(event) => setSelectedRuntimeArea(event.target.value)}
                >
                  {runtimeCatalog.cases.map(item => (
                    <option key={item.area} value={item.area}>
                      {item.display_name || item.area} · {formatCount(item.valid_pixels)} 有效像元
                    </option>
                  ))}
                </select>
              </label>

              <label className="v11-field">
                <span>Paper58 方法</span>
                <select
                  value={selectedRuntimeMethod}
                  disabled={runningRuntime}
                  onChange={(event) => setSelectedRuntimeMethod(event.target.value)}
                >
                  {(selectedRuntimeCase?.methods?.length ? selectedRuntimeCase.methods : ['paper58_spatial_demand_ratio_claim_robustness_v4']).map(method => (
                    <option key={method} value={method}>{formatMethodLabel(method)}</option>
                  ))}
                </select>
              </label>

              <div className="v11-actions">
                <button className="primary-button" type="button" onClick={startRuntimeRun} disabled={runningRuntime || runtimeCatalog.cases.length === 0}>
                  <PlayCircle size={14} />
                  {runningRuntime ? '运行中' : '运行并生成图层'}
                </button>
                <button className="secondary-button" type="button" onClick={loadRuntimeCases} disabled={runningRuntime}>
                  <RefreshCw size={14} />
                  刷新样本
                </button>
              </div>
            </div>

            <div className={runtimeCatalog.engines?.geosos_flus?.available ? 'v11-crs-note ready' : 'v11-crs-note warning'}>
              <span>{runtimeCatalog.engines?.geosos_flus?.available ? 'GeoSOS-FLUS 可运行' : 'GeoSOS-FLUS 未检测到可执行程序'}</span>
              {runtimeCatalog.engines?.geosos_flus?.path && <span title={runtimeCatalog.engines.geosos_flus.path}>来源：{runtimeCatalog.engines.geosos_flus.path.split('/').slice(-3).join('/')}</span>}
            </div>
          </section>

          <section className="v11-panel">
            <div className="v11-panel-header">
              <ListChecks size={16} />
              <strong>运行阶段</strong>
              <span className={statusBadgeClass(runtimeRun?.status)}>{statusText(runtimeRun?.status)}</span>
            </div>
            <div className="v11-stage-list">
              {(runtimeRun?.stages?.length ? runtimeRun.stages : [
                { key: 'validate_inputs', label: '输入检查', status: 'pending' },
                { key: 'paper58', label: 'Paper58 运行', status: 'pending' },
                { key: 'geosos_flus', label: 'GeoSOS-FLUS 运行', status: 'pending' },
                { key: 'metrics', label: '指标计算', status: 'pending' },
                { key: 'layers', label: '图层生成', status: 'pending' },
              ]).map(stage => (
                <div className={`v11-stage-item ${stage.status || 'pending'}`} key={stage.key || stage.label}>
                  <span className="v11-stage-dot" />
                  <strong>{stage.label}</strong>
                  <span>{statusText(stage.status)}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="v11-panel">
            <div className="v11-panel-header">
              <BarChart3 size={16} />
              <strong>运行指标</strong>
            </div>
            <div className="v11-table-wrap">
              <table className="data-table compact-table">
                <thead>
                  <tr><th>指标</th><th>Paper58</th><th>GeoSOS-FLUS</th></tr>
                </thead>
                <tbody>
                  {runtimeMetricRows.map(row => (
                    <tr key={row.key}>
                      <td>{row.label}</td>
                      <td>{formatValue(row.paper58)}</td>
                      <td>{formatValue(row.geososFlus)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="v11-panel">
            <div className="v11-panel-header">
              <Layers size={16} />
              <strong>运行图层</strong>
            </div>
            <div className="v11-layer-list">
              {(runtimeRun?.layers || []).map((layer, index) => (
                <div className="v11-layer-item" key={layer.name || index}>
                  <span>{index + 1}</span>
                  <strong>{layer.name}</strong>
                </div>
              ))}
            </div>
            <div className="v11-actions">
              <button className="primary-button" type="button" onClick={pushRuntimeRunToMap} disabled={pushingRuntimeMap || runtimeRun?.status !== 'completed'}>
                <Layers size={14} />
                {pushingRuntimeMap ? '加载中' : '加载运行结果到地图'}
              </button>
            </div>
          </section>
        </>
      )}

      {viewMode === 'results' && (
        <>
      <section className="v11-panel v11-control-panel">
        <div className="v11-panel-header">
          <Map size={16} />
          <strong>Paper58 与 GeoSOS-FLUS 对比结果</strong>
        </div>
        <div className="v11-controls">
          <label className="v11-field">
            <span>样本区域</span>
            <select
              value={selectedArea}
              disabled={loading || visualization.areas.length === 0}
              onChange={(event) => {
                const nextArea = event.target.value;
                setSelectedArea(nextArea);
                loadVisualization(nextArea, selectedMethod);
              }}
            >
              {visualization.areas.map(area => (
                <option key={area.area} value={area.area}>
                  {area.display_name || area.area} · {formatCount(area.n_pixels)} 像元
                </option>
              ))}
            </select>
          </label>

          <label className="v11-field">
            <span>Paper58 方法</span>
            <select
              value={selectedMethod}
              disabled={loading || visualization.method_summary.length === 0}
              onChange={(event) => {
                const nextMethod = event.target.value;
                setSelectedMethod(nextMethod);
                loadVisualization(selectedArea, nextMethod);
              }}
            >
              {visualization.method_summary.map(method => (
                <option key={method.method || 'unknown'} value={method.method || ''}>
                  {formatMethodLabel(method.method)}
                </option>
              ))}
            </select>
          </label>

          <div className="v11-actions">
            <button className="primary-button" type="button" onClick={pushVisualizationToMap} disabled={pushingMap || loading || !selectedArea || !selectedMethod}>
              <Layers size={14} />
              {pushingMap ? '发送中' : '发送到地图'}
            </button>
            <button className="secondary-button" type="button" onClick={() => loadVisualization(selectedArea, selectedMethod)} disabled={loading}>
              <RefreshCw size={14} />
              {loading ? '加载中' : '刷新'}
            </button>
          </div>
        </div>

        <div className={georeferenced ? 'v11-crs-note ready' : 'v11-crs-note warning'}>
          <span>{georeferenced ? `地理坐标：${displayCrs}` : `局部网格坐标：${displayCrs}`}</span>
          {georefSource && <span title={georefSource}>来源：{georefSource.split('/').slice(-3).join('/')}</span>}
        </div>
      </section>

      <div className="v11-kpi-grid">
        <div className="v11-kpi"><span>区域数</span><strong>{formatCount(visualization.areas.length)}</strong></div>
        <div className="v11-kpi"><span>当前样本</span><MetricValueText value={selectedAreaRecord?.display_name || selectedAreaRecord?.area} /></div>
        <div className="v11-kpi"><span>像元数</span><strong>{formatCount(selectedAreaRecord?.n_pixels)}</strong></div>
        <div className="v11-kpi"><span>对比基线</span><strong>{formatMethodLabel(visualization.baseline_method)}</strong></div>
      </div>

      <section className="v11-panel">
        <div className="v11-panel-header">
          <BarChart3 size={16} />
          <strong>选中区域指标</strong>
        </div>
        <div className="v11-table-wrap">
          <table className="data-table compact-table">
            <thead>
              <tr><th>指标</th><th>Paper58</th><th>GeoSOS-FLUS</th><th>差值</th></tr>
            </thead>
            <tbody>
              {areaMetricRows.map(row => (
                <tr key={row.key}>
                  <td>{row.label}</td>
                  <td>{formatValue(row.paper58)}</td>
                  <td>{formatValue(row.baseline)}</td>
                  <td>{formatValue(row.delta)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="v11-panel">
        <div className="v11-panel-header">
          <Layers size={16} />
          <strong>地图图层</strong>
        </div>
        <div className="v11-layer-list">
          {visualLayers.map((layer, index) => (
            <div className="v11-layer-item" key={layer}>
              <span>{index + 1}</span>
              <strong>{layer}</strong>
            </div>
          ))}
        </div>
      </section>

      <section className="v11-panel">
        <div className="v11-panel-header">
          <BarChart3 size={16} />
          <strong>方法对比</strong>
        </div>
        <div className="v11-table-wrap">
          <table className="data-table compact-table">
            <thead>
              <tr>
                <th>方法</th>
                {Object.values(methodMetricLabels).map(label => <th key={label}>{label}</th>)}
              </tr>
            </thead>
            <tbody>
              {visualization.method_summary.map(method => (
                <tr key={method.method || 'unknown'}>
                  <td title={method.method || ''}>{formatMethodLabel(method.method)}</td>
                  <td>{formatValue(method.mean_change_f1)}</td>
                  <td>{formatValue(method.mean_fom)}</td>
                  <td>{formatValue(method.mean_transition_accuracy)}</td>
                  <td>{formatValue(method.mean_allocation_disagreement)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <details className="v11-panel v11-boundary">
        <summary className="v11-panel-header">
          <ShieldCheck size={16} />
          <strong>证据边界</strong>
          <span className={statusBadgeClass(evidence.status)}>{statusText(evidence.status)}</span>
        </summary>
        <div className="v11-boundary-grid">
          <div><span>声明范围</span><MetricValueText value={evidence.claim_scope} /></div>
          <div><span>运行依赖</span><MetricValueText value={evidence.runtime_dependency} /></div>
          <div><span>是否允许作为 GeoFM 运行时</span><MetricValueText value={evidence.geofm_runtime_allowed} /></div>
          <div><span>生成器角色</span><MetricValueText value={evidence.twm_generator_role || BOUNDARY_DEFAULTS.twm_generator_role} /></div>
          <div><span>主运行路径</span><MetricValueText value={evidence.primary_twm_route} /></div>
          <div><span>是否提升声明等级</span><MetricValueText value={evidence.can_promote_claim_ladder} /></div>
        </div>
        <p className="v11-muted">{evidence.claim_boundary || BOUNDARY_DEFAULTS.claim_boundary}</p>
        <div className="v11-actions compact">
          <button className="secondary-button" type="button" onClick={refreshEvidence} disabled={refreshing || loading}>
            <RefreshCw size={14} />
            {refreshing ? '刷新中' : '刷新证据'}
          </button>
        </div>
        <div className="v11-source-grid">
          <div><span>paper58_benchmark_dir</span><MetricValueText value={sourceFiles.paper58_benchmark_dir} /></div>
          <div><span>metric_summary_by_method.csv</span><MetricValueText value={sourceFiles.metric_summary_by_method} /></div>
          <div><span>metrics_by_method.csv</span><MetricValueText value={sourceFiles.metrics_by_method} /></div>
          <div><span>manifest.json</span><MetricValueText value={sourceFiles.manifest} /></div>
        </div>
        {missingEvidence.length > 0 && <p className="v11-muted">缺失文件：{missingEvidence.join(', ')}</p>}
        {readErrors.length > 0 && <p className="v11-muted">读取错误：{readErrors.map(item => item.error || item.path).join('; ')}</p>}
      </details>
        </>
      )}
    </div>
  );
}

export default function WorldModelV11Tab() {
  const [scope, setScope] = useState<'abu_dhabi' | 'external'>('abu_dhabi');

  return (
    <div className="world-model-v11-scope">
      <div className="v11-mode-switch abu-v11-scope-switch" aria-label="Paper58 数据范围">
        <button type="button" className={scope === 'abu_dhabi' ? 'active' : ''} onClick={() => setScope('abu_dhabi')}>
          阿布扎比冻结实验
        </button>
        <button type="button" className={scope === 'external' ? 'active' : ''} onClick={() => setScope('external')}>
          历史外部基准
        </button>
      </div>
      {scope === 'abu_dhabi' ? <AbuDhabiLandUseModelTab modelId="paper58" /> : <LegacyWorldModelV11Tab />}
    </div>
  );
}
