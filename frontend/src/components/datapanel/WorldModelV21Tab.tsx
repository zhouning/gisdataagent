import { useEffect, useMemo, useState } from 'react';
import { Play, RefreshCw } from 'lucide-react';

type EnvKind = 'county' | 'restoration';
type Continuation = 'random' | 'greedy';
type Scoring = 'reward' | 'slope';

interface V21Status {
  status: 'ready' | 'unavailable';
  version: string;
  paper9: {
    repo_path: string;
    repo_exists: boolean;
    remote?: string | null;
    commit?: string | null;
    commit_date?: string | null;
    package_version?: string | null;
    importable: boolean;
    error?: string | null;
  };
  defaults: {
    prepared_dir: string;
    ensemble_dir: string;
    out_dir_policy?: string;
  };
  capabilities: Record<string, boolean>;
  onnx_member_count?: number;
}

interface V21Result {
  status: string;
  version: string;
  source: string;
  mode: string;
  env_kind: EnvKind;
  prepared_dir: string;
  ensemble_dir: string;
  out_dir: string;
  summary: Record<string, number | string | null | undefined>;
  artifacts: Record<string, string | null>;
  map_update_queued: boolean;
  warnings?: string[];
}

const DEFAULT_FORM = {
  prepared_dir: '',
  ensemble_dir: '',
  env_kind: 'county' as EnvKind,
  horizon: 5,
  top_k: 50,
  n_episodes: 1,
  continuation: 'random' as Continuation,
  scoring: 'reward' as Scoring,
  threads: 0,
  seed_offset: 0,
  proj_crs: '',
  cultivated_area_floor_delta_ha: '',
  baimu_area_floor_delta_ha: '',
  gamma_conn: '',
  delta_conn: '',
};

type V21Form = typeof DEFAULT_FORM;

const metricLabels: Record<string, string> = {
  total_reward: '总奖励',
  steps_run: '执行步数',
  swaps_completed: '完成 swap',
  n_selected: '选中单元',
  budget_used: '预算使用',
  budget_fraction_used: '预算比例',
  slope_change_pct: '坡度变化',
  cont_change: '连片度变化',
  baimu_area_change_ha: '百亩方面积变化',
  n_blocks: '块数量',
  n_parcels: '地块/单元数',
  max_steps: '最大步数',
  ensemble_members: 'ONNX 成员',
};

function optionalNumber(value: string): number | null {
  const trimmed = value.trim();
  return trimmed === '' ? null : Number(trimmed);
}

function formatValue(value: number | string | null | undefined, suffix = '') {
  if (value === null || typeof value === 'undefined') return '-';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '-';
    const formatted = Math.abs(value) >= 100
      ? value.toFixed(1)
      : Math.abs(value) >= 10
        ? value.toFixed(2)
        : value.toFixed(4);
    return `${formatted}${suffix}`;
  }
  return value || '-';
}

