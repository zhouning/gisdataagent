import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  CircleAlert,
  CircleDashed,
  CloudRain,
  Database,
  Download,
  Gauge,
  GitBranch,
  History,
  Info,
  Layers3,
  MapPinned,
  Play,
  RefreshCw,
  ServerCog,
  Square,
  Waves,
} from 'lucide-react';
import { getLocaleHeaders } from '../../i18n';
import './AbuDhabiHydroWorkbenchTab.css';

type ModelType = 'one_d' | 'two_d' | 'coupled_1d_2d';
type InputMode = 'development_fixture' | 'customer_mount';
type ResourceProfile = 'cpu_small' | 'cpu_large' | 'gpu';
type StepKey = 'data' | 'area' | 'parameters' | 'preflight' | 'results';
type SourceKey = 'network' | 'terrain' | 'rainfall' | 'tide' | 'outfalls' | 'pumps';
type AreaSelectionMode = 'administrative' | 'model_region' | 'catchment' | 'freehand';

interface AoiValues { minLon: number; minLat: number; maxLon: number; maxLat: number; }
interface GeoJSONPolygon { type: 'Polygon'; coordinates: number[][][]; }
interface GeoJSONMultiPolygon { type: 'MultiPolygon'; coordinates: number[][][][]; }
type GeoJSONAreaGeometry = GeoJSONPolygon | GeoJSONMultiPolygon;
interface AreaOption { id: string; name: string; geometry: GeoJSONAreaGeometry; properties?: Record<string, unknown>; }
interface AreaOptionsResponse {
  administrative_units?: AreaOption[];
  model_regions?: AreaOption[];
  subcatchments?: AreaOption[];
  catchments?: AreaOption[];
  sources?: {
    administrative_units?: { status?: string; uri?: string; count?: number };
    model_regions?: { status?: string; uri?: string; count?: number };
    catchments?: { status?: string; uri?: string; count?: number };
  };
  freehand?: { status?: string };
}
interface FeatureCollection { features?: Array<{ geometry?: { type?: string; coordinates?: unknown }; properties?: Record<string, unknown> }>; }
interface HydroTimeline { available?: boolean; endpoint?: string; kind?: 'swmm-node' | 'surface-cell'; time_values?: string[]; elapsed_minutes?: number[]; period_count?: number; total_node_count?: number; total_cell_count?: number; report_step_minutes?: number; step_minutes?: number; initial_time_index?: number; }
interface HydroTimelineResponse { available?: boolean; layers?: { one_d?: HydroTimeline; two_d?: HydroTimeline }; }
interface SourceCheck { key: SourceKey; label: string; required: boolean; status: 'ready' | 'blocked' | 'optional'; uri: string; format: string; version?: string; detail: string; detail_code?: string; provided_by_customer?: boolean; }
interface RegisteredSource {
  uri: string;
  format: string;
  version: string;
  provided_by_customer: boolean;
  etl_required: boolean;
  registered: boolean;
  source_uri?: string;
  source_format?: string;
  source_name?: string;
  size_bytes?: number | null;
  sha256?: string;
  crs?: string;
  resolution_m?: number | null;
  event_id?: string;
  time_standard?: string;
  start_time?: string;
  end_time?: string;
  total_mm?: number;
  duration_minutes?: number;
  peak_interval_mm?: number;
  interval_count?: number;
  interval_minutes?: number;
  evidence_class?: string;
  admission?: string;
  calibration_admitted?: boolean;
  diagnostic_forcing_admitted?: boolean;
}
interface RegionalPilotSummary {
  status?: string;
  engineering_admission?: string;
  catchment_count?: number;
  dynamic_tide_available?: boolean;
  scada_available?: boolean;
}
interface SourceDefaultsResponse {
  sources?: Partial<Record<SourceKey, RegisteredSource>>;
  region?: string | null;
  regional_pilot?: RegionalPilotSummary & { region?: string };
  regional_pilots?: Record<string, RegionalPilotSummary>;
}
interface ParameterReadiness { key: string; value: unknown; source: 'user' | 'system_default' | 'derived'; editable: boolean; }
interface PreflightResponse {
  status: 'ready' | 'blocked';
  can_submit: boolean;
  manifest_preview?: { run_id: string; request: { model_type: ModelType; input_mode: InputMode; resource_profile: ResourceProfile }; area: { selection_mode?: AreaSelectionMode; selection_ids?: string[]; user_aoi?: { type?: string; bbox?: number[] }; model_calculation_domain: { buffer_m: number; bbox?: number[] } }; parameter_provenance?: Record<string, string> };
  checks: Array<{ key: string; label: string; status: string; detail: string }>;
  required_sources: SourceCheck[];
  sources?: SourceCheck[];
  parameter_readiness?: ParameterReadiness[];
  warnings: string[];
  warning_codes?: string[];
}
interface RunRecord { run_id: string; status?: { status?: string; progress?: number; message?: string; error?: string }; manifest?: PreflightResponse['manifest_preview']; }
interface RunHistoryRecord {
  run_id: string;
  created_at?: string;
  status?: { status?: string; progress?: number; message?: string; error?: string };
  result_available?: boolean;
  request?: { model_type?: ModelType; input_mode?: InputMode; resource_profile?: ResourceProfile };
  area?: { selection_mode?: AreaSelectionMode; selection_ids?: string[]; selection_labels?: string[]; region?: string | null };
}
interface RunHistoryResponse { runs?: RunHistoryRecord[]; count?: number; }

const initialAoi: AoiValues = { minLon: 54.35, minLat: 24.35, maxLon: 54.45, maxLat: 24.45 };
const sourceKeys: SourceKey[] = ['network', 'terrain', 'rainfall', 'tide', 'outfalls', 'pumps'];
const stepKeys: StepKey[] = ['data', 'area', 'parameters', 'preflight', 'results'];
const fallbackSourceFormats: Record<SourceKey, string> = { network: 'SWMM_INP/GDB', terrain: 'GeoTIFF/NPZ', rainfall: 'CSV/JSON time series', tide: 'CSV/JSON time series', outfalls: 'GeoPackage/GeoJSON', pumps: 'CSV/GeoPackage' };
const numberValue = (value: string) => { const parsed = Number(value); return Number.isFinite(parsed) ? parsed : 0; };
const polygonBbox = (geometry: GeoJSONAreaGeometry): AoiValues => {
  const points: number[][] = [];
  const collect = (value: unknown): void => {
    if (!Array.isArray(value)) return;
    if (value.length >= 2 && typeof value[0] === 'number' && typeof value[1] === 'number') {
      points.push(value as number[]);
      return;
    }
    value.forEach(collect);
  };
  collect(geometry.coordinates);
  const xs = points.map(point => point[0]).filter(value => Number.isFinite(value));
  const ys = points.map(point => point[1]).filter(value => Number.isFinite(value));
  if (xs.length < 4 || ys.length < 4) return initialAoi;
  return { minLon: Math.min(...xs), minLat: Math.min(...ys), maxLon: Math.max(...xs), maxLat: Math.max(...ys) };
};
const isValidPolygon = (geometry: GeoJSONAreaGeometry | null) => {
  if (!geometry || geometry.type !== 'Polygon') return false;
  const ring = geometry?.coordinates?.[0];
  if (!ring || ring.length < 4) return false;
  const first = ring[0]; const last = ring[ring.length - 1];
  return Boolean(first && last && first[0] === last[0] && first[1] === last[1]);
};
const sleep = (milliseconds: number) => new Promise(resolve => setTimeout(resolve, milliseconds));
const formatBytes = (value?: number | null) => {
  if (!value || value < 1) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / (1024 ** index)).toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
};

