import { useEffect, useMemo, useState } from 'react';
import { Brain, Database, GitBranch, MapPin, Play, RefreshCw } from 'lucide-react';

type EnvKind = 'county' | 'restoration';
type Continuation = 'random' | 'greedy';
type Scoring = 'reward' | 'slope';
type DemoDataset = 'bishan' | 'dongxing';
type InputSource = 'governed' | 'direct';

interface GovernedProduct {
  role: string;
  status: string;
  product_id?: string | null;
  path?: string | null;
  sha256?: string | null;
  format?: string | null;
  mapping_status?: string | null;
  available?: boolean;
  crs?: string | null;
  bbox?: number[] | null;
  reference_year?: number | null;
  reference_year_source?: string | null;
  reference_year_authoritative?: boolean;
  columns?: string[] | null;
}

interface GovernedHandoff {
  handoff_id: string;
  created_at?: string;
  source?: string;
  quality_status?: string;
  production_eligible?: boolean;
  governed_input_ready?: boolean;
  administrative_units_ready?: boolean;
  latest_derived_run?: {
    run_id: string;
    status: string;
    production_eligible?: boolean;
    manifest_path?: string;
    artifact_count?: number;
    available?: boolean;
  } | null;
  suggested_prepared_dir: string;
  suggested_ensemble_dir: string;
  products: {
    dltb?: GovernedProduct | null;
    dem?: GovernedProduct | null;
    administrative_units?: GovernedProduct | null;
  };
}

interface GovernedInputsResponse {
  status: string;
  lake_root: string;
  count: number;
  items: GovernedHandoff[];
}

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
  input_quality?: {
    status: string;
    dem_direct_coverage_fraction: number;
    administrative_units_present: boolean;
    production_gate_passed: boolean;
    findings: string[];
    reference_year_gap?: number | null;
    reference_years?: Record<string, number | null>;
    reference_year_sources?: Record<string, string>;
    reference_year_authority?: Record<string, boolean>;
    administrative_code_contract?: {
      exact_match_fraction?: number;
      dltb_field?: string | null;
      administrative_field?: string | null;
    } | null;
    spatial_reference_contract?: {
      analysis_crs?: string;
      all_required_transformable?: boolean;
    } | null;
  };
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
  audit_result?: {
    hard_constraint_passed?: boolean;
    all_expected_outputs_exist?: boolean;
    next_action?: string;
  } | null;
  derived_publication?: {
    status: string;
    production_eligible: boolean;
    manifest_path: string;
    catalog_path: string;
    artifact_count: number;
  } | null;
}

