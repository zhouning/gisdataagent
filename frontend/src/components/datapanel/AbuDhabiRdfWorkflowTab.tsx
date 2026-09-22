import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  CircleDashed,
  Database,
  FileCheck2,
  Gauge,
  GitBranch,
  Layers3,
  LoaderCircle,
  LockKeyhole,
  Map as MapIcon,
  Network,
  Play,
  RefreshCw,
  ShieldCheck,
  Waves,
} from 'lucide-react';
import { getLocaleHeaders } from '../../i18n';

type StageStatus = 'ready' | 'partial' | 'blocked';

interface RdfStage {
  key: string;
  index: string;
  title: string;
  status: StageStatus;
  status_label: string;
  summary: string;
}

interface RdfSource {
  path?: string;
  filename?: string;
  size_bytes?: number;
  sections?: Record<string, number>;
  bbox_epsg32640?: number[] | null;
  span_km?: { east_west?: number; north_south?: number };
  inflow_series_count?: number;
  timeseries_count?: number;
  missing_inflow_series_count?: number;
  external_inflow_driven?: boolean;
  source_ready?: boolean;
  sha256?: string;
}

interface RdfRun {
  run_id?: string;
  status?: string;
  created_at?: string;
  started_at?: string;
  finished_at?: string;
  error?: string;
  summary?: {
    solver?: { name?: string; version?: string };
    flow_units?: string;
    routing_method?: string;
    node_count?: number;
    link_count?: number;
    external_outflow_million_litres?: number | null;
    flooding_loss_million_litres?: number | null;
    routing_continuity_error_percent?: number | null;
    nonconverging_steps_percent?: number | null;
    warning_count?: number;
    error_count?: number;
    quality?: {
      passed?: boolean;
      checks?: Array<{ key: string; passed: boolean; value?: number | null; limit?: number }>;
    };
  };
  artifacts?: Record<string, { name?: string; size_bytes?: number; sha256?: string }>;
  claim_boundary?: string;
}

interface RdfWorkflow {
  status: string;
  source: RdfSource;
  latest_run?: RdfRun | null;
  stages: RdfStage[];
  ready_stage_count: number;
  stage_count: number;
  claim_boundary?: string;
}

interface RdfMapPayload {
  type: 'FeatureCollection';
  metadata?: {
    run_id?: string;
    center?: number[];
    feature_count?: number;
    claim_boundary?: string;
  };
  features: any[];
}

const stageIcons: Record<string, typeof Database> = {
  input: Database,
  swmm: Waves,
  surface: Layers3,
  gwm: GitBranch,
  validation: ShieldCheck,
};

const statusIcons: Record<StageStatus, typeof CheckCircle2> = {
  ready: CheckCircle2,
  partial: CircleDashed,
  blocked: LockKeyhole,
};

const stageDetails: Record<string, { inputs: string[]; outputs: string[]; next: string }> = {
  input: {
    inputs: ['客户原始 RD F.inp', 'EPSG:32640 节点坐标', '3,464 组外部节点入流时序'],
    outputs: ['原文件 SHA-256', '输入结构与引用完整性回执', '局部模型空间范围'],
    next: '原样调用 EPA SWMM，不替换 [TIMESERIES]，不套用全市汇水区改写器。',
  },
  swmm: {
    inputs: ['原始 INP 私有快照', '外部节点入流', '泵站、调蓄和出水口配置'],
    outputs: ['原生 RPT / OUT', '节点最大水深与溢流', '连续性和收敛质量门'],
    next: '完成节点—DTM—局部二维网格映射，再进入一二维耦合。',
  },
  surface: {
    inputs: ['SWMM 节点交换量', '客户 5 m DTM', '地表糙率与边界条件'],
    outputs: ['局部二维积水深度、流速和时序', '一二维体积交换对账'],
    next: '批量生成多事件、多情景物理标签。',
  },
  gwm: {
    inputs: ['RD F 局部二维训练标签', '降雨和边界强迫', '静态地形与排水特征'],
    outputs: ['RD F 独立局部 GWM', '快速动态积水推演', '不确定性结果'],
    next: '使用独立事件和实测水深进行验证；不复用全市 250 m 冻结参数。',
  },
  validation: {
    inputs: ['物理基线、GWM 预测', '客户积水观测', '质量门和版本回执'],
    outputs: ['精度与物理一致性报告', '可追溯交付包', '工程准入边界'],
    next: '达到样本量、精度和稳定性阈值后，再申请工程复核。',
  },
};

