import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Cpu, Layers, LoaderCircle, Play, RefreshCw, ShieldCheck } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { getLocaleHeaders } from '../../i18n';

import {
  API_BASE,
  formatCount,
  formatMetric,
  formatPercent,
  rasterUrl,
  runtimeRasterUrl,
  type AbuDhabiModelId,
  type AbuDhabiModelPayload,
  type AbuDhabiRun,
  type AbuDhabiTrack,
} from './abuDhabiLandUse';

interface Props { modelId: AbuDhabiModelId }

function trainingSummary(modelId: AbuDhabiModelId, training: Record<string, unknown>, t: TFunction) {
  const seconds = typeof training.fit_seconds === 'number' ? `${training.fit_seconds.toFixed(1)}s` : '-';
  if (modelId === 'geospatial_kernel') return t('abuDhabiModel.trainingFeatures', { count: training.feature_count ?? '-', rows: formatCount(training.training_pixel_rows as number), seconds });
  if (modelId === 'paper58') return t('abuDhabiModel.trainingPatches', { epochs: training.epochs ?? '-', patches: training.training_patch_count ?? '-', seconds });
  const featureNames = Array.isArray(training.feature_names) ? training.feature_names.length : '-';
  return t('abuDhabiModel.trainingDrivers', { count: featureNames, rows: formatCount(training.training_pixel_rows as number), seconds });
}

