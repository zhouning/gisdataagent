import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { formatNumber, getLocaleHeaders } from '../../i18n';

interface ScenarioInfo {
  id: string;
  name_zh: string;
  name_en: string;
  description: string;
}

interface ModelStatus {
  weights_exist: boolean;
  decoder_exist: boolean;
  gee_available: boolean;
  param_count: number;
  version?: string;
}

interface AreaDist {
  [className: string]: { class_id: number; count: number; percentage: number };
}

interface PredictionResult {
  status: string;
  error?: string;
  scenario: string;
  scenario_zh: string;
  bbox: number[];
  start_year: number;
  years: number[];
  grid_shape: number[];
  area_distribution: { [year: string]: AreaDist };
  transition_matrix: { [from: string]: { [to: string]: number } };
  summary: string;
  elapsed_seconds: number;
}

const LULC_COLORS: Record<string, string> = {
  '\u6c34\u4f53': '#4169E1',
  '\u6811\u6728': '#228B22',
  '\u8349\u5730': '#90EE90',
  '\u704c\u6728': '#DEB887',
  '\u8015\u5730': '#FFD700',
  '\u5efa\u8bbe\u7528\u5730': '#DC143C',
  '\u88f8\u5730': '#D2B48C',
  '\u51b0\u96ea': '#FFFFFF',
  '\u6e7f\u5730': '#20B2AA',
};

interface CounterfactualResult {
  status: string;
  error?: string;
  scenario_a: string;
  scenario_b: string;
  per_year_effects?: { [year: string]: { changed_pixels: number; changed_pct: number } };
  aggregate_effects?: { total_changed_pct: number; dominant_change: string };
  summary?: string;
}

