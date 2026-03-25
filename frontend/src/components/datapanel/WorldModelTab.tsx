import { useState, useEffect } from 'react';

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
  '水体': '#4169E1',
  '树木': '#228B22',
  '草地': '#90EE90',
  '灌木': '#DEB887',
  '耕地': '#FFD700',
  '建设用地': '#DC143C',
  '裸地': '#D2B48C',
  '冰雪': '#FFFFFF',
  '湿地': '#20B2AA',
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
    fetch('/api/world-model/status', { credentials: 'include' })
      .then(r => r.ok ? r.json() : null)
      .then(d => d && setStatus(d))
      .catch(() => {});
    fetch('/api/world-model/scenarios', { credentials: 'include' })
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
        setError('bbox 格式错误，应为 minx,miny,maxx,maxy');
        return;
      }
      const resp = await fetch('/api/world-model/predict', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
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
          const mapResp = await fetch('/api/map/pending', { credentials: 'include' });
          const mapData = await mapResp.json();
          if (mapData.map_update && (window as any).__handleMapUpdate) {
            (window as any).__handleMapUpdate(mapData.map_update);
          }
        } catch { /* map update is best-effort */ }
      }
    } catch (e: any) {
      setError(e.message || 'Request failed');
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
        headers: { 'Content-Type': 'application/json' },
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
      setError(e.message || 'Request failed');
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
        headers: { 'Content-Type': 'application/json' },
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
      setError(e.message || 'Request failed');
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
              {m === 'predict' ? '预测' : m === 'intervene' ? '干预' : '反事实'}
            </button>
          ))}
        </div>

        <div className="worldmodel-status">
          {status ? (
            <span className={`status-badge ${status.weights_exist && status.gee_available ? 'ready' : 'warning'}`}>
              {status.weights_exist && status.gee_available ? '就绪' : status.gee_available ? '需训练' : 'GEE 不可用'}
            </span>
          ) : (
            <span className="status-badge loading">检测中...</span>
          )}
          {status?.param_count ? <span className="param-info">{(status.param_count / 1000).toFixed(1)}K params</span> : null}
        </div>

        <div className="config-row">
          <label>区域 (bbox)</label>
          <input
            type="text"
            value={bbox}
            onChange={e => setBbox(e.target.value)}
            placeholder="minx,miny,maxx,maxy"
          />
        </div>

        <div className="config-row">
          <label>情景</label>
          <select value={selectedScenario} onChange={e => setSelectedScenario(e.target.value)}>
            {scenarios.map(s => (
              <option key={s.id} value={s.id}>
                {s.name_zh} ({s.id})
              </option>
            ))}
          </select>
        </div>
        {scenarios.find(s => s.id === selectedScenario)?.description && (
          <div className="scenario-desc">
            {scenarios.find(s => s.id === selectedScenario)?.description}
          </div>
        )}

        <div className="config-row-group">
          <div className="config-row">
            <label>起始年份</label>
            <input
              type="number"
              min={2017}
              max={2024}
              value={startYear}
              onChange={e => setStartYear(Number(e.target.value))}
            />
          </div>
          <div className="config-row">
            <label>预测年数</label>
            <input
              type="range"
              min={1}
              max={10}
              value={nYears}
              onChange={e => setNYears(Number(e.target.value))}
            />
            <span className="range-label">{nYears} 年</span>
          </div>
        </div>

        {/* Mode-specific inputs */}
        {mode === 'intervene' && (
          <>
            <div className="config-row">
              <label>干预子区域</label>
              <input
                type="text"
                value={interventionSubBbox}
                onChange={e => setInterventionSubBbox(e.target.value)}
                placeholder="minx,miny,maxx,maxy (须在主区域内)"
              />
            </div>
            <div className="config-row">
              <label>干预类型</label>
              <select value={interventionType} onChange={e => setInterventionType(e.target.value)}>
                {scenarios.map(s => (
                  <option key={s.id} value={s.id}>{s.name_zh}</option>
                ))}
              </select>
            </div>
          </>
        )}
        {mode === 'counterfactual' && (
          <div className="config-row">
            <label>对照情景 (B)</label>
            <select value={scenarioB} onChange={e => setScenarioB(e.target.value)}>
              {scenarios.map(s => (
                <option key={s.id} value={s.id}>{s.name_zh}</option>
              ))}
            </select>
          </div>
        )}

        <button
          className="predict-btn"
          onClick={mode === 'predict' ? handlePredict : mode === 'intervene' ? handleIntervene : handleCounterfactual}
          disabled={loading}
        >
          {loading ? '计算中...' : mode === 'predict' ? '运行预测' : mode === 'intervene' ? '运行干预分析' : '运行反事实对比'}
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
              <h4>面积分布变化趋势</h4>
              <div className="timeline-chart">
                <table className="timeline-table">
                  <thead>
                    <tr>
                      <th>类别</th>
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
                          {s.name}
                        </td>
                        {s.data.map((v, i) => (
                          <td key={i} className="pct-cell">
                            {v.toFixed(1)}%
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
                            title={`${s.name}: ${s.data[yi].toFixed(1)}%`}
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
                转移矩阵 ({prediction.start_year} → {prediction.years[prediction.years.length - 1]})
              </h4>
              <div className="transition-matrix">
                <table>
                  <thead>
                    <tr>
                      <th>From ↓ / To →</th>
                      {tmClasses.map(c => (
                        <th key={c}>
                          <span className="color-dot" style={{ backgroundColor: LULC_COLORS[c] || '#808080' }} />
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {tmClasses.map(from => (
                      <tr key={from}>
                        <td className="row-header">
                          <span className="color-dot" style={{ backgroundColor: LULC_COLORS[from] || '#808080' }} />
                          {from}
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
                              {val > 0 ? val : '—'}
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
            网格: {prediction.grid_shape[0]}×{prediction.grid_shape[1]} | 耗时: {prediction.elapsed_seconds}s
          </div>
        </div>
      )}

      {/* Causal World Model Results (Angle C) */}
      {cfResult && (
        <div className="worldmodel-results">
          <div className="result-summary">{cfResult.summary || '分析完成'}</div>
          {cfResult.aggregate_effects && (
            <div style={{ background: '#f5f5f5', padding: '8px 12px', borderRadius: '6px', margin: '8px 0', fontSize: '13px' }}>
              <strong>总体效应：</strong>
              变化像素占比 {cfResult.aggregate_effects.total_changed_pct?.toFixed(1)}%
              {cfResult.aggregate_effects.dominant_change && ` | 主要变化: ${cfResult.aggregate_effects.dominant_change}`}
            </div>
          )}
          {cfResult.per_year_effects && (
            <div className="timeline-section">
              <h4>逐年效应</h4>
              <table className="timeline-table">
                <thead>
                  <tr>
                    <th>年份</th>
                    <th>变化像素</th>
                    <th>变化比例</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(cfResult.per_year_effects).map(([year, eff]) => (
                    <tr key={year}>
                      <td>{year}</td>
                      <td>{(eff as any).changed_pixels}</td>
                      <td>{((eff as any).changed_pct ?? 0).toFixed(1)}%</td>
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
          <div>配置参数后点击"运行预测"</div>
          <div className="empty-hint">
            世界模型将预测指定区域在不同政策情景下的土地利用变化趋势
          </div>
        </div>
      )}
    </div>
  );
}