const fmt = (value: unknown, digits = 2) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—';
};

export function buildRdfMapUpdate(payload: RdfMapPayload) {
  const runId = String(payload?.metadata?.run_id || 'unknown');
  const center = Array.isArray(payload?.metadata?.center) && payload.metadata.center.length === 2
    ? payload.metadata.center.map(Number)
    : [24.46, 54.45];
  return {
    schema: 'map_update.v1',
    summary: {
      title: '阿布扎比 RD F 局部模型 · 原生 SWMM 基线',
      subtitle: `${Number(payload?.metadata?.feature_count || payload?.features?.length || 0).toLocaleString()} 个节点最大水深与溢流结果`,
      source_status: 'customer_rd_f_native_swmm_result',
      layer_group: 'abu_dhabi_rd_f_local_workflow',
      result_status: 'diagnostic_not_engineering_admitted',
      event_id: runId,
      solver: 'EPA SWMM 5.2.4',
      claim_boundary: payload?.metadata?.claim_boundary,
    },
    center,
    zoom: 14,
    layers: [
      {
        name: `RD F 局部 SWMM · 节点最大水深 · ${runId}`,
        type: 'bubble',
        geojsonData: payload,
        value_column: 'scenario_max_water_depth_m',
        breaks: [0.01, 0.05, 0.1, 0.2, 0.5, 1, 3],
        color_scheme: 'YlOrRd',
        legend_title: '节点最大水深（m）',
        style: { min_radius: 2, max_radius: 13, color: '#7f1d1d', opacity: 0.9, fillOpacity: 0.72 },
        tooltip_fields: [
          'node_id', 'node_type', 'scenario_max_water_depth_m',
          'scenario_max_hydraulic_head_m', 'scenario_max_overflow_or_flooding_m3s',
          'scenario_flooded_hours', 'scenario_total_flood_volume_million_litres',
          'scenario_node_flooding_detected', 'scenario_max_depth_time', 'model_scope',
        ],
        tooltip_labels: {
          node_id: '节点 ID', node_type: '节点类型', scenario_max_water_depth_m: '最大水深（m）',
          scenario_max_hydraulic_head_m: '最大液压水头（m）',
          scenario_max_overflow_or_flooding_m3s: '最大溢流量（m³/s）',
          scenario_flooded_hours: '积水时长（小时）',
          scenario_total_flood_volume_million_litres: '累计溢流量（百万升）',
          scenario_node_flooding_detected: '发生积水', scenario_max_depth_time: '最大水深时刻',
          model_scope: '模型范围',
        },
      },
      {
        name: `RD F 局部 SWMM · 溢流节点 · ${runId}`,
        type: 'bubble',
        geojsonData: {
          type: 'FeatureCollection',
          features: (payload?.features || []).filter(
            feature => Number(feature?.properties?.scenario_max_overflow_or_flooding_m3s || 0) > 0,
          ),
        },
        value_column: 'scenario_max_overflow_or_flooding_m3s',
        breaks: [0.0001, 0.001, 0.005, 0.01, 0.03, 0.1],
        color_scheme: 'Reds',
        legend_title: '节点最大溢流（m³/s）',
        visible: false,
        style: { min_radius: 3, max_radius: 15, color: '#991b1b', opacity: 0.95, fillOpacity: 0.82 },
      },
    ],
  };
}

