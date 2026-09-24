import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import L from 'leaflet';
import 'leaflet-draw';
import 'leaflet-draw/dist/leaflet.draw.css';
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
type AreaSelectionMode = 'administrative' | 'catchment' | 'freehand';

interface AoiValues { minLon: number; minLat: number; maxLon: number; maxLat: number; }
interface GeoJSONPolygon { type: 'Polygon'; coordinates: number[][][]; }
interface AreaOption { id: string; name: string; geometry: GeoJSONPolygon; properties?: Record<string, unknown>; }
interface AreaOptionsResponse {
  administrative_units?: AreaOption[];
  catchments?: AreaOption[];
  sources?: {
    administrative_units?: { status?: string; uri?: string; count?: number };
    catchments?: { status?: string; uri?: string; count?: number };
  };
  freehand?: { status?: string };
}
interface FeatureCollection { features?: Array<{ geometry?: { type?: string; coordinates?: unknown }; properties?: Record<string, unknown> }>; }
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
}
interface SourceDefaultsResponse { sources?: Partial<Record<'network' | 'terrain', RegisteredSource>>; }
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

const initialAoi: AoiValues = { minLon: 54.35, minLat: 24.35, maxLon: 54.45, maxLat: 24.45 };
const sourceKeys: SourceKey[] = ['network', 'terrain', 'rainfall', 'tide', 'outfalls', 'pumps'];
const stepKeys: StepKey[] = ['data', 'area', 'parameters', 'preflight', 'results'];
const fallbackSourceFormats: Record<SourceKey, string> = { network: 'SWMM_INP/GDB', terrain: 'GeoTIFF/NPZ', rainfall: 'CSV/JSON time series', tide: 'CSV/JSON time series', outfalls: 'GeoPackage/GeoJSON', pumps: 'CSV/GeoPackage' };
const numberValue = (value: string) => { const parsed = Number(value); return Number.isFinite(parsed) ? parsed : 0; };
const polygonBbox = (geometry: GeoJSONPolygon): AoiValues => {
  const points = geometry.coordinates[0] || [];
  const xs = points.map(point => point[0]).filter(value => Number.isFinite(value));
  const ys = points.map(point => point[1]).filter(value => Number.isFinite(value));
  if (xs.length < 4 || ys.length < 4) return initialAoi;
  return { minLon: Math.min(...xs), minLat: Math.min(...ys), maxLon: Math.max(...xs), maxLat: Math.max(...ys) };
};
const isValidPolygon = (geometry: GeoJSONPolygon | null) => {
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
  const { t } = useTranslation('common');
  const tr = (key: string) => String(t(`hydroWorkbench.${key}`));
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
  const [selectedCatchmentId, setSelectedCatchmentId] = useState('');
  const [aoiGeometry, setAoiGeometry] = useState<GeoJSONPolygon | null>(null);
  const [areaOptions, setAreaOptions] = useState<AreaOptionsResponse>({ administrative_units: [], catchments: [] });
  const [areaOptionsState, setAreaOptionsState] = useState<'loading' | 'ready' | 'unavailable'>('loading');
  const [sources, setSources] = useState<Record<SourceKey, string>>({ network: '', terrain: '', rainfall: '', tide: '', outfalls: '', pumps: '' });
  const [sourceDefaults, setSourceDefaults] = useState<Partial<Record<'network' | 'terrain', RegisteredSource>>>({});
  const [sourceDefaultsState, setSourceDefaultsState] = useState<'loading' | 'ready' | 'unavailable'>('loading');
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [preflight, setPreflight] = useState<PreflightResponse | null>(null);
  const [run, setRun] = useState<RunRecord | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [map, setMap] = useState<FeatureCollection | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const stopPollingRef = useRef(false);
  const areaMapRef = useRef<HTMLDivElement | null>(null);
  const areaMapInstanceRef = useRef<L.Map | null>(null);
  const areaDrawnItemsRef = useRef<L.FeatureGroup | null>(null);
  const areaDrawControlRef = useRef<any>(null);
  const areaHighlightRef = useRef<L.GeoJSON | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const loadSourceDefaults = async () => {
      try {
        const response = await fetch('/api/abu-dhabi/flood/hydro-runs/source-defaults', { credentials: 'include', headers: getLocaleHeaders(), signal: controller.signal });
        if (!response.ok) throw new Error(`source defaults: ${response.status}`);
        const data = await response.json() as SourceDefaultsResponse;
        const registered = data.sources || {};
        const hasRegisteredSource = Boolean(registered.network?.registered || registered.terrain?.registered);
        setSourceDefaults(registered);
        setSources(current => ({
          ...current,
          network: current.network.trim() || (registered.network?.registered ? registered.network.uri : ''),
          terrain: current.terrain.trim() || (registered.terrain?.registered ? registered.terrain.uri : ''),
        }));
        setSourceDefaultsState(hasRegisteredSource ? 'ready' : 'unavailable');
      } catch (caught) {
        if (!(caught instanceof DOMException && caught.name === 'AbortError')) setSourceDefaultsState('unavailable');
      }
    };
    void loadSourceDefaults();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const loadAreaOptions = async () => {
      try {
        const response = await fetch('/api/abu-dhabi/flood/hydro-runs/area-options', { credentials: 'include', headers: getLocaleHeaders(), signal: controller.signal });
        if (!response.ok) throw new Error(`area options: ${response.status}`);
        const data = await response.json() as AreaOptionsResponse;
        setAreaOptions(data);
        setAreaOptionsState((data.administrative_units?.length || data.catchments?.length) ? 'ready' : 'unavailable');
      } catch (caught) {
        if (!(caught instanceof DOMException && caught.name === 'AbortError')) setAreaOptionsState('unavailable');
      }
    };
    void loadAreaOptions();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (step !== 'area' || !areaMapRef.current || areaMapInstanceRef.current) return;
    const map = L.map(areaMapRef.current, { zoomControl: true, attributionControl: true }).setView([aoi.minLat, aoi.minLon], 11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
    const drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);
    areaMapInstanceRef.current = map;
    areaDrawnItemsRef.current = drawnItems;
    const drawControl = new (L.Control as any).Draw({
      position: 'topright',
      draw: { polygon: { allowIntersection: false, showArea: true, shapeOptions: { color: '#22c55e' } }, polyline: false, rectangle: false, circle: false, marker: false, circlemarker: false },
      edit: { featureGroup: drawnItems, remove: true },
    });
    areaDrawControlRef.current = drawControl;
    const drawCreated = (event: any) => {
      const layer = event.layer as L.Layer & { toGeoJSON?: () => any };
      const geojson = layer.toGeoJSON?.();
      const geometry = geojson?.geometry as GeoJSONPolygon | undefined;
      if (!geometry || geometry.type !== 'Polygon') return;
      drawnItems.clearLayers();
      drawnItems.addLayer(layer);
      setAreaSelectionMode('freehand');
      setSelectedAdministrativeId('');
      setSelectedCatchmentId('');
      setAoiGeometry(geometry);
      setAoi(polygonBbox(geometry));
      invalidatePreflight();
    };
    map.on('draw:created', drawCreated);
    const redraw = () => window.setTimeout(() => map.invalidateSize(), 0);
    window.addEventListener('resize', redraw);
    redraw();
    return () => {
      window.removeEventListener('resize', redraw);
      map.off('draw:created', drawCreated);
      map.remove();
      areaMapInstanceRef.current = null;
      areaDrawnItemsRef.current = null;
      areaDrawControlRef.current = null;
      areaHighlightRef.current = null;
    };
  }, [step]);

  useEffect(() => {
    const map = areaMapInstanceRef.current;
    const drawControl = areaDrawControlRef.current;
    if (!map || !drawControl) return;
    if (areaSelectionMode === 'freehand') {
      map.addControl(drawControl);
    } else {
      try { map.removeControl(drawControl); } catch { /* control not mounted */ }
    }
  }, [areaSelectionMode, step]);

  useEffect(() => {
    const map = areaMapInstanceRef.current;
    if (!map) return;
    if (areaHighlightRef.current) map.removeLayer(areaHighlightRef.current);
    areaHighlightRef.current = null;
    if (aoiGeometry && areaSelectionMode !== 'freehand') {
      areaHighlightRef.current = L.geoJSON(aoiGeometry as any, { style: { color: '#fbbf24', weight: 3, fillColor: '#fbbf24', fillOpacity: 0.2 } }).addTo(map);
      try { map.fitBounds(areaHighlightRef.current.getBounds(), { padding: [20, 20] }); } catch { /* invalid geometry is reported by the form */ }
    }
    if (areaSelectionMode === 'freehand' && areaDrawnItemsRef.current) {
      areaDrawnItemsRef.current.clearLayers();
      if (aoiGeometry) areaDrawnItemsRef.current.addLayer(L.geoJSON(aoiGeometry as any));
    }
  }, [aoiGeometry, areaSelectionMode]);

  const invalidatePreflight = () => { setPreflight(null); if (step === 'preflight' || step === 'results') setStep('parameters'); };
  const markTouched = (key: string) => { setTouched(current => ({ ...current, [key]: true })); invalidatePreflight(); };
  const parameterPayload = useMemo(() => ({
    ...(touched.rainfall_total_mm ? { rainfall_total_mm: rainfallTotal } : {}),
    ...(touched.rainfall_duration_minutes ? { rainfall_duration_minutes: rainfallDuration } : {}),
    ...(touched.rainfall_pattern ? { rainfall_pattern: rainfallPattern } : {}),
    ...(touched.one_d_routing_method ? { one_d_routing_method: oneDRoutingMethod } : {}),
    ...(touched.one_d_infiltration_method ? { one_d_infiltration_method: oneDInfiltrationMethod } : {}),
    ...(touched.two_d_grid_resolution_m ? { two_d_grid_resolution_m: gridResolution } : {}),
    ...(touched.two_d_manning_n ? { two_d_manning_n: manningN } : {}),
    ...(touched.two_d_timestep_seconds ? { two_d_timestep_seconds: twoDTimestep } : {}),
    ...(touched.domain_buffer_m ? { domain_buffer_m: domainBuffer } : {}),
    ...(touched.coupling_mode ? { coupling_mode: couplingMode } : {}),
  }), [couplingMode, domainBuffer, gridResolution, manningN, oneDInfiltrationMethod, oneDRoutingMethod, rainfallDuration, rainfallPattern, rainfallTotal, touched, twoDTimestep]);
  const payload = useMemo(() => ({
    model_type: modelType, input_mode: inputMode, resource_profile: resourceProfile, ...parameterPayload,
    aoi: aoiGeometry || [aoi.minLon, aoi.minLat, aoi.maxLon, aoi.maxLat],
    area_selection: {
      mode: areaSelectionMode,
      ids: areaSelectionMode === 'administrative' ? (selectedAdministrativeId ? [selectedAdministrativeId] : []) : areaSelectionMode === 'catchment' ? (selectedCatchmentId ? [selectedCatchmentId] : []) : [],
      labels: areaSelectionMode === 'administrative' ? (areaOptions.administrative_units || []).filter(item => item.id === selectedAdministrativeId).map(item => item.name) : areaSelectionMode === 'catchment' ? (areaOptions.catchments || []).filter(item => item.id === selectedCatchmentId).map(item => item.name) : [],
    },
    data_sources: Object.fromEntries(sourceKeys.map(key => {
      const registered = key === 'network' || key === 'terrain' ? sourceDefaults[key] : undefined;
      const usesRegisteredSource = Boolean(registered?.registered && registered.uri === sources[key]);
      return [key, {
        uri: sources[key],
        format: usesRegisteredSource ? registered?.format : fallbackSourceFormats[key],
        version: usesRegisteredSource ? registered?.version : 'unversioned',
        provided_by_customer: usesRegisteredSource ? registered?.provided_by_customer : inputMode === 'customer_mount',
        etl_required: usesRegisteredSource ? registered?.etl_required : true,
      }];
    })),
  }), [aoi, aoiGeometry, areaOptions, areaSelectionMode, inputMode, modelType, parameterPayload, resourceProfile, selectedAdministrativeId, selectedCatchmentId, sourceDefaults, sources]);
  const requiredSourceKeys = useMemo<SourceKey[]>(() => modelType === 'one_d' ? ['network'] : modelType === 'two_d' ? ['terrain'] : ['network', 'terrain'], [modelType]);
  const aoiError = useMemo(() => {
    if (areaSelectionMode === 'administrative' && !selectedAdministrativeId) return tr('area.selectionRequired');
    if (areaSelectionMode === 'catchment' && !selectedCatchmentId) return tr('area.selectionRequired');
    if (areaSelectionMode === 'freehand' && !isValidPolygon(aoiGeometry)) return tr('area.drawRequired');
    if (aoi.minLon >= aoi.maxLon || aoi.minLat >= aoi.maxLat) return tr('area.invalidOrder');
    if (aoi.maxLon - aoi.minLon > 5 || aoi.maxLat - aoi.minLat > 5) return tr('area.tooLarge');
    return '';
  }, [aoi, aoiGeometry, areaSelectionMode, selectedAdministrativeId, selectedCatchmentId, tr]);
  const aoiMetrics = useMemo(() => ({ widthKm: Math.max(0, (aoi.maxLon - aoi.minLon) * 111.32 * Math.cos(((aoi.minLat + aoi.maxLat) / 2) * Math.PI / 180)), heightKm: Math.max(0, (aoi.maxLat - aoi.minLat) * 111.32) }), [aoi]);
  const updateAoi = (key: keyof AoiValues, value: string) => { setAoi(current => ({ ...current, [key]: numberValue(value) })); invalidatePreflight(); };
  const updateSource = (key: SourceKey, value: string) => { setSources(current => ({ ...current, [key]: value })); invalidatePreflight(); };
  const applyAreaOption = (mode: Exclude<AreaSelectionMode, 'freehand'>, id: string) => {
    const options = mode === 'administrative' ? (areaOptions.administrative_units || []) : (areaOptions.catchments || []);
    const option = options.find(item => item.id === id);
    setAreaSelectionMode(mode);
    if (mode === 'administrative') { setSelectedAdministrativeId(id); setSelectedCatchmentId(''); }
    else { setSelectedCatchmentId(id); setSelectedAdministrativeId(''); }
    if (!option) { setAoiGeometry(null); invalidatePreflight(); return; }
    setAoiGeometry(option.geometry);
    setAoi(polygonBbox(option.geometry));
    invalidatePreflight();
  };
  const switchAreaSelectionMode = (mode: AreaSelectionMode) => {
    setAreaSelectionMode(mode);
    if (mode === 'freehand') {
      setSelectedAdministrativeId('');
      setSelectedCatchmentId('');
      setAoiGeometry(null);
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
      if (mapResponse.ok) setMap(await mapResponse.json() as FeatureCollection);
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

  const pointFeatures = (map?.features || []).filter(feature => { const coordinates = feature.geometry?.coordinates; return Array.isArray(coordinates) && typeof coordinates[0] === 'number' && typeof coordinates[1] === 'number'; });
  const mapCoordinates = pointFeatures.map(feature => feature.geometry?.coordinates as number[]); const minX = Math.min(...mapCoordinates.map(coordinates => coordinates[0]), 0); const maxX = Math.max(...mapCoordinates.map(coordinates => coordinates[0]), 1); const minY = Math.min(...mapCoordinates.map(coordinates => coordinates[1]), 0); const maxY = Math.max(...mapCoordinates.map(coordinates => coordinates[1]), 1);
  const runState = run?.status?.status || 'idle'; const allSources = preflight?.sources || preflight?.required_sources || []; const activeStepIndex = stepKeys.indexOf(step);
  const goNext = () => { if (step === 'data') setStep('area'); else if (step === 'area' && !aoiError) setStep('parameters'); else if (step === 'parameters') setStep('preflight'); };
  const goBack = () => { if (activeStepIndex > 0) setStep(stepKeys[activeStepIndex - 1]); };

  const sourceCard = (key: SourceKey) => {
    const required = requiredSourceKeys.includes(key);
    const registered = key === 'network' || key === 'terrain' ? sourceDefaults[key] : undefined;
    const usesRegisteredSource = Boolean(registered?.registered && registered.uri === sources[key]);
    const sourceAsset = registered?.source_uri || registered?.source_name;
    const metadata = [registered?.format, formatBytes(registered?.size_bytes), registered?.crs, registered?.resolution_m ? `${registered.resolution_m} m` : ''].filter(Boolean).join(' · ');
    return <div key={key} className={`abu-hydro-asset ${required ? 'required' : ''} ${usesRegisteredSource ? 'registered' : ''}`}>
      <div className="abu-hydro-asset-heading"><strong>{tr(`sources.${key}`)}</strong><div className="abu-hydro-asset-badges">{usesRegisteredSource && <span className="abu-hydro-chip registered"><CheckCircle2 size={10} />{tr('data.registered')}</span>}<span className={`abu-hydro-chip ${required ? 'required' : 'optional'}`}>{required ? tr('data.required') : tr('data.optional')}</span></div></div>
      <input aria-label={tr(`sources.${key}`)} placeholder={tr(`sourcePlaceholders.${key}`)} value={sources[key]} onChange={event => updateSource(key, event.target.value)} />
      <small>{tr(`sourceFormats.${key}`)}</small>
      {usesRegisteredSource && registered && <div className="abu-hydro-source-lineage"><div><span>{tr('data.modelInput')}</span><code title={registered.uri}>{registered.uri}</code></div>{sourceAsset && <div><span>{tr('data.sourceAsset')}</span><code title={sourceAsset}>{sourceAsset}</code></div>}<small>{metadata}{registered.sha256 ? ` · SHA-256 ${registered.sha256.slice(0, 12)}…` : ''}</small></div>}
    </div>;
  };
  const provenance = (key: string) => touched[key] ? tr('parameterSource.user') : tr('parameterSource.default');

  return <div className="abu-hydro-workbench">
    <section className="abu-hydro-hero"><div><span className="abu-hydro-kicker">ABU DHABI / HYDRODYNAMIC MODEL WORKBENCH</span><h2>{tr('title')}</h2><p>{tr('subtitle')}</p></div><div className="abu-hydro-hero-status"><ServerCog size={18} /><strong>{tr(`statuses.${runState}`)}</strong><small>{tr('heroStatus')}</small></div></section>
    <section className="abu-hydro-notice"><AlertTriangle size={17} /><div><strong>{tr('productionNotice.title')}</strong><span>{tr('productionNotice.body')}</span></div></section>
    <nav className="abu-hydro-stepper" aria-label={tr('stepsLabel')}>{stepKeys.map((key, index) => { const done = index < activeStepIndex; const enabled = index <= activeStepIndex || (key === 'preflight' && Boolean(preflight)) || key === 'results'; return <button key={key} type="button" className={`abu-hydro-step ${key === step ? 'active' : ''} ${done ? 'done' : ''}`} onClick={() => enabled && setStep(key)} disabled={!enabled}><span>{done ? <CheckCircle2 size={15} /> : index + 1}</span><strong>{tr(`steps.${key}.title`)}</strong><small>{tr(`steps.${key}.short`)}</small></button>; })}</nav>
    <section className="abu-hydro-flow" aria-label={tr('flowLabel')}>{[['data', Database], ['etl', GitBranch], ['solver', Waves], ['result', Layers3]].map(([key, Icon]) => <div key={String(key)} className="abu-hydro-flow-step"><Icon size={16} /><span>{tr(`flow.${String(key)}`)}</span></div>)}</section>

    {step === 'data' && <section className="abu-hydro-card abu-hydro-step-panel"><div className="abu-hydro-card-heading"><Database size={16} /><div><h3>{tr('data.title')}</h3><small>{tr('data.subtitle')}</small></div></div><div className="abu-hydro-mode-row"><div><strong>{tr('data.modeTitle')}</strong><span>{inputMode === 'customer_mount' ? tr('data.customerMode') : tr('data.fixtureMode')}</span></div>{showDevelopmentOptions && <label className="abu-hydro-mode-select">{tr('configuration.inputMode')}<select value={inputMode} onChange={event => { setInputMode(event.target.value as InputMode); invalidatePreflight(); }}><option value="customer_mount">{tr('inputModes.customer')}</option><option value="development_fixture">{tr('inputModes.fixture')}</option></select></label>}</div><div className={`abu-hydro-default-status ${sourceDefaultsState}`}>{sourceDefaultsState === 'loading' ? <RefreshCw size={13} /> : sourceDefaultsState === 'ready' ? <CheckCircle2 size={13} /> : <CircleAlert size={13} />}<span>{tr(`data.defaults.${sourceDefaultsState}`)}</span></div><div className="abu-hydro-asset-grid">{sourceKeys.map(sourceCard)}</div>{inputMode === 'development_fixture' && <p className="abu-hydro-warning"><AlertTriangle size={13} />{tr('data.fixtureWarning')}</p>}<div className="abu-hydro-actions"><button type="button" className="primary" onClick={goNext}>{tr('actions.next')}<ArrowRight size={15} /></button></div></section>}

    {step === 'area' && <section className="abu-hydro-card abu-hydro-step-panel"><div className="abu-hydro-card-heading"><MapPinned size={16} /><div><h3>{tr('area.title')}</h3><small>{tr('area.subtitle')}</small></div></div><div className="abu-hydro-area-order"><strong>{tr('area.selectionOrder')}</strong><span>{tr('area.selectionOrderDetail')}</span></div><div className="abu-hydro-area-modes">{(['administrative', 'catchment', 'freehand'] as AreaSelectionMode[]).map((mode, index) => <button key={mode} type="button" className={`abu-hydro-area-mode ${areaSelectionMode === mode ? 'active' : ''}`} onClick={() => switchAreaSelectionMode(mode)}><span>{index + 1}</span><strong>{tr(`area.modes.${mode}.title`)}</strong><small>{tr(`area.modes.${mode}.subtitle`)}</small></button>)}</div><div className="abu-hydro-area-layout"><div className="abu-hydro-area-selection-panel">{areaSelectionMode === 'administrative' && <div className="abu-hydro-selection-block"><label>{tr('area.modes.administrative.label')}<select value={selectedAdministrativeId} onChange={event => applyAreaOption('administrative', event.target.value)} disabled={!areaOptions.administrative_units?.length}><option value="">{areaOptions.administrative_units?.length ? tr('area.selectPlaceholder') : tr('area.notRegistered')}</option>{(areaOptions.administrative_units || []).map(option => <option key={option.id} value={option.id}>{option.name} · {option.id}</option>)}</select></label><small>{areaOptions.sources?.administrative_units?.uri ? `${tr('area.source')}: ${areaOptions.sources.administrative_units.uri}` : tr('area.modes.administrative.empty')}</small></div>}{areaSelectionMode === 'catchment' && <div className="abu-hydro-selection-block"><label>{tr('area.modes.catchment.label')}<select value={selectedCatchmentId} onChange={event => applyAreaOption('catchment', event.target.value)} disabled={!areaOptions.catchments?.length}><option value="">{areaOptions.catchments?.length ? tr('area.selectPlaceholder') : tr('area.notRegistered')}</option>{(areaOptions.catchments || []).map(option => <option key={option.id} value={option.id}>{option.name} · {option.id}</option>)}</select></label><small>{areaOptions.sources?.catchments?.uri ? `${tr('area.source')}: ${areaOptions.sources.catchments.uri}` : tr('area.modes.catchment.empty')}</small></div>}{areaSelectionMode === 'freehand' && <div className="abu-hydro-selection-block"><strong>{tr('area.modes.freehand.label')}</strong><small>{tr('area.modes.freehand.empty')}</small><span className="abu-hydro-draw-hint"><Info size={13} />{tr('area.drawHint')}</span></div>}<div className={`abu-hydro-area-options-status ${areaOptionsState}`}><Info size={13} />{areaOptionsState === 'loading' ? tr('area.loading') : areaOptionsState === 'ready' ? tr('area.boundariesReady') : tr('area.boundariesUnavailable')}</div><div className="abu-hydro-area-selection-summary"><small>{tr('area.selected')}</small><strong>{areaSelectionMode === 'administrative' ? ((areaOptions.administrative_units || []).find(item => item.id === selectedAdministrativeId)?.name || '—') : areaSelectionMode === 'catchment' ? ((areaOptions.catchments || []).find(item => item.id === selectedCatchmentId)?.name || '—') : (isValidPolygon(aoiGeometry) ? tr('area.freehandSelected') : '—')}</strong><span>{aoiMetrics.widthKm.toFixed(2)} km × {aoiMetrics.heightKm.toFixed(2)} km · {tr('area.crs')}</span></div></div><div className="abu-hydro-area-map-panel"><div ref={areaMapRef} className="abu-hydro-area-map" aria-label={tr('area.mapLabel')} /><small>{areaSelectionMode === 'freehand' ? tr('area.mapDrawHelp') : tr('area.mapSelectionHelp')}</small></div></div><details className="abu-hydro-advanced-aoi"><summary>{tr('area.advanced')}</summary><div className="abu-hydro-form-grid aoi-grid">{(['minLon', 'minLat', 'maxLon', 'maxLat'] as const).map(key => <label key={key}>{tr(`aoi.${key}`)}<input type="number" step="0.00001" value={aoi[key]} onChange={event => { updateAoi(key, event.target.value); setAoiGeometry(null); switchAreaSelectionMode('freehand'); }} /></label>)}<div className="abu-hydro-field-note"><Info size={13} />{tr('area.crs')}</div></div></details><div className="abu-hydro-domain-control"><label>{tr('configuration.domainBuffer')}<input type="number" min="0" max="10000" step="10" value={domainBuffer} onChange={event => { setDomainBuffer(numberValue(event.target.value)); markTouched('domain_buffer_m'); }} /><em>{provenance('domain_buffer_m')}</em></label><small>{tr('area.bufferInputHint')}</small></div><div className="abu-hydro-domain-summary"><div><small>{tr('area.modelDomain')}</small><strong>{domainBuffer} m</strong></div><div><small>{tr('area.displayExtent')}</small><strong>{tr('area.sameAsAoi')}</strong></div><div><small>{tr('area.calculationRule')}</small><strong>{tr('area.bufferRule')}</strong></div></div>{aoiError && <p className="abu-hydro-error"><CircleAlert size={13} />{aoiError}</p>}<div className="abu-hydro-actions"><button type="button" onClick={goBack}><ArrowLeft size={15} />{tr('actions.back')}</button><button type="button" className="primary" disabled={Boolean(aoiError)} onClick={goNext}>{tr('actions.next')}<ArrowRight size={15} /></button></div></section>}

    {step === 'parameters' && <section className="abu-hydro-card abu-hydro-step-panel"><div className="abu-hydro-card-heading"><Gauge size={16} /><div><h3>{tr('parameters.title')}</h3><small>{tr('parameters.subtitle')}</small></div></div><div className="abu-hydro-form-grid"><label>{tr('configuration.model')}<select value={modelType} onChange={event => { setModelType(event.target.value as ModelType); invalidatePreflight(); }}><option value="coupled_1d_2d">{tr('models.coupled')}</option><option value="one_d">{tr('models.oneD')}</option><option value="two_d">{tr('models.twoD')}</option></select></label><label>{tr('configuration.resource')}<select value={resourceProfile} onChange={event => { setResourceProfile(event.target.value as ResourceProfile); invalidatePreflight(); }}><option value="cpu_small">{tr('resources.cpuSmall')}</option><option value="cpu_large">{tr('resources.cpuLarge')}</option><option value="gpu">{tr('resources.gpu')}</option></select></label></div><div className="abu-hydro-parameter-section"><div className="abu-hydro-subheading"><CloudRain size={14} />{tr('parameters.rainfall')}</div><div className="abu-hydro-form-grid"><label>{tr('configuration.rainfall')}<input type="number" min="0.01" value={rainfallTotal} onChange={event => { setRainfallTotal(numberValue(event.target.value)); markTouched('rainfall_total_mm'); }} /><em>{provenance('rainfall_total_mm')}</em></label><label>{tr('configuration.duration')}<input type="number" min="1" value={rainfallDuration} onChange={event => { setRainfallDuration(numberValue(event.target.value)); markTouched('rainfall_duration_minutes'); }} /><em>{provenance('rainfall_duration_minutes')}</em></label><label>{tr('configuration.pattern')}<select value={rainfallPattern} onChange={event => { setRainfallPattern(event.target.value); markTouched('rainfall_pattern'); }}><option value="uniform">{tr('patterns.uniform')}</option><option value="alternating_block">{tr('patterns.alternating')}</option></select><em>{provenance('rainfall_pattern')}</em></label></div></div>{(modelType === 'one_d' || modelType === 'coupled_1d_2d') && <div className="abu-hydro-parameter-section"><div className="abu-hydro-subheading"><GitBranch size={14} />{tr('parameters.oneD')}</div><div className="abu-hydro-form-grid"><label>{tr('configuration.routing')}<select value={oneDRoutingMethod} onChange={event => { setOneDRoutingMethod(event.target.value); markTouched('one_d_routing_method'); }}><option value="KINWAVE">KINWAVE</option><option value="DYNWAVE">DYNWAVE</option><option value="STEADY">STEADY</option></select><em>{provenance('one_d_routing_method')}</em></label><label>{tr('configuration.infiltration')}<select value={oneDInfiltrationMethod} onChange={event => { setOneDInfiltrationMethod(event.target.value); markTouched('one_d_infiltration_method'); }}><option value="HORTON">HORTON</option><option value="GREEN_AMPT">GREEN_AMPT</option><option value="CURVE_NUMBER">CURVE_NUMBER</option></select><em>{provenance('one_d_infiltration_method')}</em></label></div></div>}{(modelType === 'two_d' || modelType === 'coupled_1d_2d') && <div className="abu-hydro-parameter-section"><div className="abu-hydro-subheading"><Waves size={14} />{tr('parameters.twoD')}</div><div className="abu-hydro-form-grid"><label>{tr('configuration.grid')}<input type="number" min="0.5" value={gridResolution} onChange={event => { setGridResolution(numberValue(event.target.value)); markTouched('two_d_grid_resolution_m'); }} /><em>{provenance('two_d_grid_resolution_m')}</em></label><label>{tr('configuration.manning')}<input type="number" min="0.005" step="0.005" value={manningN} onChange={event => { setManningN(numberValue(event.target.value)); markTouched('two_d_manning_n'); }} /><em>{provenance('two_d_manning_n')}</em></label><label>{tr('configuration.timestep')}<input type="number" min="1" value={twoDTimestep} onChange={event => { setTwoDTimestep(numberValue(event.target.value)); markTouched('two_d_timestep_seconds'); }} /><em>{provenance('two_d_timestep_seconds')}</em></label></div></div>}{modelType === 'coupled_1d_2d' && <div className="abu-hydro-parameter-section"><div className="abu-hydro-subheading"><GitBranch size={14} />{tr('parameters.coupling')}</div><div className="abu-hydro-form-grid"><label>{tr('configuration.coupling')}<select value={couplingMode} onChange={event => { setCouplingMode(event.target.value); markTouched('coupling_mode'); }}><option value="two_way_swmm_anuga">{tr('coupling.twoWay')}</option><option value="one_way_swmm_to_anuga">{tr('coupling.oneWay')}</option></select><em>{provenance('coupling_mode')}</em></label></div></div>}<div className="abu-hydro-actions"><button type="button" onClick={goBack}><ArrowLeft size={15} />{tr('actions.back')}</button><button type="button" className="primary" onClick={runPreflight} disabled={busy || Boolean(aoiError)}><RefreshCw size={15} />{busy ? tr('actions.working') : tr('actions.preflight')}</button></div></section>}

    {step === 'preflight' && <section className="abu-hydro-card abu-hydro-step-panel"><div className="abu-hydro-card-heading"><CircleDashed size={16} /><div><h3>{tr('preflight.title')}</h3><small>{tr('preflight.subtitle')}</small></div></div>{!preflight ? <div className="abu-hydro-empty"><CircleDashed size={22} /><p>{tr('preflight.empty')}</p><button type="button" className="primary" onClick={runPreflight} disabled={busy}>{tr('actions.preflight')}</button></div> : <><div className={`abu-hydro-readiness ${preflight.status}`}><strong>{tr(`preflight.status.${preflight.status}`)}</strong><span>{preflight.can_submit ? tr('preflight.readyDetail') : tr('preflight.blockedDetail')}</span></div><div className="abu-hydro-check-list">{preflight.checks.map(check => <div key={check.key} className="abu-hydro-check"><CheckCircle2 size={14} className={check.status === 'ready' ? 'ok' : 'warn'} /><div><strong>{checkLabel(check)}</strong><small>{checkDetail(check)}</small></div></div>)}</div><div className="abu-hydro-review-grid"><div><h4>{tr('preflight.sourcesTitle')}</h4><div className="abu-hydro-source-list">{allSources.map(source => <div key={source.key}><span>{tr(`sources.${source.key}`)}{source.required ? ` · ${tr('data.required')}` : ` · ${tr('data.optional')}`}</span><strong className={source.status}>{tr(`sourceStatus.${source.status}`)}</strong><small>{source.format} · {sourceDetail(source)}</small></div>)}</div></div><div><h4>{tr('preflight.parametersTitle')}</h4><div className="abu-hydro-provenance-list">{(preflight.parameter_readiness || []).map(parameter => <div key={parameter.key}><span>{parameterLabel(parameter.key)}</span><strong className={parameter.source}>{tr(`parameterSource.${parameter.source === 'system_default' ? 'default' : parameter.source}`)}</strong><small>{parameterValue(parameter)}</small></div>)}</div></div></div>{preflight.warnings.map((warning, index) => <p className="abu-hydro-warning" key={warning}><AlertTriangle size={13} />{String(t(`hydroWorkbench.preflight.warningCodes.${preflight.warning_codes?.[index] || 'unknown'}`, { defaultValue: warning }))}</p>)}{error && <p className="abu-hydro-error"><CircleAlert size={13} />{error}</p>}<div className="abu-hydro-actions"><button type="button" onClick={goBack}><ArrowLeft size={15} />{tr('actions.back')}</button><button type="button" className="primary" onClick={submitRun} disabled={busy || !preflight.can_submit}><Play size={15} />{tr('actions.submit')}</button></div></>}</section>}

    {step === 'results' && <><section className="abu-hydro-card abu-hydro-run-card"><div className="abu-hydro-card-heading"><ServerCog size={16} /><div><h3>{tr('run.title')}</h3><small>{tr('run.subtitle')}</small></div><span className={`abu-hydro-state ${runState}`}>{tr(`statuses.${runState}`)}</span></div><div className="abu-hydro-run-summary"><div><small>{tr('run.id')}</small><strong>{run?.run_id || '—'}</strong></div><div><small>{tr('run.progress')}</small><strong>{run?.status?.progress ?? 0}%</strong></div><div><small>{tr('run.message')}</small><strong>{run?.status?.message || tr('run.waiting')}</strong></div></div>{runState === 'queued' || runState === 'running' ? <><div className="abu-hydro-progress"><span style={{ width: `${run?.status?.progress || 5}%` }} /></div><button type="button" className="abu-hydro-cancel" onClick={cancelRun} disabled={!run?.run_id}><Square size={14} />{tr('actions.cancel')}</button></> : null}{runState === 'failed' && <p className="abu-hydro-error"><CircleAlert size={13} />{run?.status?.error || tr('errors.runFailed')}</p>}</section>{result && <section className="abu-hydro-results"><div className="abu-hydro-card"><div className="abu-hydro-card-heading"><Layers3 size={16} /><h3>{tr('results.title')}</h3><button type="button" className="abu-hydro-icon-button" onClick={downloadResult} title={tr('results.download')}><Download size={14} /></button></div><div className="abu-hydro-result-disclosure"><span>{tr('results.inputMode')}</span><strong>{String(result.input_disclosure || '—')}</strong><span>{tr('results.engineeringUse')}</span><strong className={result.engineering_use === true ? 'allowed' : 'blocked'}>{engineeringUseLabel(result.engineering_use)}</strong></div><details><summary>{tr('results.raw')}</summary><pre>{JSON.stringify(result, null, 2)}</pre></details></div><div className="abu-hydro-card"><div className="abu-hydro-card-heading"><Waves size={16} /><h3>{tr('results.map')}</h3></div>{pointFeatures.length ? <svg className="abu-hydro-result-map" viewBox="0 0 100 100" role="img" aria-label={tr('results.map')}>{pointFeatures.map((feature, index) => { const coordinates = feature.geometry?.coordinates as number[]; const x = ((coordinates[0] - minX) / (maxX - minX || 1)) * 90 + 5; const y = 95 - ((coordinates[1] - minY) / (maxY - minY || 1)) * 90; return <circle key={index} cx={x} cy={y} r="1.8" className="abu-hydro-result-point"><title>{JSON.stringify(feature.properties || {})}</title></circle>; })}</svg> : <div className="abu-hydro-empty">{tr('results.noMap')}</div>}</div></section>}{!result && <div className="abu-hydro-card abu-hydro-empty"><ServerCog size={22} /><p>{tr('results.waiting')}</p></div>}</>}
    {error && step !== 'preflight' && <p className="abu-hydro-error"><CircleAlert size={13} />{error}</p>}
  </div>;
}
