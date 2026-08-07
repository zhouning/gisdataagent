import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, BarChart3, CheckCircle2, Database, RefreshCw, ShieldCheck } from 'lucide-react';

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
      const response = await fetch(`${API_BASE}/overview`, { credentials: 'include' });
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || '阿布扎比实验结果不可用');
      setPayload(data as AbuDhabiOverview);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '阿布扎比实验结果不可用');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const models = useMemo(() => {
    const byId = new Map((payload?.models || []).map(model => [model.id, model]));
    return MODEL_IDS.map(id => byId.get(id)).filter((model): model is NonNullable<typeof model> => Boolean(model));
  }, [payload]);

  const selectedYear = track === 'historical' ? historicalYear : planningYear;

  return (
    <div className="datapanel-section abu-land-use-tab">
      <header className="abu-header">
        <div>
          <span className="abu-eyebrow">ABU DHABI LAND-COVER BENCHMARK</span>
          <h3>阿布扎比三模型对比</h3>
          <p>统一边界、网格、状态、需求动作、硬约束与评价器</p>
        </div>
        <div className="abu-header-actions">
          {payload && (
            <span className={`abu-status ${payload.output_audit.status === 'PASS' ? 'pass' : 'warning'}`}>
              <CheckCircle2 size={13} /> {payload.output_audit.prediction_count} 张栅格通过审计
            </span>
          )}
          <button type="button" className="abu-icon-button" onClick={() => void load()} disabled={loading} title="刷新冻结结果">
            <RefreshCw size={15} className={loading ? 'spin' : ''} />
          </button>
        </div>
      </header>

      {error && <div className="abu-message error"><AlertTriangle size={15} />{error}</div>}
      {loading && !payload && <div className="abu-loading">读取冻结实验结果...</div>}

      {payload && (
        <>
          <section className="abu-kpi-strip">
            <div><span>空间范围</span><strong>{payload.scope.area_km2.toFixed(2)} km²</strong><small>OSM 阿布扎比城市边界</small></div>
            <div><span>统一网格</span><strong>{payload.scope.resolution_m} m</strong><small>{payload.scope.width} x {payload.scope.height} · {payload.scope.crs}</small></div>
            <div><span>共同有效像元</span><strong>{formatCount(payload.scope.valid_pixels)}</strong><small>2017-2024 连续覆盖</small></div>
            <div className="warning"><span>低置信度标签</span><strong>{formatPercent(payload.data_quality.mean_low_confidence_fraction, 1)}</strong><small>Dynamic World 年度均值</small></div>
          </section>

          <section className="abu-section">
            <div className="abu-section-title"><Database size={15} /><strong>冻结输入</strong><span>{payload.input_sources.length} 类数据源</span></div>
            <div className="abu-input-layout">
              <div className="abu-table-wrap">
                <table className="abu-table">
                  <thead><tr><th>数据</th><th>来源</th><th>时期</th><th>模型作用</th></tr></thead>
                  <tbody>{payload.input_sources.map(source => (
                    <tr key={source.name}><td>{source.name}</td><td>{source.source}</td><td>{source.years}</td><td>{source.role}</td></tr>
                  ))}</tbody>
                </table>
              </div>
              <img className="abu-context-figure" src={figureUrl('land_cover_overview')} alt="阿布扎比年度土地覆盖输入概览" />
            </div>
          </section>

          <section className="abu-section">
            <div className="abu-toolbar">
              <div className="abu-segmented" aria-label="实验轨道">
                <button type="button" className={track === 'historical' ? 'active' : ''} onClick={() => setTrack('historical')}>历史回测</button>
                <button type="button" className={track === 'planning' ? 'active' : ''} onClick={() => setTrack('planning')}>规划情景</button>
              </div>
              {track === 'historical' ? (
                <label>目标年<select value={historicalYear} onChange={event => setHistoricalYear(Number(event.target.value))}><option value={2023}>2023 单步</option><option value={2024}>2024 两步开环</option></select></label>
              ) : (
                <>
                  <label>情景<select value={scenario} onChange={event => setScenario(event.target.value)}>{Object.entries(SCENARIO_LABELS).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
                  <label>目标年<select value={planningYear} onChange={event => setPlanningYear(Number(event.target.value))}>{[2025, 2026, 2027, 2028, 2029, 2030].map(year => <option key={year}>{year}</option>)}</select></label>
                </>
              )}
              <label>结果<select value={seed} onChange={event => setSeed(event.target.value)}><option value="ensemble">三种子集成</option><option value="31">Seed 31</option><option value="47">Seed 47</option><option value="73">Seed 73</option></select></label>
            </div>

            <div className={`abu-map-grid ${track === 'historical' ? 'with-observed' : ''}`}>
              {track === 'historical' && (
                <figure className="abu-map-card">
                  <figcaption><strong>实际观测</strong><span>Dynamic World {selectedYear}</span></figcaption>
                  <img src={rasterUrl('observed', 'historical', selectedYear)} alt={`${selectedYear} 年实际土地覆盖`} />
                </figure>
              )}
              {MODEL_IDS.map(modelId => (
                <figure className="abu-map-card" key={`${modelId}-${track}-${selectedYear}-${scenario}-${seed}`}>
                  <figcaption><strong>{MODEL_LABELS[modelId]}</strong><span>{track === 'historical' ? `${selectedYear} 历史模拟` : `${SCENARIO_LABELS[scenario]} ${selectedYear}`}</span></figcaption>
                  <img src={rasterUrl(modelId, track, selectedYear, seed, track === 'planning' ? scenario : undefined)} alt={`${MODEL_LABELS[modelId]} ${selectedYear} 结果`} />
                </figure>
              ))}
            </div>

            <div className="abu-legend">{payload.legend.map(item => <span key={item.value}><i style={{ background: item.color }} />{item.label}</span>)}</div>
          </section>

          <section className="abu-section">
            <div className="abu-section-title"><BarChart3 size={15} /><strong>{track === 'historical' ? `${historicalYear} 历史指标` : `${SCENARIO_LABELS[scenario]} ${planningYear} 规划指标`}</strong></div>
            <div className="abu-table-wrap">
              {track === 'historical' ? (
                <table className="abu-table metrics">
                  <thead><tr><th>模型</th><th>Change FoM</th><th>Change F1</th><th>Macro F1</th><th>总体精度</th><th>高置信 FoM</th><th>需求误差</th></tr></thead>
                  <tbody>{models.map(model => {
                    const metrics = model.historical?.[String(historicalYear)] || {};
                    return <tr key={model.id}><td><strong>{model.label}</strong></td><td>{formatMetric(metrics.change_fom)}</td><td>{formatMetric(metrics.change_f1)}</td><td>{formatMetric(metrics.macro_f1)}</td><td>{formatMetric(metrics.overall_accuracy)}</td><td>{formatMetric(metrics.high_confidence_change_fom)}</td><td>{formatPercent(metrics.demand_total_variation)}</td></tr>;
                  })}</tbody>
                </table>
              ) : (
                <table className="abu-table metrics">
                  <thead><tr><th>模型</th><th>新增建成</th><th>新增绿地</th><th>退出建成</th><th>邻接既有建成</th><th>生态转换率</th><th>Pareto</th></tr></thead>
                  <tbody>{models.map(model => {
                    const row = model.planning?.find(candidate => candidate.scenario_id === scenario);
                    const pareto = model.pareto_scenarios?.includes(scenario);
                    return <tr key={model.id}><td><strong>{model.label}</strong></td><td>{formatCount(row?.built_gain_pixels)} px</td><td>{formatCount(row?.green_gain_pixels)} px</td><td>{formatCount(row?.removed_built_pixels)} px</td><td>{formatPercent(row?.new_built_neighbor_fraction)}</td><td>{formatPercent(row?.ecological_conversion_rate)}</td><td><span className={`abu-mini-status ${pareto ? 'pass' : ''}`}>{pareto ? '是' : '否'}</span></td></tr>;
                  })}</tbody>
                </table>
              )}
            </div>
          </section>

          <section className="abu-boundary">
            <ShieldCheck size={16} />
            <div><strong>结论边界</strong><p>历史结果衡量给定目标总量时的空间分配能力；规划需求是压力测试，不是阿布扎比真实政策预测。所有模型的高置信度变化 FoM 仍然很低。</p></div>
          </section>
        </>
      )}
    </div>
  );
}