export default function WorldModelTab() {
  const { t } = useTranslation();
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>([]);
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [selectedScenario, setSelectedScenario] = useState('baseline');
  const [bbox, setBbox] = useState('121.2,31.0,121.3,31.1');
  const [startYear, setStartYear] = useState(2023);
  const [nYears, setNYears] = useState(5);
  const [prediction, setPrediction] = useState<PredictionResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // --- Intervention mode state (Angle C) ---
  const [mode, setMode] = useState<'predict' | 'intervene' | 'counterfactual'>('predict');
  const [interventionSubBbox, setInterventionSubBbox] = useState('');
  const [interventionType, setInterventionType] = useState('ecological_restoration');
  const [scenarioB, setScenarioB] = useState('ecological_restoration');
  const [cfResult, setCfResult] = useState<CounterfactualResult | null>(null);

  useEffect(() => {
    fetch('/api/world-model/status', { credentials: 'include', headers: getLocaleHeaders() })
      .then(r => r.ok ? r.json() : null)
      .then(d => d && setStatus(d))
      .catch(() => {});
    fetch('/api/world-model/scenarios', { credentials: 'include', headers: getLocaleHeaders() })
      .then(r => r.ok ? r.json() : null)
      .then(d => d?.scenarios && setScenarios(d.scenarios))
      .catch(() => {});
  }, []);

  const handlePredict = async () => {
    setLoading(true);
    setError('');
    setPrediction(null);
    try {
      const parts = bbox.split(',').map(Number);
      if (parts.length !== 4 || parts.some(isNaN)) {
        setError(t('worldModel.errors.invalidBbox'));
        return;
      }
      const resp = await fetch('/api/world-model/predict', {
        method: 'POST',
        credentials: 'include',
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bbox: parts,
          scenario: selectedScenario,
          start_year: startYear,
          n_years: nYears,
        }),
      });
      const data = await resp.json();
      if (data.error) {
        setError(data.error);
      } else {
        setPrediction(data);
        // Trigger map panel update by fetching pending map data
        try {
          const mapResp = await fetch('/api/map/pending', { credentials: 'include', headers: getLocaleHeaders() });
          const mapData = await mapResp.json();
          if (mapData.map_update && (window as any).__handleMapUpdate) {
            (window as any).__handleMapUpdate(mapData.map_update);
          }
        } catch { /* map update is best-effort */ }
      }
    } catch (e: any) {
      setError(e.message || t('worldModel.errors.requestFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleIntervene = async () => {
    setLoading(true);
    setError('');
    setPrediction(null);
    setCfResult(null);
    try {
      const resp = await fetch('/api/causal-world-model/intervene', {
        method: 'POST',
        credentials: 'include',
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bbox,
          intervention_sub_bbox: interventionSubBbox,
          intervention_type: interventionType,
          baseline_scenario: selectedScenario,
          start_year: startYear,
          n_years: nYears,
        }),
      });
      const data = await resp.json();
      if (data.error) setError(data.error);
      else setCfResult(data);
    } catch (e: any) {
      setError(e.message || t('worldModel.errors.requestFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleCounterfactual = async () => {
    setLoading(true);
    setError('');
    setPrediction(null);
    setCfResult(null);
    try {
      const resp = await fetch('/api/causal-world-model/counterfactual', {
        method: 'POST',
        credentials: 'include',
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bbox,
          scenario_a: selectedScenario,
          scenario_b: scenarioB,
          start_year: startYear,
          n_years: nYears,
        }),
      });
      const data = await resp.json();
      if (data.error) setError(data.error);
      else setCfResult(data);
    } catch (e: any) {
      setError(e.message || t('worldModel.errors.requestFailed'));
    } finally {
      setLoading(false);
    }
  };

  // Build stacked area data for timeline chart
  const buildTimelineData = () => {
    if (!prediction) return null;
    const years = prediction.years.map(String);
    const allClasses = new Set<string>();
    for (const yd of Object.values(prediction.area_distribution)) {
      for (const cls of Object.keys(yd)) allClasses.add(cls);
    }
    const classes = Array.from(allClasses);
    const series = classes.map(cls => ({
      name: cls,
      color: LULC_COLORS[cls] || '#808080',
      data: years.map(y => {
        const d = prediction.area_distribution[y];
        return d?.[cls]?.percentage ?? 0;
      }),
    }));
    return { years, series };
  };

  const timelineData = buildTimelineData();

  const scenarioLabel = (scenario: ScenarioInfo) => t(`worldModel.scenarios.${scenario.id}.name`, { defaultValue: scenario.name_en || scenario.name_zh || scenario.id });
  const scenarioDescription = (scenario: ScenarioInfo) => t(`worldModel.scenarios.${scenario.id}.description`, { defaultValue: scenario.description });
  const lulcLabel = (name: string) => {
    const keyByName: Record<string, string> = {
      '\u6c34\u4f53': 'water', '\u6811\u6728': 'trees', '\u8349\u5730': 'grass', '\u704c\u6728': 'shrub', '\u8015\u5730': 'cropland',
      '\u5efa\u8bbe\u7528\u5730': 'builtUp', '\u88f8\u5730': 'bare', '\u51b0\u96ea': 'snowIce', '\u6e7f\u5730': 'wetland',
    };
    return t(`worldModel.lulc.${keyByName[name] || name}`, { defaultValue: name });
  };
  const formatPercent = (value: number) => `${formatNumber(value, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;

  // Get all unique classes from transition matrix
  const tmClasses = prediction
    ? Array.from(new Set([
        ...Object.keys(prediction.transition_matrix),
        ...Object.values(prediction.transition_matrix).flatMap(v => Object.keys(v)),
      ]))
    : [];

  return (
    <div className="worldmodel-tab">
      {/* Mode Toggle */}
      <div className="worldmodel-config">
        <div style={{ display: 'flex', gap: '4px', marginBottom: '8px' }}>
          {(['predict', 'intervene', 'counterfactual'] as const).map(m => (
            <button
              key={m}
              onClick={() => { setMode(m); setError(''); setPrediction(null); setCfResult(null); }}
              style={{
                flex: 1, padding: '4px 8px', fontSize: '12px', borderRadius: '4px', border: '1px solid #ddd', cursor: 'pointer',
                background: mode === m ? 'var(--color-primary, #4169E1)' : '#fff',
                color: mode === m ? '#fff' : '#333',
              }}
            >
              {t(`worldModel.modes.${m}`)}
            </button>
          ))}
        </div>

        <div className="worldmodel-status">
          {status ? (
            <span className={`status-badge ${status.weights_exist && status.gee_available ? 'ready' : 'warning'}`}>
              {status.weights_exist && status.gee_available ? t('worldModel.status.ready') : status.gee_available ? t('worldModel.status.trainingRequired') : t('worldModel.status.geeUnavailable')}
            </span>
          ) : (
            <span className="status-badge loading">{t('worldModel.status.checking')}</span>
          )}
          {status?.param_count ? <span className="param-info">{formatNumber(status.param_count / 1000, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}K {t('worldModel.status.parameters')}</span> : null}
        </div>

        <div className="config-row">
          <label>{t('worldModel.controls.region')}</label>
          <input
            type="text"
            value={bbox}
            onChange={e => setBbox(e.target.value)}
            placeholder={t('worldModel.controls.bboxPlaceholder')}
          />
        </div>

        <div className="config-row">
          <label>{t('worldModel.controls.scenario')}</label>
          <select value={selectedScenario} onChange={e => setSelectedScenario(e.target.value)}>
            {scenarios.map(s => (
              <option key={s.id} value={s.id}>
                {scenarioLabel(s)} ({s.id})
              </option>
            ))}
          </select>
        </div>
        {scenarios.find(s => s.id === selectedScenario)?.description && (
          <div className="scenario-desc">
            {scenarioDescription(scenarios.find(s => s.id === selectedScenario)!)}
          </div>
        )}

        <div className="config-row-group">
          <div className="config-row">
            <label>{t('worldModel.controls.startYear')}</label>
            <input
              type="number"
              min={2017}
              max={2024}
              value={startYear}
              onChange={e => setStartYear(Number(e.target.value))}
            />
          </div>
          <div className="config-row">
            <label>{t('worldModel.controls.horizon')}</label>
            <input
              type="range"
              min={1}
              max={10}
              value={nYears}
              onChange={e => setNYears(Number(e.target.value))}
            />
            <span className="range-label">{t('worldModel.controls.years', { count: formatNumber(nYears) })}</span>
          </div>
        </div>

        {/* Mode-specific inputs */}
        {mode === 'intervene' && (
          <>
            <div className="config-row">
              <label>{t('worldModel.controls.interventionBbox')}</label>
              <input
                type="text"
                value={interventionSubBbox}
                onChange={e => setInterventionSubBbox(e.target.value)}
                placeholder={t('worldModel.controls.interventionBboxPlaceholder')}
              />
            </div>
            <div className="config-row">
              <label>{t('worldModel.controls.interventionType')}</label>
              <select value={interventionType} onChange={e => setInterventionType(e.target.value)}>
                {scenarios.map(s => (
                  <option key={s.id} value={s.id}>{scenarioLabel(s)}</option>
                ))}
              </select>
            </div>
          </>
        )}
        {mode === 'counterfactual' && (
          <div className="config-row">
            <label>{t('worldModel.controls.scenarioB')}</label>
            <select value={scenarioB} onChange={e => setScenarioB(e.target.value)}>
              {scenarios.map(s => (
                <option key={s.id} value={s.id}>{scenarioLabel(s)}</option>
              ))}
            </select>
          </div>
        )}

        <button
          className="predict-btn"
          onClick={mode === 'predict' ? handlePredict : mode === 'intervene' ? handleIntervene : handleCounterfactual}
          disabled={loading}
        >
          {loading ? t('worldModel.actions.computing') : t(`worldModel.actions.${mode}`)}
        </button>

        {error && <div className="error-msg">{error}</div>}
      </div>

      {/* Results */}
      {prediction && (
        <div className="worldmodel-results">
          {/* Summary */}
          <div className="result-summary">{prediction.summary}</div>

          {/* Timeline Chart - Stacked Area */}
          {timelineData && (
            <div className="timeline-section">
              <h4>{t('worldModel.results.areaTrend')}</h4>
              <div className="timeline-chart">
                <table className="timeline-table">
                  <thead>
                    <tr>
                      <th>{t('worldModel.results.class')}</th>
                      {timelineData.years.map(y => (
                        <th key={y}>{y}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {timelineData.series.map(s => (
                      <tr key={s.name}>
                        <td>
                          <span
                            className="color-dot"
                            style={{ backgroundColor: s.color }}
                          />
                          {lulcLabel(s.name)}
                        </td>
                        {s.data.map((v, i) => (
                          <td key={i} className="pct-cell">
                            {formatPercent(v)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {/* Visual bars per year */}
                <div className="stacked-bars">
                  {timelineData.years.map((year, yi) => (
                    <div key={year} className="bar-column">
                      <div className="bar-stack">
                        {timelineData.series.map(s => (
                          <div
                            key={s.name}
                            className="bar-segment"
                            style={{
                              height: `${s.data[yi]}%`,
                              backgroundColor: s.color,
                            }}
                            title={`${lulcLabel(s.name)}: ${formatPercent(s.data[yi])}`}
                          />
                        ))}
                      </div>
                      <div className="bar-label">{year}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Transition Matrix */}
          {tmClasses.length > 0 && (
            <div className="transition-section">
              <h4>
                {t('worldModel.results.transitionMatrix', { from: prediction.start_year, to: prediction.years[prediction.years.length - 1] })}
              </h4>
              <div className="transition-matrix">
                <table>
                  <thead>
                    <tr>
                      <th>{t('worldModel.results.fromTo')}</th>
                      {tmClasses.map(c => (
                        <th key={c}>
                          <span className="color-dot" style={{ backgroundColor: LULC_COLORS[c] || '#808080' }} />
                          {lulcLabel(c)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {tmClasses.map(from => (
                      <tr key={from}>
                        <td className="row-header">
                          <span className="color-dot" style={{ backgroundColor: LULC_COLORS[from] || '#808080' }} />
                          {lulcLabel(from)}
                        </td>
                        {tmClasses.map(to => {
                          const val = prediction.transition_matrix[from]?.[to] ?? 0;
                          const maxVal = Math.max(
                            ...Object.values(prediction.transition_matrix)
                              .flatMap(v => Object.values(v))
                          );
                          const intensity = maxVal > 0 ? val / maxVal : 0;
                          return (
                            <td
                              key={to}
                              className="matrix-cell"
                              style={{
                                backgroundColor: val > 0
                                  ? `rgba(220, 20, 60, ${intensity * 0.5})`
                                  : 'transparent',
                              }}
                            >
                              {val > 0 ? formatNumber(val) : '—'}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="result-meta">
            {t('worldModel.results.meta', { rows: formatNumber(prediction.grid_shape[0]), columns: formatNumber(prediction.grid_shape[1]), seconds: formatNumber(prediction.elapsed_seconds, { maximumFractionDigits: 2 }) })}
          </div>
        </div>
      )}

      {/* Causal World Model Results (Angle C) */}
      {cfResult && (
        <div className="worldmodel-results">
          <div className="result-summary">{cfResult.summary || t('worldModel.results.analysisComplete')}</div>
          {cfResult.aggregate_effects && (
            <div style={{ background: '#f5f5f5', padding: '8px 12px', borderRadius: '6px', margin: '8px 0', fontSize: '13px' }}>
              <strong>{t('worldModel.results.aggregateEffect')}：</strong>
              {t('worldModel.results.changedPixelShare', { value: formatPercent(cfResult.aggregate_effects.total_changed_pct ?? 0) })}
              {cfResult.aggregate_effects.dominant_change && ` | ${t('worldModel.results.dominantChange')}: ${lulcLabel(cfResult.aggregate_effects.dominant_change)}`}
            </div>
          )}
          {cfResult.per_year_effects && (
            <div className="timeline-section">
              <h4>{t('worldModel.results.yearlyEffects')}</h4>
              <table className="timeline-table">
                <thead>
                  <tr>
                    <th>{t('worldModel.results.year')}</th>
                    <th>{t('worldModel.results.changedPixels')}</th>
                    <th>{t('worldModel.results.changedShare')}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(cfResult.per_year_effects).map(([year, eff]) => (
                    <tr key={year}>
                      <td>{year}</td>
                      <td>{formatNumber((eff as any).changed_pixels)}</td>
                      <td>{formatPercent((eff as any).changed_pct ?? 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {!prediction && !cfResult && !loading && !error && (
        <div className="empty-state">
          <div className="empty-icon">🌍</div>
          <div>{t('worldModel.empty.title')}</div>
          <div className="empty-hint">
            {t('worldModel.empty.description')}
          </div>
        </div>
      )}
    </div>
  );
}
