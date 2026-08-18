import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, BarChart3, CheckCircle2, Database, RefreshCw, ShieldCheck } from 'lucide-react';
import { formatNumber, getLocaleHeaders } from '../../i18n';

import {
  API_BASE,
  MODEL_LABELS,
  SCENARIO_LABELS,
  figureUrl,
  formatCount,
  formatMetric,
  formatPercent,
  rasterUrl,
  type AbuDhabiModelId,
  type AbuDhabiOverview,
  type AbuDhabiTrack,
} from './abuDhabiLandUse';

const MODEL_IDS: AbuDhabiModelId[] = ['geosos_flus', 'geospatial_kernel', 'paper58'];

export default function AbuDhabiLandUseComparisonTab() {
  const { t, i18n } = useTranslation();
  const [payload, setPayload] = useState<AbuDhabiOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [track, setTrack] = useState<AbuDhabiTrack>('historical');
  const [historicalYear, setHistoricalYear] = useState(2024);
  const [planningYear, setPlanningYear] = useState(2030);
  const [scenario, setScenario] = useState('compact');
  const [seed, setSeed] = useState('ensemble');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`${API_BASE}/overview`, { credentials: 'include', headers: getLocaleHeaders() });
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || t('abuDhabiLandUse.errors.unavailable'));
      setPayload(data as AbuDhabiOverview);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('abuDhabiLandUse.errors.unavailable'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [i18n.resolvedLanguage]);

  const models = useMemo(() => {
    const byId = new Map((payload?.models || []).map(model => [model.id, model]));
    return MODEL_IDS.map(id => byId.get(id)).filter((model): model is NonNullable<typeof model> => Boolean(model));
  }, [payload]);

  const selectedYear = track === 'historical' ? historicalYear : planningYear;

  return (
    <div className="datapanel-section abu-land-use-tab">
      <header className="abu-header">
        <div>
          <span className="abu-eyebrow">{t('abuDhabiLandUse.eyebrow')}</span>
          <h3>{t('abuDhabiLandUse.title')}</h3>
          <p>{t('abuDhabiLandUse.subtitle')}</p>
        </div>
        <div className="abu-header-actions">
          {payload && (
            <span className={`abu-status ${payload.output_audit.status === 'PASS' ? 'pass' : 'warning'}`}>
              <CheckCircle2 size={13} /> {t('abuDhabiLandUse.audit', { count: formatNumber(payload.output_audit.prediction_count) })}
            </span>
          )}
          <button type="button" className="abu-icon-button" onClick={() => void load()} disabled={loading} title={t('abuDhabiLandUse.actions.refresh')}>
            <RefreshCw size={15} className={loading ? 'spin' : ''} />
          </button>
        </div>
      </header>

      {error && <div className="abu-message error"><AlertTriangle size={15} />{error}</div>}
      {loading && !payload && <div className="abu-loading">{t('abuDhabiLandUse.loading')}</div>}

      {payload && (
        <>
          <section className="abu-kpi-strip">
            <div><span>{t('abuDhabiLandUse.kpis.spatialExtent')}</span><strong>{formatNumber(payload.scope.area_km2, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} km²</strong><small>{t('abuDhabiLandUse.kpis.boundary')}</small></div>
            <div><span>{t('abuDhabiLandUse.kpis.grid')}</span><strong>{formatNumber(payload.scope.resolution_m)} m</strong><small>{payload.scope.width} x {payload.scope.height} · {payload.scope.crs}</small></div>
            <div><span>{t('abuDhabiLandUse.kpis.validPixels')}</span><strong>{formatCount(payload.scope.valid_pixels)}</strong><small>{t('abuDhabiLandUse.kpis.coverage')}</small></div>
            <div className="warning"><span>{t('abuDhabiLandUse.kpis.lowConfidence')}</span><strong>{formatPercent(payload.data_quality.mean_low_confidence_fraction, 1)}</strong><small>{t('abuDhabiLandUse.kpis.dynamicWorld')}</small></div>
          </section>

          <section className="abu-section">
            <div className="abu-section-title"><Database size={15} /><strong>{t('abuDhabiLandUse.sections.inputs')}</strong><span>{t('abuDhabiLandUse.sources', { count: formatNumber(payload.input_sources.length) })}</span></div>
            <div className="abu-input-layout">
              <div className="abu-table-wrap">
                <table className="abu-table">
                  <thead><tr><th>{t('abuDhabiLandUse.table.data')}</th><th>{t('abuDhabiLandUse.table.source')}</th><th>{t('abuDhabiLandUse.table.period')}</th><th>{t('abuDhabiLandUse.table.role')}</th></tr></thead>
                  <tbody>{payload.input_sources.map(source => (
                    <tr key={source.name}><td>{source.name}</td><td>{source.source}</td><td>{source.years}</td><td>{source.role}</td></tr>
                  ))}</tbody>
                </table>
              </div>
              <img className="abu-context-figure" src={figureUrl('land_cover_overview')} alt={t('abuDhabiLandUse.images.inputAlt')} />
            </div>
          </section>

          <section className="abu-section">
            <div className="abu-toolbar">
              <div className="abu-segmented" aria-label={t('abuDhabiLandUse.controls.track')}>
                <button type="button" className={track === 'historical' ? 'active' : ''} onClick={() => setTrack('historical')}>{t('abuDhabiLandUse.controls.historical')}</button>
                <button type="button" className={track === 'planning' ? 'active' : ''} onClick={() => setTrack('planning')}>{t('abuDhabiLandUse.controls.planning')}</button>
              </div>
              {track === 'historical' ? (
                <label>{t('abuDhabiLandUse.controls.targetYear')}<select value={historicalYear} onChange={event => setHistoricalYear(Number(event.target.value))}><option value={2023}>{t('abuDhabiLandUse.controls.singleStep', { year: 2023 })}</option><option value={2024}>{t('abuDhabiLandUse.controls.openLoop', { year: 2024 })}</option></select></label>
              ) : (
                <>
                  <label>{t('abuDhabiLandUse.controls.scenario')}<select value={scenario} onChange={event => setScenario(event.target.value)}>{Object.keys(SCENARIO_LABELS).map(id => <option key={id} value={id}>{t(`abuDhabiLandUse.scenarios.${id}`)}</option>)}</select></label>
                  <label>{t('abuDhabiLandUse.controls.targetYear')}<select value={planningYear} onChange={event => setPlanningYear(Number(event.target.value))}>{[2025, 2026, 2027, 2028, 2029, 2030].map(year => <option key={year}>{year}</option>)}</select></label>
                </>
              )}
              <label>{t('abuDhabiLandUse.controls.result')}<select value={seed} onChange={event => setSeed(event.target.value)}><option value="ensemble">{t('abuDhabiLandUse.controls.ensemble')}</option><option value="31">{t('abuDhabiLandUse.controls.seed', { value: 31 })}</option><option value="47">{t('abuDhabiLandUse.controls.seed', { value: 47 })}</option><option value="73">{t('abuDhabiLandUse.controls.seed', { value: 73 })}</option></select></label>
            </div>

            <div className={`abu-map-grid ${track === 'historical' ? 'with-observed' : ''}`}>
              {track === 'historical' && (
                <figure className="abu-map-card">
                  <figcaption><strong>{t('abuDhabiLandUse.map.observed')}</strong><span>Dynamic World {selectedYear}</span></figcaption>
                  <img src={rasterUrl('observed', 'historical', selectedYear)} alt={t('abuDhabiLandUse.images.observedAlt', { year: selectedYear })} />
                </figure>
              )}
              {MODEL_IDS.map(modelId => (
                <figure className="abu-map-card" key={`${modelId}-${track}-${selectedYear}-${scenario}-${seed}`}>
                  <figcaption><strong>{MODEL_LABELS[modelId]}</strong><span>{track === 'historical' ? t('abuDhabiLandUse.map.historicalSim', { year: selectedYear }) : `${t(`abuDhabiLandUse.scenarios.${scenario}`)} ${selectedYear}`}</span></figcaption>
                  <img src={rasterUrl(modelId, track, selectedYear, seed, track === 'planning' ? scenario : undefined)} alt={t('abuDhabiLandUse.images.modelAlt', { model: MODEL_LABELS[modelId], year: selectedYear })} />
                </figure>
              ))}
            </div>

            <div className="abu-legend">{payload.legend.map(item => <span key={item.value}><i style={{ background: item.color }} />{item.label}</span>)}</div>
          </section>

          <section className="abu-section">
            <div className="abu-section-title"><BarChart3 size={15} /><strong>{track === 'historical' ? t('abuDhabiLandUse.metrics.historicalTitle', { year: historicalYear }) : t('abuDhabiLandUse.metrics.planningTitle', { scenario: t(`abuDhabiLandUse.scenarios.${scenario}`), year: planningYear })}</strong></div>
            <div className="abu-table-wrap">
              {track === 'historical' ? (
                <table className="abu-table metrics">
                  <thead><tr><th>{t('abuDhabiLandUse.metrics.model')}</th><th>{t('abuDhabiLandUse.metrics.changeFom')}</th><th>{t('abuDhabiLandUse.metrics.changeF1')}</th><th>{t('abuDhabiLandUse.metrics.macroF1')}</th><th>{t('abuDhabiLandUse.metrics.overallAccuracy')}</th><th>{t('abuDhabiLandUse.metrics.highConfidenceFom')}</th><th>{t('abuDhabiLandUse.metrics.demandError')}</th></tr></thead>
                  <tbody>{models.map(model => {
                    const metrics = model.historical?.[String(historicalYear)] || {};
                    return <tr key={model.id}><td><strong>{model.label}</strong></td><td>{formatMetric(metrics.change_fom)}</td><td>{formatMetric(metrics.change_f1)}</td><td>{formatMetric(metrics.macro_f1)}</td><td>{formatMetric(metrics.overall_accuracy)}</td><td>{formatMetric(metrics.high_confidence_change_fom)}</td><td>{formatPercent(metrics.demand_total_variation)}</td></tr>;
                  })}</tbody>
                </table>
              ) : (
                <table className="abu-table metrics">
                  <thead><tr><th>{t('abuDhabiLandUse.metrics.model')}</th><th>{t('abuDhabiLandUse.metrics.builtGain')}</th><th>{t('abuDhabiLandUse.metrics.greenGain')}</th><th>{t('abuDhabiLandUse.metrics.builtLoss')}</th><th>{t('abuDhabiLandUse.metrics.builtNeighbor')}</th><th>{t('abuDhabiLandUse.metrics.ecologicalConversion')}</th><th>{t('abuDhabiLandUse.metrics.pareto')}</th></tr></thead>
                  <tbody>{models.map(model => {
                    const row = model.planning?.find(candidate => candidate.scenario_id === scenario);
                    const pareto = model.pareto_scenarios?.includes(scenario);
                    return <tr key={model.id}><td><strong>{model.label}</strong></td><td>{formatCount(row?.built_gain_pixels)} px</td><td>{formatCount(row?.green_gain_pixels)} px</td><td>{formatCount(row?.removed_built_pixels)} px</td><td>{formatPercent(row?.new_built_neighbor_fraction)}</td><td>{formatPercent(row?.ecological_conversion_rate)}</td><td><span className={`abu-mini-status ${pareto ? 'pass' : ''}`}>{pareto ? t('abuDhabiLandUse.common.yes') : t('abuDhabiLandUse.common.no')}</span></td></tr>;
                  })}</tbody>
                </table>
              )}
            </div>
          </section>

          <section className="abu-boundary">
            <ShieldCheck size={16} />
            <div><strong>{t('abuDhabiLandUse.boundary.title')}</strong><p>{t('abuDhabiLandUse.boundary.description')}</p></div>
          </section>
        </>
      )}
    </div>
  );
}
