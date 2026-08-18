import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { formatNumber, getLocaleHeaders } from '../../i18n';

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

export default function WorldModelV2Tab() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<V2Status | null>(null);
  const [result, setResult] = useState<V2Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [nEpisodes, setNEpisodes] = useState(1);
  const [mode, setMode] = useState<V2Mode>('ppo');

  useEffect(() => {
    fetch('/api/world-model-v2/status', { credentials: 'include', headers: getLocaleHeaders() })
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
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ n_episodes: nEpisodes, mode }),
      });
      const data = await resp.json();
      if (data.error) {
        setError(data.error);
      } else {
        setResult(data);
        try {
          const mapResp = await fetch('/api/map/pending', { credentials: 'include', headers: getLocaleHeaders() });
          const mapData = await mapResp.json();
          if (mapData.map_update && (window as any).__handleMapUpdate) {
            (window as any).__handleMapUpdate(mapData.map_update);
          }
        } catch { /* map update is best-effort */ }
      }
    } catch (e: any) {
      setError(e.message || t('worldModelV2.errors.requestFailed'));
    } finally {
      setLoading(false);
    }
  };

  const pct = (x?: number) => (typeof x === 'number' ? `${formatNumber(x * 100, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%` : '—');
  const number = (x?: number, maximumFractionDigits = 3) => typeof x === 'number' ? formatNumber(x, { maximumFractionDigits }) : '—';
  const resultStatus = (value: string) => t(`statusLabels.${value}`, { defaultValue: value });

  return (
    <div className="worldmodel-tab">
      <div className="worldmodel-config">
        <div style={{ marginBottom: '8px', fontSize: '13px', color: '#666' }}>
          {t('worldModelV2.description')}
        </div>

        <div className="worldmodel-status">
          {status ? (
            <span className={`status-badge ${modeAvailable ? 'ready' : 'warning'}`}>
              {modeAvailable ? t('worldModelV2.status.ready') : t('worldModelV2.status.unavailable')}
            </span>
          ) : (
            <span className="status-badge loading">{t('worldModelV2.status.checking')}</span>
          )}
          {status && <span className="param-info">{status.version} · {status.region}</span>}
        </div>

        <div style={{ fontSize: '12px', color: '#999', margin: '6px 0', padding: '6px 8px', background: '#f8f9fa', borderRadius: '4px' }}>
          {t('worldModelV2.builtInData')}
        </div>

        <div className="config-row">
          <label>{t('worldModelV2.controls.mode')}</label>
          <select
            value={mode}
            onChange={e => setMode(e.target.value as V2Mode)}
            style={{ width: '100%' }}
            disabled={loading || !status}
          >
            {(['ppo', 'dream_v5', 'mpc'] as V2Mode[]).map(m => (
              <option key={m} value={m} disabled={status ? !status.modes?.[m]?.available : false}>
                {t(`worldModelV2.modes.${m}`)}
              </option>
            ))}
          </select>
        </div>

        {currentModeInfo && (
          <div style={{ fontSize: '11px', color: '#666', margin: '6px 0', padding: '6px 8px', background: '#f8f9fa', borderRadius: '4px' }}>
            <div>{t('worldModelV2.details.model')}: {currentModeInfo.model}</div>
            <div>
              {t('worldModelV2.details.typicalSlope')}: {number(currentModeInfo.typical_slope_improvement_pct, 3)}%
              {typeof currentModeInfo.slope_improvement_pct_5seed_std === 'number' &&
                ` ± ${number(currentModeInfo.slope_improvement_pct_5seed_std, 3)}% (${t('worldModelV2.details.seeds', { count: 5 })})`}
            </div>
            <div>{t('worldModelV2.details.timePerEpisode')} ≈ {number(currentModeInfo.time_per_episode_s, 1)}s</div>
          </div>
        )}

        <div className="config-row">
          <label>{t('worldModelV2.controls.episodes')}</label>
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
          {loading ? t('worldModelV2.actions.running', { mode: t(`worldModelV2.modeNames.${mode}`) }) : t('worldModelV2.actions.run')}
        </button>

        {loading && mode === 'mpc' && (
          <div style={{ fontSize: '11px', color: '#b45309', marginTop: '6px' }}>
            {t('worldModelV2.mpcNotice')}
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
          <h4 style={{ margin: '12px 0 8px', fontSize: '13px' }}>{t('worldModelV2.results.title')} ({result.mode})</h4>
          <table style={{ width: '100%', fontSize: '12px', borderCollapse: 'collapse' }}>
            <tbody>
              <tr><td style={{ padding: '4px 8px', color: '#666' }}>{t('worldModelV2.results.status')}</td><td style={{ padding: '4px 8px' }}>{resultStatus(result.status)}</td></tr>
              <tr><td style={{ padding: '4px 8px', color: '#666' }}>{t('worldModelV2.results.reward')}</td><td style={{ padding: '4px 8px', fontWeight: 600 }}>{number(result.total_reward, 2)}</td></tr>
              <tr><td style={{ padding: '4px 8px', color: '#666' }}>{t('worldModelV2.results.slopeImprovement')}</td><td style={{ padding: '4px 8px', fontWeight: 600, color: (result.slope_improvement ?? 0) > 0 ? '#28a745' : '#dc3545' }}>{number(result.slope_improvement, 4)}</td></tr>
              <tr><td style={{ padding: '4px 8px', color: '#666' }}>{t('worldModelV2.results.slopeImprovementPct')}</td><td style={{ padding: '4px 8px' }}>{result.initial_slope && result.slope_improvement ? pct(result.slope_improvement / result.initial_slope) : '—'}</td></tr>
              <tr><td style={{ padding: '4px 8px', color: '#666' }}>{t('worldModelV2.results.contiguity')}</td><td style={{ padding: '4px 8px' }}>{number(result.contiguity_improvement, 4)}</td></tr>
              <tr><td style={{ padding: '4px 8px', color: '#666' }}>{t('worldModelV2.results.swaps')}</td><td style={{ padding: '4px 8px' }}>{number(result.n_swaps, 0)}</td></tr>
              <tr><td style={{ padding: '4px 8px', color: '#666' }}>{t('worldModelV2.results.bestEpisode')}</td><td style={{ padding: '4px 8px' }}>{number((result.best_episode ?? 0) + 1, 0)}/{number(result.n_episodes, 0)}</td></tr>
              <tr><td style={{ padding: '4px 8px', color: '#666' }}>{t('worldModelV2.results.slopeRange')}</td><td style={{ padding: '4px 8px' }}>{number(result.initial_slope)} → {number(result.final_slope)}</td></tr>
            </tbody>
          </table>
          <div style={{ fontSize: '11px', color: '#999', marginTop: '8px' }}>
            {t('worldModelV2.results.mapUpdated')}
          </div>
        </div>
      )}
    </div>
  );
}
