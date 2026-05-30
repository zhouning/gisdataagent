import { useState, useEffect } from 'react';

type V2Mode = 'ppo' | 'dream_v5' | 'mpc';

interface V2ModeInfo {
  model: string;
  checkpoint: string;
  available: boolean;
  typical_slope_improvement_pct: number;
  time_per_episode_s: number;
  slope_improvement_pct_5seed_std?: number;
  slope_improvement_pct_this_ensemble?: number;
}

interface V2Status {
  version: string;
  region: string;
  modes: Record<V2Mode, V2ModeInfo>;
  default_mode: V2Mode;
  supported_actions: string[];
}

interface V2Result {
  status: string;
  error?: string;
  version?: string;
  region?: string;
  mode?: V2Mode;
  model?: string;
  n_episodes?: number;
  best_episode?: number;
  total_reward?: number;
  n_swaps?: number;
  initial_slope?: number;
  final_slope?: number;
  slope_improvement?: number;
  contiguity_improvement?: number;
  geojson_optimized?: string;
  geojson_diff?: string;
}

const MODE_LABELS: Record<V2Mode, string> = {
  ppo: 'PPO (快速, ~1s/回合)',
  dream_v5: 'Dream-v5 (中等, ~4s/回合)',
  mpc: 'Contrastive MPC (高质量, ~18min/回合)',
};

