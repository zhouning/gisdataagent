import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  CircleDot,
  FileCheck2,
  Droplets,
  Gauge,
  GitBranch,
  Info,
  Layers3,
  LockKeyhole,
  MessageSquareText,
  Network,
  Play,
  RotateCcw,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Timer,
  Waves,
} from 'lucide-react';
import {
  fetchIrrigationBootstrap,
  reviewIrrigationProposal,
  runIrrigationScenario,
  type Horizon,
  type IrrigationBootstrap,
  type IrrigationRun,
  type Mode,
  type Node,
  type OntologyLink,
  type ProposalStatus,
  type ScenarioResult,
} from './irrigationWorldModelApi';
import './irrigation-world-model-demo.css';

type DetailTab = 'object' | 'link' | 'state' | 'action' | 'constraint' | 'evidence';
const DEFAULT_MODES: Array<{ id: Mode; label: string; note: string }> = [
  { id: 'baseline', label: 'Baseline', note: '不调整' },
  { id: 'candidateA', label: 'Candidate A', note: '仅时段调整' },
  { id: 'candidateB', label: 'Candidate B', note: '时段 + 比例' },
];
const format = (value: number, digits = 0) => new Intl.NumberFormat('zh-CN', {
  minimumFractionDigits: digits,
  maximumFractionDigits: digits,
}).format(value);

function valueForNode(nodeId: string, result: ScenarioResult): string {
  const state = result.nodeStates[nodeId];
  if (!state) return nodeId;
  if (typeof state.demand === 'number') return `${format(state.value)} / ${format(state.demand)} ${state.unit}`;
  return `${format(state.value, state.unit === '%' ? 1 : 0)} ${state.unit}`;
}