export default function WorldModelV21Tab() {
  const [status, setStatus] = useState<V21Status | null>(null);
  const [form, setForm] = useState<V21Form>(DEFAULT_FORM);
  const [result, setResult] = useState<V21Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [statusLoading, setStatusLoading] = useState(false);
  const [error, setError] = useState('');

  const ready = status?.status === 'ready';
  const canRun = useMemo(
    () => ready && form.prepared_dir.trim() !== '' && form.ensemble_dir.trim() !== '' && !loading,
    [ready, form.prepared_dir, form.ensemble_dir, loading],
  );

  const updateForm = <K extends keyof V21Form>(key: K, value: V21Form[K]) => {
    setForm(prev => ({ ...prev, [key]: value }));
  };

  const loadStatus = async () => {
    setStatusLoading(true);
    setError('');
    try {
      const resp = await fetch('/api/world-model-v21/status', { credentials: 'include' });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        setError(data.error || '状态检查失败');
        return;
      }
      setStatus(data as V21Status);
      setForm(prev => ({
        ...prev,
        prepared_dir: prev.prepared_dir || data.defaults?.prepared_dir || '',
        ensemble_dir: prev.ensemble_dir || data.defaults?.ensemble_dir || '',
      }));
    } catch (e: any) {
      setError(e.message || '状态检查失败');
    } finally {
      setStatusLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const requestBody = () => ({
    prepared_dir: form.prepared_dir.trim(),
    ensemble_dir: form.ensemble_dir.trim(),
    env_kind: form.env_kind,
    horizon: form.horizon,
    top_k: form.top_k,
    n_episodes: form.n_episodes,
    continuation: form.continuation,
    scoring: form.scoring,
    threads: form.threads,
    seed_offset: form.seed_offset,
    proj_crs: form.proj_crs.trim() || null,
    cultivated_area_floor_delta_ha: optionalNumber(form.cultivated_area_floor_delta_ha),
    baimu_area_floor_delta_ha: optionalNumber(form.baimu_area_floor_delta_ha),
    gamma_conn: optionalNumber(form.gamma_conn),
    delta_conn: optionalNumber(form.delta_conn),
  });

  const runPlan = async () => {
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const resp = await fetch('/api/world-model-v21/plan', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody()),
      });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        setError(data.error || '规划运行失败');
        return;
      }
      setResult(data as V21Result);
      try {
        const mapResp = await fetch('/api/map/pending', { credentials: 'include' });
        const mapData = await mapResp.json();
        if (mapData.map_update && (window as any).__handleMapUpdate) {
          (window as any).__handleMapUpdate(mapData.map_update);
        }
      } catch {
        // Map handoff is best-effort; the result panel still shows artifacts.
      }
    } catch (e: any) {
      setError(e.message || '规划运行失败');
    } finally {
      setLoading(false);
    }
  };

  const statusClass = ready ? 'success' : status ? 'warning' : 'warning';
  const commit = status?.paper9?.commit ? status.paper9.commit.slice(0, 12) : '-';
  const metrics = result ? [
    'total_reward',
    'steps_run',
    result.env_kind === 'restoration' ? 'n_selected' : 'swaps_completed',
    'budget_used',
    'budget_fraction_used',
    'slope_change_pct',
    'cont_change',
    'baimu_area_change_ha',
    'n_blocks',
    'max_steps',
    'ensemble_members',
  ] : [];

  return (
    <div className="worldmodel-tab worldmodel-v21-panel">
      <div className="worldmodel-config">
        <div className="worldmodel-v21-toolbar" style={{ marginBottom: 8 }}>
          <span className={`status-badge ${statusClass}`}>
            {statusLoading ? '检测中' : ready ? 'Paper9 就绪' : '未就绪'}
          </span>
          <button
            type="button"
            onClick={loadStatus}
            disabled={statusLoading || loading}
            title="刷新状态"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              padding: '3px 8px',
              borderRadius: 4,
              border: '1px solid var(--border)',
              background: 'var(--bg)',
              color: 'var(--text-secondary)',
              cursor: statusLoading || loading ? 'default' : 'pointer',
              fontSize: 11,
            }}
          >
            <RefreshCw size={12} />
            刷新
          </button>
          <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
            v{status?.version || '2.1.0'} / Paper9 {status?.paper9?.package_version || '-'}
          </span>
        </div>

        {status && (
          <div style={{ marginBottom: 10, padding: '6px 8px', border: '1px solid var(--border)', borderRadius: 4 }}>
            <div className="worldmodel-v21-path">{status.paper9.repo_path}</div>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 4, fontSize: 11, color: 'var(--text-secondary)' }}>
              <span>commit: {commit}</span>
              <span>ONNX: {status.onnx_member_count ?? 0}</span>
              <span>{status.paper9.remote || '-'}</span>
            </div>
            {!ready && (
              <div style={{ marginTop: 4, color: 'var(--danger)', fontSize: 11 }}>
                {status.paper9.error || 'Paper9 仓库或依赖不可用'}
              </div>
            )}
          </div>
        )}

        <div className="config-row">
          <label>prepared_dir</label>
          <input
            type="text"
            value={form.prepared_dir}
            onChange={e => updateForm('prepared_dir', e.target.value)}
            placeholder="D:\\test\\_publish\\arcgis-farmland-mpc\\runs\\..."
            disabled={loading}
          />
        </div>
        <div className="config-row">
          <label>ensemble_dir</label>
          <input
            type="text"
            value={form.ensemble_dir}
            onChange={e => updateForm('ensemble_dir', e.target.value)}
            placeholder="...\\paper\\checkpoints\\...\\ensemble_seed0"
            disabled={loading}
          />
        </div>

        <div className="worldmodel-v21-grid">
          <div className="config-row">
            <label>env</label>
            <select
              value={form.env_kind}
              onChange={e => updateForm('env_kind', e.target.value as EnvKind)}
              disabled={loading}
            >
              <option value="county">county</option>
              <option value="restoration">restoration</option>
            </select>
          </div>
          <div className="config-row">
            <label>CRS</label>
            <input
              type="text"
              value={form.proj_crs}
              onChange={e => updateForm('proj_crs', e.target.value)}
              placeholder="EPSG:32648"
              disabled={loading}
            />
          </div>
          <div className="config-row">
            <label>horizon</label>
            <input
              type="number"
              min={1}
              max={20}
              value={form.horizon}
              onChange={e => updateForm('horizon', Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
              disabled={loading}
            />
          </div>
          <div className="config-row">
            <label>top_k</label>
            <input
              type="number"
              min={1}
              max={500}
              value={form.top_k}
              onChange={e => updateForm('top_k', Math.max(1, Math.min(500, Number(e.target.value) || 1)))}
              disabled={loading}
            />
          </div>
          <div className="config-row">
            <label>episodes</label>
            <input
              type="number"
              min={1}
              max={20}
              value={form.n_episodes}
              onChange={e => updateForm('n_episodes', Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
              disabled={loading}
            />
          </div>
          <div className="config-row">
            <label>threads</label>
            <input
              type="number"
              min={0}
              max={64}
              value={form.threads}
              onChange={e => updateForm('threads', Math.max(0, Math.min(64, Number(e.target.value) || 0)))}
              disabled={loading}
            />
          </div>
          <div className="config-row">
            <label>continuation</label>
            <select
              value={form.continuation}
              onChange={e => updateForm('continuation', e.target.value as Continuation)}
              disabled={loading}
            >
              <option value="random">random</option>
              <option value="greedy">greedy</option>
            </select>
          </div>
          <div className="config-row">
            <label>scoring</label>
            <select
              value={form.scoring}
              onChange={e => updateForm('scoring', e.target.value as Scoring)}
              disabled={loading}
            >
              <option value="reward">reward</option>
              <option value="slope">slope</option>
            </select>
          </div>
        </div>

        <div className="worldmodel-v21-grid" style={{ marginTop: 8 }}>
          <div className="config-row">
            <label>耕地面积下限 delta(ha)</label>
            <input
              type="number"
              value={form.cultivated_area_floor_delta_ha}
              onChange={e => updateForm('cultivated_area_floor_delta_ha', e.target.value)}
              disabled={loading}
            />
          </div>
          <div className="config-row">
            <label>百亩方面积下限 delta(ha)</label>
            <input
              type="number"
              value={form.baimu_area_floor_delta_ha}
              onChange={e => updateForm('baimu_area_floor_delta_ha', e.target.value)}
              disabled={loading}
            />
          </div>
          <div className="config-row">
            <label>gamma_conn</label>
            <input
              type="number"
              value={form.gamma_conn}
              onChange={e => updateForm('gamma_conn', e.target.value)}
              disabled={loading}
            />
          </div>
          <div className="config-row">
            <label>delta_conn</label>
            <input
              type="number"
              value={form.delta_conn}
              onChange={e => updateForm('delta_conn', e.target.value)}
              disabled={loading}
            />
          </div>
        </div>

        <button
          type="button"
          onClick={runPlan}
          disabled={!canRun}
          style={{
            width: '100%',
            marginTop: 10,
            padding: '8px 10px',
            border: 'none',
            borderRadius: 6,
            background: canRun ? 'var(--primary)' : 'var(--border)',
            color: '#fff',
            cursor: canRun ? 'pointer' : 'default',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 6,
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          <Play size={14} />
          {loading ? '规划运行中...' : '运行 Paper9 Tool 4'}
        </button>

        {error && (
          <div style={{ marginTop: 8, padding: '6px 8px', borderRadius: 4, color: 'var(--danger)', background: 'var(--danger-light)', fontSize: 12, overflowWrap: 'anywhere' }}>
            {error}
          </div>
        )}
      </div>

      {result && (
        <div className="worldmodel-results">
          <h4 style={{ margin: '4px 0 8px', fontSize: 13 }}>规划结果 ({result.env_kind})</h4>
          <div className="worldmodel-v21-results-grid">
            {metrics.map(key => (
              <div className="worldmodel-v21-metric" key={key}>
                <span>{metricLabels[key] || key}</span>
                <strong>{formatValue(result.summary[key], key.includes('pct') || key.includes('fraction') ? '%' : '')}</strong>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginBottom: 2 }}>输出目录</div>
            <div className="worldmodel-v21-path">{result.out_dir}</div>
          </div>
          <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-secondary)' }}>
            summary: {result.artifacts.summary_json || '-'} / map: {result.map_update_queued ? '已推送' : '未推送'}
          </div>
          {result.warnings && result.warnings.length > 0 && (
            <div style={{ marginTop: 8, color: 'var(--warning)', fontSize: 11 }}>
              {result.warnings.map(w => <div key={w}>{w}</div>)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
