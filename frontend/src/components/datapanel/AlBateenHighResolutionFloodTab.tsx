import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Database,
  Download,
  Gauge,
  Layers3,
  LoaderCircle,
  Map as MapIcon,
  Mountain,
  Network,
  Play,
  RefreshCw,
  Timer,
  Waves,
} from 'lucide-react';
import { getLocaleHeaders } from '../../i18n';

interface AssetStatus {
  key: string;
  label: string;
  ready: boolean;
  filename?: string | null;
  role?: string;
  available_return_periods?: number[];
}

interface DesignStorm {
  return_period_years: number;
  total_depth_mm: number;
  swmm_forcing_ready: boolean;
}

interface PrecomputedResultEntry {
  run_id: string;
  status: 'ready' | 'incomplete';
  return_period_years: number;
  cell_size_m: number;
  total_depth_mm?: number;
  simulation_duration_minutes?: number;
  snapshot_count?: number;
  operational_complete_dewatering?: boolean;
  final_wet_cells_ge_0_01m?: number;
}

interface PrecomputedResultCatalog {
  status: 'ready' | 'partial';
  expected_combination_count: number;
  available_combination_count: number;
  entries: PrecomputedResultEntry[];
  pending?: Array<{ return_period_years: number; cell_size_m: number }>;
}

interface AlBateenStatus {
  status: string;
  scope: {
    name: string;
    name_ar?: string;
    municipality?: string;
    district_id?: number;
    dmt_district_id?: number;
    area_km2?: number;
    center?: number[];
  };
  model: {
    terrain_source_resolution_m?: number;
    default_computation_cell_size_m?: number;
    supported_computation_cell_sizes_m?: number[];
    solver?: string;
    coupling?: string;
    uses_citywide_250m_gwm?: boolean;
    uses_250m_interpolation?: boolean;
  };
  assets: AssetStatus[];
  supported_design_storms: DesignStorm[];
  precomputed_library?: PrecomputedResultCatalog;
  boundary?: GeoJSON.FeatureCollection;
  latest_run?: AlBateenRun | null;
  claim_boundary?: string;
}

interface AlBateenRun {
  run_id?: string;
  status?: string;
  created_at?: string;
  started_at?: string;
  finished_at?: string;
  scenario?: {
    return_period_years?: number;
    total_depth_mm?: number;
    duration_minutes?: number;
    cell_size_m?: number;
    tail_minutes?: number;
    output_step_minutes?: number;
    tide_level_m?: number;
    manning_n?: number;
  };
  progress?: { stage?: string; percent?: number };
  summary?: {
    solver?: string;
    terrain?: {
      source_product?: string;
      source_resolution_m?: number;
      computation_cell_size_m?: number;
      district_land_cells?: number;
      district_land_area_m2?: number;
    };
    timeline?: {
      snapshot_count?: number;
      output_step_minutes?: number;
      simulation_duration_minutes?: number;
    };
    results?: {
      maximum_depth_m?: number;
      maximum_depth_time_minutes?: number;
      maximum_speed_m_s?: number;
      maximum_hazard_index?: number;
      inundated_area_ge_0_01m_m2?: number;
      inundated_area_ge_0_05m_m2?: number;
      inundated_area_ge_0_30m_m2?: number;
      final_surface_volume_m3?: number;
      final_wet_cells_ge_0_01m?: number;
      final_inundated_area_ge_0_01m_m2?: number;
      final_mean_depth_m?: number;
      mapped_maximum_feature_count?: number;
    };
    dewatering?: {
      enabled?: boolean;
      operational_complete?: boolean;
      actual_tail_minutes?: number;
      maximum_tail_minutes?: number;
      stop_reason?: string;
    };
    claim_boundary?: string;
  };
  error?: string;
}

interface AlBateenMapPayload {
  type: 'FeatureCollection';
  name?: string;
  metadata?: {
    run_id?: string;
    cell_size_m?: number;
    source_dtm_resolution_m?: number;
    feature_count?: number;
    center?: number[];
    timeline?: Array<{ index?: number; time_minutes?: number; feature_count?: number }>;
    results?: AlBateenRun['summary'] extends infer S ? S extends { results?: infer R } ? R : never : never;
    claim_boundary?: string;
  };
  boundary?: GeoJSON.FeatureCollection;
  features: any[];
}

const fmt = (value: unknown, digits = 2) => {
  const number = Number(value);
  return Number.isFinite(number)
    ? number.toLocaleString(undefined, { maximumFractionDigits: digits })
    : '—';
};