export default function IrrigationWorldModelDemoTab() {
  const [bootstrap, setBootstrap] = useState<IrrigationBootstrap | null>(null);
  const [run, setRun] = useState<IrrigationRun | null>(null);
  const [supplyDrop, setSupplyDrop] = useState(20);
  const [westShift, setWestShift] = useState(6);
  const [candidateEastRatio, setCandidateEastRatio] = useState(45);
  const [horizon, setHorizon] = useState<Horizon>(24);
  const [activeMode, setActiveMode] = useState<Mode>('candidateB');
  const [selectedNodeId, setSelectedNodeId] = useState('C3');
  const [detailTab, setDetailTab] = useState<DetailTab>('object');
  const [isRunning, setIsRunning] = useState(false);
  const [isReviewing, setIsReviewing] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [loadNonce, setLoadNonce] = useState(0);
  const [serviceError, setServiceError] = useState('');
  const [reviewNote, setReviewNote] = useState('待调度人员核对现场规则');

  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    setServiceError('');
    fetchIrrigationBootstrap(controller.signal)
      .then(payload => {
        const parameters = payload.run.parameters;
        setBootstrap(payload);
        setRun(payload.run);
        setSupplyDrop(parameters.supply_drop_percent);
        setWestShift(parameters.west_shift_hours);
        setCandidateEastRatio(parameters.candidate_east_ratio_percent);
        setHorizon(parameters.horizon_hours);
        setReviewNote(payload.run.proposal.review_note);
        setActiveMode(payload.run.proposal.candidate_mode);
      })
      .catch(error => {
        if ((error as Error).name !== 'AbortError') setServiceError((error as Error).message);
      })
      .finally(() => setIsLoading(false));
    return () => controller.abort();
  }, [loadNonce]);

  const modes = bootstrap?.modes || DEFAULT_MODES;
  const nodeById = useMemo(() => Object.fromEntries((bootstrap?.objects || []).map(node => [node.id, node])), [bootstrap]);
  const results = run?.results || [];
  const selectedResult = results.find(result => result.mode === activeMode) || results[2] || results[0];
  const selectedNode = nodeById[selectedNodeId];
  const committed = run?.parameters;
  const dirty = !!committed && (
    committed.supply_drop_percent !== supplyDrop
    || committed.west_shift_hours !== westShift
    || committed.candidate_east_ratio_percent !== candidateEastRatio
    || committed.horizon_hours !== horizon
  );
  const displayedWestShift = committed?.west_shift_hours ?? westShift;
  const committedHorizon = committed?.horizon_hours ?? horizon;
  const proposalStatus = run?.proposal.status || 'pending';
  const auditEvents = run?.audit_events || [];

  const runSimulation = async () => {
    setIsRunning(true);
    setServiceError('');
    try {
      const nextRun = await runIrrigationScenario({
        supply_drop_percent: supplyDrop,
        west_shift_hours: westShift,
        candidate_east_ratio_percent: candidateEastRatio,
        horizon_hours: horizon,
      });
      setRun(nextRun);
      setReviewNote(nextRun.proposal.review_note);
      setActiveMode(nextRun.proposal.candidate_mode);
    } catch (error) {
      setServiceError((error as Error).message);
    } finally {
      setIsRunning(false);
    }
  };

  const openOntologyModel = () => {
    const detail = { tab: 'ontology', ontology_key: bootstrap?.ontology_profile.profile_id || 'irrigation-district-water', view: 'graph' };
    (window as any).__pendingGdaWorkspaceUpdate = detail;
    window.dispatchEvent(new CustomEvent('gda-workspace-update', { detail }));
  };

  const reset = () => {
    const defaults = bootstrap?.default_parameters;
    setSupplyDrop(defaults?.supply_drop_percent ?? 20);
    setWestShift(defaults?.west_shift_hours ?? 6);
    setCandidateEastRatio(defaults?.candidate_east_ratio_percent ?? 45);
    setHorizon(defaults?.horizon_hours ?? 24);
    setActiveMode('candidateB');
  };

  const proposalStatusLabel: Record<ProposalStatus, string> = {
    pending: '待人工审查',
    returned: '已退回修改',
    approved: '已通过审查（不执行）',
  };
  const reviewProposal = async (status: Exclude<ProposalStatus, 'pending'>) => {
    if (!run) return;
    setIsReviewing(true);
    setServiceError('');
    try {
      const defaultNote = status === 'approved'
        ? '已核对本次模型条件；通过审查但不执行设备动作。'
        : '请补充现场规则、设备状态或数据证据后重新运行。';
      const submittedNote = reviewNote.trim() && reviewNote !== '待调度人员核对现场规则' ? reviewNote : defaultNote;
      const reviewed = await reviewIrrigationProposal(run.proposal.proposal_id, status, submittedNote);
      setRun(reviewed);
      setReviewNote(reviewed.proposal.review_note);
    } catch (error) {
      setServiceError((error as Error).message);
    } finally {
      setIsReviewing(false);
    }
  };

  if (isLoading || !bootstrap || !run || !selectedResult) {
    return (
      <div className="odiwm-demo-shell">
        <div className="odiwm-dirty-banner">
          {serviceError ? <AlertTriangle size={15} /> : <Activity size={15} className="odiwm-spin" />}
          <span>{serviceError || '正在连接灌区世界模型后端服务...'}</span>
          {serviceError && <button type="button" className="odiwm-reset-button" onClick={() => setLoadNonce(value => value + 1)}>重试</button>}
        </div>
      </div>
    );
  }

  return (
    <div className="odiwm-demo-shell">
      <header className="odiwm-demo-header">
        <div className="odiwm-demo-title">
          <span className="odiwm-demo-mark"><Waves size={17} /></span>
          <div>
            <strong>本体驱动的灌区条件推演</strong>
            <span>Ontology-grounded irrigation scenario workspace</span>
          </div>
        </div>
        <div className="odiwm-demo-badges" aria-label="System status">
          <span className="odiwm-badge odiwm-badge-green"><Sparkles size={12} />后端服务运行</span>
          <span className="odiwm-badge"><Activity size={12} />有状态模型执行</span>
          <span className="odiwm-badge"><Layers3 size={12} />合成灌区数据</span>
          <span className="odiwm-badge odiwm-badge-warn"><ShieldCheck size={12} />不连接生产控制</span>
          <button className="odiwm-reset-button" type="button" onClick={openOntologyModel}><Network size={13} />打开灌区本体</button>
        </div>
      </header>

      <section className="odiwm-demo-question">
        <div>
          <span>当前问题</span>
          <strong>未来 {horizon} 小时上游可供水量下降 {supplyDrop}% 时，怎样降低末端供水缺口？</strong>
          <small>通过正式本体包固定 Object/Link，再执行 Manning 参数化的有状态运动波近似与逐步水量账。</small>
        </div>
        <button className="odiwm-primary-button" type="button" onClick={runSimulation} disabled={isRunning}>
          {isRunning ? <Activity size={14} className="odiwm-spin" /> : <Play size={14} />}
          {isRunning ? '推演中...' : '运行推演'}
        </button>
      </section>

      <section className="odiwm-controls" aria-label="Scenario controls">
        <div className="odiwm-control-block">
          <div className="odiwm-control-label"><SlidersHorizontal size={14} /><span>上游供水下降</span><strong>{supplyDrop}%</strong></div>
          <input type="range" min="0" max="40" step="5" value={supplyDrop} onChange={event => setSupplyDrop(Number(event.target.value))} aria-label="上游供水下降百分比" />
          <div className="odiwm-range-hints"><span>0%</span><span>情景输入，非实测预报</span><span>40%</span></div>
        </div>
        <div className="odiwm-control-block">
          <div className="odiwm-control-label"><Timer size={14} /><span>西支渠时段后移</span><strong>{westShift} h</strong></div>
          <input type="range" min="0" max="12" step="2" value={westShift} onChange={event => setWestShift(Number(event.target.value))} aria-label="西支渠时段后移小时数" />
          <div className="odiwm-range-hints"><span>0 h</span><span>用于比较时序假设</span><span>12 h</span></div>
        </div>
        <div className="odiwm-control-block">
          <div className="odiwm-control-label"><GitBranch size={14} /><span>Candidate B 东支渠比例</span><strong>{candidateEastRatio}%</strong></div>
          <input type="range" min="40" max="60" step="5" value={candidateEastRatio} onChange={event => setCandidateEastRatio(Number(event.target.value))} aria-label="Candidate B 东支渠目标比例" />
          <div className="odiwm-range-hints"><span>40%</span><span>动作参数</span><span>60%</span></div>
        </div>
        <div className="odiwm-control-block odiwm-horizon-control">
          <div className="odiwm-control-label"><CalendarDays size={14} /><span>评估时间窗</span></div>
          <select value={horizon} onChange={event => setHorizon(Number(event.target.value) as Horizon)} aria-label="评估时间窗">
            <option value="6">未来 6 小时</option>
            <option value="12">未来 12 小时</option>
            <option value="24">未来 24 小时</option>
          </select>
          <div className="odiwm-range-hints"><span>回放步长 6 h</span><span>情景评估</span></div>
        </div>
        <div className="odiwm-control-block odiwm-mode-control">
          <div className="odiwm-control-label"><GitBranch size={14} /><span>查看方案</span></div>
          <div className="odiwm-segmented" role="tablist" aria-label="查看方案">
            {modes.map(mode => (
              <button key={mode.id} type="button" className={activeMode === mode.id ? 'active' : ''} onClick={() => setActiveMode(mode.id)} role="tab" aria-selected={activeMode === mode.id}>
                <span>{mode.label}</span><small>{mode.note}</small>
              </button>
            ))}
          </div>
        </div>
        <button className="odiwm-reset-button" type="button" onClick={reset} title="恢复默认情景"><RotateCcw size={14} />重置</button>
      </section>

      {dirty && <div className="odiwm-dirty-banner"><Info size={14} />参数已改变，结果区等待重新运行。当前仍显示上一次已确认的情景。</div>}
      {serviceError && <div className="odiwm-dirty-banner"><AlertTriangle size={14} />后端服务：{serviceError}</div>}

      <section className="odiwm-run-context" aria-label="Run context">
        <div className="odiwm-context-card"><span className="odiwm-context-icon"><CalendarDays size={14} /></span><div><small>状态快照</small><strong>{new Date(run.state_snapshot.effective_at).toLocaleString('zh-CN', { hour12: false })} · {run.state_snapshot.snapshot_id}</strong></div></div>
        <div className="odiwm-context-card"><span className="odiwm-context-icon"><ClipboardCheck size={14} /></span><div><small>数据质量</small><strong>{run.state_snapshot.quality_label}</strong></div><span className="odiwm-context-status warn">需现场校准</span></div>
        <div className="odiwm-context-card"><span className="odiwm-context-icon"><LockKeyhole size={14} /></span><div><small>运行权限</small><strong>条件推演 · Proposal only</strong></div><span className="odiwm-context-status ok">无控制权限</span></div>
        <div className="odiwm-context-card"><span className="odiwm-context-icon"><Activity size={14} /></span><div><small>后端运行</small><strong>{run.run_id}</strong></div><span className="odiwm-context-status ok">{format(run.model.numerical_evidence.timestep_count)} steps</span></div>
      </section>

      <section className="odiwm-pipeline-strip" aria-label="Run pipeline">
        {run.pipeline.map(stage => {
          const status = stage.key === 'proposal' ? proposalStatusLabel[proposalStatus] : stage.status;
          return <div key={stage.key} className={status === '禁止' ? 'blocked' : status === '待运行' ? 'idle' : 'done'}><b>{stage.index}</b><span><strong>{stage.label}</strong><small>{status}</small></span></div>;
        })}
      </section>

      <section className="odiwm-main-grid">
          <div className="odiwm-network-panel">
          <div className="odiwm-section-heading"><div><strong>灌区语义网络</strong><span>点击对象查看 Object / Link / State / Action</span></div><span className="odiwm-live-tag"><CircleDot size={10} />已冻结状态</span></div>
          <div className="odiwm-network-map">
            <div className="odiwm-network-source-row">
              <button type="button" className={`odiwm-node odiwm-node-source ${selectedNodeId === 'R1' ? 'selected' : ''}`} onClick={() => setSelectedNodeId('R1')}>
                <Droplets size={16} /><span><strong>R1</strong><small>{nodeById.R1?.label}</small></span><em>{valueForNode('R1', selectedResult)}</em>
              </button>
              <span className="odiwm-flow-line"><ChevronRight size={17} /></span>
              <button type="button" className={`odiwm-node odiwm-node-trunk ${selectedNodeId === 'C1' ? 'selected' : ''}`} onClick={() => setSelectedNodeId('C1')}>
                <Waves size={15} /><span><strong>C1</strong><small>{nodeById.C1?.label}</small></span><em>{valueForNode('C1', selectedResult)}</em>
              </button>
            </div>
            <div className="odiwm-branch-grid">
              <BranchNetwork branch="east" selectedNodeId={selectedNodeId} onSelect={setSelectedNodeId} result={selectedResult} nodeById={nodeById} />
              <BranchNetwork branch="west" selectedNodeId={selectedNodeId} onSelect={setSelectedNodeId} result={selectedResult} nodeById={nodeById} />
            </div>
          </div>
          <div className="odiwm-network-legend"><span><i className="legend-dot object" />本体对象</span><span><i className="legend-dot state" />状态值</span><span><i className="legend-dot action" />候选动作</span><span><i className="legend-dot constraint" />约束</span></div>
        </div>

        <aside className="odiwm-detail-panel">
          <div className="odiwm-section-heading"><div><strong>本体对象详情</strong><span>稳定 ID 与关系可追溯</span></div><span className="odiwm-version-tag">v{bootstrap.ontology_profile.version}</span></div>
          <div className="odiwm-detail-object-head"><span className="odiwm-object-icon"><Layers3 size={15} /></span><div><strong>{selectedNode?.label || selectedNodeId}</strong><span>{selectedNode?.type} · {selectedNodeId}</span></div></div>
          <div className="odiwm-detail-tabs" role="tablist">
            {(['object', 'link', 'state', 'action', 'constraint', 'evidence'] as DetailTab[]).map(tab => {
              const labels: Record<DetailTab, string> = { object: 'Object', link: 'Link', state: 'State', action: 'Action', constraint: 'Constraint', evidence: 'Evidence' };
              return <button key={tab} type="button" className={detailTab === tab ? 'active' : ''} onClick={() => setDetailTab(tab)} role="tab" aria-selected={detailTab === tab}>{labels[tab]}</button>;
            })}
          </div>
          <DetailBody tab={detailTab} node={selectedNode} nodeId={selectedNodeId} result={selectedResult} links={bootstrap.links} westShift={displayedWestShift} horizon={committedHorizon} ontologyVersion={`${bootstrap.ontology_profile.profile_id}:${bootstrap.ontology_profile.version}`} />
        </aside>
      </section>

      <section className="odiwm-results-panel">
        <div className="odiwm-section-heading"><div><strong>情景结果对比</strong><span>运行版本 {run.version} · {run.run_id}</span></div><span className="odiwm-compute-tag"><Gauge size={12} />运动波近似 · 有状态</span></div>
        <div className="odiwm-results-table-wrap">
          <table className="odiwm-results-table">
            <thead><tr><th>指标</th>{results.map(result => <th key={result.mode} className={activeMode === result.mode ? 'active-col' : ''}>{result.label}</th>)}</tr></thead>
            <tbody>
              <MetricRow label="到田水量" values={results.map(result => `${format(result.delivered)} m³/d`)} activeMode={activeMode} />
              <MetricRow label="供水缺口" values={results.map(result => `${format(result.shortage)} m³/d`)} activeMode={activeMode} tone="warning" />
              <MetricRow label="尾端最低保障" values={results.map(result => `${format(result.tailCoverage, 1)}%`)} activeMode={activeMode} />
              <MetricRow label="公平 CV（越低越好）" values={results.map(result => format(result.fairnessCv, 3))} activeMode={activeMode} />
              <MetricRow label="容量违规" values={results.map(result => result.capacityViolations ? `${result.capacityViolations} 项` : '0 项')} activeMode={activeMode} tone="constraint" />
              <MetricRow label="水量账残差" values={results.map(result => `${format(result.residual, 3)} m³/d`)} activeMode={activeMode} />
            </tbody>
          </table>
        </div>
        <div className="odiwm-result-notes">
          <span><CheckCircle2 size={13} />连续方程残差 {format(selectedResult.residualVolumeM3, 4)} m³</span>
          <span><Timer size={13} />{format(selectedResult.numerical.timestep_count)} 步 · {format(selectedResult.numerical.runtime_ms, 1)} ms</span>
          <span><Waves size={13} />水深范围 {format(selectedResult.numerical.minimum_depth_m, 3)}–{format(selectedResult.numerical.maximum_depth_m, 3)} m</span>
          <span><AlertTriangle size={13} />超容量仅标记为阻断，不自动修正动作</span>
        </div>
      </section>

      <section className="odiwm-timeline-panel">
        <div className="odiwm-section-heading"><div><strong>时序回放 · {selectedResult.label}</strong><span>以 6 小时步长查看末端状态变化；数值为模型条件下的合成回放</span></div><span className="odiwm-compute-tag"><Timer size={12} />T+0 ~ T+{committedHorizon} h</span></div>
        <div className="odiwm-timeline-grid">
          {selectedResult.timeline.map(point => <div key={point.hour} className="odiwm-timeline-point"><div className="odiwm-timeline-hour">T+{point.hour} h</div><div className="odiwm-timeline-bar"><span style={{ width: `${Math.max(4, point.tailCoverage)}%` }} /></div><strong>{format(point.tailCoverage, 1)}%</strong><small>尾端保障</small><em className={point.status === '可评估' ? 'ready' : point.status === '部分到达' ? 'partial' : 'waiting'}>{point.status}</em><span className="odiwm-timeline-shortage">缺口 {format(point.shortage)} m³/d</span></div>)}
        </div>
      </section>

      <section className="odiwm-proposal-grid">
        <div className="odiwm-proposal-card">
          <div className="odiwm-section-heading"><div><strong>Proposal · {modes.find(mode => mode.id === run.proposal.candidate_mode)?.label || run.proposal.candidate_mode}</strong><span>有约束候选排序 · {run.proposal.proposal_id}</span></div><span className={`odiwm-review-tag ${proposalStatus === 'approved' ? 'approved' : proposalStatus === 'returned' ? 'returned' : ''}`}><AlertTriangle size={12} />{proposalStatusLabel[proposalStatus]}</span></div>
          <div className="odiwm-action-list">
            {run.proposal.actions.map(action => <div key={action.order}><span className="action-index">{action.order}</span><span>{action.summary}</span></div>)}
          </div>
          <div className="odiwm-review-form">
            <label htmlFor="odiwm-review-note"><MessageSquareText size={13} />审核意见</label>
            <textarea id="odiwm-review-note" value={reviewNote} onChange={event => setReviewNote(event.target.value)} rows={2} disabled={proposalStatus !== 'pending' || isReviewing} />
            <div className="odiwm-review-actions"><button type="button" className="odiwm-return-button" onClick={() => reviewProposal('returned')} disabled={proposalStatus !== 'pending' || isReviewing}><AlertTriangle size={13} />退回修改</button><button type="button" className="odiwm-approve-button" onClick={() => reviewProposal('approved')} disabled={proposalStatus !== 'pending' || isReviewing}><FileCheck2 size={13} />通过审查（不执行）</button></div>
          </div>
          <div className="odiwm-no-control"><ShieldCheck size={14} /><strong>当前系统不执行设备动作</strong><span>Proposal 用于解释、比较和人工审查，不会调用闸门、泵站或生产 API。</span></div>
        </div>
        <div className="odiwm-evidence-card">
          <div className="odiwm-section-heading"><div><strong>证据、运行记录与边界</strong><span>让结果知道自己从哪里来</span></div><Info size={14} /></div>
          <dl className="odiwm-evidence-list">
            <div><dt>Ontology profile</dt><dd>{bootstrap.ontology_profile.profile_id}:{bootstrap.ontology_profile.version}</dd></div>
            <div><dt>Ontology package</dt><dd>{bootstrap.ontology_profile.content_sha256.slice(0, 16)}</dd></div>
            <div><dt>Data source</dt><dd>{run.claim_boundary.data}</dd></div>
            <div><dt>Kernel</dt><dd>{run.model.model_id}:{run.model.version}</dd></div>
            <div><dt>State transition</dt><dd>{run.model.numerical_evidence.equations}</dd></div>
            <div><dt>Execution</dt><dd>{format(run.model.numerical_evidence.timestep_count)} steps / {format(run.model.numerical_evidence.runtime_ms, 1)} ms</dd></div>
            <div><dt>Planner</dt><dd>{run.planner?.planner_id || 'legacy-run-metadata'} · {run.planner?.selected_mode || run.proposal.candidate_mode}</dd></div>
            <div><dt>Claim</dt><dd>{run.claim_boundary.claim}</dd></div>
            <div><dt>Uncertainty</dt><dd>{run.claim_boundary.calibration}</dd></div>
          </dl>
          <div className="odiwm-audit-list"><div className="odiwm-audit-title"><ClipboardCheck size={13} />运行审计</div>{auditEvents.slice(-5).map((event, index) => <div className="odiwm-audit-event" key={`${event.time}-${event.step}-${index}`}><span>{event.time}</span><strong>{event.step}</strong><em className={event.status === '通过' ? 'ok' : event.status === '待审查' ? 'wait' : ''}>{event.status}</em><small>{event.detail}</small></div>)}</div>
        </div>
      </section>
    </div>
  );
}

