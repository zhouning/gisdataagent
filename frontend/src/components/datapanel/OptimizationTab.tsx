import { useState, useEffect } from 'react';

interface ScenarioWeights {
  slope: number;
  contiguity: number;
  balance: number;
}

interface Scenario {
  id: string;
  name: string;
  description: string;
  source_types: string[];
  target_types: string[];
  weights: ScenarioWeights;
  max_conversions: number;
}

interface RunResult {
  status?: string;
  error?: string;
  output_path?: string;
  summary?: string;
  result?: string;
  [key: string]: unknown;
}

const DEFAULT_PAIR_BONUS = 1.0;

export default function OptimizationTab() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState('farmland_optimization');
  const [dataPath, setDataPath] = useState('');
  const [slopeWeight, setSlopeWeight] = useState(1000);
  const [contiguityWeight, setContiguityWeight] = useState(500);
  const [balanceWeight, setBalanceWeight] = useState(500);
  const [pairBonus, setPairBonus] = useState(DEFAULT_PAIR_BONUS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<RunResult | null>(null);
  const [explainLoading, setExplainLoading] = useState(false);
  const [explainResult, setExplainResult] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [compareA, setCompareA] = useState<number | null>(null);
  const [compareB, setCompareB] = useState<number | null>(null);
  const [compareResult, setCompareResult] = useState<any>(null);

  useEffect(() => {
    fetch('/api/drl/scenarios', { credentials: 'include' })
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d?.scenarios?.length) {
          setScenarios(d.scenarios);
          applyDefaults(d.scenarios[0]);
        }
      })
      .catch(() => {});
  }, []);

  const applyDefaults = (s: Scenario) => {
    setSlopeWeight(s.weights.slope);
    setContiguityWeight(s.weights.contiguity);
    setBalanceWeight(s.weights.balance);
    setPairBonus(DEFAULT_PAIR_BONUS);
  };

  const handleScenarioChange = (id: string) => {
    setScenarioId(id);
    const s = scenarios.find(sc => sc.id === id);
    if (s) applyDefaults(s);
  };

  const handleReset = () => {
    const s = scenarios.find(sc => sc.id === scenarioId);
    if (s) applyDefaults(s);
  };

  const currentDefaults = scenarios.find(s => s.id === scenarioId);

  const handleRun = async () => {
    if (!dataPath.trim()) { setError('请输入数据文件路径'); return; }
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const resp = await fetch('/api/drl/run-custom', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          data_path: dataPath.trim(),
          scenario_id: scenarioId,
          slope_weight: slopeWeight,
          contiguity_weight: contiguityWeight,
          balance_weight: balanceWeight,
          pair_bonus: pairBonus,
        }),
      });
      const data = await resp.json();
      if (data.error) setError(data.error);
      else setResult(data);
    } catch (e: any) {
      setError(e.message || '请求失败');
    } finally {
      setLoading(false);
    }
  };

  const loadHistory = async () => {
    setHistoryLoading(true);
    try {
      const r = await fetch('/api/drl/history', { credentials: 'include' });
      if (r.ok) { const d = await r.json(); setHistory(d.runs || []); }
    } catch { /* ignore */ }
    finally { setHistoryLoading(false); }
  };

  const doCompare = async () => {
    if (!compareA || !compareB) return;
    try {
      const r = await fetch(`/api/drl/compare?a=${compareA}&b=${compareB}`, { credentials: 'include' });
      if (r.ok) setCompareResult(await r.json());
    } catch { /* ignore */ }
  };

  const sliderRow = (
    label: string, value: number, setter: (v: number) => void,
    min: number, max: number, step: number, defaultVal: number | undefined,
  ) => (
    <div style={{ marginBottom: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '4px' }}>
        <span style={{ color: 'var(--text)' }}>{label}</span>
        <span>
          <strong>{value}</strong>
          {defaultVal !== undefined && (
            <span style={{
              marginLeft: '6px', fontSize: '11px', color: 'var(--text-tertiary)',
              background: 'var(--surface)', padding: '1px 6px', borderRadius: 'var(--radius-sm)',
            }}>
              默认: {defaultVal}
            </span>
          )}
        </span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={e => setter(Number(e.target.value))}
        style={{ width: '100%', accentColor: 'var(--primary)' }}
      />
    </div>
  );

  const summaryText = result?.summary || result?.result || '';

  return (
    <div style={{ padding: '12px 16px', fontSize: '13px', overflowY: 'auto', height: '100%' }}>
      {/* Scenario selector */}
      <div className="config-row" style={{ marginBottom: '10px' }}>
        <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
          优化场景
        </label>
        <select
          value={scenarioId}
          onChange={e => handleScenarioChange(e.target.value)}
          style={{
            width: '100%', padding: '6px 8px', borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border)', fontSize: '13px', background: 'var(--surface-elevated)',
          }}
        >
          {scenarios.map(s => (
            <option key={s.id} value={s.id}>{s.name} ({s.id})</option>
          ))}
        </select>
        {currentDefaults && (
          <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
            {currentDefaults.description}
          </div>
        )}
      </div>

      {/* Data path */}
      <div style={{ marginBottom: '12px' }}>
        <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
          数据文件路径
        </label>
        <input
          type="text" value={dataPath} onChange={e => setDataPath(e.target.value)}
          placeholder="输入数据文件路径，如 uploads/user/data.shp"
          style={{
            width: '100%', padding: '6px 8px', borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border)', fontSize: '13px', background: 'var(--surface-elevated)',
          }}
        />
      </div>

      {/* Weight sliders */}
      <div style={{
        background: 'var(--surface)', padding: '12px', borderRadius: 'var(--radius-md)', marginBottom: '12px',
      }}>
        {sliderRow('坡度权重 (slope_weight)', slopeWeight, setSlopeWeight, 100, 3000, 50, currentDefaults?.weights.slope)}
        {sliderRow('连片权重 (contiguity_weight)', contiguityWeight, setContiguityWeight, 100, 2000, 50, currentDefaults?.weights.contiguity)}
        {sliderRow('平衡权重 (balance_weight)', balanceWeight, setBalanceWeight, 100, 2000, 50, currentDefaults?.weights.balance)}
        {sliderRow('配对奖励 (pair_bonus)', pairBonus, setPairBonus, 0.1, 10.0, 0.1, DEFAULT_PAIR_BONUS)}
      </div>

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
        <button
          onClick={handleReset}
          style={{
            padding: '6px 14px', fontSize: '12px', borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border)', background: 'var(--surface-elevated)',
            cursor: 'pointer', color: 'var(--text-secondary)',
          }}
        >
          重置为默认
        </button>
        <button
          onClick={handleRun} disabled={loading}
          style={{
            flex: 1, padding: '6px 14px', fontSize: '12px', borderRadius: 'var(--radius-sm)',
            border: 'none', background: loading ? 'var(--text-tertiary)' : 'var(--primary)',
            color: '#fff', cursor: loading ? 'not-allowed' : 'pointer',
          }}
        >
          {loading ? '优化计算中...' : '运行优化'}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div style={{
          padding: '8px 12px', borderRadius: 'var(--radius-sm)', marginBottom: '10px',
          background: '#fef2f2', color: '#b91c1c', fontSize: '12px',
        }}>
          {error}
        </div>
      )}

      {/* Results */}
      {result && (
        <div style={{
          background: 'var(--surface)', padding: '12px', borderRadius: 'var(--radius-md)', fontSize: '12px',
        }}>
          {summaryText && <div style={{ marginBottom: '8px', lineHeight: 1.6 }}>{summaryText}</div>}
          {result.output_path && (
            <div style={{ marginBottom: '6px' }}>
              <span style={{ color: 'var(--text-secondary)' }}>输出文件: </span>
              <code style={{
                fontFamily: 'var(--font-mono)', background: 'var(--surface-elevated)',
                padding: '2px 6px', borderRadius: '4px',
              }}>
                {result.output_path}
              </code>
            </div>
          )}
          {result.output_path?.endsWith('.png') && (
            <img
              src={`/uploads/${result.output_path}`}
              alt="优化结果" style={{ width: '100%', borderRadius: 'var(--radius-sm)', marginTop: '6px' }}
            />
          )}
        </div>
      )}

      {/* Explainability section */}
      <div style={{ marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
        <button
          onClick={async () => {
            setExplainLoading(true);
            try {
              const r = await fetch('/api/drl/explain', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ scenario_id: scenarioId }),
              });
              if (r.ok) setExplainResult(await r.json());
            } catch { /* ignore */ }
            finally { setExplainLoading(false); }
          }}
          disabled={explainLoading}
          style={{
            padding: '6px 14px', fontSize: '12px', borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border)', background: 'var(--surface-elevated)',
            cursor: explainLoading ? 'not-allowed' : 'pointer', color: 'var(--text-secondary)',
          }}
        >
          {explainLoading ? '分析中...' : '特征重要性分析'}
        </button>
        {explainResult && explainResult.feature_importance && (
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>特征重要性排名</div>
            {explainResult.feature_importance.slice(0, 6).map((f: any, i: number) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, marginBottom: 4 }}>
                <span style={{ width: 140, color: 'var(--text-secondary)' }}>{f.feature}</span>
                <div style={{ flex: 1, background: 'var(--bg-secondary)', borderRadius: 4, height: 14 }}>
                  <div style={{ width: `${f.importance}%`, background: i < 3 ? 'var(--primary)' : 'var(--text-secondary)', borderRadius: 4, height: '100%' }} />
                </div>
                <span style={{ fontSize: 11, width: 40, textAlign: 'right' }}>{f.importance}%</span>
              </div>
            ))}
            {explainResult.summary && (
              <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 6 }}>{explainResult.summary}</div>
            )}
          </div>
        )}
        {explainResult && explainResult.mode === 'scenario_based' && (
          <div style={{ marginTop: 8, fontSize: 12 }}>
            <div style={{ fontWeight: 600 }}>场景特征分析</div>
            <div style={{ color: 'var(--text-secondary)', marginTop: 4 }}>{explainResult.description}</div>
            <div style={{ marginTop: 4 }}>关键特征: {explainResult.key_features?.join(', ')}</div>
          </div>
        )}
      </div>

      {/* History & Comparison */}
      <div style={{ marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
        <button
          className="btn-secondary btn-sm"
          onClick={() => { setShowHistory(!showHistory); if (!showHistory) loadHistory(); }}
          style={{
            padding: '6px 14px', fontSize: '12px', borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border)', background: 'var(--surface-elevated)',
            cursor: 'pointer', color: 'var(--text-secondary)',
          }}
        >
          {showHistory ? '收起历史' : '运行历史'}
        </button>
        {showHistory && (
          <div style={{ marginTop: 8 }}>
            {historyLoading ? <div style={{ fontSize: 12 }}>加载中...</div> : (
              <>
                {history.length === 0 && <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>暂无历史记录</div>}
                {history.map(run => (
                  <div key={run.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, padding: '4px 0', borderBottom: '1px solid var(--border-light, #eee)' }}>
                    <input type="radio" name="compareA" checked={compareA === run.id} onChange={() => setCompareA(run.id)} />
                    <input type="radio" name="compareB" checked={compareB === run.id} onChange={() => setCompareB(run.id)} />
                    <span style={{ flex: 1 }}>#{run.id} {run.scenario_id} — {run.summary?.slice(0, 40) || '(无摘要)'}</span>
                    <span style={{ color: 'var(--text-secondary)' }}>{run.created_at?.slice(0, 16)}</span>
                  </div>
                ))}
                {compareA && compareB && compareA !== compareB && (
                  <button
                    onClick={doCompare}
                    style={{
                      marginTop: 8, padding: '6px 14px', fontSize: '12px', borderRadius: 'var(--radius-sm)',
                      border: 'none', background: 'var(--primary)', color: '#fff', cursor: 'pointer',
                    }}
                  >
                    对比 #{compareA} vs #{compareB}
                  </button>
                )}
                {compareResult && compareResult.metrics_comparison && (
                  <div style={{ marginTop: 8 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>指标对比</div>
                    <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
                      <thead>
                        <tr style={{ borderBottom: '1px solid var(--border)' }}>
                          <th style={{ textAlign: 'left', padding: '4px' }}>指标</th>
                          <th style={{ textAlign: 'right', padding: '4px' }}>Run A</th>
                          <th style={{ textAlign: 'right', padding: '4px' }}>Run B</th>
                          <th style={{ textAlign: 'right', padding: '4px' }}>差异</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(compareResult.metrics_comparison).map(([key, v]: [string, any]) => (
                          <tr key={key} style={{ borderBottom: '1px solid var(--border-light, #eee)' }}>
                            <td style={{ padding: '3px 4px' }}>{key}</td>
                            <td style={{ textAlign: 'right', padding: '3px 4px' }}>{v.run_a ?? '—'}</td>
                            <td style={{ textAlign: 'right', padding: '3px 4px' }}>{v.run_b ?? '—'}</td>
                            <td style={{ textAlign: 'right', padding: '3px 4px', color: v.delta > 0 ? '#22c55e' : v.delta < 0 ? '#ef4444' : '' }}>
                              {v.delta != null ? (v.delta > 0 ? '+' : '') + v.delta.toFixed(3) : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* Empty state */}
      {!result && !loading && !error && (
        <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--text-tertiary)' }}>
          <div style={{ fontSize: '28px', marginBottom: '8px' }}>⚙</div>
          <div>选择场景、输入数据路径并调整权重后运行优化</div>
          <div style={{ fontSize: '11px', marginTop: '4px' }}>
            DRL 模型将通过强化学习寻找最优的用地空间布局调整方案
          </div>
        </div>
      )}
    </div>
  );
}