export default function AbuDhabiRdfWorkflowTab() {
  const { i18n } = useTranslation();
  const english = i18n.resolvedLanguage === 'en-US';
  const tr = (zh: string, en: string) => english ? en : zh;
  const [workflow, setWorkflow] = useState<RdfWorkflow | null>(null);
  const [run, setRun] = useState<RdfRun | null>(null);
  const [mapPayload, setMapPayload] = useState<RdfMapPayload | null>(null);
  const [selectedStage, setSelectedStage] = useState('input');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [mapSent, setMapSent] = useState(false);

  const loadWorkflow = useCallback(async () => {
    const response = await fetch('/api/abu-dhabi/flood/rd-f/workflow', {
      credentials: 'include', headers: getLocaleHeaders(),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.detail || payload?.error || 'RD F 工作流状态读取失败');
    setWorkflow(payload);
    setRun(current => current || payload.latest_run || null);
    return payload as RdfWorkflow;
  }, []);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    loadWorkflow()
      .catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : 'RD F 工作流状态读取失败'); })
      .finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, [loadWorkflow]);

  useEffect(() => {
    if (!run?.run_id || !['queued', 'running'].includes(String(run.status))) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const response = await fetch(`/api/abu-dhabi/flood/rd-f/runs/${encodeURIComponent(String(run.run_id))}`, {
          credentials: 'include', headers: getLocaleHeaders(),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail || payload?.error || 'RD F 运行状态读取失败');
        if (cancelled) return;
        setRun(payload);
        if (['completed', 'completed_with_warnings', 'failed'].includes(String(payload.status))) {
          await loadWorkflow();
        }
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : 'RD F 运行状态读取失败');
      }
    };
    const timer = window.setInterval(poll, 2000);
    poll();
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [loadWorkflow, run?.run_id, run?.status]);

  useEffect(() => {
    if (!run?.run_id || !['completed', 'completed_with_warnings'].includes(String(run.status))) return;
    if (mapPayload?.metadata?.run_id === run.run_id) return;
    let cancelled = false;
    fetch(`/api/abu-dhabi/flood/rd-f/runs/${encodeURIComponent(String(run.run_id))}/map`, {
      credentials: 'include', headers: getLocaleHeaders(),
    })
      .then(async response => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail || payload?.error || 'RD F 地图结果读取失败');
        if (!cancelled) setMapPayload(payload);
      })
      .catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : 'RD F 地图结果读取失败'); });
    return () => { cancelled = true; };
  }, [mapPayload?.metadata?.run_id, run?.run_id, run?.status]);

  useEffect(() => {
    if (!mapPayload) return;
    const publish = () => {
      const handler = (window as any).__handleMapUpdate;
      if (typeof handler !== 'function') return false;
      handler(buildRdfMapUpdate(mapPayload));
      setMapSent(true);
      return true;
    };
    if (publish()) return;
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (publish() || attempts >= 20) window.clearInterval(timer);
    }, 150);
    return () => window.clearInterval(timer);
  }, [mapPayload]);

  const startRun = async () => {
    setBusy(true); setError(''); setMapPayload(null); setMapSent(false); setSelectedStage('swmm');
    try {
      const response = await fetch('/api/abu-dhabi/flood/rd-f/runs', {
        method: 'POST', credentials: 'include', headers: getLocaleHeaders(),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.detail || payload?.error || 'RD F 原生 SWMM 启动失败');
      setRun(payload);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'RD F 原生 SWMM 启动失败');
    } finally {
      setBusy(false);
    }
  };

  const publishMap = () => {
    const handler = (window as any).__handleMapUpdate;
    if (!mapPayload || typeof handler !== 'function') return;
    handler(buildRdfMapUpdate(mapPayload));
    setMapSent(true);
  };

  const source = workflow?.source || {};
  const stages = workflow?.stages || [];
  const currentStage = stages.find(stage => stage.key === selectedStage) || stages[0];
  const details = currentStage ? stageDetails[currentStage.key] : null;
  const running = ['queued', 'running'].includes(String(run?.status));
  const completed = ['completed', 'completed_with_warnings'].includes(String(run?.status));
  const runQuality = run?.summary?.quality;
  const nodeCount = Number(source.sections?.['[JUNCTIONS]'] || 0)
    + Number(source.sections?.['[OUTFALLS]'] || 0)
    + Number(source.sections?.['[STORAGE]'] || 0);
  const linkCount = Number(source.sections?.['[CONDUITS]'] || 0)
    + Number(source.sections?.['[PUMPS]'] || 0);
  const readyCount = Number(workflow?.ready_stage_count || 0);
  const stageCount = Number(workflow?.stage_count || 5);
  const runLabel = running ? tr('运行中', 'Running')
    : run?.status === 'completed' ? tr('质量门通过', 'Quality gates passed')
      : run?.status === 'completed_with_warnings' ? tr('完成 · 质量告警', 'Complete · quality warning')
        : run?.status === 'failed' ? tr('运行失败', 'Run failed') : tr('尚未运行', 'Not run');

  return (
    <div className="abu-flood-tab" data-testid="abu-rdf-workflow-tab">
      <section className="abu-flood-hero">
        <div>
          <span className="abu-flood-kicker">ABU DHABI / RD F LOCAL WORKFLOW</span>
          <h2>{tr('RD F 局部城市内涝全流程', 'RD F Local Urban-Flood Workflow')}</h2>
          <p>{tr('保留客户原始外部节点入流模型，建立独立的一维、二维、局部 GWM 与验证链路。', 'Preserve the customer external-inflow model and build an isolated 1D, 2D, local-GWM and validation chain.')}</p>
          <div className="abu-flood-hero-meta">
            <span><FileCheck2 size={13} /> {source.source_ready ? tr('原始输入已核验', 'Source verified') : tr('输入待核验', 'Source pending')}</span>
            <span><Network size={13} /> {tr('局部工程网络', 'Local engineering network')}</span>
            <span><LockKeyhole size={13} /> {tr('与全市 V1 结果隔离', 'Isolated from citywide V1')}</span>
          </div>
        </div>
        <div className="abu-flood-hero-side">
          <div className={`abu-flood-readiness-ring ${readyCount === stageCount ? 'complete' : ''}`}><strong>{readyCount} / {stageCount}</strong><span>{tr('阶段就绪', 'stages ready')}</span></div>
          <div className="abu-flood-hero-note">{tr('当前定位：高可信局部试点', 'Scope: high-trust local pilot')}<br />{tr('不是阿布扎比全市模型', 'Not the Abu Dhabi citywide model')}</div>
        </div>
      </section>

      <section className="abu-flood-metrics" aria-label={tr('RD F 输入快照', 'RD F input snapshot')}>
        <div><Database size={15} /><span>{tr('原始输入', 'Source input')}</span><strong>{source.filename || 'RD F.inp'}</strong></div>
        <div><Network size={15} /><span>{tr('节点', 'Nodes')}</span><strong>{nodeCount.toLocaleString()}</strong></div>
        <div><Waves size={15} /><span>{tr('管线与泵', 'Links and pumps')}</span><strong>{linkCount.toLocaleString()}</strong></div>
        <div><Activity size={15} /><span>{tr('外部入流序列', 'External inflow series')}</span><strong>{Number(source.inflow_series_count || 0).toLocaleString()}</strong></div>
        <div><Gauge size={15} /><span>{tr('模型范围', 'Model extent')}</span><strong>{fmt(source.span_km?.east_west)} × {fmt(source.span_km?.north_south)} km</strong></div>
      </section>

      <section className="abu-flood-scenario-section" aria-label={tr('RD F 原生 SWMM 基线', 'RD F native SWMM baseline')}>
        <div className="abu-flood-section-heading">
          <div><span className="abu-flood-overline">NATIVE BASELINE</span><h3>{tr('阶段 2 · 原生 EPA SWMM 基线', 'Stage 2 · Native EPA SWMM baseline')}</h3></div>
          <span className={`abu-flood-scenario-badge ${run?.status === 'completed' ? 'abu-flood-status-ready' : run?.status === 'failed' ? 'abu-flood-status-blocked' : ''}`}>{running ? <LoaderCircle className="abu-flood-loading-icon" size={13} /> : <Activity size={13} />}{runLabel}</span>
        </div>
        <div className="abu-flood-scenario-disclaimer"><AlertTriangle size={14} /><span>{tr('运行会复制原始 INP 后原样调用 EPA SWMM；不会改写 166 万行时序。当前结果仅作诊断，未校准、未工程准入。', 'The run snapshots the original INP and invokes EPA SWMM without rewriting its 1.66 million time-series rows. Results are diagnostic, uncalibrated and not engineering-admitted.')}</span></div>
        <div className="abu-flood-scenario-actions">
          <button className="abu-flood-map-action" type="button" onClick={startRun} disabled={busy || running || !source.source_ready}><Play size={15} />{running ? tr('SWMM 正在运行…', 'SWMM is running...') : tr('运行 RD F 原生 SWMM', 'Run native RD F SWMM')}</button>
          <button className="abu-flood-reset-action" type="button" onClick={() => loadWorkflow().catch(reason => setError(String(reason)))} disabled={busy}><RefreshCw size={14} />{tr('刷新状态', 'Refresh status')}</button>
          {mapPayload && <button className="abu-flood-map-action" type="button" onClick={publishMap}><MapIcon size={15} />{mapSent ? tr('重新发送结果到地图', 'Resend result to map') : tr('在地图上展示结果', 'Show result on map')}</button>}
        </div>
        {error && <div className="abu-flood-form-error"><AlertTriangle size={14} />{error}</div>}
        {run?.run_id && <div className="abu-flood-scenario-run-id"><Activity size={12} /><span>RUN ID</span><code>{run.run_id}</code></div>}
        {completed && run?.summary && <>
          <div className="abu-flood-scenario-result-metrics">
            <div><span>{tr('路由连续性误差', 'Routing continuity error')}</span><strong>{fmt(run.summary.routing_continuity_error_percent, 3)}%</strong><small>{tr('阈值 ±5%', 'limit ±5%')}</small></div>
            <div><span>{tr('不收敛步数', 'Non-converging steps')}</span><strong>{fmt(run.summary.nonconverging_steps_percent, 2)}%</strong><small>{tr('阈值 5%', 'limit 5%')}</small></div>
            <div><span>{tr('严格质量门', 'Strict quality gate')}</span><strong>{runQuality?.passed ? tr('通过', 'Passed') : tr('未通过', 'Not passed')}</strong><small>{Number(run.summary.warning_count || 0)} {tr('条警告', 'warnings')}</small></div>
          </div>
          <div className="abu-flood-scenario-result-metrics">
            <div><span>{tr('外排量', 'External outflow')}</span><strong>{fmt(run.summary.external_outflow_million_litres)}</strong><small>{tr('百万升', 'million litres')}</small></div>
            <div><span>{tr('洪涝损失', 'Flooding loss')}</span><strong>{fmt(run.summary.flooding_loss_million_litres)}</strong><small>{tr('百万升', 'million litres')}</small></div>
            <div><span>{tr('地图节点', 'Mapped nodes')}</span><strong>{Number(mapPayload?.metadata?.feature_count || 0).toLocaleString()}</strong><small>{tr('最大值结果', 'maximum results')}</small></div>
          </div>
        </>}
        {run?.error && <div className="abu-flood-form-error"><AlertTriangle size={14} />{run.error}</div>}
      </section>

      <section className="abu-flood-section">
        <div className="abu-flood-section-heading">
          <div><span className="abu-flood-overline">ISOLATED PIPELINE</span><h3>{tr('RD F 五阶段全流程', 'RD F five-stage workflow')}</h3></div>
          <span className="abu-flood-muted">{tr('点击阶段查看输入、输出和下一步', 'Select a stage for inputs, outputs and next action')}</span>
        </div>
        <div className="abu-flood-stage-track">
          {stages.map((stage, index) => {
            const Icon = stageIcons[stage.key] || Database;
            const StatusIcon = statusIcons[stage.status] || CircleDashed;
            return <div className="abu-flood-stage-wrap" key={stage.key}>
              <button className={`abu-flood-stage ${selectedStage === stage.key ? 'active' : ''}`} type="button" onClick={() => setSelectedStage(stage.key)} aria-pressed={selectedStage === stage.key}>
                <div className="abu-flood-stage-top"><span>{stage.index}</span><StatusIcon size={14} className={`abu-flood-status-${stage.status}`} /></div>
                <Icon size={20} /><strong>{stage.title}</strong><small>{stage.status_label}</small>
              </button>
              {index < stages.length - 1 && <ArrowRight size={15} className="abu-flood-stage-arrow" />}
            </div>;
          })}
        </div>
      </section>

      {currentStage && details && <div className="abu-flood-detail-grid">
        <section className="abu-flood-detail-panel">
          <div className="abu-flood-detail-heading"><div className="abu-flood-detail-title"><div className="abu-flood-detail-icon">{(() => { const Icon = stageIcons[currentStage.key] || Database; return <Icon size={18} />; })()}</div><div><span className="abu-flood-overline">STAGE {currentStage.index}</span><h3>{currentStage.title}</h3><p>{currentStage.status_label}</p></div></div><span className={`abu-flood-pill abu-flood-status-${currentStage.status}`}>{currentStage.status}</span></div>
          <p className="abu-flood-detail-summary">{currentStage.summary}</p>
          <div className="abu-flood-io-grid"><div><span>{tr('输入', 'Inputs')}</span>{details.inputs.map(item => <div key={item}><ArrowRight size={11} />{item}</div>)}</div><div><span>{tr('输出', 'Outputs')}</span>{details.outputs.map(item => <div key={item}><CheckCircle2 size={11} />{item}</div>)}</div></div>
          <div className="abu-flood-next"><ArrowRight size={14} /><div><span>{tr('下一步', 'Next')}</span><strong>{details.next}</strong></div></div>
        </section>
        <aside className="abu-flood-gates-panel">
          <div className="abu-flood-section-heading compact"><div><span className="abu-flood-overline">BOUNDARY</span><h3>{tr('真实性与准入边界', 'Truth and admission boundary')}</h3></div><LockKeyhole size={16} /></div>
          <div className="abu-flood-gate-list">
            <div className="abu-flood-gate"><span className="abu-flood-gate-dot ready" /><div><strong>{tr('原始入流引用完整', 'Original inflow references complete')}</strong><small>{Number(source.missing_inflow_series_count || 0)} {tr('条缺失', 'missing')}</small></div><CheckCircle2 size={14} /></div>
            <div className="abu-flood-gate"><span className={`abu-flood-gate-dot ${runQuality?.checks?.[1]?.passed ? 'ready' : 'partial'}`} /><div><strong>{tr('SWMM 数值质量', 'SWMM numerical quality')}</strong><small>{run ? runLabel : tr('等待首次运行', 'Awaiting first run')}</small></div>{runQuality?.passed ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}</div>
            <div className="abu-flood-gate"><span className="abu-flood-gate-dot" /><div><strong>{tr('二维耦合和 GWM 尚未完成', '2D coupling and GWM are pending')}</strong><small>{tr('需节点映射、局部网格、物理标签和独立验证', 'Requires node mapping, local mesh, physics labels and independent validation')}</small></div><LockKeyhole size={14} /></div>
          </div>
          <div className="abu-flood-gate-note"><AlertTriangle size={13} />{tr('RD F 只能表述为约 3.55 × 3.21 km 的局部诊断模型，不能表述为阿布扎比全市模型。', 'RD F is a roughly 3.55 × 3.21 km local diagnostic model and must not be represented as the Abu Dhabi citywide model.')}</div>
        </aside>
      </div>}
    </div>
  );
}