function BranchNetwork({ branch, selectedNodeId, onSelect, result, nodeById }: { branch: 'east' | 'west'; selectedNodeId: string; onSelect: (id: string) => void; result: ScenarioResult; nodeById: Record<string, Node> }) {
  const ids = branch === 'east' ? ['C2', 'D1', 'F1', 'F2'] : ['C3', 'D2', 'F3', 'F4'];
  const label = branch === 'east' ? '东支渠' : '西支渠';
  return (
    <div className={`odiwm-branch ${branch}`}>
      <div className="odiwm-branch-label"><span>{label}</span><small>{branch === 'east' ? `${format(result.branchRatio * 100, 1)}%` : `${format((1 - result.branchRatio) * 100, 1)}%`} 分配</small></div>
      <div className="odiwm-branch-chain">
        <button type="button" className={`odiwm-node odiwm-node-compact ${selectedNodeId === ids[0] ? 'selected' : ''}`} onClick={() => onSelect(ids[0])}><Waves size={14} /><span><strong>{ids[0]}</strong><small>{nodeById[ids[0]]?.label}</small></span><em>{valueForNode(ids[0], result)}</em></button>
        <span className="odiwm-branch-line"><ChevronRight size={15} /></span>
        <button type="button" className={`odiwm-node odiwm-node-compact ${selectedNodeId === ids[1] ? 'selected' : ''}`} onClick={() => onSelect(ids[1])}><Gauge size={14} /><span><strong>{ids[1]}</strong><small>{nodeById[ids[1]]?.label}</small></span><em>{valueForNode(ids[1], result)}</em></button>
      </div>
      <div className="odiwm-field-line"><span className="odiwm-field-stem" />{ids.slice(2).map(fieldId => <button type="button" key={fieldId} className={`odiwm-field-node ${selectedNodeId === fieldId ? 'selected' : ''}`} onClick={() => onSelect(fieldId)}><span>{fieldId}</span><small>{format(result.fields[fieldId].coverage * 100, 1)}% 保障</small></button>)}</div>
    </div>
  );
}

