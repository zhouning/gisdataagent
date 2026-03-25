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
