import { useEffect, useMemo, useState } from 'react';
import { Brain, Database, GitBranch, MapPin, Play, RefreshCw } from 'lucide-react';

type EnvKind = 'county' | 'restoration';
type Continuation = 'random' | 'greedy';
type Scoring = 'reward' | 'slope';
type DemoDataset = 'bishan' | 'dongxing';

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

interface V21PipelineStep {
  step: string;
  status?: string;
  mode?: string;
  prepared_dir?: string;
  ensemble_dir?: string | null;
  out_dir?: string;
  onnx_member_count?: number;
  summary?: Record<string, number | string | null | undefined>;
  warnings?: string[];
}

interface V21PipelineResult {
  status: string;
  version: string;
  source: string;
  mode: string;
  prepared_dir: string;
  ensemble_dir?: string | null;
  steps: V21PipelineStep[];
  plan_result?: V21Result | null;
  map_update_queued?: boolean;
}

const DEFAULT_FORM = {
  dltb_path: '',
  dem_path: '',
  prepared_dir: '',
  ensemble_dir: '',
  env_kind: 'county' as EnvKind,
  horizon: 1,
  top_k: 1,
  n_episodes: 1,
  continuation: 'greedy' as Continuation,
  scoring: 'reward' as Scoring,
  threads: 0,
  seed_offset: 0,
  reuse_existing: true,
  run_prepare: true,
  run_sample: true,
  run_train: true,
  run_plan: true,
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

const stageDefinitions = [
  {
    key: 'prepare',
    formKey: 'run_prepare',
    capability: 'tool1_prepare',
    letter: 'A',
    title: 'Tool 1 Prepare',
    subtitle: 'DLTB + DEM -> prepared_dir',
    icon: Database,
  },
  {
    key: 'sample',
    formKey: 'run_sample',
    capability: 'tool2_sample',
    letter: 'B',
    title: 'Tool 2 Sample',
    subtitle: 'prepared_dir -> tool2 samples',
    icon: GitBranch,
  },
  {
    key: 'train',
    formKey: 'run_train',
    capability: 'tool3_train',
    letter: 'C',
    title: 'Tool 3 Train',
    subtitle: 'samples -> ONNX ensemble',
    icon: Brain,
  },
  {
    key: 'plan',
    formKey: 'run_plan',
    capability: 'tool4_plan',
    letter: 'D',
    title: 'Tool 4 Plan',
    subtitle: 'ensemble -> MPC output',
    icon: MapPin,
  },
] as const;

const demoDatasets: Record<DemoDataset, {
  label: string;
  dltb_path: string;
  dem_path: string;
  prepared_dir: string;
  ensemble_dir: string;
  proj_crs: string;
}> = {
  bishan: {
    label: 'Bishan',
    dltb_path: '',
    dem_path: '/app/bishan-runs/dem.tif',
    prepared_dir: '/app/bishan-runs/prepared',
    ensemble_dir: '/app/bishan-runs/prepared/ensemble_seed0',
    proj_crs: 'EPSG:32648',
  },
  dongxing: {
    label: 'Dongxing',
    dltb_path: '/app/dongxing-runs/dongxing.shp',
    dem_path: '/app/dongxing-runs/dem.tif',
    prepared_dir: '/app/dongxing-runs/prepared',
    ensemble_dir: '/app/dongxing-runs/prepared/ensemble_seed0',
    proj_crs: 'EPSG:32648',
  },
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
  const [pipelineResult, setPipelineResult] = useState<V21PipelineResult | null>(null);
  const [activeRun, setActiveRun] = useState<'plan' | 'pipeline' | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [error, setError] = useState('');

  const ready = status?.status === 'ready';
  const loading = activeRun !== null;
  const canRun = useMemo(
    () => ready && form.prepared_dir.trim() !== '' && form.ensemble_dir.trim() !== '' && !loading,
    [ready, form.prepared_dir, form.ensemble_dir, loading],
  );
  const canRunPipeline = useMemo(() => {
    if (!ready || loading || !form.prepared_dir.trim()) return false;
    if (!form.run_train && !form.ensemble_dir.trim()) return false;
    if (!form.reuse_existing && form.run_prepare && (!form.dltb_path.trim() || !form.dem_path.trim())) {
      return false;
    }
    return form.run_prepare || form.run_sample || form.run_train || form.run_plan;
  }, [
    ready,
    loading,
    form.prepared_dir,
    form.ensemble_dir,
    form.reuse_existing,
    form.run_prepare,
    form.run_sample,
    form.run_train,
    form.run_plan,
    form.dltb_path,
    form.dem_path,
  ]);

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
    dltb_path: form.dltb_path.trim() || null,
    dem_path: form.dem_path.trim() || null,
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

  const pipelineBody = () => ({
    ...requestBody(),
    reuse_existing: form.reuse_existing,
    run_prepare: form.run_prepare,
    run_sample: form.run_sample,
    run_train: form.run_train,
    run_plan: form.run_plan,
  });

  const syncPendingMap = async () => {
    try {
      const mapResp = await fetch('/api/map/pending', { credentials: 'include' });
      const mapData = await mapResp.json();
      if (mapData.map_update && (window as any).__handleMapUpdate) {
        (window as any).__handleMapUpdate(mapData.map_update);
      }
    } catch {
      // Map handoff is best-effort; the result panel still shows artifacts.
    }
  };

  const applyDemoDataset = (dataset: DemoDataset) => {
    const preset = demoDatasets[dataset];
    setForm(prev => ({
      ...prev,
      dltb_path: preset.dltb_path,
      dem_path: preset.dem_path,
      prepared_dir: preset.prepared_dir,
      ensemble_dir: preset.ensemble_dir,
      env_kind: 'county',
      proj_crs: preset.proj_crs,
      horizon: 1,
      top_k: 1,
      n_episodes: 1,
      continuation: 'greedy',
      scoring: 'reward',
      threads: 0,
      seed_offset: 0,
      reuse_existing: true,
      run_prepare: true,
      run_sample: true,
      run_train: true,
      run_plan: true,
      cultivated_area_floor_delta_ha: '',
      baimu_area_floor_delta_ha: '',
      gamma_conn: '',
      delta_conn: '',
    }));
    setPipelineResult(null);
    setResult(null);
    setError('');
  };

  const runPlan = async () => {
    setActiveRun('plan');
    setError('');
    setResult(null);
    setPipelineResult(null);
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
      await syncPendingMap();
    } catch (e: any) {
      setError(e.message || '规划运行失败');
    } finally {
      setActiveRun(null);
    }
  };

  const runPipeline = async () => {
    setActiveRun('pipeline');
    setError('');
    setResult(null);
    setPipelineResult(null);
    try {
      const resp = await fetch('/api/world-model-v21/pipeline', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pipelineBody()),
      });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        setError(data.error || 'A/B/C/D 编排运行失败');
        return;
      }
      setPipelineResult(data as V21PipelineResult);
      if (data.plan_result) {
        setResult(data.plan_result as V21Result);
        await syncPendingMap();
      }
    } catch (e: any) {
      setError(e.message || 'A/B/C/D 编排运行失败');
    } finally {
      setActiveRun(null);
    }
  };

  const statusClass = ready ? 'success' : status ? 'warning' : 'warning';
  const commit = status?.paper9?.commit ? status.paper9.commit.slice(0, 12) : '-';
  const selectedDataset = (Object.keys(demoDatasets) as DemoDataset[]).find(key => {
    const preset = demoDatasets[key];
    return form.prepared_dir === preset.prepared_dir
      && form.ensemble_dir === preset.ensemble_dir
      && form.dem_path === preset.dem_path;
  });
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
  const stageStepByKey = new Map((pipelineResult?.steps || []).map(step => [step.step, step]));
  const stageBadge = (step: V21PipelineStep | undefined, enabled: boolean, capability: string) => {
    if (step?.status === 'skipped_reused') return { className: 'success', label: '复用完成' };
    if (step?.status === 'ok') return { className: 'success', label: '执行完成' };
    if (step?.status) return { className: 'warning', label: step.status };
    if (!enabled) return { className: 'warning', label: '本次跳过' };
    if (!status?.capabilities?.[capability]) return { className: 'warning', label: '不可用' };
    return { className: 'success', label: '可执行' };
  };
  const stageArtifact = (key: string, step?: V21PipelineStep) => {
    if (key === 'prepare') return step?.prepared_dir || form.prepared_dir || '-';
    if (key === 'sample') return step?.out_dir || `${form.prepared_dir || '-'}/tool2`;
    if (key === 'train') return step?.ensemble_dir || form.ensemble_dir || '-';
    return step?.out_dir || result?.out_dir || '-';
  };

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
            className="worldmodel-v21-icon-button"
          >
            <RefreshCw size={12} />
            刷新
          </button>
          <span className="worldmodel-v21-subtle-text">
            v{status?.version || '2.1.0'} / Paper9 {status?.paper9?.package_version || '-'}
          </span>
        </div>

        {status && (
          <div className="worldmodel-v21-status-card">
            <div className="worldmodel-v21-path">{status.paper9.repo_path}</div>
            <div className="worldmodel-v21-status-meta">
              <span>commit: {commit}</span>
              <span>ONNX: {status.onnx_member_count ?? 0}</span>
              <span>{status.paper9.remote || '-'}</span>
            </div>
            {!ready && (
              <div className="worldmodel-v21-status-error">
                {status.paper9.error || 'Paper9 仓库或依赖不可用'}
              </div>
            )}
          </div>
        )}

        <div className="worldmodel-v21-presets">
          {(Object.keys(demoDatasets) as DemoDataset[]).map(key => (
            <button
              type="button"
              key={key}
              onClick={() => applyDemoDataset(key)}
              disabled={loading}
              className={selectedDataset === key ? 'active' : ''}
              aria-pressed={selectedDataset === key}
            >
              {demoDatasets[key].label}
            </button>
          ))}
          <span>Docker 演示数据集</span>
        </div>

        <div className="worldmodel-v21-stage-grid" aria-label="World Model v2.1 A/B/C/D 阶段">
          {stageDefinitions.map(stage => {
            const enabled = Boolean(form[stage.formKey]);
            const step = stageStepByKey.get(stage.key);
            const badge = stageBadge(step, enabled, stage.capability);
            const Icon = stage.icon;
            return (
              <div
                className={`worldmodel-v21-stage ${enabled ? '' : 'disabled'} ${step ? 'done' : ''}`}
                key={stage.key}
              >
                <div className="worldmodel-v21-stage-head">
                  <span className="worldmodel-v21-stage-letter">{stage.letter}</span>
                  <Icon size={14} />
                  <div>
                    <strong>{stage.title}</strong>
                    <span>{stage.subtitle}</span>
                  </div>
                </div>
                <div className="worldmodel-v21-stage-foot">
                  <span className={`status-badge ${badge.className}`}>{badge.label}</span>
                  <code>{stageArtifact(stage.key, step)}</code>
                </div>
              </div>
            );
          })}
        </div>

        <div className="worldmodel-v21-toggle-row">
          <label>
            <input
              type="checkbox"
              checked={form.reuse_existing}
              onChange={e => updateForm('reuse_existing', e.target.checked)}
              disabled={loading}
            />
            复用已有产物
          </label>
          {stageDefinitions.map(stage => (
            <label key={stage.key}>
              <input
                type="checkbox"
                checked={Boolean(form[stage.formKey])}
                onChange={e => updateForm(stage.formKey, e.target.checked)}
                disabled={loading}
              />
              {stage.letter}
            </label>
          ))}
        </div>

        <div className="worldmodel-v21-grid">
          <div className="config-row">
            <label>DLTB 路径</label>
            <input
              type="text"
              value={form.dltb_path}
              onChange={e => updateForm('dltb_path', e.target.value)}
              placeholder="/app/.../DLTB.shp"
              disabled={loading}
            />
          </div>
          <div className="config-row">
            <label>DEM 路径</label>
            <input
              type="text"
              value={form.dem_path}
              onChange={e => updateForm('dem_path', e.target.value)}
              placeholder="/app/bishan-runs/dem.tif"
              disabled={loading}
            />
          </div>
        </div>

        <div className="config-row">
          <label>Prepared 目录</label>
          <input
            type="text"
            value={form.prepared_dir}
            onChange={e => updateForm('prepared_dir', e.target.value)}
            placeholder="/app/bishan-runs/prepared"
            disabled={loading}
          />
        </div>
        <div className="config-row">
          <label>Ensemble 目录</label>
          <input
            type="text"
            value={form.ensemble_dir}
            onChange={e => updateForm('ensemble_dir', e.target.value)}
            placeholder="/app/bishan-runs/prepared/ensemble_seed0"
            disabled={loading}
          />
        </div>

        <div className="worldmodel-v21-grid">
          <div className="config-row">
            <label>环境</label>
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
            <label>坐标系</label>
            <input
              type="text"
              value={form.proj_crs}
              onChange={e => updateForm('proj_crs', e.target.value)}
              placeholder="EPSG:32648"
              disabled={loading}
            />
          </div>
          <div className="config-row">
            <label>规划步长</label>
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
            <label>候选数</label>
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
            <label>回合数</label>
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
            <label>线程</label>
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
            <label>延续策略</label>
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
            <label>评分</label>
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
            <label>耕地面积下限</label>
            <input
              type="number"
              value={form.cultivated_area_floor_delta_ha}
              onChange={e => updateForm('cultivated_area_floor_delta_ha', e.target.value)}
              disabled={loading}
            />
          </div>
          <div className="config-row">
            <label>百亩方面积下限</label>
            <input
              type="number"
              value={form.baimu_area_floor_delta_ha}
              onChange={e => updateForm('baimu_area_floor_delta_ha', e.target.value)}
              disabled={loading}
            />
          </div>
          <div className="config-row">
            <label>连片权重</label>
            <input
              type="number"
              value={form.gamma_conn}
              onChange={e => updateForm('gamma_conn', e.target.value)}
              disabled={loading}
            />
          </div>
          <div className="config-row">
            <label>连片约束</label>
            <input
              type="number"
              value={form.delta_conn}
              onChange={e => updateForm('delta_conn', e.target.value)}
              disabled={loading}
            />
          </div>
        </div>

        <div className="worldmodel-v21-actions">
          <button
            type="button"
            onClick={runPipeline}
            disabled={!canRunPipeline}
            className="worldmodel-v21-primary-action"
          >
            <Play size={14} />
            {activeRun === 'pipeline' ? 'A/B/C/D 编排运行中...' : '运行/复用 A→D 编排'}
          </button>
          <button
            type="button"
            onClick={runPlan}
            disabled={!canRun}
            className="worldmodel-v21-secondary-action"
          >
            <Play size={14} />
            {activeRun === 'plan' ? 'Tool 4 运行中...' : '只运行 Tool 4'}
          </button>
        </div>

        {error && (
          <div className="worldmodel-v21-error">
            {error}
          </div>
        )}
      </div>

      {pipelineResult && (
        <div className="worldmodel-results">
          <h4 style={{ margin: '4px 0 8px', fontSize: 13 }}>A/B/C/D 编排结果</h4>
          <div className="worldmodel-v21-pipeline-steps">
            {pipelineResult.steps.map((step, index) => {
              const stage = stageDefinitions.find(item => item.key === step.step);
              const badge = stageBadge(step, true, stage?.capability || '');
              return (
                <div className="worldmodel-v21-pipeline-step" key={`${step.step}-${index}`}>
                  <span className="worldmodel-v21-step-letter">{stage?.letter || index + 1}</span>
                  <div>
                    <strong>{stage?.title || step.step}</strong>
                    <span>{step.mode || step.status || '-'}</span>
                  </div>
                  <span className={`status-badge ${badge.className}`}>{badge.label}</span>
                  <code>{stageArtifact(step.step, step)}</code>
                </div>
              );
            })}
          </div>
          <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text-secondary)' }}>
            prepared: <span className="worldmodel-v21-path">{pipelineResult.prepared_dir}</span>
            <br />
            ensemble: <span className="worldmodel-v21-path">{pipelineResult.ensemble_dir || '-'}</span>
          </div>
        </div>
      )}

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