function DetailBody({ tab, node, nodeId, result, links, westShift, horizon, ontologyVersion }: { tab: DetailTab; node?: Node; nodeId: string; result: ScenarioResult; links: OntologyLink[]; westShift: number; horizon: Horizon; ontologyVersion: string }) {
  if (!node) return <div className="odiwm-detail-empty">请选择一个本体对象。</div>;
  const incoming = links.filter(link => link.object === nodeId).map(link => `${link.subject} ${link.predicate} ${nodeId}`);
  const outgoing = links.filter(link => link.subject === nodeId).map(link => `${nodeId} ${link.predicate} ${link.object}`);
  if (tab === 'object') return <div className="odiwm-detail-body"><DetailRow label="稳定 ID" value={node.stable_id} /><DetailRow label="类型" value={node.type} /><DetailRow label="业务角色" value={node.role} /><DetailRow label="本体版本" value={ontologyVersion} /></div>;
  if (tab === 'link') return <div className="odiwm-detail-body"><DetailRow label="入向关系" value={incoming.join('；') || '无（边界源）'} /><DetailRow label="出向关系" value={outgoing.join('；') || '无'} /><DetailRow label="关系权威" value={links.find(link => link.subject === nodeId || link.object === nodeId)?.authority || '未发布'} /></div>;
  if (tab === 'state') return <div className="odiwm-detail-body"><DetailRow label="当前状态" value={node.state} /><DetailRow label="状态值" value={valueForNode(nodeId, result)} /><DetailRow label="时间窗" value={`T+0 ~ T+${horizon} h`} /><DetailRow label="传播时延" value={nodeId === 'C3' || nodeId === 'D2' ? `${result.westDelay} h（假设）` : '由后端模型按拓扑计算'} /><DetailRow label="质量标记" value="合成状态 · 未校准" tone="warning" /></div>;
  if (tab === 'action') return <div className="odiwm-detail-body"><DetailRow label="候选动作" value={nodeId === 'D2' || nodeId === 'C3' ? `西支渠时段后移 ${westShift} h` : nodeId === 'D1' || nodeId === 'C2' ? `东支渠比例 ${format(result.branchRatio * 100, 1)}%` : '保持不变'} /><DetailRow label="执行方式" value="Proposal only" /><DetailRow label="人工审查" value="required" /></div>;
  if (tab === 'constraint') return <div className="odiwm-detail-body"><DetailRow label="容量上限" value={node.capacity ? `${format(node.capacity)} m³/d` : '由规则约束'} /><DetailRow label="约束结果" value={node.capacity && (nodeId === 'C2' || nodeId === 'C3') ? (result.capacityViolations ? '需阻断并复核' : '通过') : '通过 / 待校准'} tone={result.capacityViolations ? 'warning' : 'ok'} /><DetailRow label="守恒残差" value={`${format(result.residual, 3)} m³/d`} /></div>;
  return <div className="odiwm-detail-body"><DetailRow label="证据类型" value="合成数据 + 显式假设" /><DetailRow label="来源标识" value="synthetic_seed_dataset" /><DetailRow label="可支持结论" value="模型条件下的方案比较" /><DetailRow label="不可支持结论" value="真实灌区调度承诺" /></div>;
}

function DetailRow({ label, value, tone }: { label: string; value: string; tone?: 'ok' | 'warning' }) {
  return <div className="odiwm-detail-row"><dt>{label}</dt><dd className={tone ? `tone-${tone}` : ''}>{value}</dd></div>;
}

function MetricRow({ label, values, activeMode, tone }: { label: string; values: string[]; activeMode: Mode; tone?: 'warning' | 'constraint' }) {
  return <tr><th>{label}</th>{values.map((value, index) => { const mode = (['baseline', 'candidateA', 'candidateB'] as Mode[])[index]; return <td key={mode} className={`${activeMode === mode ? 'active-col' : ''} ${tone ? `metric-${tone}` : ''}`}>{value}</td>; })}</tr>;
}
