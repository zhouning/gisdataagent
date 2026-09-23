import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  CloudRain,
  Database,
  Gauge,
  GitBranch,
  Layers3,
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

interface AoiValues {
  minLon: number;
  minLat: number;
  maxLon: number;
  maxLat: number;
}

interface FeatureCollection {
  features?: Array<{ geometry?: { type?: string; coordinates?: unknown }; properties?: Record<string, unknown> }>;
}

interface PreflightResponse {
  status: 'ready' | 'blocked';
  can_submit: boolean;
  manifest_preview?: {
    run_id: string;
    request: { model_type: ModelType; input_mode: InputMode; resource_profile: ResourceProfile };
    area: { model_calculation_domain: { buffer_m: number } };
  };
  checks: Array<{ key: string; label: string; status: string; detail: string }>;
  required_sources: Array<{ key: string; status: string; uri: string; format: string; detail: string }>;
  warnings: string[];
};

interface RunRecord {
  run_id: string;
  status?: { status?: string; progress?: number; message?: string; error?: string };
  manifest?: PreflightResponse['manifest_preview'];
}

const initialAoi: AoiValues = { minLon: 54.35, minLat: 24.35, maxLon: 54.45, maxLat: 24.45 };

const numberValue = (value: string) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

export default function AbuDhabiHydroWorkbenchTab() {
  const { t } = useTranslation('common');
  const [modelType, setModelType] = useState<ModelType>('coupled_1d_2d');
  const [inputMode, setInputMode] = useState<InputMode>('development_fixture');
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
  const [networkUri, setNetworkUri] = useState('');
  const [terrainUri, setTerrainUri] = useState('');
  const [rainfallUri, setRainfallUri] = useState('');
  const [tideUri, setTideUri] = useState('');
  const [outfallsUri, setOutfallsUri] = useState('');
  const [pumpsUri, setPumpsUri] = useState('');
  const [preflight, setPreflight] = useState<PreflightResponse | null>(null);
  const [run, setRun] = useState<RunRecord | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [map, setMap] = useState<FeatureCollection | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const tr = (key: string) => String(t(`hydroWorkbench.${key}`));
  const payload = useMemo(() => ({
    model_type: modelType,
    input_mode: inputMode,
    resource_profile: resourceProfile,
    rainfall_total_mm: rainfallTotal,
    rainfall_duration_minutes: rainfallDuration,
    rainfall_pattern: rainfallPattern,
    one_d_routing_method: oneDRoutingMethod,
    one_d_infiltration_method: oneDInfiltrationMethod,
    two_d_grid_resolution_m: gridResolution,
    two_d_manning_n: manningN,
    two_d_timestep_seconds: twoDTimestep,
    domain_buffer_m: domainBuffer,
    coupling_mode: couplingMode,
    aoi: [aoi.minLon, aoi.minLat, aoi.maxLon, aoi.maxLat],
    data_sources: {
      network: { uri: networkUri, format: 'SWMM_INP/GDB' },
      terrain: { uri: terrainUri, format: 'GeoTIFF/NPZ' },
      rainfall: { uri: rainfallUri, format: 'CSV/JSON time series' },
      tide: { uri: tideUri, format: 'CSV/JSON time series' },
      outfalls: { uri: outfallsUri, format: 'GeoPackage/GeoJSON' },
      pumps: { uri: pumpsUri, format: 'CSV/GeoPackage' },
    },
  }), [aoi, couplingMode, domainBuffer, gridResolution, inputMode, manningN, modelType, networkUri, oneDInfiltrationMethod, oneDRoutingMethod, pumpsUri, rainfallDuration, rainfallPattern, rainfallTotal, rainfallUri, resourceProfile, terrainUri, tideUri, twoDTimestep, outfallsUri]);

  const updateAoi = (key: keyof AoiValues, value: string) => {
    setAoi(current => ({ ...current, [key]: numberValue(value) }));
  };

  const runPreflight = async () => {
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/api/abu-dhabi/flood/hydro-runs/preflight', {
        method: 'POST',
        credentials: 'include',
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json() as PreflightResponse & { error?: string };
      if (!response.ok) throw new Error(data.error || tr('errors.preflight'));
      setPreflight(data);
      setRun(null);
      setResult(null);
      setMap(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : tr('errors.preflight'));
    } finally {
      setBusy(false);
    }
  };

  const loadRun = async (runId: string) => {
    const response = await fetch(`/api/abu-dhabi/flood/hydro-runs/${runId}`, {
      credentials: 'include', headers: getLocaleHeaders(),
    });
    if (!response.ok) throw new Error(tr('errors.status'));
    const record = await response.json() as RunRecord;
    setRun(record);
    const state = record.status?.status;
    if (state === 'completed') {
      const [resultResponse, mapResponse] = await Promise.all([
        fetch(`/api/abu-dhabi/flood/hydro-runs/${runId}/result`, { credentials: 'include' }),
        fetch(`/api/abu-dhabi/flood/hydro-runs/${runId}/map`, { credentials: 'include' }),
      ]);
      if (resultResponse.ok) setResult(await resultResponse.json() as Record<string, unknown>);
      if (mapResponse.ok) setMap(await mapResponse.json() as FeatureCollection);
      return true;
    }
    return ['failed', 'cancelled', 'submit_failed'].includes(state || '');
  };

  const submitRun = async () => {
    if (!preflight?.can_submit) return;
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/api/abu-dhabi/flood/hydro-runs', {
        method: 'POST',
        credentials: 'include',
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json() as RunRecord & { error?: string };
      if (!response.ok) throw new Error(data.error || tr('errors.submit'));
      setRun(data);
      for (let attempt = 0; attempt < 120; attempt += 1) {
        if (await loadRun(data.run_id)) break;
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : tr('errors.submit'));
    } finally {
      setBusy(false);
    }
  };

  const pointFeatures = (map?.features || []).filter(feature => {
    const coordinates = feature.geometry?.coordinates;
    return Array.isArray(coordinates) && typeof coordinates[0] === 'number' && typeof coordinates[1] === 'number';
  });
  const mapCoordinates = pointFeatures.map(feature => feature.geometry?.coordinates as number[]);
  const minX = Math.min(...mapCoordinates.map(coordinates => coordinates[0]), 0);
  const maxX = Math.max(...mapCoordinates.map(coordinates => coordinates[0]), 1);
  const minY = Math.min(...mapCoordinates.map(coordinates => coordinates[1]), 0);
  const maxY = Math.max(...mapCoordinates.map(coordinates => coordinates[1]), 1);
  const runState = run?.status?.status || 'idle';

  return (
    <div className="abu-hydro-workbench">
      <section className="abu-hydro-hero">
        <div>
          <span className="abu-hydro-kicker">ABU DHABI / HYDRODYNAMIC MODEL WORKBENCH</span>
          <h2>{tr('title')}</h2>
          <p>{tr('subtitle')}</p>
        </div>
        <div className="abu-hydro-hero-status"><ServerCog size={18} /><strong>{tr(`statuses.${runState}`)}</strong><small>{tr('heroStatus')}</small></div>
      </section>

      <section className="abu-hydro-notice"><AlertTriangle size={17} /><span>{tr('notice')}</span></section>

      <section className="abu-hydro-flow" aria-label={tr('flowLabel')}>
        {[['data', Database], ['etl', GitBranch], ['solver', Waves], ['result', Layers3]].map(([key, Icon]) => (
          <div key={String(key)} className="abu-hydro-flow-step"><Icon size={16} /><span>{tr(`flow.${String(key)}`)}</span></div>
        ))}
      </section>

      <section className="abu-hydro-grid">
        <div className="abu-hydro-card">
          <div className="abu-hydro-card-heading"><Gauge size={16} /><h3>{tr('configuration.title')}</h3></div>
          <div className="abu-hydro-form-grid">
            <label>{tr('configuration.model')}<select value={modelType} onChange={event => setModelType(event.target.value as ModelType)}><option value="coupled_1d_2d">{tr('models.coupled')}</option><option value="one_d">{tr('models.oneD')}</option><option value="two_d">{tr('models.twoD')}</option></select></label>
            <label>{tr('configuration.inputMode')}<select value={inputMode} onChange={event => setInputMode(event.target.value as InputMode)}><option value="development_fixture">{tr('inputModes.fixture')}</option><option value="customer_mount">{tr('inputModes.customer')}</option></select></label>
            <label>{tr('configuration.resource')}<select value={resourceProfile} onChange={event => setResourceProfile(event.target.value as ResourceProfile)}><option value="cpu_small">CPU small</option><option value="cpu_large">CPU large</option><option value="gpu">GPU / H100 profile</option></select></label>
            <label>{tr('configuration.rainfall')}<input type="number" min="0.01" value={rainfallTotal} onChange={event => setRainfallTotal(numberValue(event.target.value))} /></label>
            <label>{tr('configuration.duration')}<input type="number" min="1" value={rainfallDuration} onChange={event => setRainfallDuration(numberValue(event.target.value))} /></label>
            <label>{tr('configuration.pattern')}<select value={rainfallPattern} onChange={event => setRainfallPattern(event.target.value)}><option value="uniform">Uniform</option><option value="alternating_block">Alternating block</option></select></label>
            <label>{tr('configuration.domainBuffer')}<input type="number" min="0" value={domainBuffer} onChange={event => setDomainBuffer(numberValue(event.target.value))} /></label>
            <label>{tr('configuration.grid')}<input type="number" min="0.5" value={gridResolution} onChange={event => setGridResolution(numberValue(event.target.value))} /></label>
            <label>{tr('configuration.manning')}<input type="number" min="0.005" step="0.005" value={manningN} onChange={event => setManningN(numberValue(event.target.value))} /></label>
            <label>{tr('configuration.timestep')}<input type="number" min="1" value={twoDTimestep} onChange={event => setTwoDTimestep(numberValue(event.target.value))} /></label>
            <label>{tr('configuration.coupling')}<select value={couplingMode} onChange={event => setCouplingMode(event.target.value)}><option value="two_way_swmm_anuga">{tr('coupling.twoWay')}</option><option value="one_way_swmm_to_anuga">{tr('coupling.oneWay')}</option></select></label>
          </div>
          <div className="abu-hydro-subheading"><GitBranch size={14} />{tr('configuration.oneD')}</div>
          <div className="abu-hydro-form-grid">
            <label>{tr('configuration.routing')}<select value={oneDRoutingMethod} onChange={event => setOneDRoutingMethod(event.target.value)}><option value="KINWAVE">KINWAVE</option><option value="DYNWAVE">DYNWAVE</option><option value="STEADY">STEADY</option></select></label>
            <label>{tr('configuration.infiltration')}<select value={oneDInfiltrationMethod} onChange={event => setOneDInfiltrationMethod(event.target.value)}><option value="HORTON">HORTON</option><option value="GREEN_AMPT">GREEN_AMPT</option><option value="CURVE_NUMBER">CURVE_NUMBER</option></select></label>
          </div>
          <div className="abu-hydro-subheading"><CloudRain size={14} />{tr('configuration.aoi')}</div>
          <div className="abu-hydro-form-grid aoi-grid">
            {(['minLon', 'minLat', 'maxLon', 'maxLat'] as const).map(key => <label key={key}>{tr(`aoi.${key}`)}<input type="number" step="0.00001" value={aoi[key]} onChange={event => updateAoi(key, event.target.value)} /></label>)}
          </div>
          <div className="abu-hydro-subheading"><Database size={14} />{tr('configuration.sources')}</div>
          <div className="abu-hydro-source-grid">
            <label>{tr('sources.network')}<input placeholder="s3://… / nas://… / normalized SWMM INP" value={networkUri} onChange={event => setNetworkUri(event.target.value)} /></label>
            <label>{tr('sources.terrain')}<input placeholder="s3://… / nas://… / ANUGA NPZ or COG" value={terrainUri} onChange={event => setTerrainUri(event.target.value)} /></label>
            <label>{tr('sources.rainfall')}<input placeholder="s3://… / nas://… / rainfall CSV or JSON" value={rainfallUri} onChange={event => setRainfallUri(event.target.value)} /></label>
            <label>{tr('sources.tide')}<input placeholder="s3://… / nas://… / tide CSV or JSON" value={tideUri} onChange={event => setTideUri(event.target.value)} /></label>
            <label>{tr('sources.outfalls')}<input placeholder="s3://… / nas://… / outfalls GeoPackage" value={outfallsUri} onChange={event => setOutfallsUri(event.target.value)} /></label>
            <label>{tr('sources.pumps')}<input placeholder="s3://… / nas://… / pumps CSV or GeoPackage" value={pumpsUri} onChange={event => setPumpsUri(event.target.value)} /></label>
          </div>
          <div className="abu-hydro-actions"><button type="button" onClick={runPreflight} disabled={busy}><RefreshCw size={15} />{busy ? tr('actions.working') : tr('actions.preflight')}</button><button type="button" className="primary" onClick={submitRun} disabled={busy || !preflight?.can_submit}><Play size={15} />{tr('actions.submit')}</button></div>
        </div>

        <div className="abu-hydro-card">
          <div className="abu-hydro-card-heading"><CircleDashed size={16} /><h3>{tr('preflight.title')}</h3></div>
          {!preflight && <div className="abu-hydro-empty">{tr('preflight.empty')}</div>}
          {preflight && <>
            <div className={`abu-hydro-readiness ${preflight.status}`}><strong>{tr(`preflight.status.${preflight.status}`)}</strong><span>{preflight.manifest_preview?.run_id}</span></div>
            <div className="abu-hydro-check-list">{preflight.checks.map(check => <div key={check.key} className="abu-hydro-check"><CheckCircle2 size={14} className={check.status === 'ready' ? 'ok' : 'warn'} /><div><strong>{check.label}</strong><small>{check.detail}</small></div></div>)}</div>
            <div className="abu-hydro-source-list">{preflight.required_sources.map(source => <div key={source.key}><span>{source.key}</span><strong className={source.status}>{source.status}</strong><small>{source.format} · {source.detail}</small></div>)}</div>
            {preflight.warnings.map(warning => <p className="abu-hydro-warning" key={warning}><AlertTriangle size={13} />{warning}</p>)}
          </>}
          {error && <p className="abu-hydro-error">{error}</p>}
        </div>
      </section>

      <section className="abu-hydro-card abu-hydro-run-card">
        <div className="abu-hydro-card-heading"><ServerCog size={16} /><h3>{tr('run.title')}</h3><span className={`abu-hydro-state ${runState}`}>{tr(`statuses.${runState}`)}</span></div>
        <div className="abu-hydro-run-summary"><div><small>{tr('run.id')}</small><strong>{run?.run_id || '—'}</strong></div><div><small>{tr('run.progress')}</small><strong>{run?.status?.progress ?? 0}%</strong></div><div><small>{tr('run.message')}</small><strong>{run?.status?.message || tr('run.waiting')}</strong></div></div>
        {runState === 'queued' || runState === 'running' ? <div className="abu-hydro-progress"><span style={{ width: `${run?.status?.progress || 5}%` }} /></div> : null}
      </section>

      {result && <section className="abu-hydro-results">
        <div className="abu-hydro-card"><div className="abu-hydro-card-heading"><Layers3 size={16} /><h3>{tr('results.title')}</h3></div><pre>{JSON.stringify(result, null, 2)}</pre></div>
        <div className="abu-hydro-card"><div className="abu-hydro-card-heading"><Waves size={16} /><h3>{tr('results.map')}</h3></div>{pointFeatures.length ? <svg className="abu-hydro-result-map" viewBox="0 0 100 100" role="img" aria-label={tr('results.map')}>
          {pointFeatures.map((feature, index) => { const coordinates = feature.geometry?.coordinates as number[]; const x = ((coordinates[0] - minX) / (maxX - minX || 1)) * 90 + 5; const y = 95 - ((coordinates[1] - minY) / (maxY - minY || 1)) * 90; return <circle key={index} cx={x} cy={y} r="1.8" className="abu-hydro-result-point"><title>{JSON.stringify(feature.properties || {})}</title></circle>; })}
        </svg> : <div className="abu-hydro-empty">{tr('results.noMap')}</div>}</div>
      </section>}
    </div>
  );
}