export default function WorldModelV2Tab() {
  const [status, setStatus] = useState<V2Status | null>(null);
  const [result, setResult] = useState<V2Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [nEpisodes, setNEpisodes] = useState(1);
  const [mode, setMode] = useState<V2Mode>('ppo');

  useEffect(() => {
    fetch('/api/world-model-v2/status', { credentials: 'include' })
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d && d.modes) {
          setStatus(d as V2Status);
          if (d.default_mode) setMode(d.default_mode as V2Mode);
        }
      })
      .catch(() => {});
  }, []);

  const currentModeInfo = status?.modes?.[mode];
  const modeAvailable = !!currentModeInfo?.available;

  const handleRun = async () => {
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const resp = await fetch('/api/world-model-v2/run', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ n_episodes: nEpisodes, mode }),
      });
      const data = await resp.json();
      if (data.error) {
        setError(data.error);
      } else {
        setResult(data);
        try {
          const mapResp = await fetch('/api/map/pending', { credentials: 'include' });
          const mapData = await mapResp.json();
          if (mapData.map_update && (window as any).__handleMapUpdate) {
            (window as any).__handleMapUpdate(mapData.map_update);
          }
        } catch { /* map update is best-effort */ }
      }
    } catch (e: any) {
      setError(e.message || '请求失败');
    } finally {
      setLoading(false);
    }
  };

  const pct = (x?: number) => (typeof x === 'number' ? (x * 100).toFixed(2) + '%' : '—');

  return (
    <div className="worldmodel-tab">
      <div className="worldmodel-config">
        <div style={{ marginBottom: '8px', fontSize: '13px', color: '#666' }}>
          基于 Contrastive World Model + Dream/MPC 规划的璧山区耕地布局优化
        </div>

        <div className="worldmodel-status">
          {status ? (
            <span className={`status-badge ${modeAvailable ? 'ready' : 'warning'}`}>
              {modeAvailable ? '模型就绪' : '该模式不可用'}
            </span>
          ) : (
            <span className="status-badge loading">检测中...</span>
          )}
          {status && <span className="param-info">{status.version} · {status.region}</span>}
        </div>

        <div style={{ fontSize: '12px', color: '#999', margin: '6px 0', padding: '6px 8px', background: '#f8f9fa', borderRadius: '4px' }}>
          当前仅支持璧山区内置数据，无需上传文件
        </div>

        <div className="config-row">
          <label>推理模式</label>
          <select
            value={mode}
            onChange={e => setMode(e.target.value as V2Mode)}
            style={{ width: '100%' }}
            disabled={loading || !status}
          >
            {(['ppo', 'dream_v5', 'mpc'] as V2Mode[]).map(m => (
              <option key={m} value={m} disabled={status ? !status.modes?.[m]?.available : false}>
                {MODE_LABELS[m]}
              </option>
            ))}
          </select>
        </div>

        {currentModeInfo && (
          <div style={{ fontSize: '11px', color: '#666', margin: '6px 0', padding: '6px 8px', background: '#f8f9fa', borderRadius: '4px' }}>
            <div>模型: {currentModeInfo.model}</div>
            <div>
              典型坡度改善: {currentModeInfo.typical_slope_improvement_pct?.toFixed(3)}%
              {typeof currentModeInfo.slope_improvement_pct_5seed_std === 'number' &&
                ` ± ${currentModeInfo.slope_improvement_pct_5seed_std.toFixed(3)}% (5 seeds)`}
            </div>
            <div>单回合耗时 ≈ {currentModeInfo.time_per_episode_s}s</div>
          </div>
        )}

        <div className="config-row">
          <label>评估回合数</label>
          <input
            type="number"
            min={1}
            max={50}
            value={nEpisodes}
            onChange={e => setNEpisodes(Math.max(1, Math.min(50, parseInt(e.target.value) || 1)))}
            style={{ width: '60px' }}
          />
        </div>

        <button
          onClick={handleRun}
          disabled={loading || !modeAvailable}
          style={{
            width: '100%', padding: '8px', marginTop: '8px',
            background: loading ? '#ccc' : 'var(--color-primary, #4169E1)',
            color: '#fff', border: 'none', borderRadius: '6px', cursor: loading ? 'wait' : 'pointer',
            fontSize: '13px', fontWeight: 500,
          }}
        >
          {loading ? `${mode} 优化运行中...` : '运行耕地布局优化'}
        </button>

        {loading && mode === 'mpc' && (
          <div style={{ fontSize: '11px', color: '#b45309', marginTop: '6px' }}>
            MPC 模式单回合约 18 分钟，请耐心等待
          </div>
        )}
      </div>

      {error && (
        <div style={{ color: '#dc3545', fontSize: '12px', margin: '8px 0', padding: '6px 8px', background: '#fff5f5', borderRadius: '4px' }}>
          {error}
        </div>
      )}

      {result && (
        <div className="worldmodel-results">
          <h4 style={{ margin: '12px 0 8px', fontSize: '13px' }}>优化结果 ({result.mode})</h4>
          <table style={{ width: '100%', fontSize: '12px', borderCollapse: 'collapse' }}>
            <tbody>
              <tr><td style={{ padding: '4px 8px', color: '#666' }}>状态</td><td style={{ padding: '4px 8px' }}>{result.status}</td></tr>
              <tr><td style={{ padding: '4px 8px', color: '#666' }}>总奖励</td><td style={{ padding: '4px 8px', fontWeight: 600 }}>{result.total_reward?.toFixed(2)}</td></tr>
              <tr><td style={{ padding: '4px 8px', color: '#666' }}>坡度改善 (绝对值)</td><td style={{ padding: '4px 8px', fontWeight: 600, color: (result.slope_improvement ?? 0) > 0 ? '#28a745' : '#dc3545' }}>{result.slope_improvement?.toFixed(4)}</td></tr>
              <tr><td style={{ padding: '4px 8px', color: '#666' }}>坡度改善 (%)</td><td style={{ padding: '4px 8px' }}>{result.initial_slope && result.slope_improvement ? pct(result.slope_improvement / result.initial_slope) : '—'}</td></tr>
              <tr><td style={{ padding: '4px 8px', color: '#666' }}>连片度改善</td><td style={{ padding: '4px 8px' }}>{result.contiguity_improvement?.toFixed(4)}</td></tr>
              <tr><td style={{ padding: '4px 8px', color: '#666' }}>swap 次数</td><td style={{ padding: '4px 8px' }}>{result.n_swaps}</td></tr>
              <tr><td style={{ padding: '4px 8px', color: '#666' }}>最佳回合</td><td style={{ padding: '4px 8px' }}>{(result.best_episode ?? 0) + 1}/{result.n_episodes}</td></tr>
              <tr><td style={{ padding: '4px 8px', color: '#666' }}>初始/最终坡度</td><td style={{ padding: '4px 8px' }}>{result.initial_slope?.toFixed(3)} → {result.final_slope?.toFixed(3)}</td></tr>
            </tbody>
          </table>
          <div style={{ fontSize: '11px', color: '#999', marginTop: '8px' }}>
            优化后布局和变化差异已推送到地图面板
          </div>
        </div>
      )}
    </div>
  );
}