const stageLabel = (value: string | undefined, english: boolean) => {
  const labels: Record<string, [string, string]> = {
    queued: ['等待计算资源', 'Waiting for compute'],
    preparing_high_resolution_inputs: ['裁剪客户5米DTM与局部网格', 'Preparing customer 5 m DTM and local grid'],
    running_swmm_anuga_coupled_model: ['运行一二维耦合水动力计算', 'Running coupled 1D/2D hydrodynamics'],
    completed: ['计算完成', 'Completed'],
    failed: ['计算失败', 'Failed'],
  };
  const pair = labels[String(value || '')] || [String(value || '—'), String(value || '—')];
  return english ? pair[1] : pair[0];
};

export function findAlBateenPrecomputedResult(
  catalog: PrecomputedResultCatalog | null | undefined,
  returnPeriod: number,
  cellSize: number,
) {
  return catalog?.entries?.find(item => (
    Number(item.return_period_years) === Number(returnPeriod)
    && Number(item.cell_size_m) === Number(cellSize)
    && item.status === 'ready'
  )) || null;
}

export function buildAlBateenCustomerHotspotLayer(
  hotspots?: GeoJSON.FeatureCollection | null,
  english = false,
) {
  if (!hotspots?.features?.length) return [];
  return [{
    name: english
      ? `Customer latest urban-flood critical points (${hotspots.features.length} records)`
      : `客户最新城市积水关键点（${hotspots.features.length} 条）`,
    type: 'categorized' as const,
    geojsonData: hotspots,
    category_column: 'priority',
    category_colors: {
      'Very Important': '#dc2626',
      Important: '#f59e0b',
    },
    category_labels: {
      'Very Important': 'Very Important',
      Important: 'Important',
    },
    legend_title: english
      ? 'Customer latest flood critical-point priority'
      : '客户最新积水关键点优先级',
    visible: true,
    style: { radius: 7, weight: 1.8, color: '#fff7ed', opacity: 1, fillOpacity: 0.92 },
    tooltip_fields: [
      'hotspot_id', 'priority', 'description_ar', 'service_center_ar',
      'service_center_en', 'latitude', 'longitude', 'inventory_version',
    ],
    tooltip_labels: english ? {
      hotspot_id: 'Critical-point ID', priority: 'Priority', description_ar: 'Arabic description',
      service_center_ar: 'Service centre (Arabic)', service_center_en: 'Service centre',
      latitude: 'Latitude', longitude: 'Longitude', inventory_version: 'Inventory version',
    } : {
      hotspot_id: '积水点 ID', priority: '优先级', description_ar: '阿拉伯语描述',
      service_center_ar: '服务中心（阿拉伯语）', service_center_en: '服务中心',
      latitude: '纬度', longitude: '经度', inventory_version: '清单版本',
    },
  }];
}

export function buildAlBateenBoundaryMapUpdate(
  status: AlBateenStatus,
  english = false,
  hotspotLatest506?: GeoJSON.FeatureCollection | null,
) {
  const center = Array.isArray(status?.scope?.center) && status.scope.center.length === 2
    ? status.scope.center.map(Number)
    : [24.453842, 54.345674];
  return {
    schema: 'map_update.v1',
    summary: {
      title: english ? 'Al Bateen high-resolution flood model' : 'Al Bateen 高精度城市内涝模型',
      subtitle: english
        ? 'ADM District 147 · customer 5 m DTM · local 1D/2D hydrodynamic workflow'
        : 'ADM District 147 · 客户5米DTM · 局部一二维水动力流程',
      source_status: 'customer_dtm_local_hydrodynamic_scope',
      layer_group: 'al_bateen_high_resolution_flood',
      result_status: 'scope_ready_for_local_high_resolution_simulation',
      claim_boundary: status?.claim_boundary,
    },
    center,
    zoom: 13.0,
    layers: [
      {
        name: english ? 'Al Bateen · Model boundary' : 'Al Bateen · 模型边界',
        type: 'fill',
        geojsonData: status?.boundary || { type: 'FeatureCollection', features: [] },
        color_scheme: 'Blues',
        style: { color: '#38bdf8', fillColor: '#38bdf8', weight: 2, opacity: 0.95, fillOpacity: 0.08 },
      },
      ...buildAlBateenCustomerHotspotLayer(hotspotLatest506, english),
    ],
  };
}