const DEFAULT_FORM = {
  dltb_path: '',
  dem_path: '',
  xzq_path: '',
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

function applyGovernedHandoff(prev: V21Form, handoff: GovernedHandoff): V21Form {
  return {
    ...prev,
    dltb_path: handoff.products.dltb?.path || '',
    dem_path: handoff.products.dem?.path || '',
    xzq_path: handoff.products.administrative_units?.path || '',
    prepared_dir: handoff.suggested_prepared_dir,
    ensemble_dir: handoff.suggested_ensemble_dir,
    reuse_existing: false,
    run_prepare: true,
    run_sample: true,
    run_train: true,
    run_plan: true,
  };
}

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

function formatReferenceYear(product: GovernedProduct) {
  if (!product.reference_year) return '年份待确认';
  if (product.reference_year_authoritative) {
    return `${product.reference_year}（已确认）`;
  }
  if (product.reference_year_source === 'path_inferred') {
    return `${product.reference_year}（路径推断）`;
  }
  return `${product.reference_year}（未确认）`;
}

export default function WorldModelV21Tab() {
  const [status, setStatus] = useState<V21Status | null>(null);
  const [form, setForm] = useState<V21Form>(DEFAULT_FORM);
  const [inputSource, setInputSource] = useState<InputSource>('governed');
  const [governedInputs, setGovernedInputs] = useState<GovernedInputsResponse | null>(null);
  const [selectedHandoffId, setSelectedHandoffId] = useState('');
  const [result, setResult] = useState<V21Result | null>(null);
  const [pipelineResult, setPipelineResult] = useState<V21PipelineResult | null>(null);
  const [activeRun, setActiveRun] = useState<'plan' | 'pipeline' | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [error, setError] = useState('');

  const ready = status?.status === 'ready';
  const loading = activeRun !== null;
  const selectedHandoff = useMemo(
    () => governedInputs?.items.find(item => item.handoff_id === selectedHandoffId) || null,
    [governedInputs, selectedHandoffId],
  );
  const canRun = useMemo(
    () => ready && form.prepared_dir.trim() !== '' && form.ensemble_dir.trim() !== '' && !loading,
    [ready, form.prepared_dir, form.ensemble_dir, loading],
  );
  const canRunPipeline = useMemo(() => {
    if (!ready || loading || !form.prepared_dir.trim()) return false;
    if (!form.run_train && !form.ensemble_dir.trim()) return false;
    if (!form.reuse_existing && form.run_prepare) {
      if (inputSource === 'governed') {
        if (!selectedHandoff?.products.dltb?.available || !selectedHandoff?.products.dem?.available) {
          return false;
        }
      } else if (!form.dltb_path.trim() || !form.dem_path.trim()) {
        return false;
      }
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
    inputSource,
    selectedHandoff,
  ]);

  const updateForm = <K extends keyof V21Form>(key: K, value: V21Form[K]) => {
    setForm(prev => ({ ...prev, [key]: value }));
  };

  const loadStatus = async () => {
    setStatusLoading(true);
    setError('');
    try {
      const [resp, governedResp] = await Promise.all([
        fetch('/api/world-model-v21/status', { credentials: 'include' }),
        fetch('/api/world-model-v21/governed-inputs', { credentials: 'include' }),
      ]);
      const data = await resp.json();
      if (!resp.ok || data.error) {
        setError(data.error || '状态检查失败');
        return;
      }
      setStatus(data as V21Status);
      const governedData = await governedResp.json();
      if (governedResp.ok && !governedData.error) {
        const catalog = governedData as GovernedInputsResponse;
        setGovernedInputs(catalog);
        const candidate = catalog.items.find(item => item.handoff_id === selectedHandoffId)
          || catalog.items.find(item => item.governed_input_ready)
          || catalog.items[0];
        if (candidate) {
          setSelectedHandoffId(candidate.handoff_id);
          if (inputSource === 'governed') {
            setForm(prev => applyGovernedHandoff(prev, candidate));
          }
        }
      }
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
    xzq_path: form.xzq_path.trim() || null,
    input_mode: inputSource,
    dltb_expected_sha256: inputSource === 'governed'
      ? selectedHandoff?.products.dltb?.sha256 || null
      : null,
    dem_expected_sha256: inputSource === 'governed'
      ? selectedHandoff?.products.dem?.sha256 || null
      : null,
    xzq_expected_sha256: inputSource === 'governed'
      ? selectedHandoff?.products.administrative_units?.sha256 || null
      : null,
    governed_handoff_id: inputSource === 'governed' ? selectedHandoffId || null : null,
    dltb_reference_year: inputSource === 'governed'
      ? selectedHandoff?.products.dltb?.reference_year || null
      : null,
    dem_reference_year: inputSource === 'governed'
      ? selectedHandoff?.products.dem?.reference_year || null
      : null,
    administrative_reference_year: inputSource === 'governed'
      ? selectedHandoff?.products.administrative_units?.reference_year || null
      : null,
    reference_year_sources: inputSource === 'governed'
      ? {
          dltb: selectedHandoff?.products.dltb?.reference_year_source || 'missing',
          dem: selectedHandoff?.products.dem?.reference_year_source || 'missing',
          administrative_units:
            selectedHandoff?.products.administrative_units?.reference_year_source || 'missing',
        }
      : {},
    reference_year_authority: inputSource === 'governed'
      ? {
          dltb: Boolean(selectedHandoff?.products.dltb?.reference_year_authoritative),
          dem: Boolean(selectedHandoff?.products.dem?.reference_year_authoritative),
          administrative_units: Boolean(
            selectedHandoff?.products.administrative_units?.reference_year_authoritative,
          ),
        }
      : {},
    require_reference_years: inputSource === 'governed',
    require_authoritative_reference_years: inputSource === 'governed',
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
      xzq_path: '',
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
    setInputSource('direct');
    setPipelineResult(null);
    setResult(null);
    setError('');
  };

  const selectGovernedHandoff = (handoffId: string) => {
    const handoff = governedInputs?.items.find(item => item.handoff_id === handoffId);
    setSelectedHandoffId(handoffId);
    if (handoff) {
      setForm(prev => applyGovernedHandoff(prev, handoff));
    }
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
  const inputQuality = stageStepByKey.get('prepare')?.input_quality;
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

        <div className="worldmodel-v21-input-source" aria-label="Paper9 输入来源">
          <button
            type="button"
            className={inputSource === 'governed' ? 'active' : ''}
            onClick={() => {
              setInputSource('governed');
              if (selectedHandoff) setForm(prev => applyGovernedHandoff(prev, selectedHandoff));
            }}
            disabled={loading}
          >
            数据湖治理产品
          </button>
          <button
            type="button"
            className={inputSource === 'direct' ? 'active' : ''}
            onClick={() => setInputSource('direct')}
            disabled={loading}
          >
            直接文件
          </button>
        </div>

        {inputSource === 'governed' && (
          <div className="worldmodel-v21-governed-source">
            <div className="config-row">
              <label>阶段 1 交接批次</label>
              <select
                value={selectedHandoffId}
                onChange={e => selectGovernedHandoff(e.target.value)}
                disabled={loading || !governedInputs?.items.length}
              >
                {!governedInputs?.items.length && <option value="">暂无治理产品</option>}
                {governedInputs?.items.map(item => (
                  <option value={item.handoff_id} key={item.handoff_id}>
                    {item.source?.split(/[\\/]/).pop() || item.handoff_id} / {item.quality_status || 'unknown'}
                  </option>
                ))}
              </select>
            </div>
            {selectedHandoff ? (
              <div className="worldmodel-v21-product-list">
                {([
                  ['DLTB', selectedHandoff.products.dltb],
                  ['DEM', selectedHandoff.products.dem],
                  ['行政区划', selectedHandoff.products.administrative_units],
                ] as const).map(([label, product]) => (
                  <div className="worldmodel-v21-product-row" key={label}>
                    <strong>{label}</strong>
                    <span className={`status-badge ${product?.available ? 'success' : 'warning'}`}>
                      {product?.available ? '已锁定' : '缺失'}
                    </span>
                    <code>{product?.path || '-'}</code>
                    {product?.available && (
                      <small>
                        {product.crs || 'CRS 待识别'} / {formatReferenceYear(product)}
                      </small>
                    )}
                  </div>
                ))}
                <div className="worldmodel-v21-source-meta">
                  <span>质量：{selectedHandoff.quality_status || '-'}</span>
                  <span>生产资格：{selectedHandoff.production_eligible ? '通过' : '未通过'}</span>
                  <span>行政区划：{selectedHandoff.administrative_units_ready ? '已接入' : '待接入'}</span>
                  <span>
                    最近结果：{selectedHandoff.latest_derived_run?.available
                      ? `${selectedHandoff.latest_derived_run.status} / ${selectedHandoff.latest_derived_run.artifact_count || 0} 个产物`
                      : '暂无'}
                  </span>
                </div>
                {selectedHandoff.latest_derived_run?.available && (
                  <div className="worldmodel-v21-path">
                    {selectedHandoff.latest_derived_run.manifest_path}
                  </div>
                )}
              </div>
            ) : (
              <div className="worldmodel-v21-subtle-text">
                请先在“离线入湖”完成阶段 1，系统会自动登记可供 Paper9 使用的治理产品。
              </div>
            )}
          </div>
        )}

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

        {inputSource === 'direct' && <div className="worldmodel-v21-grid">
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
          <div className="config-row">
            <label>行政区划路径（可选）</label>
            <input
              type="text"
              value={form.xzq_path}
              onChange={e => updateForm('xzq_path', e.target.value)}
              placeholder="D:\\NX_INCOMING\\XZQ.gdb"
              disabled={loading}
            />
          </div>
        </div>}

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
          {inputQuality && (
            <div className={`worldmodel-v21-input-quality ${inputQuality.production_gate_passed ? 'pass' : 'review'}`}>
              <strong>联合输入门禁</strong>
              <span>DEM 直接覆盖 {(inputQuality.dem_direct_coverage_fraction * 100).toFixed(2)}%</span>
              <span>行政区划 {inputQuality.administrative_units_present ? '已接入' : '缺失'}</span>
              <span>
                CRS {inputQuality.spatial_reference_contract?.all_required_transformable ? '可转换' : '待核验'}
              </span>
              <span>
                行政代码覆盖 {((inputQuality.administrative_code_contract?.exact_match_fraction || 0) * 100).toFixed(2)}%
              </span>
              <span>年份差 {inputQuality.reference_year_gap ?? '待确认'}</span>
              <span>
                权威年份 {Object.values(inputQuality.reference_year_authority || {}).filter(Boolean).length} 项
              </span>
              <span>{inputQuality.production_gate_passed ? '生产门禁通过' : '仅可演练'}</span>
              {inputQuality.findings.map(item => <div key={item}>{item}</div>)}
            </div>
          )}
          {pipelineResult.audit_result && (
            <div className={`worldmodel-v21-input-quality ${pipelineResult.audit_result.hard_constraint_passed ? 'pass' : 'review'}`}>
              <strong>Paper9 硬约束审计</strong>
              <span>{pipelineResult.audit_result.hard_constraint_passed ? '通过' : '未通过'}</span>
              <span>空间结果 {pipelineResult.audit_result.all_expected_outputs_exist ? '完整' : '不完整'}</span>
              <span>下一步 {pipelineResult.audit_result.next_action || '-'}</span>
            </div>
          )}
          {pipelineResult.derived_publication && (
            <div className={`worldmodel-v21-input-quality ${pipelineResult.derived_publication.production_eligible ? 'pass' : 'review'}`}>
              <strong>数据湖 Derived 固化</strong>
              <span>{pipelineResult.derived_publication.status}</span>
              <span>{pipelineResult.derived_publication.artifact_count} 个产物</span>
              <span>{pipelineResult.derived_publication.production_eligible ? '可用于生产' : '候选结果'}</span>
              <div className="worldmodel-v21-path">{pipelineResult.derived_publication.manifest_path}</div>
            </div>
          )}
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
