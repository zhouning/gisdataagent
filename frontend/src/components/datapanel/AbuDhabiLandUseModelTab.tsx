import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Cpu, Layers, LoaderCircle, Play, RefreshCw, ShieldCheck } from 'lucide-react';

import {
  API_BASE,
  SCENARIO_LABELS,
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

function trainingSummary(modelId: AbuDhabiModelId, training: Record<string, unknown>) {
  const seconds = typeof training.fit_seconds === 'number' ? `${training.fit_seconds.toFixed(1)}s` : '-';
  if (modelId === 'geospatial_kernel') return `${training.feature_count ?? '-'} 个特征 · ${formatCount(training.training_pixel_rows as number)} 样本行 · ${seconds}`;
  if (modelId === 'paper58') return `${training.epochs ?? '-'} epochs · ${training.training_patch_count ?? '-'} patches · ${seconds}`;
  const featureNames = Array.isArray(training.feature_names) ? training.feature_names.length : '-';
  return `${featureNames} 个驱动 · ${formatCount(training.training_pixel_rows as number)} 样本行 · ${seconds}`;
}

export default function AbuDhabiLandUseModelTab({ modelId }: Props) {
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
      const response = await fetch(`${API_BASE}/models/${modelId}`, { credentials: 'include' });
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || '模型结果不可用');
      setPayload(data as AbuDhabiModelPayload);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '模型结果不可用');
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
        headers: { 'Content-Type': 'application/json' },
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
        throw new Error(data.error || '地图序列加载失败');
      }
      (window as any).__handleMapUpdate?.(data.map_update);
      setRunMessage(`${completedRun ? '本次运行' : '冻结'}时间序列已加载到地图`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '地图序列加载失败');
    }
  }, [modelId, scenario, seed, track]);

  const executeModel = async () => {
    setError('');
    setRunMessage('正在提交模型运行...');
    try {
      const response = await fetch(`${API_BASE}/runs`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model_id: modelId,
          track,
          seed: executionSeed,
          scenario: track === 'planning' ? scenario : null,
        }),
      });
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || '模型运行提交失败');
      setRun(data as AbuDhabiRun);
      setRunMessage('模型已进入执行队列');
    } catch (requestError) {
      setRunMessage('');
      setError(requestError instanceof Error ? requestError.message : '模型运行提交失败');
    }
  };

  useEffect(() => {
    if (!run || run.status === 'complete' || run.status === 'failed') return;
    let cancelled = false;
    const poll = async () => {
      try {
        const response = await fetch(`${API_BASE}/runs/${run.run_id}`, { credentials: 'include' });
        const data = await response.json() as AbuDhabiRun & { error?: string };
        if (!response.ok || data.error) throw new Error(data.error || '运行状态读取失败');
        if (cancelled) return;
        setRun(data);
        if (data.status === 'complete') {
          setTrack(data.track);
          setSeed(String(data.seed));
          if (data.scenario) setScenario(data.scenario);
          setRunMessage('真实模型运行完成');
          if (autoMappedRun.current !== data.run_id) {
            autoMappedRun.current = data.run_id;
            await sendToMap(data);
          }
        } else if (data.status === 'failed') {
          setRunMessage('');
          setError(data.error || '真实模型运行失败');
        } else {
          setRunMessage(data.status === 'queued' ? '等待执行' : '真实模型执行中');
        }
      } catch (requestError) {
        if (!cancelled) setError(requestError instanceof Error ? requestError.message : '运行状态读取失败');
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

  return (
    <div className="datapanel-section abu-land-use-tab abu-model-tab">
      <header className="abu-header">
        <div>
          <span className="abu-eyebrow">ABU DHABI · FROZEN RUN</span>
          <h3>{payload?.model.label || modelId}</h3>
          <p>{payload?.model.family || '读取模型证据'}</p>
        </div>
        <div className="abu-header-actions">
          {payload && <span className="abu-status pass"><CheckCircle2 size={13} /> 冻结运行完成</span>}
          <button type="button" className="abu-icon-button" onClick={() => void load()} disabled={loading} title="刷新冻结结果"><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
        </div>
      </header>

      {error && <div className="abu-message error"><AlertTriangle size={15} />{error}</div>}
      {loading && !payload && <div className="abu-loading">读取模型结果...</div>}

      {payload && (
        <>
          <section className="abu-model-contract">
            <div><span>状态</span><strong>{payload.model.state}</strong></div>
            <div><span>动作</span><strong>{payload.model.action}</strong></div>
            <div><span>运行时</span><strong>{payload.model.runtime}</strong></div>
            <div><span>状态写回</span><strong>{payload.state_writeback ? '逐年写回' : '不写回'}</strong></div>
          </section>

          <section className="abu-mechanism"><Cpu size={17} /><div><strong>模型机制</strong><p>{payload.model.mechanism}</p></div></section>

          <section className="abu-runtime-panel">
            <div className="abu-runtime-heading">
              <div><Play size={15} /><strong>模型执行</strong></div>
              {run && <span className={`abu-mini-status ${run.status === 'complete' ? 'pass' : ''}`}>{run.status}</span>}
            </div>
            <div className="abu-runtime-controls">
              <label>执行种子<select value={executionSeed} onChange={event => setExecutionSeed(Number(event.target.value))} disabled={isExecuting}>{[31, 47, 73].map(value => <option key={value}>{value}</option>)}</select></label>
              <button type="button" className="abu-command-button primary" onClick={() => void executeModel()} disabled={isExecuting}>
                {isExecuting ? <LoaderCircle size={14} className="spin" /> : <Play size={14} />}
                {isExecuting ? '执行中' : `执行 ${payload.model.label}`}
              </button>
              <button type="button" className="abu-command-button" onClick={() => void sendToMap(matchingRun || undefined)} disabled={isExecuting}>
                <Layers size={14} />加载时间序列到地图
              </button>
            </div>
            {(runMessage || run?.error) && <div className={`abu-run-message ${run?.status === 'failed' ? 'error' : ''}`}>{runMessage || run?.error}</div>}
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
                  <label>情景<select value={scenario} onChange={event => setScenario(event.target.value)}>{payload.options.scenarios.map(id => <option key={id} value={id}>{SCENARIO_LABELS[id] || id}</option>)}</select></label>
                  <label>目标年<select value={planningYear} onChange={event => setPlanningYear(Number(event.target.value))}>{payload.options.planning_years.map(value => <option key={value}>{value}</option>)}</select></label>
                </>
              )}
              <label>结果<select value={seed} onChange={event => setSeed(event.target.value)}><option value="ensemble">三种子集成</option><option value="31">Seed 31</option><option value="47">Seed 47</option><option value="73">Seed 73</option></select></label>
            </div>

            <div className={`abu-model-map-grid ${track === 'historical' ? 'three' : ''}`}>
              <figure className="abu-map-card"><figcaption><strong>起点状态</strong><span>观测 {track === 'historical' ? 2022 : 2024}</span></figcaption><img src={rasterUrl('observed', 'historical', track === 'historical' ? 2022 : 2024)} alt="起点土地覆盖" /></figure>
              {track === 'historical' && <figure className="abu-map-card"><figcaption><strong>目标观测</strong><span>Dynamic World {year}</span></figcaption><img src={rasterUrl('observed', 'historical', year)} alt={`${year} 目标观测`} /></figure>}
              <figure className="abu-map-card"><figcaption><strong>模型结果</strong><span>{matchingRun ? '本次运行 · ' : ''}{track === 'historical' ? `${year} 历史模拟` : `${SCENARIO_LABELS[scenario]} ${year}`}</span></figcaption><img src={resultImageUrl} alt={`${payload.model.label} ${year} 结果`} /></figure>
            </div>
            <div className="abu-legend">{payload.legend.map(item => <span key={item.value}><i style={{ background: item.color }} />{item.label}</span>)}</div>
          </section>

          <section className="abu-kpi-strip model-metrics">
            {track === 'historical' ? (
              <>
                <div><span>Change FoM</span><strong>{formatMetric(historicalMetrics.change_fom)}</strong><small>变化位置交并评价</small></div>
                <div><span>Change F1</span><strong>{formatMetric(historicalMetrics.change_f1)}</strong><small>变化像元识别</small></div>
                <div><span>Macro F1</span><strong>{formatMetric(historicalMetrics.macro_f1)}</strong><small>六类别宏平均</small></div>
                <div className="warning"><span>高置信 FoM</span><strong>{formatMetric(historicalMetrics.high_confidence_change_fom)}</strong><small>标签质量敏感性</small></div>
              </>
            ) : (
              <>
                <div><span>新增建成区</span><strong>{formatCount(planningMetrics?.built_gain_pixels)} px</strong><small>{formatCount((planningMetrics?.built_gain_pixels || 0) / 100)} km²</small></div>
                <div><span>新增绿地</span><strong>{formatCount(planningMetrics?.green_gain_pixels)} px</strong><small>目标年累计</small></div>
                <div><span>邻接既有建成</span><strong>{formatPercent(planningMetrics?.new_built_neighbor_fraction)}</strong><small>空间紧凑代理</small></div>
                <div className={planningMetrics?.pareto ? '' : 'warning'}><span>Pareto 前沿</span><strong>{planningMetrics?.pareto ? '进入' : '未进入'}</strong><small>冻结目标集</small></div>
              </>
            )}
          </section>

          <section className="abu-section">
            <div className="abu-section-title"><Cpu size={15} /><strong>训练与运行证据</strong><span>测试标签未参与拟合</span></div>
            <div className="abu-table-wrap"><table className="abu-table"><thead><tr><th>随机种子</th><th>训练摘要</th></tr></thead><tbody>{payload.training_runs.map(run => <tr key={run.seed}><td>Seed {run.seed}</td><td>{trainingSummary(modelId, run.training)}</td></tr>)}</tbody></table></div>
          </section>

          <section className="abu-boundary">
            <ShieldCheck size={16} />
            <div><strong>模型边界</strong>{payload.model.caveats.map(text => <p key={text}>{text}</p>)}</div>
          </section>
        </>
      )}
    </div>
  );
}