export function buildAlBateenMapUpdate(
  payload: AlBateenMapPayload,
  current?: GeoJSON.FeatureCollection,
  english = false,
  hotspotLatest506?: GeoJSON.FeatureCollection | null,
) {
  const result = current || payload;
  const runId = String(payload?.metadata?.run_id || 'al-bateen');
  const center = Array.isArray(payload?.metadata?.center) && payload.metadata.center.length === 2
    ? payload.metadata.center.map(Number)
    : [24.453842, 54.345674];
  const cellSize = Number(payload?.metadata?.cell_size_m || 20);
  return {
    schema: 'map_update.v1',
    summary: {
      title: english ? 'Al Bateen high-resolution flood simulation' : 'Al Bateen 高精度城市内涝推演',
      subtitle: english
        ? `${cellSize} m ANUGA 2D · customer 5 m DTM · ${Number(result?.features?.length || 0).toLocaleString()} wet cells`
        : `${cellSize} m ANUGA 2D · 客户5 m DTM · ${Number(result?.features?.length || 0).toLocaleString()} 个湿网格`,
      source_status: 'customer_dtm_local_hydrodynamic_result',
      layer_group: 'al_bateen_high_resolution_flood',
      result_status: 'local_high_resolution_diagnostic_not_engineering_admitted',
      event_id: runId,
      solver: 'ANUGA 2D + EPA SWMM',
      claim_boundary: payload?.metadata?.claim_boundary,
    },
    center,
    zoom: 13.0,
    layers: [
      {
        name: `Al Bateen · ${english ? 'Model boundary' : '区域边界'} · ${runId}`,
        type: 'fill',
        geojsonData: payload.boundary || { type: 'FeatureCollection', features: [] },
        color_scheme: 'Blues',
        style: { color: '#38bdf8', fillColor: '#38bdf8', weight: 2, opacity: 0.95, fillOpacity: 0.04 },
      },
      {
        name: `Al Bateen · ${english ? 'Dynamic flood depth' : '动态积水深度'} · ${runId}`,
        type: 'fill',
        geojsonData: result,
        value_column: 'depth_m',
        breaks: [0.01, 0.03, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0],
        color_scheme: 'Blues',
        legend_title: english ? 'Flood depth (m)' : '积水深度（m）',
        style: { color: '#075985', weight: 0.15, opacity: 0.45, fillOpacity: 0.78 },
        tooltip_fields: [
          'cell_id', 'depth_m', 'speed_m_s', 'hazard_index', 'time_minutes',
          'maximum_depth_m', 'maximum_speed_m_s', 'peak_time_minutes',
          'cell_size_m', 'source_dtm_resolution_m', 'model_scope',
        ],
        tooltip_labels: english ? {
          cell_id: 'Cell ID', depth_m: 'Flood depth (m)', speed_m_s: 'Velocity (m/s)',
          hazard_index: 'Hazard index', time_minutes: 'Simulation time (min)',
          maximum_depth_m: 'Maximum depth (m)', maximum_speed_m_s: 'Maximum velocity (m/s)',
          peak_time_minutes: 'Peak time (min)', cell_size_m: 'Compute grid (m)',
          source_dtm_resolution_m: 'DTM resolution (m)', model_scope: 'Model scope',
        } : {
          cell_id: '网格ID', depth_m: '积水深度（m）', speed_m_s: '流速（m/s）',
          hazard_index: '危险度指标', time_minutes: '推演时刻（分钟）',
          maximum_depth_m: '最大水深（m）', maximum_speed_m_s: '最大流速（m/s）',
          peak_time_minutes: '峰值时刻（分钟）', cell_size_m: '计算网格（m）',
          source_dtm_resolution_m: 'DTM分辨率（m）', model_scope: '模型范围',
        },
      },
      ...buildAlBateenCustomerHotspotLayer(hotspotLatest506, english),
    ],
  };
}