export default function AbuDhabiLandUseModelTab({ modelId }: Props) {
  const { t } = useTranslation('common');
  const [payload, setPayload] = useState<AbuDhabiModelPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [track, setTrack] = useState<AbuDhabiTrack>('historical');
  const [historicalYear, setHistoricalYear] = useState(2024);
  const [planningYear, setPlanningYear] = useState(2030);
  const [scenario, setScenario] = useState('compact');
  const [seed, setSeed] = useState('ensemble');
  const [executionSeed, setExecutionSeed] = useState(31);
  const [run, setRun] = useState<AbuDhabiRun | null>(null);
  const [runMessage, setRunMessage] = useState('');
  const autoMappedRun = useRef('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`${API_BASE}/models/${modelId}`, { credentials: 'include', headers: getLocaleHeaders() });
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || t('abuDhabiModel.resultUnavailable'));
      setPayload(data as AbuDhabiModelPayload);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('abuDhabiModel.resultUnavailable'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [modelId]);

  const sendToMap = useCallback(async (completedRun?: AbuDhabiRun) => {
    setError('');
    setRunMessage('');
    const mapTrack = completedRun?.track || track;
    const mapScenario = completedRun?.scenario || (mapTrack === 'planning' ? scenario : undefined);
    const mapSeed = completedRun ? String(completedRun.seed) : seed;
    try {
      const response = await fetch(`${API_BASE}/map`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({
          model_id: modelId,
          track: mapTrack,
          scenario: mapScenario,
          seed: mapSeed,
          run_id: completedRun?.run_id,
        }),
      });
      const data = await response.json();
      if (!response.ok || data.error || !data.map_update) {
        throw new Error(data.error || t('abuDhabiModel.mapLoadFailed'));
      }
      (window as any).__handleMapUpdate?.(data.map_update);
      setRunMessage(completedRun ? t('abuDhabiModel.currentTimelineLoaded') : t('abuDhabiModel.frozenTimelineLoaded'));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('abuDhabiModel.mapLoadFailed'));
    }
  }, [modelId, scenario, seed, track]);

  const executeModel = async () => {
    setError('');
    setRunMessage(t('abuDhabiModel.submittingRun'));
    try {
      const response = await fetch(`${API_BASE}/runs`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({
          model_id: modelId,
          track,
          seed: executionSeed,
          scenario: track === 'planning' ? scenario : null,
        }),
      });
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || t('abuDhabiModel.submitFailed'));
      setRun(data as AbuDhabiRun);
      setRunMessage(t('abuDhabiModel.queued'));
    } catch (requestError) {
      setRunMessage('');
      setError(requestError instanceof Error ? requestError.message : t('abuDhabiModel.submitFailed'));
    }
  };

  useEffect(() => {
    if (!run || run.status === 'complete' || run.status === 'failed') return;
    let cancelled = false;
    const poll = async () => {
      try {
        const response = await fetch(`${API_BASE}/runs/${run.run_id}`, { credentials: 'include', headers: getLocaleHeaders() });
        const data = await response.json() as AbuDhabiRun & { error?: string };
        if (!response.ok || data.error) throw new Error(data.error || t('abuDhabiModel.statusReadFailed'));
        if (cancelled) return;
        setRun(data);
        if (data.status === 'complete') {
          setTrack(data.track);
          setSeed(String(data.seed));
          if (data.scenario) setScenario(data.scenario);
          setRunMessage(t('abuDhabiModel.runCompleted'));
          if (autoMappedRun.current !== data.run_id) {
            autoMappedRun.current = data.run_id;
            await sendToMap(data);
          }
        } else if (data.status === 'failed') {
          setRunMessage('');
          setError(data.error || t('abuDhabiModel.runFailed'));
        } else {
          setRunMessage(data.status === 'queued' ? t('abuDhabiModel.waiting') : t('abuDhabiModel.running'));
        }
      } catch (requestError) {
        if (!cancelled) setError(requestError instanceof Error ? requestError.message : t('abuDhabiModel.statusReadFailed'));
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [run?.run_id, run?.status, sendToMap]);

  const historicalMetrics = payload?.historical[String(historicalYear)] || {};
  const planningMetrics = useMemo(
    () => payload?.planning.find(row => row.scenario_id === scenario),
    [payload, scenario],
  );
  const year = track === 'historical' ? historicalYear : planningYear;
  const matchingRun = run?.status === 'complete'
    && run.model_id === modelId
    && run.track === track
    && String(run.seed) === seed
    && (track === 'historical' || run.scenario === scenario)
    ? run
    : null;
  const resultImageUrl = matchingRun?.years.includes(year)
    ? runtimeRasterUrl(matchingRun.run_id, year)
    : rasterUrl(modelId, track, year, seed, track === 'planning' ? scenario : undefined);
  const isExecuting = run?.status === 'queued' || run?.status === 'running';
  const scenarioLabel = (id: string) => t(`abuDhabiModel.scenarios.${id}`, { defaultValue: id });

  return (
    <div className="datapanel-section abu-land-use-tab abu-model-tab">
      <header className="abu-header">
        <div>
          <span className="abu-eyebrow">{t('abuDhabiModel.eyebrow')}</span>
          <h3>{payload?.model.label || modelId}</h3>
          <p>{payload?.model.family || t('abuDhabiModel.readingEvidence')}</p>
        </div>
        <div className="abu-header-actions">
          {payload && <span className="abu-status pass"><CheckCircle2 size={13} /> {t('abuDhabiModel.frozenRunComplete')}</span>}
          <button type="button" className="abu-icon-button" onClick={() => void load()} disabled={loading} title={t('abuDhabiModel.refreshFrozenResult')} aria-label={t('abuDhabiModel.refreshFrozenResult')}><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
        </div>
      </header>

      {error && <div className="abu-message error"><AlertTriangle size={15} />{error}</div>}
      {loading && !payload && <div className="abu-loading">{t('abuDhabiModel.loadingResult')}</div>}

      {payload && (
        <>
          <section className="abu-model-contract">
            <div><span>{t('abuDhabiModel.state')}</span><strong>{payload.model.state}</strong></div>
            <div><span>{t('abuDhabiModel.action')}</span><strong>{payload.model.action}</strong></div>
            <div><span>{t('abuDhabiModel.runtime')}</span><strong>{payload.model.runtime}</strong></div>
            <div><span>{t('abuDhabiModel.stateWriteback')}</span><strong>{payload.state_writeback ? t('abuDhabiModel.annualWriteback') : t('abuDhabiModel.noWriteback')}</strong></div>
          </section>

          <section className="abu-mechanism"><Cpu size={17} /><div><strong>{t('abuDhabiModel.mechanism')}</strong><p>{payload.model.mechanism}</p></div></section>

          <section className="abu-runtime-panel">
            <div className="abu-runtime-heading">
              <div><Play size={15} /><strong>{t('abuDhabiModel.execution')}</strong></div>
              {run && <span className={`abu-mini-status ${run.status === 'complete' ? 'pass' : ''}`}>{t(`statusLabels.${run.status}`, { defaultValue: run.status })}</span>}
            </div>
            <div className="abu-runtime-controls">
              <label>{t('abuDhabiModel.executionSeed')}<select value={executionSeed} onChange={event => setExecutionSeed(Number(event.target.value))} disabled={isExecuting}>{[31, 47, 73].map(value => <option key={value}>{value}</option>)}</select></label>
              <button type="button" className="abu-command-button primary" onClick={() => void executeModel()} disabled={isExecuting}>
                {isExecuting ? <LoaderCircle size={14} className="spin" /> : <Play size={14} />}
                {isExecuting ? t('abuDhabiModel.executing') : t('abuDhabiModel.executeModel', { model: payload.model.label })}
              </button>
              <button type="button" className="abu-command-button" onClick={() => void sendToMap(matchingRun || undefined)} disabled={isExecuting}>
                <Layers size={14} />{t('abuDhabiModel.loadTimeline')}
              </button>
            </div>
            {(runMessage || run?.error) && <div className={`abu-run-message ${run?.status === 'failed' ? 'error' : ''}`}>{runMessage || run?.error}</div>}
          </section>

          <section className="abu-section">
            <div className="abu-toolbar">
              <div className="abu-segmented" aria-label={t('abuDhabiModel.experimentTrack')}>
                <button type="button" className={track === 'historical' ? 'active' : ''} onClick={() => setTrack('historical')}>{t('abuDhabiModel.historicalBacktest')}</button>
                <button type="button" className={track === 'planning' ? 'active' : ''} onClick={() => setTrack('planning')}>{t('abuDhabiModel.planningScenario')}</button>
              </div>
              {track === 'historical' ? (
                <label>{t('abuDhabiModel.targetYear')}<select value={historicalYear} onChange={event => setHistoricalYear(Number(event.target.value))}><option value={2023}>{t('abuDhabiModel.singleStep', { year: 2023 })}</option><option value={2024}>{t('abuDhabiModel.twoStepOpenLoop', { year: 2024 })}</option></select></label>
              ) : (
                <>
                  <label>{t('abuDhabiModel.scenario')}<select value={scenario} onChange={event => setScenario(event.target.value)}>{payload.options.scenarios.map(id => <option key={id} value={id}>{scenarioLabel(id)}</option>)}</select></label>
                  <label>{t('abuDhabiModel.targetYear')}<select value={planningYear} onChange={event => setPlanningYear(Number(event.target.value))}>{payload.options.planning_years.map(value => <option key={value}>{value}</option>)}</select></label>
                </>
              )}
              <label>{t('abuDhabiModel.result')}<select value={seed} onChange={event => setSeed(event.target.value)}><option value="ensemble">{t('abuDhabiModel.threeSeedEnsemble')}</option><option value="31">{t('abuDhabiModel.seed', { value: 31 })}</option><option value="47">{t('abuDhabiModel.seed', { value: 47 })}</option><option value="73">{t('abuDhabiModel.seed', { value: 73 })}</option></select></label>
            </div>

            <div className={`abu-model-map-grid ${track === 'historical' ? 'three' : ''}`}>
              <figure className="abu-map-card"><figcaption><strong>{t('abuDhabiModel.startState')}</strong><span>{t('abuDhabiModel.observedYear', { year: track === 'historical' ? 2022 : 2024 })}</span></figcaption><img src={rasterUrl('observed', 'historical', track === 'historical' ? 2022 : 2024)} alt={t('abuDhabiModel.startLandCover')} /></figure>
              {track === 'historical' && <figure className="abu-map-card"><figcaption><strong>{t('abuDhabiModel.targetObservation')}</strong><span>Dynamic World {year}</span></figcaption><img src={rasterUrl('observed', 'historical', year)} alt={t('abuDhabiModel.targetObservationYear', { year })} /></figure>}
              <figure className="abu-map-card"><figcaption><strong>{t('abuDhabiModel.modelResult')}</strong><span>{matchingRun ? `${t('abuDhabiModel.currentRun')} · ` : ''}{track === 'historical' ? t('abuDhabiModel.historicalSimulation', { year }) : `${scenarioLabel(scenario)} ${year}`}</span></figcaption><img src={resultImageUrl} alt={t('abuDhabiModel.modelResultAlt', { model: payload.model.label, year })} /></figure>
            </div>
            <div className="abu-legend">{payload.legend.map(item => <span key={item.value}><i style={{ background: item.color }} />{item.label}</span>)}</div>
          </section>

          <section className="abu-kpi-strip model-metrics">
            {track === 'historical' ? (
              <>
                <div><span>{t('abuDhabiModel.changeFom')}</span><strong>{formatMetric(historicalMetrics.change_fom)}</strong><small>{t('abuDhabiModel.changeLocationOverlap')}</small></div>
                <div><span>{t('abuDhabiModel.changeF1')}</span><strong>{formatMetric(historicalMetrics.change_f1)}</strong><small>{t('abuDhabiModel.changedPixelDetection')}</small></div>
                <div><span>{t('abuDhabiModel.macroF1')}</span><strong>{formatMetric(historicalMetrics.macro_f1)}</strong><small>{t('abuDhabiModel.sixClassMacroAverage')}</small></div>
                <div className="warning"><span>{t('abuDhabiModel.highConfidenceFom')}</span><strong>{formatMetric(historicalMetrics.high_confidence_change_fom)}</strong><small>{t('abuDhabiModel.labelQualitySensitivity')}</small></div>
              </>
            ) : (
              <>
                <div><span>{t('abuDhabiModel.newBuiltArea')}</span><strong>{formatCount(planningMetrics?.built_gain_pixels)} px</strong><small>{formatCount((planningMetrics?.built_gain_pixels || 0) / 100)} km²</small></div>
                <div><span>{t('abuDhabiModel.newGreenArea')}</span><strong>{formatCount(planningMetrics?.green_gain_pixels)} px</strong><small>{t('abuDhabiModel.targetYearCumulative')}</small></div>
                <div><span>{t('abuDhabiModel.adjacentToExistingBuilt')}</span><strong>{formatPercent(planningMetrics?.new_built_neighbor_fraction)}</strong><small>{t('abuDhabiModel.spatialCompactnessProxy')}</small></div>
                <div className={planningMetrics?.pareto ? '' : 'warning'}><span>{t('abuDhabiModel.paretoFront')}</span><strong>{planningMetrics?.pareto ? t('abuDhabiModel.included') : t('abuDhabiModel.notIncluded')}</strong><small>{t('abuDhabiModel.frozenObjectiveSet')}</small></div>
              </>
            )}
          </section>

          <section className="abu-section">
            <div className="abu-section-title"><Cpu size={15} /><strong>{t('abuDhabiModel.trainingEvidence')}</strong><span>{t('abuDhabiModel.testLabelsExcluded')}</span></div>
            <div className="abu-table-wrap"><table className="abu-table"><thead><tr><th>{t('abuDhabiModel.randomSeed')}</th><th>{t('abuDhabiModel.trainingSummary')}</th></tr></thead><tbody>{payload.training_runs.map(run => <tr key={run.seed}><td>Seed {run.seed}</td><td>{trainingSummary(modelId, run.training, t)}</td></tr>)}</tbody></table></div>
          </section>

          <section className="abu-boundary">
            <ShieldCheck size={16} />
            <div><strong>{t('abuDhabiModel.modelBoundary')}</strong>{payload.model.caveats.map(text => <p key={text}>{text}</p>)}</div>
          </section>
        </>
      )}
    </div>
  );
}