export default function AbuDhabiHydroWorkbenchTab() {
  const { t, i18n } = useTranslation('common');
  const tr = (key: string, options?: Record<string, unknown>) => String(t(`hydroWorkbench.${key}`, options));
  const modelRegionText = (key: string) => {
    const language = String(i18n.language || '').toLowerCase();
    const copy: Record<string, Record<string, string>> = {
      title: { en: 'Complete model region', zh: '完整模型区域', ar: 'منطقة النموذج الكاملة' },
      subtitle: { en: 'Use the complete solver-ready package', zh: '使用完整的可求解模型包', ar: 'استخدم حزمة النموذج الجاهزة للحل' },
      label: { en: 'Model region', zh: '模型区域', ar: 'منطقة النموذج' },
      empty: { en: 'No complete model region is registered.', zh: '尚未登记完整模型区域。', ar: 'لم يتم تسجيل منطقة نموذج كاملة.' },
      ready: { en: '{{count}} complete model region(s) registered', zh: '已登记 {{count}} 个完整模型区域', ar: 'تم تسجيل {{count}} من مناطق النموذج الكاملة' },
      subcatchments: { en: '{{count}} internal subcatchments', zh: '内部子汇水区 {{count}} 个', ar: '{{count}} من أحواض التجميع الداخلية' },
      role: { en: 'Subcatchments are runoff units for filtering/statistics, not standalone solver domains.', zh: '子汇水区仅用于产流单元筛选/统计，不作为独立求解域。', ar: 'أحواض التجميع وحدات جريان للترشيح والإحصاء وليست نطاقات حل مستقلة.' },
      areaSubtitle: { en: 'Choose an administrative area, then a complete solver-ready model region. Individual catchments are internal runoff units, not standalone calculation domains.', zh: '先选择行政区，再选择完整的可求解模型区域。单个子汇水区是内部产流单元，不是独立计算范围。', ar: 'اختر منطقة إدارية ثم منطقة نموذج كاملة جاهزة للحل. أحواض التجميع وحدات جريان داخلية وليست نطاقات حساب مستقلة.' },
      selectionOrder: { en: '1 Administrative area → 2 Complete model region → 3 Freehand polygon', zh: '1 行政区 → 2 完整模型区域 → 3 自由绘制多边形', ar: '1 المنطقة الإدارية ← 2 منطقة النموذج الكاملة ← 3 مضلع حر' },
      bufferInput: { en: 'For a registered model region the complete solver package is used; freehand AOIs use the configured buffer.', zh: '登记的模型区域将使用完整求解包；自由绘制 AOI 使用配置的缓冲范围。', ar: 'تستخدم منطقة النموذج المسجلة حزمة الحل الكاملة؛ وتستخدم مناطق الرسم الحر النطاق العازل المكوّن.' },
    };
    const locale = language.startsWith('zh') ? 'zh' : language.startsWith('ar') ? 'ar' : 'en';
    return copy[key]?.[locale] || copy[key]?.en || key;
  };
  // Development fixtures are intentionally opt-in in every build.  Append
  // `?hydroDev=1` only in a local developer session; customer deployments do
  // not expose the fixture selector.
  // This selector is only discoverable in an explicit developer URL. The
  // backend environment gate is authoritative and still rejects fixture runs
  // in every production deployment.
  const showDevelopmentOptions = typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('hydroDev') === '1';
  const [step, setStep] = useState<StepKey>('data');
  const [modelType, setModelType] = useState<ModelType>('coupled_1d_2d');
  const [inputMode, setInputMode] = useState<InputMode>(showDevelopmentOptions ? 'development_fixture' : 'customer_mount');
  const [resourceProfile, setResourceProfile] = useState<ResourceProfile>('cpu_small');
  const [rainfallTotal, setRainfallTotal] = useState(50);
  const [rainfallDuration, setRainfallDuration] = useState(60);
  const [rainfallPattern, setRainfallPattern] = useState('uniform');
  const [oneDRoutingMethod, setOneDRoutingMethod] = useState('KINWAVE');
  const [oneDInfiltrationMethod, setOneDInfiltrationMethod] = useState('HORTON');
  const [gridResolution, setGridResolution] = useState(5);
  const [manningN, setManningN] = useState(0.03);
  const [twoDTimestep, setTwoDTimestep] = useState(300);
  const [domainBuffer, setDomainBuffer] = useState(500);
  const [couplingMode, setCouplingMode] = useState('two_way_swmm_anuga');
  const [aoi, setAoi] = useState(initialAoi);
  const [areaSelectionMode, setAreaSelectionMode] = useState<AreaSelectionMode>('administrative');
  const [selectedAdministrativeId, setSelectedAdministrativeId] = useState('');
  const [selectedModelRegionId, setSelectedModelRegionId] = useState('');
  const [selectedCatchmentId, setSelectedCatchmentId] = useState('');
  const [aoiGeometry, setAoiGeometry] = useState<GeoJSONAreaGeometry | null>(null);
  const [areaOptions, setAreaOptions] = useState<AreaOptionsResponse>({ administrative_units: [], catchments: [] });
  const [areaOptionsState, setAreaOptionsState] = useState<'loading' | 'ready' | 'unavailable'>('loading');
  const [sources, setSources] = useState<Record<SourceKey, string>>({ network: '', terrain: '', rainfall: '', tide: '', outfalls: '', pumps: '' });
  const [sourceDefaults, setSourceDefaults] = useState<Partial<Record<SourceKey, RegisteredSource>>>({});
  const [sourceDefaultsState, setSourceDefaultsState] = useState<'loading' | 'ready' | 'unavailable'>('loading');
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [preflight, setPreflight] = useState<PreflightResponse | null>(null);
  const [run, setRun] = useState<RunRecord | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [map, setMap] = useState<FeatureCollection | null>(null);
  const [timeline, setTimeline] = useState<HydroTimelineResponse | null>(null);
  const [history, setHistory] = useState<RunHistoryRecord[]>([]);
  const [historyState, setHistoryState] = useState<'loading' | 'ready' | 'unavailable'>('loading');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const stopPollingRef = useRef(false);

  const selectedModelRegion = useMemo(
    () => (areaOptions.model_regions || []).find(item => item.id === selectedModelRegionId),
    [areaOptions.model_regions, selectedModelRegionId],
  );
  const selectedPilotRegion = areaSelectionMode === 'model_region'
    ? String(selectedModelRegion?.properties?.region || selectedModelRegionId || '')
    : '';
  const [regionalPilot, setRegionalPilot] = useState<RegionalPilotSummary | null>(null);

  const loadHistory = async () => {
    try {
      setHistoryState('loading');
      const response = await fetch('/api/abu-dhabi/flood/hydro-runs/history?limit=50', { credentials: 'include', headers: getLocaleHeaders() });
      if (!response.ok) throw new Error(`history: ${response.status}`);
      const data = await response.json() as RunHistoryResponse;
      setHistory(data.runs || []);
      setHistoryState('ready');
    } catch {
      setHistoryState('unavailable');
    }
  };

  useEffect(() => {
    void loadHistory();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const loadSourceDefaults = async () => {
      try {
        const query = selectedPilotRegion ? `?region=${encodeURIComponent(selectedPilotRegion)}` : '';
        setSourceDefaultsState('loading');
        const response = await fetch(`/api/abu-dhabi/flood/hydro-runs/source-defaults${query}`, { credentials: 'include', headers: getLocaleHeaders(), signal: controller.signal });
        if (!response.ok) throw new Error(`source defaults: ${response.status}`);
        const data = await response.json() as SourceDefaultsResponse;
        const registered = data.sources || {};
        const hasRegisteredSource = Boolean(Object.values(registered).some(source => source?.registered));
        setSourceDefaults(registered);
        setSources(current => ({
          ...current,
          network: registered.network?.registered ? registered.network.uri : current.network,
          terrain: registered.terrain?.registered ? registered.terrain.uri : current.terrain,
          rainfall: registered.rainfall?.registered ? registered.rainfall.uri : current.rainfall,
          tide: selectedPilotRegion ? (registered.tide?.registered ? registered.tide.uri : '') : '',
          outfalls: selectedPilotRegion ? (registered.outfalls?.registered ? registered.outfalls.uri : '') : '',
          pumps: selectedPilotRegion ? (registered.pumps?.registered ? registered.pumps.uri : '') : '',
        }));
        if (registered.rainfall?.registered) {
          if (typeof registered.rainfall.total_mm === 'number') setRainfallTotal(registered.rainfall.total_mm);
          if (typeof registered.rainfall.duration_minutes === 'number') setRainfallDuration(registered.rainfall.duration_minutes);
        }
        setRegionalPilot(data.regional_pilot || null);
        setSourceDefaultsState(hasRegisteredSource ? 'ready' : 'unavailable');
      } catch (caught) {
        if (!(caught instanceof DOMException && caught.name === 'AbortError')) setSourceDefaultsState('unavailable');
      }
    };
    void loadSourceDefaults();
    return () => controller.abort();
  }, [selectedPilotRegion]);

  useEffect(() => {
    const controller = new AbortController();
    const loadAreaOptions = async () => {
      try {
        const response = await fetch('/api/abu-dhabi/flood/hydro-runs/area-options', { credentials: 'include', headers: getLocaleHeaders(), signal: controller.signal });
        if (!response.ok) throw new Error(`area options: ${response.status}`);
        const data = await response.json() as AreaOptionsResponse;
        setAreaOptions(data);
        setAreaOptionsState((data.administrative_units?.length || data.model_regions?.length || data.catchments?.length) ? 'ready' : 'unavailable');
      } catch (caught) {
        if (!(caught instanceof DOMException && caught.name === 'AbortError')) setAreaOptionsState('unavailable');
      }
    };
    void loadAreaOptions();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const handleDrawnAoi = (event: Event) => {
      const geometry = (event as CustomEvent<{ geometry?: GeoJSONPolygon }>).detail?.geometry;
      if (!geometry || geometry.type !== 'Polygon') return;
      setAreaSelectionMode('freehand');
      setSelectedAdministrativeId('');
      setSelectedCatchmentId('');
      setAoiGeometry(geometry);
      setAoi(polygonBbox(geometry));
      invalidatePreflight();
    };
    window.addEventListener('hydro-workbench-aoi-drawn', handleDrawnAoi);
    return () => window.removeEventListener('hydro-workbench-aoi-drawn', handleDrawnAoi);
  }, []);

  const invalidatePreflight = () => { setPreflight(null); if (step === 'preflight' || step === 'results') setStep('parameters'); };
  const markTouched = (key: string) => { setTouched(current => ({ ...current, [key]: true })); invalidatePreflight(); };
  const rainfallSourceRegistered = Boolean(sourceDefaults.rainfall?.registered && sourceDefaults.rainfall.uri === sources.rainfall);
  const parameterPayload = useMemo(() => ({
    ...(touched.rainfall_total_mm || rainfallSourceRegistered ? { rainfall_total_mm: rainfallTotal } : {}),
    ...(touched.rainfall_duration_minutes || rainfallSourceRegistered ? { rainfall_duration_minutes: rainfallDuration } : {}),
    ...(touched.rainfall_pattern ? { rainfall_pattern: rainfallPattern } : {}),
    ...(touched.one_d_routing_method ? { one_d_routing_method: oneDRoutingMethod } : {}),
    ...(touched.one_d_infiltration_method ? { one_d_infiltration_method: oneDInfiltrationMethod } : {}),
    ...(touched.two_d_grid_resolution_m ? { two_d_grid_resolution_m: gridResolution } : {}),
    ...(touched.two_d_manning_n ? { two_d_manning_n: manningN } : {}),
    ...(touched.two_d_timestep_seconds ? { two_d_timestep_seconds: twoDTimestep } : {}),
    ...(touched.domain_buffer_m ? { domain_buffer_m: domainBuffer } : {}),
    ...(touched.coupling_mode ? { coupling_mode: couplingMode } : {}),
  }), [couplingMode, domainBuffer, gridResolution, manningN, oneDInfiltrationMethod, oneDRoutingMethod, rainfallDuration, rainfallPattern, rainfallSourceRegistered, rainfallTotal, touched, twoDTimestep]);
  const payload = useMemo(() => ({
    model_type: modelType, input_mode: inputMode, resource_profile: resourceProfile, ...parameterPayload,
    parameter_source_hints: {
      ...(rainfallSourceRegistered && !touched.rainfall_total_mm ? { rainfall_total_mm: 'registered_dataset' } : {}),
      ...(rainfallSourceRegistered && !touched.rainfall_duration_minutes ? { rainfall_duration_minutes: 'registered_dataset' } : {}),
    },
    aoi: aoiGeometry || [aoi.minLon, aoi.minLat, aoi.maxLon, aoi.maxLat],
    area_selection: {
      mode: areaSelectionMode,
      ids: areaSelectionMode === 'administrative' ? (selectedAdministrativeId ? [selectedAdministrativeId] : []) : areaSelectionMode === 'model_region' ? (selectedModelRegionId ? [selectedModelRegionId] : []) : [],
      labels: areaSelectionMode === 'administrative' ? (areaOptions.administrative_units || []).filter(item => item.id === selectedAdministrativeId).map(item => item.name) : areaSelectionMode === 'model_region' ? (areaOptions.model_regions || []).filter(item => item.id === selectedModelRegionId).map(item => item.name) : [],
      region: selectedPilotRegion || null,
      model_region: selectedPilotRegion || null,
      subcatchment_ids: areaSelectionMode === 'catchment' && selectedCatchmentId ? [selectedCatchmentId] : [],
    },
    data_sources: Object.fromEntries(sourceKeys.map(key => {
      const registered = sourceDefaults[key];
      const usesRegisteredSource = Boolean(registered?.registered && registered.uri === sources[key]);
      return [key, {
        uri: sources[key],
        format: usesRegisteredSource ? registered?.format : fallbackSourceFormats[key],
        version: usesRegisteredSource ? registered?.version : 'unversioned',
        provided_by_customer: usesRegisteredSource ? registered?.provided_by_customer : inputMode === 'customer_mount',
        etl_required: usesRegisteredSource ? registered?.etl_required : true,
      }];
    })),
  }), [aoi, aoiGeometry, areaOptions, areaSelectionMode, inputMode, modelType, parameterPayload, rainfallSourceRegistered, resourceProfile, selectedAdministrativeId, selectedModelRegionId, selectedCatchmentId, selectedPilotRegion, sourceDefaults, sources, touched]);
  const requiredSourceKeys = useMemo<SourceKey[]>(() => modelType === 'one_d' ? ['network'] : modelType === 'two_d' ? ['terrain'] : ['network', 'terrain'], [modelType]);
  const aoiError = useMemo(() => {
    if (areaSelectionMode === 'administrative' && !selectedAdministrativeId) return tr('area.selectionRequired');
    if (areaSelectionMode === 'model_region' && !selectedModelRegionId) return tr('area.selectionRequired');
    if (areaSelectionMode === 'freehand' && !isValidPolygon(aoiGeometry)) return tr('area.drawRequired');
    if (aoi.minLon >= aoi.maxLon || aoi.minLat >= aoi.maxLat) return tr('area.invalidOrder');
    if (aoi.maxLon - aoi.minLon > 5 || aoi.maxLat - aoi.minLat > 5) return tr('area.tooLarge');
    return '';
  }, [aoi, aoiGeometry, areaSelectionMode, selectedAdministrativeId, selectedModelRegionId, tr]);
  const aoiMetrics = useMemo(() => ({ widthKm: Math.max(0, (aoi.maxLon - aoi.minLon) * 111.32 * Math.cos(((aoi.minLat + aoi.maxLat) / 2) * Math.PI / 180)), heightKm: Math.max(0, (aoi.maxLat - aoi.minLat) * 111.32) }), [aoi]);
  const updateAoi = (key: keyof AoiValues, value: string) => { setAoi(current => ({ ...current, [key]: numberValue(value) })); invalidatePreflight(); };
  const updateSource = (key: SourceKey, value: string) => { setSources(current => ({ ...current, [key]: value })); invalidatePreflight(); };
  const applyAreaOption = (mode: Exclude<AreaSelectionMode, 'freehand' | 'catchment'>, id: string) => {
    const options = mode === 'administrative' ? (areaOptions.administrative_units || []) : (areaOptions.model_regions || []);
    const option = options.find(item => item.id === id);
    setAreaSelectionMode(mode);
    window.dispatchEvent(new CustomEvent('hydro-workbench-draw-aoi', { detail: { active: false } }));
    if (mode === 'administrative') { setSelectedAdministrativeId(id); setSelectedModelRegionId(''); setSelectedCatchmentId(''); }
    else { setSelectedModelRegionId(id); setSelectedAdministrativeId(''); setSelectedCatchmentId(''); }
    if (!option) {
      setAoiGeometry(null);
      window.dispatchEvent(new CustomEvent('hydro-workbench-area-selection', { detail: { geometry: null } }));
      invalidatePreflight();
      return;
    }
    setAoiGeometry(option.geometry);
    setAoi(polygonBbox(option.geometry));
    window.dispatchEvent(new CustomEvent('hydro-workbench-area-selection', { detail: { geometry: option.geometry, mode } }));
    invalidatePreflight();
  };
  const switchAreaSelectionMode = (mode: AreaSelectionMode) => {
    setAreaSelectionMode(mode);
    if (mode === 'freehand') {
      setSelectedAdministrativeId('');
      setSelectedModelRegionId('');
      setSelectedCatchmentId('');
      setAoiGeometry(null);
      window.dispatchEvent(new CustomEvent('hydro-workbench-area-selection', { detail: { geometry: null } }));
      window.dispatchEvent(new CustomEvent('hydro-workbench-draw-aoi', { detail: { active: true } }));
    } else {
      window.dispatchEvent(new CustomEvent('hydro-workbench-draw-aoi', { detail: { active: false } }));
    }
    invalidatePreflight();
  };

  const runPreflight = async () => {
    setBusy(true); setError('');
    try {
      const response = await fetch('/api/abu-dhabi/flood/hydro-runs/preflight', { method: 'POST', credentials: 'include', headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const data = await response.json() as PreflightResponse & { error?: string };
      if (!response.ok) throw new Error(data.error || tr('errors.preflight'));
      setPreflight(data); setRun(null); setResult(null); setMap(null); setStep('preflight');
    } catch (caught) { setError(caught instanceof Error ? caught.message : tr('errors.preflight')); } finally { setBusy(false); }
  };
  const loadRun = async (runId: string) => {
    const response = await fetch(`/api/abu-dhabi/flood/hydro-runs/${runId}`, { credentials: 'include', headers: getLocaleHeaders() });
    if (!response.ok) throw new Error(tr('errors.status'));
    const record = await response.json() as RunRecord; setRun(record);
    const state = record.status?.status;
    if (state === 'completed') {
      const [resultResponse, mapResponse] = await Promise.all([fetch(`/api/abu-dhabi/flood/hydro-runs/${runId}/result`, { credentials: 'include' }), fetch(`/api/abu-dhabi/flood/hydro-runs/${runId}/map`, { credentials: 'include' })]);
      if (!resultResponse.ok) return false;
      setResult(await resultResponse.json() as Record<string, unknown>);
      let payloadMap: FeatureCollection | null = null;
      if (mapResponse.ok) {
        payloadMap = await mapResponse.json() as FeatureCollection;
        setMap(payloadMap);
      }
      const timelineResponse = await fetch(`/api/abu-dhabi/flood/hydro-runs/${runId}/timeline`, { credentials: 'include' });
      const timelinePayload = timelineResponse.ok ? await timelineResponse.json() as HydroTimelineResponse : null;
      setTimeline(timelinePayload);
      publishResultToMainMap(payloadMap, runId, timelinePayload);
      setStep('results'); return true;
    }
    return ['failed', 'cancelled', 'submit_failed'].includes(state || '');
  };
  const submitRun = async () => {
    if (!preflight?.can_submit || aoiError) return;
    setBusy(true); setError(''); stopPollingRef.current = false;
    try {
      const response = await fetch('/api/abu-dhabi/flood/hydro-runs', { method: 'POST', credentials: 'include', headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const data = await response.json() as RunRecord & { error?: string };
      if (!response.ok) throw new Error(data.error || tr('errors.submit'));
      setRun(data); setStep('results');
      let terminal = false;
      for (let attempt = 0; attempt < 120 && !stopPollingRef.current; attempt += 1) {
        terminal = await loadRun(data.run_id);
        if (terminal) break;
        await sleep(2_000);
      }
      if (!terminal && !stopPollingRef.current) setError(tr('errors.timeout'));
      void loadHistory();
    } catch (caught) { setError(caught instanceof Error ? caught.message : tr('errors.submit')); } finally { setBusy(false); }
  };
  const cancelRun = async () => {
    if (!run?.run_id || !['queued', 'running'].includes(run.status?.status || '')) return;
    stopPollingRef.current = true;
    try {
      const response = await fetch(`/api/abu-dhabi/flood/hydro-runs/${run.run_id}`, { method: 'DELETE', credentials: 'include' });
      if (!response.ok) throw new Error(tr('errors.cancel'));
      setRun(current => current ? { ...current, status: { ...current.status, status: 'cancelled', progress: 100, message: tr('run.cancelled') } } : current);
    } catch (caught) { setError(caught instanceof Error ? caught.message : tr('errors.cancel')); }
  };
  const parameterLabel = (key: string) => {
    const labels: Record<string, string> = {
      'rainfall.total_mm': 'configuration.rainfall',
      'rainfall.duration_minutes': 'configuration.duration',
      'rainfall.pattern': 'configuration.pattern',
      'one_d.routing_method': 'configuration.routing',
      'one_d.infiltration_method': 'configuration.infiltration',
      'two_d.grid_resolution_m': 'configuration.grid',
      'two_d.manning_n': 'configuration.manning',
      'two_d.timestep_seconds': 'configuration.timestep',
      'coupling.mode': 'configuration.coupling',
      'area.domain_buffer_m': 'configuration.domainBuffer',
    };
    return tr(labels[key] || key);
  };
  const parameterValue = (parameter: ParameterReadiness) => {
    if (parameter.key === 'rainfall.pattern') return parameter.value === 'alternating_block' ? tr('patterns.alternating') : tr('patterns.uniform');
    if (parameter.key === 'coupling.mode') return parameter.value === 'one_way_swmm_to_anuga' ? tr('coupling.oneWay') : tr('coupling.twoWay');
    const units: Record<string, string> = {
      'rainfall.total_mm': ' mm',
      'rainfall.duration_minutes': ' min',
      'two_d.grid_resolution_m': ' m',
      'two_d.timestep_seconds': ' s',
      'area.domain_buffer_m': ' m',
    };
    return `${String(parameter.value)}${units[parameter.key] || ''}`;
  };
  const checkLabel = (check: PreflightResponse['checks'][number]) => String(t(`hydroWorkbench.preflight.checks.${check.key}.label`, { defaultValue: check.label }));
  const checkDetail = (check: PreflightResponse['checks'][number]) => String(t(`hydroWorkbench.preflight.checks.${check.key}.detail`, { defaultValue: check.detail }));
  const sourceDetail = (source: SourceCheck) => String(t(`hydroWorkbench.preflight.sourceDetails.${source.detail_code || 'unknown'}`, { defaultValue: source.detail }));
  const engineeringUseLabel = (value: unknown) =>
    value === true || value === 'true' ? tr('results.engineeringAllowed') : tr('results.engineeringNotAllowed');
  const downloadResult = () => {
    if (!result) return;
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }); const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${run?.run_id || 'hydro-result'}.json`; anchor.click(); URL.revokeObjectURL(url);
  };
  const timelineStatus = (key: 'one_d' | 'two_d') => {
    const item = timeline?.layers?.[key];
    if (!item?.available) return { available: false, periodCount: 0, stepMinutes: 0 };
    return {
      available: true,
      periodCount: Number(item.period_count || 0),
      stepMinutes: Number(item.report_step_minutes || item.step_minutes || 0),
    };
  };

  const publishResultToMainMap = (payloadMap: FeatureCollection | null, runId: string, timelinePayload?: HydroTimelineResponse | null) => {
    if (!payloadMap) return;
    const features = payloadMap.features || [];
    const networkFeatures = features.filter(feature => feature.properties?.kind !== 'surface_depth');
    const depthFeatures = features.filter(feature => feature.properties?.kind === 'surface_depth');
    const layers: Array<Record<string, unknown>> = [];
    const oneD = timelinePayload?.layers?.one_d;
    const twoD = timelinePayload?.layers?.two_d;
    if (oneD?.endpoint) layers.push({
      name: `Hydro ${runId} · 1D dynamic node water depth`, type: 'bubble', value_column: 'water_depth_m',
      breaks: [0.01, 0.05, 0.15, 0.30, 0.50, 1.0], color_scheme: 'Blues',
      style: { min_radius: 3, max_radius: 11, color: '#0f172a' }, tooltip_fields: ['id', 'water_depth_m', 'overflow_or_flooding_m3s'],
      scenarioTimeline: { runId, endpoint: `/api/abu-dhabi/flood/hydro-runs/${runId}/timeseries?layer=one_d`, timeValues: oneD.time_values || [], elapsedMinutes: oneD.elapsed_minutes || [], periodCount: Number(oneD.period_count || 0), totalNodeCount: Number(oneD.total_node_count || 0), reportStepMinutes: Number(oneD.report_step_minutes || 0), kind: 'swmm-node' },
    });
    if (twoD?.endpoint) layers.push({
      name: `Hydro ${runId} · 2D dynamic surface depth`, type: 'bubble', value_column: 'depth_m',
      breaks: [0.01, 0.05, 0.15, 0.30, 0.50, 1.0], color_scheme: 'Blues',
      style: { min_radius: 3, max_radius: 11, color: '#0f172a' }, tooltip_fields: ['depth_m', 'cell_index'],
      scenarioTimeline: { runId, endpoint: `/api/abu-dhabi/flood/hydro-runs/${runId}/timeseries?layer=two_d`, timeValues: twoD.time_values || [], elapsedMinutes: twoD.elapsed_minutes || [], periodCount: Number(twoD.period_count || 0), totalNodeCount: Number(twoD.total_cell_count || 0), reportStepMinutes: Number(twoD.step_minutes || 0), initialTimeIndex: Math.max(0, Number(twoD.period_count || 1) - 1), kind: 'surface-cell' },
    });
    if (networkFeatures.length) layers.push({
      name: `Hydro ${runId} · 1D network`, type: 'geojson',
      geojsonData: { type: 'FeatureCollection', features: networkFeatures },
      style: { color: '#2563eb', fillColor: '#2563eb', weight: 2, radius: 4, fillOpacity: 0.75 },
      tooltip_fields: ['id', 'kind', 'maximum_depth_m'],
    });
    if (!twoD?.endpoint && depthFeatures.length) layers.push({
      name: `Hydro ${runId} · 2D diagnostic depth`, type: 'bubble',
      geojsonData: { type: 'FeatureCollection', features: depthFeatures }, value_column: 'depth_m',
      breaks: [0.01, 0.05, 0.15, 0.30, 0.50, 1.0], color_scheme: 'Blues',
      style: { min_radius: 3, max_radius: 11, color: '#0f172a' }, tooltip_fields: ['depth_m', 'cell_index'],
    });
    if (!layers.length) return;
    window.__handleMapUpdate?.({
      schema: 'map_update.v1',
      summary: { title: `Hydrodynamic result · ${runId}`, subtitle: 'Musaffah_00 diagnostic result' },
      layers,
      center: [(aoi.minLat + aoi.maxLat) / 2, (aoi.minLon + aoi.maxLon) / 2], zoom: 13,
    });
  };
  const runState = run?.status?.status || 'idle'; const allSources = preflight?.sources || preflight?.required_sources || []; const activeStepIndex = stepKeys.indexOf(step);
  const goNext = () => { if (step === 'data') setStep('area'); else if (step === 'area' && !aoiError) setStep('parameters'); else if (step === 'parameters') setStep('preflight'); };
  const goBack = () => { if (activeStepIndex > 0) setStep(stepKeys[activeStepIndex - 1]); };

  const sourceCard = (key: SourceKey) => {
    const required = requiredSourceKeys.includes(key);
    const registered = sourceDefaults[key];
    const usesRegisteredSource = Boolean(registered?.registered && registered.uri === sources[key]);
    const regionalOnly = key === 'tide' || key === 'outfalls' || key === 'pumps';
    const sourceAsset = registered?.source_uri || registered?.source_name;
    const metadata = [registered?.format, formatBytes(registered?.size_bytes), registered?.crs, registered?.resolution_m ? `${registered.resolution_m} m` : '', registered?.event_id, registered?.total_mm ? `${registered.total_mm} mm` : '', registered?.duration_minutes ? `${registered.duration_minutes} min` : '', registered?.interval_count && registered?.interval_minutes ? `${registered.interval_count} × ${registered.interval_minutes} min` : '', registered?.admission].filter(Boolean).join(' · ');
    return <div key={key} className={`abu-hydro-asset ${required ? 'required' : ''} ${usesRegisteredSource ? 'registered' : ''}`}>
      <div className="abu-hydro-asset-heading"><strong>{tr(`sources.${key}`)}</strong><div className="abu-hydro-asset-badges">{usesRegisteredSource && <span className="abu-hydro-chip registered"><CheckCircle2 size={10} />{tr('data.registered')}</span>}<span className={`abu-hydro-chip ${required ? 'required' : 'optional'}`}>{required ? tr('data.required') : tr('data.optional')}</span></div></div>
      <input aria-label={tr(`sources.${key}`)} placeholder={tr(`sourcePlaceholders.${key}`)} value={sources[key]} onChange={event => updateSource(key, event.target.value)} />
      <small>{tr(`sourceFormats.${key}`)}</small>
      {!sources[key] && regionalOnly && <small className="abu-hydro-source-missing">{selectedPilotRegion ? tr('data.sourceStates.notRegistered') : tr('data.sourceStates.selectCatchment')}</small>}
      {usesRegisteredSource && registered && <div className="abu-hydro-source-lineage"><div><span>{tr('data.modelInput')}</span><code title={registered.uri}>{registered.uri}</code></div>{sourceAsset && <div><span>{tr('data.sourceAsset')}</span><code title={sourceAsset}>{sourceAsset}</code></div>}<small>{metadata}{registered.sha256 ? ` · SHA-256 ${registered.sha256.slice(0, 12)}…` : ''}</small></div>}
    </div>;
  };
  const provenance = (key: string) => {
    if (touched[key]) return tr('parameterSource.user');
    if (rainfallSourceRegistered && (key === 'rainfall_total_mm' || key === 'rainfall_duration_minutes')) return tr('parameterSource.derived');
    return tr('parameterSource.default');
  };

  return <div className="abu-hydro-workbench">
    <section className="abu-hydro-hero"><div><span className="abu-hydro-kicker">ABU DHABI / HYDRODYNAMIC MODEL WORKBENCH</span><h2>{tr('title')}</h2><p>{tr('subtitle')}</p></div><div className="abu-hydro-hero-status"><ServerCog size={18} /><strong>{tr(`statuses.${runState}`)}</strong><small>{tr('heroStatus')}</small></div></section>
    <section className="abu-hydro-notice"><AlertTriangle size={17} /><div><strong>{tr('productionNotice.title')}</strong><span>{tr('productionNotice.body')}</span></div></section>
    <nav className="abu-hydro-stepper" aria-label={tr('stepsLabel')}>{stepKeys.map((key, index) => { const done = index < activeStepIndex; const enabled = index <= activeStepIndex || (key === 'preflight' && Boolean(preflight)) || key === 'results'; return <button key={key} type="button" className={`abu-hydro-step ${key === step ? 'active' : ''} ${done ? 'done' : ''}`} onClick={() => enabled && setStep(key)} disabled={!enabled}><span>{done ? <CheckCircle2 size={15} /> : index + 1}</span><strong>{tr(`steps.${key}.title`)}</strong><small>{tr(`steps.${key}.short`)}</small></button>; })}</nav>
    <section className="abu-hydro-flow" aria-label={tr('flowLabel')}>{[['data', Database], ['etl', GitBranch], ['solver', Waves], ['result', Layers3]].map(([key, Icon]) => <div key={String(key)} className="abu-hydro-flow-step"><Icon size={16} /><span>{tr(`flow.${String(key)}`)}</span></div>)}</section>

    {step === 'data' && <section className="abu-hydro-card abu-hydro-step-panel"><div className="abu-hydro-card-heading"><Database size={16} /><div><h3>{tr('data.title')}</h3><small>{tr('data.subtitle')}</small></div></div><div className="abu-hydro-mode-row"><div><strong>{tr('data.modeTitle')}</strong><span>{inputMode === 'customer_mount' ? tr('data.customerMode') : tr('data.fixtureMode')}</span></div>{showDevelopmentOptions && <label className="abu-hydro-mode-select">{tr('configuration.inputMode')}<select value={inputMode} onChange={event => { setInputMode(event.target.value as InputMode); invalidatePreflight(); }}><option value="customer_mount">{tr('inputModes.customer')}</option><option value="development_fixture">{tr('inputModes.fixture')}</option></select></label>}</div><div className={`abu-hydro-default-status ${sourceDefaultsState}`}>{sourceDefaultsState === 'loading' ? <RefreshCw size={13} /> : sourceDefaultsState === 'ready' ? <CheckCircle2 size={13} /> : <CircleAlert size={13} />}<span>{tr(`data.defaults.${sourceDefaultsState}`)}</span></div>{selectedPilotRegion && regionalPilot && <div className="abu-hydro-regional-pilot"><div><strong>{tr('data.regionalPilot.title')}: {selectedPilotRegion}</strong><span>{tr('data.regionalPilot.catchments', { count: regionalPilot.catchment_count || 0 })}</span></div><div className="abu-hydro-regional-pilot-flags"><span className="ready"><CheckCircle2 size={11} />{tr('data.regionalPilot.staticNetwork')}</span><span className="warning"><AlertTriangle size={11} />{tr('data.regionalPilot.dynamicTideMissing')}</span><span className="warning"><AlertTriangle size={11} />{tr('data.regionalPilot.scadaMissing')}</span></div><small>{tr('data.regionalPilot.diagnosticOnly')}</small></div>}<div className="abu-hydro-asset-grid">{sourceKeys.map(sourceCard)}</div>{inputMode === 'development_fixture' && <p className="abu-hydro-warning"><AlertTriangle size={13} />{tr('data.fixtureWarning')}</p>}<div className="abu-hydro-actions"><button type="button" className="primary" onClick={goNext}>{tr('actions.next')}<ArrowRight size={15} /></button></div></section>}

    {step === 'area' && <section className="abu-hydro-card abu-hydro-step-panel"><div className="abu-hydro-card-heading"><MapPinned size={16} /><div><h3>{tr('area.title')}</h3><small>{modelRegionText('areaSubtitle')}</small></div></div><div className="abu-hydro-area-order"><strong>{tr('area.selectionOrder')}</strong><span>{modelRegionText('selectionOrder')}</span></div><div className="abu-hydro-area-modes">{(['administrative', 'model_region', 'freehand'] as AreaSelectionMode[]).map((mode, index) => <button key={mode} type="button" className={`abu-hydro-area-mode ${areaSelectionMode === mode ? 'active' : ''}`} onClick={() => switchAreaSelectionMode(mode)}><span>{index + 1}</span><strong>{mode === 'model_region' ? modelRegionText('title') : tr(`area.modes.${mode}.title`)}</strong><small>{mode === 'model_region' ? modelRegionText('subtitle') : tr(`area.modes.${mode}.subtitle`)}</small></button>)}</div><div className="abu-hydro-area-layout"><div className="abu-hydro-area-selection-panel">{areaSelectionMode === 'administrative' && <div className="abu-hydro-selection-block"><label>{tr('area.modes.administrative.label')}<select value={selectedAdministrativeId} onChange={event => applyAreaOption('administrative', event.target.value)} disabled={!areaOptions.administrative_units?.length}><option value="">{areaOptions.administrative_units?.length ? tr('area.selectPlaceholder') : tr('area.notRegistered')}</option>{(areaOptions.administrative_units || []).map(option => <option key={option.id} value={option.id}>{option.name} · {option.id}</option>)}</select></label><small>{areaOptions.sources?.administrative_units?.uri ? `${tr('area.source')}: ${areaOptions.sources.administrative_units.uri}` : tr('area.modes.administrative.empty')}</small></div>}{areaSelectionMode === 'model_region' && <div className="abu-hydro-selection-block"><label>{modelRegionText('label')}<select value={selectedModelRegionId} onChange={event => applyAreaOption('model_region', event.target.value)} disabled={!areaOptions.model_regions?.length}><option value="">{areaOptions.model_regions?.length ? tr('area.selectPlaceholder') : tr('area.notRegistered')}</option>{(areaOptions.model_regions || []).map(option => <option key={option.id} value={option.id}>{option.name} · {option.id}</option>)}</select></label><small>{areaOptions.sources?.model_regions?.count ? modelRegionText('ready').replace('{{count}}', String(areaOptions.sources.model_regions.count)) : modelRegionText('empty')}</small>{selectedModelRegion && <div className="abu-hydro-source-lineage"><span>{modelRegionText('subcatchments').replace('{{count}}', Number(selectedModelRegion.properties?.subcatchment_count || 0).toLocaleString())}</span><small>{modelRegionText('role')}</small></div>}</div>}{areaSelectionMode === 'freehand' && <div className="abu-hydro-selection-block"><strong>{tr('area.modes.freehand.label')}</strong><small>{tr('area.modes.freehand.empty')}</small><span className="abu-hydro-draw-hint"><Info size={13} />{tr('area.drawHint')}</span></div>}<div className={`abu-hydro-area-options-status ${areaOptionsState}`}><Info size={13} />{areaOptionsState === 'loading' ? tr('area.loading') : areaOptionsState === 'ready' ? tr('area.boundariesReady') : tr('area.boundariesUnavailable')}</div><div className="abu-hydro-area-selection-summary"><small>{tr('area.selected')}</small><strong>{areaSelectionMode === 'administrative' ? ((areaOptions.administrative_units || []).find(item => item.id === selectedAdministrativeId)?.name || '—') : areaSelectionMode === 'model_region' ? (selectedModelRegion?.name || '—') : (isValidPolygon(aoiGeometry) ? tr('area.freehandSelected') : '—')}</strong><span>{aoiMetrics.widthKm.toFixed(2)} km × {aoiMetrics.heightKm.toFixed(2)} km · {tr('area.crs')}</span></div></div><div className="abu-hydro-main-map-hint"><MapPinned size={18} /><div><strong>{tr('area.mapLabel')}</strong><small>{tr('area.mapSelectionHelp')} {tr('area.mapDrawHelp')}</small></div></div></div><details className="abu-hydro-advanced-aoi"><summary>{tr('area.advanced')}</summary><div className="abu-hydro-form-grid aoi-grid">{(['minLon', 'minLat', 'maxLon', 'maxLat'] as const).map(key => <label key={key}>{tr(`aoi.${key}`)}<input type="number" step="0.00001" value={aoi[key]} onChange={event => { updateAoi(key, event.target.value); setAoiGeometry(null); switchAreaSelectionMode('freehand'); }} /></label>)}<div className="abu-hydro-field-note"><Info size={13} />{tr('area.crs')}</div></div></details><div className="abu-hydro-domain-control"><label>{tr('configuration.domainBuffer')}<input type="number" min="0" max="10000" step="10" value={domainBuffer} onChange={event => { setDomainBuffer(numberValue(event.target.value)); markTouched('domain_buffer_m'); }} /><em>{provenance('domain_buffer_m')}</em></label><small>{modelRegionText('bufferInput')}</small></div><div className="abu-hydro-domain-summary"><div><small>{tr('area.modelDomain')}</small><strong>{selectedPilotRegion || (i18n.language.startsWith('zh') ? '自定义 AOI' : 'Custom AOI')}</strong></div><div><small>{tr('area.displayExtent')}</small><strong>{tr('area.sameAsAoi')}</strong></div><div><small>{tr('area.calculationRule')}</small><strong>{selectedPilotRegion ? (i18n.language.startsWith('zh') ? '完整登记模型区域' : 'Complete registered model region') : tr('area.bufferRule')}</strong></div></div>{aoiError && <p className="abu-hydro-error"><CircleAlert size={13} />{aoiError}</p>}<div className="abu-hydro-actions"><button type="button" onClick={goBack}><ArrowLeft size={15} />{tr('actions.back')}</button><button type="button" className="primary" disabled={Boolean(aoiError)} onClick={goNext}>{tr('actions.next')}<ArrowRight size={15} /></button></div></section>}

    {step === 'parameters' && <section className="abu-hydro-card abu-hydro-step-panel"><div className="abu-hydro-card-heading"><Gauge size={16} /><div><h3>{tr('parameters.title')}</h3><small>{tr('parameters.subtitle')}</small></div></div><div className="abu-hydro-form-grid"><label>{tr('configuration.model')}<select value={modelType} onChange={event => { setModelType(event.target.value as ModelType); invalidatePreflight(); }}><option value="coupled_1d_2d">{tr('models.coupled')}</option><option value="one_d">{tr('models.oneD')}</option><option value="two_d">{tr('models.twoD')}</option></select></label><label>{tr('configuration.resource')}<select value={resourceProfile} onChange={event => { setResourceProfile(event.target.value as ResourceProfile); invalidatePreflight(); }}><option value="cpu_small">{tr('resources.cpuSmall')}</option><option value="cpu_large">{tr('resources.cpuLarge')}</option><option value="gpu">{tr('resources.gpu')}</option></select></label></div><div className="abu-hydro-parameter-section"><div className="abu-hydro-subheading"><CloudRain size={14} />{tr('parameters.rainfall')}</div><div className="abu-hydro-form-grid"><label>{tr('configuration.rainfall')}<input type="number" min="0.01" value={rainfallTotal} onChange={event => { setRainfallTotal(numberValue(event.target.value)); markTouched('rainfall_total_mm'); }} /><em>{provenance('rainfall_total_mm')}</em></label><label>{tr('configuration.duration')}<input type="number" min="1" value={rainfallDuration} onChange={event => { setRainfallDuration(numberValue(event.target.value)); markTouched('rainfall_duration_minutes'); }} /><em>{provenance('rainfall_duration_minutes')}</em></label><label>{tr('configuration.pattern')}<select value={rainfallPattern} onChange={event => { setRainfallPattern(event.target.value); markTouched('rainfall_pattern'); }}><option value="uniform">{tr('patterns.uniform')}</option><option value="alternating_block">{tr('patterns.alternating')}</option></select><em>{provenance('rainfall_pattern')}</em></label></div></div>{(modelType === 'one_d' || modelType === 'coupled_1d_2d') && <div className="abu-hydro-parameter-section"><div className="abu-hydro-subheading"><GitBranch size={14} />{tr('parameters.oneD')}</div><div className="abu-hydro-form-grid"><label>{tr('configuration.routing')}<select value={oneDRoutingMethod} onChange={event => { setOneDRoutingMethod(event.target.value); markTouched('one_d_routing_method'); }}><option value="KINWAVE">KINWAVE</option><option value="DYNWAVE">DYNWAVE</option><option value="STEADY">STEADY</option></select><em>{provenance('one_d_routing_method')}</em></label><label>{tr('configuration.infiltration')}<select value={oneDInfiltrationMethod} onChange={event => { setOneDInfiltrationMethod(event.target.value); markTouched('one_d_infiltration_method'); }}><option value="HORTON">HORTON</option><option value="GREEN_AMPT">GREEN_AMPT</option><option value="CURVE_NUMBER">CURVE_NUMBER</option></select><em>{provenance('one_d_infiltration_method')}</em></label></div></div>}{(modelType === 'two_d' || modelType === 'coupled_1d_2d') && <div className="abu-hydro-parameter-section"><div className="abu-hydro-subheading"><Waves size={14} />{tr('parameters.twoD')}</div><div className="abu-hydro-form-grid"><label>{tr('configuration.grid')}<input type="number" min="0.5" value={gridResolution} onChange={event => { setGridResolution(numberValue(event.target.value)); markTouched('two_d_grid_resolution_m'); }} /><em>{provenance('two_d_grid_resolution_m')}</em></label><label>{tr('configuration.manning')}<input type="number" min="0.005" step="0.005" value={manningN} onChange={event => { setManningN(numberValue(event.target.value)); markTouched('two_d_manning_n'); }} /><em>{provenance('two_d_manning_n')}</em></label><label>{tr('configuration.timestep')}<input type="number" min="1" value={twoDTimestep} onChange={event => { setTwoDTimestep(numberValue(event.target.value)); markTouched('two_d_timestep_seconds'); }} /><em>{provenance('two_d_timestep_seconds')}</em></label></div></div>}{modelType === 'coupled_1d_2d' && <div className="abu-hydro-parameter-section"><div className="abu-hydro-subheading"><GitBranch size={14} />{tr('parameters.coupling')}</div><div className="abu-hydro-form-grid"><label>{tr('configuration.coupling')}<select value={couplingMode} onChange={event => { setCouplingMode(event.target.value); markTouched('coupling_mode'); }}><option value="two_way_swmm_anuga">{tr('coupling.twoWay')}</option><option value="one_way_swmm_to_anuga">{tr('coupling.oneWay')}</option></select><em>{provenance('coupling_mode')}</em></label></div></div>}<div className="abu-hydro-actions"><button type="button" onClick={goBack}><ArrowLeft size={15} />{tr('actions.back')}</button><button type="button" className="primary" onClick={runPreflight} disabled={busy || Boolean(aoiError)}><RefreshCw size={15} />{busy ? tr('actions.working') : tr('actions.preflight')}</button></div></section>}

    {step === 'preflight' && <section className="abu-hydro-card abu-hydro-step-panel"><div className="abu-hydro-card-heading"><CircleDashed size={16} /><div><h3>{tr('preflight.title')}</h3><small>{tr('preflight.subtitle')}</small></div></div>{!preflight ? <div className="abu-hydro-empty"><CircleDashed size={22} /><p>{tr('preflight.empty')}</p><button type="button" className="primary" onClick={runPreflight} disabled={busy}>{tr('actions.preflight')}</button></div> : <><div className={`abu-hydro-readiness ${preflight.status}`}><strong>{tr(`preflight.status.${preflight.status}`)}</strong><span>{preflight.can_submit ? tr('preflight.readyDetail') : tr('preflight.blockedDetail')}</span></div><div className="abu-hydro-check-list">{preflight.checks.map(check => <div key={check.key} className="abu-hydro-check"><CheckCircle2 size={14} className={check.status === 'ready' ? 'ok' : 'warn'} /><div><strong>{checkLabel(check)}</strong><small>{checkDetail(check)}</small></div></div>)}</div><div className="abu-hydro-review-grid"><div><h4>{tr('preflight.sourcesTitle')}</h4><div className="abu-hydro-source-list">{allSources.map(source => <div key={source.key}><span>{tr(`sources.${source.key}`)}{source.required ? ` · ${tr('data.required')}` : ` · ${tr('data.optional')}`}</span><strong className={source.status}>{tr(`sourceStatus.${source.status}`)}</strong><small>{source.format} · {sourceDetail(source)}</small></div>)}</div></div><div><h4>{tr('preflight.parametersTitle')}</h4><div className="abu-hydro-provenance-list">{(preflight.parameter_readiness || []).map(parameter => <div key={parameter.key}><span>{parameterLabel(parameter.key)}</span><strong className={parameter.source}>{tr(`parameterSource.${parameter.source === 'system_default' ? 'default' : parameter.source}`)}</strong><small>{parameterValue(parameter)}</small></div>)}</div></div></div>{preflight.warnings.map((warning, index) => <p className="abu-hydro-warning" key={warning}><AlertTriangle size={13} />{String(t(`hydroWorkbench.preflight.warningCodes.${preflight.warning_codes?.[index] || 'unknown'}`, { defaultValue: warning }))}</p>)}{error && <p className="abu-hydro-error"><CircleAlert size={13} />{error}</p>}<div className="abu-hydro-actions"><button type="button" onClick={goBack}><ArrowLeft size={15} />{tr('actions.back')}</button><button type="button" className="primary" onClick={submitRun} disabled={busy || !preflight.can_submit}><Play size={15} />{tr('actions.submit')}</button></div></>}</section>}

    {step === 'results' && <><section className="abu-hydro-card abu-hydro-history-card"><div className="abu-hydro-card-heading"><History size={16} /><div><h3>{tr('history.title')}</h3><small>{tr('history.subtitle')}</small></div><button type="button" className="abu-hydro-icon-button" onClick={() => void loadHistory()} title={tr('history.refresh')}><RefreshCw size={14} /></button></div>{historyState === 'loading' ? <div className="abu-hydro-history-empty"><RefreshCw size={16} className="abu-hydro-spin" />{tr('history.loading')}</div> : historyState === 'unavailable' ? <div className="abu-hydro-history-empty"><CircleAlert size={16} />{tr('history.unavailable')}</div> : history.length === 0 ? <div className="abu-hydro-history-empty"><History size={16} />{tr('history.empty')}</div> : <div className="abu-hydro-history-list">{history.map(item => { const itemState = item.status?.status || 'idle'; const title = item.area?.selection_labels?.[0] || item.area?.region || item.area?.selection_mode || tr('history.unknownArea'); return <div className={`abu-hydro-history-item ${item.run_id === run?.run_id ? 'active' : ''}`} key={item.run_id}><div className="abu-hydro-history-main"><strong>{item.run_id}</strong><small>{title} · {item.request?.model_type || '—'} · {item.created_at ? new Date(item.created_at).toLocaleString() : '—'}</small></div><span className={`abu-hydro-state ${itemState}`}>{tr(`statuses.${itemState}`)}</span><button type="button" className="abu-hydro-history-load" disabled={!item.result_available || itemState !== 'completed'} onClick={() => { void loadRun(item.run_id).catch(caught => setError(caught instanceof Error ? caught.message : tr('errors.status'))); }}>{item.result_available && itemState === 'completed' ? tr('history.load') : tr('history.notReady')}</button></div>; })}</div>}</section><section className="abu-hydro-card abu-hydro-run-card"><div className="abu-hydro-card-heading"><ServerCog size={16} /><div><h3>{tr('run.title')}</h3><small>{tr('run.subtitle')}</small></div><span className={`abu-hydro-state ${runState}`}>{tr(`statuses.${runState}`)}</span></div><div className="abu-hydro-run-summary"><div><small>{tr('run.id')}</small><strong>{run?.run_id || '—'}</strong></div><div><small>{tr('run.progress')}</small><strong>{run?.status?.progress ?? 0}%</strong></div><div><small>{tr('run.message')}</small><strong>{run?.status?.message || tr('run.waiting')}</strong></div></div>{runState === 'queued' || runState === 'running' ? <><div className="abu-hydro-progress"><span style={{ width: `${run?.status?.progress || 5}%` }} /></div><button type="button" className="abu-hydro-cancel" onClick={cancelRun} disabled={!run?.run_id}><Square size={14} />{tr('actions.cancel')}</button></> : null}{runState === 'failed' && <p className="abu-hydro-error"><CircleAlert size={13} />{run?.status?.error || tr('errors.runFailed')}</p>}</section>{result && <section className="abu-hydro-results"><div className="abu-hydro-card"><div className="abu-hydro-card-heading"><Layers3 size={16} /><h3>{tr('results.title')}</h3><button type="button" className="abu-hydro-icon-button" onClick={downloadResult} title={tr('results.download')}><Download size={14} /></button></div><div className="abu-hydro-result-disclosure"><span>{tr('results.inputMode')}</span><strong>{String(result.input_disclosure || '—')}</strong><span>{tr('results.engineeringUse')}</span><strong className={result.engineering_use === true ? 'allowed' : 'blocked'}>{engineeringUseLabel(result.engineering_use)}</strong></div><div className="abu-hydro-main-map-result"><Waves size={18} /><div><strong>{map?.features?.length ? tr('results.map') : tr('results.noMap')}</strong><small>{map?.features?.length ? tr('results.mapLoaded') : tr('results.mapNotReady')}</small></div></div><div className="abu-hydro-timeline-summary"><div className="abu-hydro-timeline-summary-heading"><History size={14} /><strong>{tr('results.timelineTitle')}</strong></div><small>{tr('results.timelineHelp')}</small><div className="abu-hydro-timeline-summary-grid">{(['one_d', 'two_d'] as const).map(key => { const status = timelineStatus(key); return <div key={key} className={`abu-hydro-timeline-summary-item ${status.available ? 'available' : 'missing'}`}><strong>{tr(`results.timeline.${key}`)}</strong><span>{status.available ? tr('results.timeline.available', { count: status.periodCount, step: status.stepMinutes }) : tr('results.timeline.unavailable')}</span></div>; })}</div></div><details><summary>{tr('results.raw')}</summary><pre>{JSON.stringify(result, null, 2)}</pre></details></div></section>}{!result && <div className="abu-hydro-card abu-hydro-empty"><ServerCog size={22} /><p>{tr('results.waiting')}</p></div>}</>}
    {error && step !== 'preflight' && <p className="abu-hydro-error"><CircleAlert size={13} />{error}</p>}
  </div>;
}