export default function AlBateenHighResolutionFloodTab() {
  const { i18n } = useTranslation();
  const english = i18n.resolvedLanguage === 'en-US';
  const tr = (zh: string, en: string) => english ? en : zh;
  const [status, setStatus] = useState<AlBateenStatus | null>(null);
  const [run, setRun] = useState<AlBateenRun | null>(null);
  const [mapPayload, setMapPayload] = useState<AlBateenMapPayload | null>(null);
  const [framePayload, setFramePayload] = useState<GeoJSON.FeatureCollection | null>(null);
  const [hotspotLatest506, setHotspotLatest506] = useState<GeoJSON.FeatureCollection | null>(null);
  const [returnPeriod, setReturnPeriod] = useState(10);
  const [cellSize, setCellSize] = useState(20);
  const [tailMinutes, setTailMinutes] = useState(120);
  const [outputStep, setOutputStep] = useState(15);
  const [tideLevel, setTideLevel] = useState(0);
  const [manningN, setManningN] = useState(0.035);
  const [frameIndex, setFrameIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [loadingPrecomputed, setLoadingPrecomputed] = useState(false);
  const [error, setError] = useState('');
  const frameRequestRef = useRef(0);
  const precomputedRequestRef = useRef(0);
  const selectionInitializedRef = useRef(false);

  const loadStatus = useCallback(async () => {
    const response = await fetch('/api/abu-dhabi/flood/al-bateen/status', {
      credentials: 'include', headers: getLocaleHeaders(),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.detail || payload?.error || 'Al Bateen status failed');
    if (!selectionInitializedRef.current) {
      const latestReturnPeriod = Number(payload?.latest_run?.scenario?.return_period_years);
      const latestCellSize = Number(payload?.latest_run?.scenario?.cell_size_m);
      if (Number.isFinite(latestReturnPeriod)) setReturnPeriod(latestReturnPeriod);
      if (Number.isFinite(latestCellSize)) setCellSize(latestCellSize);
      selectionInitializedRef.current = true;
    }
    setStatus(payload);
    if (payload.latest_run) setRun(current => current || payload.latest_run);
    return payload as AlBateenStatus;
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    loadStatus()
      .catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [loadStatus]);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/abu-dhabi/flood/hotspots/latest-506/map', {
      credentials: 'include', headers: getLocaleHeaders(),
    })
      .then(async response => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail || payload?.error || 'Customer hotspot map failed');
        if (!cancelled) setHotspotLatest506(payload);
      })
      .catch(reason => {
        if (!cancelled) console.warn('[Al Bateen] failed to load customer 506-point inventory', reason);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!run?.run_id || !['queued', 'running'].includes(String(run.status))) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const response = await fetch(`/api/abu-dhabi/flood/al-bateen/runs/${encodeURIComponent(String(run.run_id))}`, {
          credentials: 'include', headers: getLocaleHeaders(),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail || payload?.error || 'Al Bateen run status failed');
        if (!cancelled) setRun(payload);
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      }
    };
    poll();
    const timer = window.setInterval(poll, 2500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [run?.run_id, run?.status]);

  useEffect(() => {
    if (!run?.run_id || run.status !== 'completed') return;
    if (mapPayload?.metadata?.run_id === run.run_id) return;
    let cancelled = false;
    fetch(`/api/abu-dhabi/flood/al-bateen/runs/${encodeURIComponent(String(run.run_id))}/map`, {
      credentials: 'include', headers: getLocaleHeaders(),
    })
      .then(async response => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail || payload?.error || 'Al Bateen map failed');
        if (cancelled) return;
        setMapPayload(payload);
        setFramePayload({ type: 'FeatureCollection', features: payload.features || [] });
        const timeline = Array.isArray(payload?.metadata?.timeline) ? payload.metadata.timeline : [];
        const defaultFrame = timeline.reduce(
          (best: { index?: number; feature_count?: number } | null, item: { index?: number; feature_count?: number }) => (
            !best || Number(item?.feature_count || 0) > Number(best?.feature_count || 0) ? item : best
          ),
          null,
        );
        setFrameIndex(Number(defaultFrame?.index || 0));
      })
      .catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason)); });
    return () => { cancelled = true; };
  }, [mapPayload?.metadata?.run_id, run?.run_id, run?.status]);

  useEffect(() => {
    if (!mapPayload || !run?.run_id) return;
    const requestId = ++frameRequestRef.current;
    fetch(`/api/abu-dhabi/flood/al-bateen/runs/${encodeURIComponent(String(run.run_id))}/timeseries?time_index=${frameIndex}`, {
      credentials: 'include', headers: getLocaleHeaders(),
    })
      .then(async response => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail || payload?.error || 'Al Bateen time series failed');
        if (requestId !== frameRequestRef.current) return;
        setFramePayload(payload);
      })
      .catch(reason => setError(reason instanceof Error ? reason.message : String(reason)));
  }, [frameIndex, mapPayload, run?.run_id]);

  useEffect(() => {
    if (!playing || !mapPayload?.metadata?.timeline?.length) return;
    const count = mapPayload.metadata.timeline.length;
    const timer = window.setInterval(() => setFrameIndex(value => (value + 1) % count), 850);
    return () => window.clearInterval(timer);
  }, [mapPayload?.metadata?.timeline?.length, playing]);

  useEffect(() => {
    if (!status || mapPayload) return;
    const handler = (window as any).__handleMapUpdate;
    if (typeof handler === 'function') {
      handler(buildAlBateenBoundaryMapUpdate(status, english, hotspotLatest506));
    }
  }, [english, hotspotLatest506, mapPayload, status]);

  useEffect(() => {
    if (!mapPayload || !framePayload) return;
    const handler = (window as any).__handleMapUpdate;
    if (typeof handler === 'function') {
      handler(buildAlBateenMapUpdate(mapPayload, framePayload, english, hotspotLatest506));
    }
  }, [english, framePayload, hotspotLatest506, mapPayload]);

  const selectedStorm = useMemo(
    () => status?.supported_design_storms?.find(item => item.return_period_years === returnPeriod),
    [returnPeriod, status?.supported_design_storms],
  );
  const availableStorms = useMemo(
    () => (status?.supported_design_storms || []).filter(item => item.swmm_forcing_ready),
    [status?.supported_design_storms],
  );
  const ready = status?.status === 'ready' && selectedStorm?.swmm_forcing_ready;
  const running = ['queued', 'running'].includes(String(run?.status));
  const selectedPrecomputed = useMemo(
    () => findAlBateenPrecomputedResult(status?.precomputed_library, returnPeriod, cellSize),
    [cellSize, returnPeriod, status?.precomputed_library],
  );
  const selectedPrecomputedLoaded = Boolean(
    selectedPrecomputed?.run_id && selectedPrecomputed.run_id === run?.run_id && run?.status === 'completed',
  );
  const timeline = mapPayload?.metadata?.timeline || [];
  const currentTime = Number(timeline[frameIndex]?.time_minutes || 0);
  const results = run?.summary?.results;
  const loadedResult = run?.status === 'completed';
  const displayedReturnPeriod = loadedResult
    ? Number(run?.scenario?.return_period_years || returnPeriod)
    : returnPeriod;
  const displayedCellSize = loadedResult
    ? Number(run?.scenario?.cell_size_m || cellSize)
    : cellSize;
  const displayedRainfallDepth = loadedResult
    ? Number(run?.scenario?.total_depth_mm || selectedStorm?.total_depth_mm || 0)
    : Number(selectedStorm?.total_depth_mm || 0);
  const displayedSimulationMinutes = loadedResult
    ? Number(run?.summary?.timeline?.simulation_duration_minutes || 0)
    : 180 + tailMinutes;

  useEffect(() => {
    if (!availableStorms.length) return;
    if (!availableStorms.some(item => item.return_period_years === returnPeriod)) {
      setReturnPeriod(availableStorms[0].return_period_years);
    }
  }, [availableStorms, returnPeriod]);

  const loadPrecomputedResult = useCallback(async (entry: PrecomputedResultEntry) => {
    const requestId = ++precomputedRequestRef.current;
    setLoadingPrecomputed(true);
    setPlaying(false);
    setError('');
    try {
      const response = await fetch(
        `/api/abu-dhabi/flood/al-bateen/runs/${encodeURIComponent(entry.run_id)}`,
        { credentials: 'include', headers: getLocaleHeaders() },
      );
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.detail || payload?.error || 'Al Bateen precomputed result failed');
      if (requestId !== precomputedRequestRef.current) return;
      setMapPayload(null);
      setFramePayload(null);
      setFrameIndex(0);
      setRun(payload);
    } catch (reason) {
      if (requestId === precomputedRequestRef.current) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      if (requestId === precomputedRequestRef.current) setLoadingPrecomputed(false);
    }
  }, []);

  useEffect(() => {
    if (!selectedPrecomputed || selectedPrecomputedLoaded || running || submitting) return;
    loadPrecomputedResult(selectedPrecomputed);
  }, [loadPrecomputedResult, running, selectedPrecomputed, selectedPrecomputedLoaded, submitting]);

  const startRun = async () => {
    setSubmitting(true); setError(''); setPlaying(false); setMapPayload(null); setFramePayload(null);
    try {
      const response = await fetch('/api/abu-dhabi/flood/al-bateen/runs', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({
          returnPeriodYears: returnPeriod,
          cellSizeM: cellSize,
          tailMinutes,
          outputStepMinutes: outputStep,
          tideLevelM: tideLevel,
          manningN,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.detail || payload?.error || 'Al Bateen run start failed');
      setRun(payload);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSubmitting(false);
    }
  };

  const publishMap = () => {
    const handler = (window as any).__handleMapUpdate;
    if (typeof handler === 'function' && mapPayload && framePayload) {
      handler(buildAlBateenMapUpdate(mapPayload, framePayload, english, hotspotLatest506));
    }
  };

  const exportGeoJson = () => {
    if (!framePayload) return;
    const blob = new Blob([JSON.stringify(framePayload)], { type: 'application/geo+json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${run?.run_id || 'al-bateen'}-t${frameIndex}.geojson`;
    link.click();
    URL.revokeObjectURL(url);
  };

  if (loading && !status) {
    return <div className="al-bateen-loading"><LoaderCircle className="abu-flood-loading-icon" size={18} />{tr('正在核验 Al Bateen 高精度数据链路…', 'Checking the Al Bateen high-resolution data chain...')}</div>;
  }

  return (
    <div className="abu-flood-tab al-bateen-tab" data-testid="al-bateen-high-resolution-tab">
      <section className="abu-flood-hero al-bateen-hero">
        <div>
          <span className="abu-flood-kicker">AL BATEEN / HIGH-RESOLUTION FLOOD MODEL</span>
          <h2>{tr('Al Bateen 区域高精度内涝推演', 'Al Bateen High-Resolution Flood Simulation')}</h2>
          <p>{tr('以客户5米DTM、Al Bateen行政边界和匹配的SWMM节点溢流为输入，独立运行局部ANUGA二维浅水模型。', 'Run an independent local ANUGA shallow-water model using the customer 5 m DTM, the Al Bateen district boundary and matching SWMM node flooding.')}</p>
          <div className="abu-flood-hero-meta">
            <span><Mountain size={13} /> {tr('客户5米DTM', 'Customer 5 m DTM')}</span>
            <span><Layers3 size={13} /> {tr(`${displayedCellSize}米计算网格`, `${displayedCellSize} m compute grid`)}</span>
            <span><Network size={13} /> {tr('SWMM–ANUGA耦合', 'SWMM–ANUGA coupling')}</span>
          </div>
        </div>
        <div className="abu-flood-hero-side">
          <div className={`abu-flood-readiness-ring ${ready ? 'complete' : ''}`}>
            <strong>{status?.assets.filter(asset => asset.ready).length || 0} / {status?.assets.length || 0}</strong>
            <span>{tr('基础资产就绪', 'assets ready')}</span>
          </div>
          <div className="abu-flood-hero-note">{tr('ADM District 147', 'ADM District 147')}<br />{fmt(status?.scope.area_km2)} km²</div>
        </div>
      </section>

      <section className="abu-flood-metrics" aria-label={tr('Al Bateen模型概况', 'Al Bateen model overview')}>
        <div><Mountain size={15} /><span>{tr('地形源精度', 'Terrain source')}</span><strong>{fmt(status?.model.terrain_source_resolution_m, 0)} m</strong></div>
        <div><Layers3 size={15} /><span>{tr('计算网格', 'Compute grid')}</span><strong>{displayedCellSize} m</strong></div>
        <div><Waves size={15} /><span>{tr('设计暴雨', 'Design storm')}</span><strong>{displayedReturnPeriod} {tr('年', 'yr')}</strong></div>
        <div><Gauge size={15} /><span>{tr('累计雨量', 'Rainfall depth')}</span><strong>{fmt(displayedRainfallDepth)} mm</strong></div>
        <div><Timer size={15} /><span>{tr('模拟时长', 'Simulation')}</span><strong>{fmt(displayedSimulationMinutes, 0)} min</strong></div>
      </section>

      <section className="abu-flood-scenario-section">
        <div className="abu-flood-section-heading">
          <div><span className="abu-flood-overline">SCENARIO CONTROL</span><h3>{tr('高精度一二维耦合推演', 'High-resolution coupled 1D/2D simulation')}</h3></div>
          <span className={`abu-flood-scenario-badge ${run?.status === 'completed' ? 'abu-flood-status-ready' : run?.status === 'failed' ? 'abu-flood-status-blocked' : ''}`}>
            {running ? <LoaderCircle className="abu-flood-loading-icon" size={13} /> : run?.status === 'completed' ? <CheckCircle2 size={13} /> : <Activity size={13} />}
            {running ? stageLabel(run?.progress?.stage, english) : run?.status === 'completed' ? tr('计算完成', 'Completed') : run?.status === 'failed' ? tr('计算失败', 'Failed') : tr('等待运行', 'Ready to run')}
          </span>
        </div>

        <div className="al-bateen-form-grid">
          <label><span>{tr('设计暴雨重现期', 'Design-storm return period')}</span><select value={returnPeriod} onChange={event => setReturnPeriod(Number(event.target.value))} disabled={running}>
            {availableStorms.map(storm => <option key={storm.return_period_years} value={storm.return_period_years}>{storm.return_period_years} {tr('年一遇', 'year')} · {storm.total_depth_mm} mm / 180 min</option>)}
          </select></label>
          <label><span>{tr('二维计算网格', '2D compute grid')}</span><select value={cellSize} onChange={event => setCellSize(Number(event.target.value))} disabled={running}>
            <option value={20}>{tr('20米 · 标准高精度', '20 m · standard high resolution')}</option>
            <option value={10}>{tr('10米 · 精细计算', '10 m · detailed compute')}</option>
          </select></label>
          <label><span>{tr('雨后退水时长', 'Post-rainfall drainage')}</span><select value={tailMinutes} onChange={event => setTailMinutes(Number(event.target.value))} disabled={running}>
            <option value={60}>60 min</option><option value={120}>120 min</option><option value={180}>180 min</option><option value={360}>360 min</option>
          </select></label>
          <label><span>{tr('结果时间步', 'Output interval')}</span><select value={outputStep} onChange={event => setOutputStep(Number(event.target.value))} disabled={running}>
            <option value={5}>5 min</option><option value={10}>10 min</option><option value={15}>15 min</option><option value={30}>30 min</option>
          </select></label>
          <label><span>{tr('海潮/尾水位', 'Tide / tailwater level')}</span><div className="al-bateen-input-suffix"><input type="number" min={-1} max={3} step={0.1} value={tideLevel} onChange={event => setTideLevel(Number(event.target.value))} disabled={running} /><em>m</em></div></label>
          <label><span>{tr('地表曼宁糙率', 'Surface Manning n')}</span><input type="number" min={0.015} max={0.15} step={0.005} value={manningN} onChange={event => setManningN(Number(event.target.value))} disabled={running} /></label>
        </div>

        <div className="abu-flood-scenario-actions">
          <button
            type="button"
            className="abu-flood-map-action"
            onClick={() => selectedPrecomputed && loadPrecomputedResult(selectedPrecomputed)}
            disabled={!selectedPrecomputed || selectedPrecomputedLoaded || running || loadingPrecomputed}
          >
            {loadingPrecomputed ? <LoaderCircle className="abu-flood-loading-icon" size={15} /> : <Database size={15} />}
            {loadingPrecomputed
              ? tr('正在加载预计算成果…', 'Loading precomputed result...')
              : selectedPrecomputedLoaded
                ? tr('预计算成果已加载', 'Precomputed result loaded')
                : selectedPrecomputed
                  ? tr('加载预计算成果', 'Load precomputed result')
                  : tr('预计算成果尚未完成', 'Precomputed result not ready')}
          </button>
          <button type="button" className="abu-flood-map-action" onClick={startRun} disabled={!ready || running || submitting}>
            {running || submitting ? <LoaderCircle className="abu-flood-loading-icon" size={15} /> : <Play size={15} />}
            {running ? tr('正在运行高精度推演…', 'Running high-resolution simulation...') : tr('运行 Al Bateen 高精度推演', 'Run Al Bateen high-resolution simulation')}
          </button>
          <button type="button" className="abu-flood-reset-action" onClick={() => loadStatus().catch(reason => setError(String(reason)))} disabled={running}><RefreshCw size={14} />{tr('刷新数据状态', 'Refresh data status')}</button>
        </div>
        <div className="abu-flood-scenario-run-id">
          <Database size={12} />
          <span>{tr('预计算成果库', 'PRECOMPUTED LIBRARY')}</span>
          <code>{Number(status?.precomputed_library?.available_combination_count || 0)}/{Number(status?.precomputed_library?.expected_combination_count || 12)}</code>
        </div>
        {running && <div className="al-bateen-progress"><span style={{ width: `${Number(run?.progress?.percent || 0)}%` }} /><em>{stageLabel(run?.progress?.stage, english)} · {Number(run?.progress?.percent || 0)}%</em></div>}
        {run?.run_id && <div className="abu-flood-scenario-run-id"><Activity size={12} /><span>RUN ID</span><code>{run.run_id}</code></div>}
        {error && <div className="abu-flood-form-error"><AlertTriangle size={14} />{error}</div>}
        {run?.error && <div className="abu-flood-form-error"><AlertTriangle size={14} />{run.error}</div>}
      </section>

      {run?.status === 'completed' && <>
        <section className="abu-flood-section">
          <div className="abu-flood-section-heading">
            <div><span className="abu-flood-overline">HYDRODYNAMIC RESULT</span><h3>{tr('局部二维水动力结果', 'Local 2D hydrodynamic results')}</h3></div>
            <span className="abu-flood-muted">{fmt(run?.summary?.terrain?.computation_cell_size_m, 0)} m · {fmt(run?.summary?.timeline?.snapshot_count, 0)} {tr('个时间片', 'time slices')}</span>
          </div>
          <div className={`al-bateen-dewatering-note ${run?.summary?.dewatering?.operational_complete ? 'complete' : 'residual'}`}>
            {run?.summary?.dewatering?.operational_complete ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
            <div>
              <strong>{run?.summary?.dewatering?.operational_complete
                ? tr('退水门禁已通过', 'Dewatering gate passed')
                : tr('96小时退水后保留局部低洼积水', 'Local depressions remain after 96-hour drainage')}</strong>
              <span>{tr(
                `最终保留 ${fmt(results?.final_wet_cells_ge_0_01m, 0)} 个≥1厘米网格（${fmt(Number(results?.final_inundated_area_ge_0_01m_m2 || 0), 0)}平方米），全区平均残余水深 ${fmt(Number(results?.final_mean_depth_m || 0) * 1000, 4)}毫米。`,
                `${fmt(results?.final_wet_cells_ge_0_01m, 0)} cells remain at or above 1 cm (${fmt(Number(results?.final_inundated_area_ge_0_01m_m2 || 0), 0)} m²); district-wide mean residual depth is ${fmt(Number(results?.final_mean_depth_m || 0) * 1000, 4)} mm.`,
              )}</span>
            </div>
          </div>
          <div className="abu-flood-scenario-result-metrics al-bateen-result-grid">
            <div><span>{tr('最大积水深度', 'Maximum depth')}</span><strong>{fmt(results?.maximum_depth_m, 3)} m</strong><small>{fmt(results?.maximum_depth_time_minutes, 0)} min</small></div>
            <div><span>{tr('最大流速', 'Maximum velocity')}</span><strong>{fmt(results?.maximum_speed_m_s, 3)} m/s</strong><small>ANUGA 2D</small></div>
            <div><span>{tr('积水≥5厘米', 'Inundation ≥5 cm')}</span><strong>{fmt(Number(results?.inundated_area_ge_0_05m_m2 || 0) / 1_000_000, 3)} km²</strong><small>{tr('局部湿网格面积', 'local wet-grid area')}</small></div>
            <div><span>{tr('积水≥30厘米', 'Inundation ≥30 cm')}</span><strong>{fmt(Number(results?.inundated_area_ge_0_30m_m2 || 0) / 1_000_000, 3)} km²</strong><small>{tr('重点风险面积', 'priority risk area')}</small></div>
            <div><span>{tr('最大危险度', 'Maximum hazard')}</span><strong>{fmt(results?.maximum_hazard_index, 3)}</strong><small>depth × (velocity + 0.5)</small></div>
          </div>
        </section>

        <section className="abu-flood-section al-bateen-timeline-section">
          <div className="abu-flood-section-heading">
            <div><span className="abu-flood-overline">MAP TIMELINE</span><h3>{tr('动态积水过程', 'Dynamic inundation timeline')}</h3></div>
            <span className="abu-flood-muted">T + {fmt(currentTime, 0)} min · {Number(framePayload?.features?.length || 0).toLocaleString()} {tr('个湿网格', 'wet cells')}</span>
          </div>
          <div className="al-bateen-timeline-controls">
            <button type="button" className="abu-flood-map-action" onClick={() => setPlaying(value => !value)}>{playing ? <Activity size={14} /> : <Play size={14} />}{playing ? tr('暂停播放', 'Pause') : tr('播放推演', 'Play simulation')}</button>
            <input type="range" min={0} max={Math.max(0, timeline.length - 1)} step={1} value={Math.min(frameIndex, Math.max(0, timeline.length - 1))} onChange={event => { setPlaying(false); setFrameIndex(Number(event.target.value)); }} />
            <button type="button" className="abu-flood-reset-action" onClick={publishMap}><MapIcon size={14} />{tr('发送到地图', 'Send to map')}</button>
            <button type="button" className="abu-flood-reset-action" onClick={exportGeoJson}><Download size={14} />GeoJSON</button>
          </div>
        </section>
      </>}

      <section className="abu-flood-section">
        <div className="abu-flood-section-heading">
          <div><span className="abu-flood-overline">DATA CHAIN</span><h3>{tr('本机高精度数据链路', 'Local high-resolution data chain')}</h3></div>
          <span className="abu-flood-muted">{tr('不依赖250米GWM结果', 'Independent of the 250 m GWM result')}</span>
        </div>
        <div className="al-bateen-asset-grid">
          {(status?.assets || []).map(asset => <div key={asset.key} className={asset.ready ? 'ready' : 'blocked'}>
            {asset.ready ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
            <div><strong>{asset.label}</strong><span>{asset.filename || asset.role || '—'}</span></div>
          </div>)}
        </div>
      </section>
    </div>
  );
}
