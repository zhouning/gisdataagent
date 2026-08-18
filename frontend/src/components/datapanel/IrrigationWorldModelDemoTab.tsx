import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
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
import i18n, { formatDate, formatNumber } from '../../i18n';

type DetailTab = 'object' | 'link' | 'state' | 'action' | 'constraint' | 'evidence';
const DEFAULT_MODES: Array<{ id: Mode; label: string; note: string }> = [
  { id: 'baseline', label: 'Baseline', note: '' },
  { id: 'candidateA', label: 'Candidate A', note: '' },
  { id: 'candidateB', label: 'Candidate B', note: '' },
];
const format = (value: number, digits = 0) => formatNumber(value, {
  minimumFractionDigits: digits,
  maximumFractionDigits: digits,
});
const tx = (key: string, options?: Record<string, unknown>) => i18n.t(key, options);
const TIMELINE_STATUS_KEYS: Record<string, 'assessable' | 'partial' | 'waiting'> = {
  '\u53ef\u8bc4\u4f30': 'assessable',
  assessable: 'assessable',
  '\u90e8\u5206\u5230\u8fbe': 'partial',
  partial: 'partial',
  '\u5f85\u8bc4\u4f30': 'waiting',
  waiting: 'waiting',
};
const AUDIT_STATUS_KEYS: Record<string, 'passed' | 'recorded' | 'review'> = {
  '\u901a\u8fc7': 'passed',
  passed: 'passed',
  '\u8bb0\u5f55': 'recorded',
  recorded: 'recorded',
  '\u5f85\u5ba1\u67e5': 'review',
  review: 'review',
};
const timelineStatusKey = (value: string) => TIMELINE_STATUS_KEYS[value] || 'waiting';
const auditStatusKey = (value: string) => AUDIT_STATUS_KEYS[value] || 'recorded';

function valueForNode(nodeId: string, result: ScenarioResult): string {
  const state = result.nodeStates[nodeId];
  if (!state) return nodeId;
  if (typeof state.demand === 'number') return `${format(state.value)} / ${format(state.demand)} ${state.unit}`;
  return `${format(state.value, state.unit === '%' ? 1 : 0)} ${state.unit}`;
}

export default function IrrigationWorldModelDemoTab() {
  const { t } = useTranslation();
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
  const [reviewNote, setReviewNote] = useState(() => t('irrigationWorldModel.review.defaultNote'));

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
    pending: t('irrigationWorldModel.proposal.pending'),
    returned: t('irrigationWorldModel.proposal.returned'),
    approved: t('irrigationWorldModel.proposal.approved'),
  };
  const reviewProposal = async (status: Exclude<ProposalStatus, 'pending'>) => {
    if (!run) return;
    setIsReviewing(true);
    setServiceError('');
    try {
      const defaultNote = status === 'approved'
        ? t('irrigationWorldModel.review.approvedNote')
        : t('irrigationWorldModel.review.returnedNote');
      const submittedNote = reviewNote.trim() && reviewNote !== t('irrigationWorldModel.review.defaultNote') ? reviewNote : defaultNote;
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
          <span>{serviceError || t('irrigationWorldModel.loading')}</span>
          {serviceError && <button type="button" className="odiwm-reset-button" onClick={() => setLoadNonce(value => value + 1)}>{t('irrigationWorldModel.retry')}</button>}
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
            <strong>{t('irrigationWorldModel.title')}</strong>
            <span>{t('irrigationWorldModelLabels.workspaceSubtitle')}</span>
          </div>
        </div>
        <div className="odiwm-demo-badges" aria-label={t('irrigationWorldModel.systemStatus')}>
          <span className="odiwm-badge odiwm-badge-green"><Sparkles size={12} />{t('irrigationWorldModel.badges.backendRunning')}</span>
          <span className="odiwm-badge"><Activity size={12} />{t('irrigationWorldModel.badges.statefulExecution')}</span>
          <span className="odiwm-badge"><Layers3 size={12} />{t('irrigationWorldModel.badges.syntheticData')}</span>
          <span className="odiwm-badge odiwm-badge-warn"><ShieldCheck size={12} />{t('irrigationWorldModel.badges.noProductionControl')}</span>
          <button className="odiwm-reset-button" type="button" onClick={openOntologyModel}><Network size={13} />{t('irrigationWorldModel.openOntology')}</button>
        </div>
      </header>

      <section className="odiwm-demo-question">
        <div>
          <span>{t('irrigationWorldModel.question.label')}</span>
          <strong>{t('irrigationWorldModel.question.prompt', { horizon, drop: supplyDrop })}</strong>
          <small>{t('irrigationWorldModel.question.description')}</small>
        </div>
        <button className="odiwm-primary-button" type="button" onClick={runSimulation} disabled={isRunning}>
          {isRunning ? <Activity size={14} className="odiwm-spin" /> : <Play size={14} />}
          {isRunning ? t('irrigationWorldModel.running') : t('irrigationWorldModel.run')}
        </button>
      </section>

      <section className="odiwm-controls" aria-label={t('irrigationWorldModel.scenarioControls')}>
        <div className="odiwm-control-block">
          <div className="odiwm-control-label"><SlidersHorizontal size={14} /><span>{t('irrigationWorldModel.controls.supplyDrop')}</span><strong>{supplyDrop}%</strong></div>
          <input type="range" min="0" max="40" step="5" value={supplyDrop} onChange={event => setSupplyDrop(Number(event.target.value))} aria-label={t('irrigationWorldModel.controls.supplyDropAria')} />
          <div className="odiwm-range-hints"><span>0%</span><span>{t('irrigationWorldModel.controls.syntheticInput')}</span><span>40%</span></div>
        </div>
        <div className="odiwm-control-block">
          <div className="odiwm-control-label"><Timer size={14} /><span>{t('irrigationWorldModel.controls.westShift')}</span><strong>{westShift} h</strong></div>
          <input type="range" min="0" max="12" step="2" value={westShift} onChange={event => setWestShift(Number(event.target.value))} aria-label={t('irrigationWorldModel.controls.westShiftAria')} />
          <div className="odiwm-range-hints"><span>0 h</span><span>{t('irrigationWorldModel.controls.timingAssumption')}</span><span>12 h</span></div>
        </div>
        <div className="odiwm-control-block">
          <div className="odiwm-control-label"><GitBranch size={14} /><span>{t('irrigationWorldModel.controls.eastRatio')}</span><strong>{candidateEastRatio}%</strong></div>
          <input type="range" min="40" max="60" step="5" value={candidateEastRatio} onChange={event => setCandidateEastRatio(Number(event.target.value))} aria-label={t('irrigationWorldModel.controls.eastRatioAria')} />
          <div className="odiwm-range-hints"><span>40%</span><span>{t('irrigationWorldModel.controls.actionParameter')}</span><span>60%</span></div>
        </div>
        <div className="odiwm-control-block odiwm-horizon-control">
          <div className="odiwm-control-label"><CalendarDays size={14} /><span>{t('irrigationWorldModel.controls.horizon')}</span></div>
          <select value={horizon} onChange={event => setHorizon(Number(event.target.value) as Horizon)} aria-label={t('irrigationWorldModel.controls.horizon')}>
            <option value="6">{t('irrigationWorldModel.controls.futureHours', { hours: 6 })}</option>
            <option value="12">{t('irrigationWorldModel.controls.futureHours', { hours: 12 })}</option>
            <option value="24">{t('irrigationWorldModel.controls.futureHours', { hours: 24 })}</option>
          </select>
          <div className="odiwm-range-hints"><span>{t('irrigationWorldModel.controls.replayStep')}</span><span>{t('irrigationWorldModel.controls.scenarioAssessment')}</span></div>
        </div>
        <div className="odiwm-control-block odiwm-mode-control">
          <div className="odiwm-control-label"><GitBranch size={14} /><span>{t('irrigationWorldModel.controls.viewPlan')}</span></div>
          <div className="odiwm-segmented" role="tablist" aria-label={t('irrigationWorldModel.controls.viewPlan')}>
            {modes.map(mode => (
              <button key={mode.id} type="button" className={activeMode === mode.id ? 'active' : ''} onClick={() => setActiveMode(mode.id)} role="tab" aria-selected={activeMode === mode.id}>
                <span>{mode.label}</span><small>{t(`irrigationWorldModel.modes.${mode.id}`, { defaultValue: mode.note })}</small>
              </button>
            ))}
          </div>
        </div>
        <button className="odiwm-reset-button" type="button" onClick={reset} title={t('irrigationWorldModel.controls.resetTitle')}><RotateCcw size={14} />{t('irrigationWorldModel.controls.reset')}</button>
      </section>

      {dirty && <div className="odiwm-dirty-banner"><Info size={14} />{t('irrigationWorldModel.dirty')}</div>}
      {serviceError && <div className="odiwm-dirty-banner"><AlertTriangle size={14} />{t('irrigationWorldModel.backendError', { message: serviceError })}</div>}

      <section className="odiwm-run-context" aria-label={t('irrigationWorldModel.runContext')}>
        <div className="odiwm-context-card"><span className="odiwm-context-icon"><CalendarDays size={14} /></span><div><small>{t('irrigationWorldModel.context.snapshot')}</small><strong>{formatDate(run.state_snapshot.effective_at, { dateStyle: 'medium', timeStyle: 'short', hour12: false })} · {run.state_snapshot.snapshot_id}</strong></div></div>
        <div className="odiwm-context-card"><span className="odiwm-context-icon"><ClipboardCheck size={14} /></span><div><small>{t('irrigationWorldModel.context.dataQuality')}</small><strong>{run.state_snapshot.quality_label}</strong></div><span className="odiwm-context-status warn">{t('irrigationWorldModel.context.needsCalibration')}</span></div>
        <div className="odiwm-context-card"><span className="odiwm-context-icon"><LockKeyhole size={14} /></span><div><small>{t('irrigationWorldModel.context.runtimePermission')}</small><strong>{t('irrigationWorldModel.context.proposalOnly')}</strong></div><span className="odiwm-context-status ok">{t('irrigationWorldModel.context.noControl')}</span></div>
        <div className="odiwm-context-card"><span className="odiwm-context-icon"><Activity size={14} /></span><div><small>{t('irrigationWorldModel.context.backendRun')}</small><strong>{run.run_id}</strong></div><span className="odiwm-context-status ok">{t('irrigationWorldModel.context.steps', { count: format(run.model.numerical_evidence.timestep_count) })}</span></div>
      </section>

      <section className="odiwm-pipeline-strip" aria-label={t('irrigationWorldModelLabels.runPipeline')}>
        {run.pipeline.map(stage => {
          const status = stage.key === 'proposal' ? proposalStatusLabel[proposalStatus] : stage.status;
          return <div key={stage.key} className={status === tx('irrigationWorldModel.pipeline.blocked') ? 'blocked' : status === tx('irrigationWorldModel.pipeline.idle') ? 'idle' : 'done'}><b>{stage.index}</b><span><strong>{stage.label}</strong><small>{status}</small></span></div>;
        })}
      </section>

      <section className="odiwm-main-grid">
        <div className="odiwm-network-panel">
          <div className="odiwm-section-heading"><div><strong>{t('irrigationWorldModel.network.title')}</strong><span>{t('irrigationWorldModel.network.description')}</span></div><span className="odiwm-live-tag"><CircleDot size={10} />{t('irrigationWorldModel.network.frozen')}</span></div>
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
          <div className="odiwm-network-legend"><span><i className="legend-dot object" />{t('irrigationWorldModel.network.legendObject')}</span><span><i className="legend-dot state" />{t('irrigationWorldModel.network.legendState')}</span><span><i className="legend-dot action" />{t('irrigationWorldModel.network.legendAction')}</span><span><i className="legend-dot constraint" />{t('irrigationWorldModel.network.legendConstraint')}</span></div>
        </div>

        <aside className="odiwm-detail-panel">
          <div className="odiwm-section-heading"><div><strong>{t('irrigationWorldModel.detail.title')}</strong><span>{t('irrigationWorldModel.detail.description')}</span></div><span className="odiwm-version-tag">v{bootstrap.ontology_profile.version}</span></div>
          <div className="odiwm-detail-object-head"><span className="odiwm-object-icon"><Layers3 size={15} /></span><div><strong>{selectedNode?.label || selectedNodeId}</strong><span>{selectedNode?.type} · {selectedNodeId}</span></div></div>
          <div className="odiwm-detail-tabs" role="tablist">
            {(['object', 'link', 'state', 'action', 'constraint', 'evidence'] as DetailTab[]).map(tab => {
              return <button key={tab} type="button" className={detailTab === tab ? 'active' : ''} onClick={() => setDetailTab(tab)} role="tab" aria-selected={detailTab === tab}>{t(`irrigationWorldModelLabels.detailTabs.${tab}`)}</button>;
            })}
          </div>
          <DetailBody tab={detailTab} node={selectedNode} nodeId={selectedNodeId} result={selectedResult} links={bootstrap.links} westShift={displayedWestShift} horizon={committedHorizon} ontologyVersion={`${bootstrap.ontology_profile.profile_id}:${bootstrap.ontology_profile.version}`} />
        </aside>
      </section>

      <section className="odiwm-results-panel">
        <div className="odiwm-section-heading"><div><strong>{t('irrigationWorldModel.results.title')}</strong><span>{t('irrigationWorldModel.results.runVersion', { version: run.version, id: run.run_id })}</span></div><span className="odiwm-compute-tag"><Gauge size={12} />{t('irrigationWorldModel.results.computeTag')}</span></div>
        <div className="odiwm-results-table-wrap">
          <table className="odiwm-results-table">
            <thead><tr><th>{t('irrigationWorldModel.results.metric')}</th>{results.map(result => <th key={result.mode} className={activeMode === result.mode ? 'active-col' : ''}>{result.label}</th>)}</tr></thead>
            <tbody>
              <MetricRow label={t('irrigationWorldModel.metrics.delivered')} values={results.map(result => `${format(result.delivered)} m³/d`)} activeMode={activeMode} />
              <MetricRow label={t('irrigationWorldModel.metrics.shortage')} values={results.map(result => `${format(result.shortage)} m³/d`)} activeMode={activeMode} tone="warning" />
              <MetricRow label={t('irrigationWorldModel.metrics.tailCoverage')} values={results.map(result => `${format(result.tailCoverage, 1)}%`)} activeMode={activeMode} />
              <MetricRow label={t('irrigationWorldModel.metrics.fairness')} values={results.map(result => format(result.fairnessCv, 3))} activeMode={activeMode} />
              <MetricRow label={t('irrigationWorldModel.metrics.capacityViolations')} values={results.map(result => result.capacityViolations ? t('irrigationWorldModel.metrics.items', { count: result.capacityViolations }) : t('irrigationWorldModel.metrics.zeroItems'))} activeMode={activeMode} tone="constraint" />
              <MetricRow label={t('irrigationWorldModel.metrics.residual')} values={results.map(result => `${format(result.residual, 3)} m³/d`)} activeMode={activeMode} />
            </tbody>
          </table>
        </div>
        <div className="odiwm-result-notes">
          <span><CheckCircle2 size={13} />{t('irrigationWorldModel.results.continuityResidual', { value: format(selectedResult.residualVolumeM3, 4) })}</span>
          <span><Timer size={13} />{t('irrigationWorldModel.results.runtime', { steps: format(selectedResult.numerical.timestep_count), ms: format(selectedResult.numerical.runtime_ms, 1) })}</span>
          <span><Waves size={13} />{t('irrigationWorldModel.results.depthRange', { min: format(selectedResult.numerical.minimum_depth_m, 3), max: format(selectedResult.numerical.maximum_depth_m, 3) })}</span>
          <span><AlertTriangle size={13} />{t('irrigationWorldModel.results.capacityBoundary')}</span>
        </div>
      </section>

      <section className="odiwm-timeline-panel">
        <div className="odiwm-section-heading"><div><strong>{t('irrigationWorldModel.timeline.title', { label: selectedResult.label })}</strong><span>{t('irrigationWorldModel.timeline.description')}</span></div><span className="odiwm-compute-tag"><Timer size={12} />{t('irrigationWorldModelLabels.timeWindow', { start: 0, end: committedHorizon })}</span></div>
        <div className="odiwm-timeline-grid">
          {selectedResult.timeline.map(point => { const statusKey = timelineStatusKey(point.status); return <div key={point.hour} className="odiwm-timeline-point"><div className="odiwm-timeline-hour">T+{point.hour} h</div><div className="odiwm-timeline-bar"><span style={{ width: `${Math.max(4, point.tailCoverage)}%` }} /></div><strong>{format(point.tailCoverage, 1)}%</strong><small>{t('irrigationWorldModel.timeline.tailCoverage')}</small><em className={statusKey === 'assessable' ? 'ready' : statusKey === 'partial' ? 'partial' : 'waiting'}>{t(`irrigationWorldModel.timeline.status.${statusKey}`)}</em><span className="odiwm-timeline-shortage">{t('irrigationWorldModel.timeline.shortage', { value: format(point.shortage) })} m³/d</span></div>; })}
        </div>
      </section>

      <section className="odiwm-proposal-grid">
        <div className="odiwm-proposal-card">
          <div className="odiwm-section-heading"><div><strong>{t('irrigationWorldModelLabels.proposal', { mode: modes.find(mode => mode.id === run.proposal.candidate_mode)?.label || run.proposal.candidate_mode })}</strong><span>{t('irrigationWorldModel.proposal.ranking', { id: run.proposal.proposal_id })}</span></div><span className={`odiwm-review-tag ${proposalStatus === 'approved' ? 'approved' : proposalStatus === 'returned' ? 'returned' : ''}`}><AlertTriangle size={12} />{proposalStatusLabel[proposalStatus]}</span></div>
          <div className="odiwm-action-list">
            {run.proposal.actions.map(action => <div key={action.order}><span className="action-index">{action.order}</span><span>{action.summary}</span></div>)}
          </div>
          <div className="odiwm-review-form">
            <label htmlFor="odiwm-review-note"><MessageSquareText size={13} />{t('irrigationWorldModel.review.label')}</label>
            <textarea id="odiwm-review-note" value={reviewNote} onChange={event => setReviewNote(event.target.value)} rows={2} disabled={proposalStatus !== 'pending' || isReviewing} />
            <div className="odiwm-review-actions"><button type="button" className="odiwm-return-button" onClick={() => reviewProposal('returned')} disabled={proposalStatus !== 'pending' || isReviewing}><AlertTriangle size={13} />{t('irrigationWorldModel.review.return')}</button><button type="button" className="odiwm-approve-button" onClick={() => reviewProposal('approved')} disabled={proposalStatus !== 'pending' || isReviewing}><FileCheck2 size={13} />{t('irrigationWorldModel.review.approve')}</button></div>
          </div>
          <div className="odiwm-no-control"><ShieldCheck size={14} /><strong>{t('irrigationWorldModel.review.noControlTitle')}</strong><span>{t('irrigationWorldModel.review.noControlDescription')}</span></div>
        </div>
        <div className="odiwm-evidence-card">
          <div className="odiwm-section-heading"><div><strong>{t('irrigationWorldModel.evidence.title')}</strong><span>{t('irrigationWorldModel.evidence.description')}</span></div><Info size={14} /></div>
          <dl className="odiwm-evidence-list">
            <div><dt>{t('irrigationWorldModelLabels.evidence.ontologyProfile')}</dt><dd>{bootstrap.ontology_profile.profile_id}:{bootstrap.ontology_profile.version}</dd></div>
            <div><dt>{t('irrigationWorldModelLabels.evidence.ontologyPackage')}</dt><dd>{bootstrap.ontology_profile.content_sha256.slice(0, 16)}</dd></div>
            <div><dt>{t('irrigationWorldModelLabels.evidence.dataSource')}</dt><dd>{run.claim_boundary.data}</dd></div>
            <div><dt>{t('irrigationWorldModelLabels.evidence.kernel')}</dt><dd>{run.model.model_id}:{run.model.version}</dd></div>
            <div><dt>{t('irrigationWorldModelLabels.evidence.stateTransition')}</dt><dd>{run.model.numerical_evidence.equations}</dd></div>
            <div><dt>{t('irrigationWorldModelLabels.evidence.execution')}</dt><dd>{t('irrigationWorldModel.evidence.execution', { steps: format(run.model.numerical_evidence.timestep_count), ms: format(run.model.numerical_evidence.runtime_ms, 1) })}</dd></div>
            <div><dt>{t('irrigationWorldModelLabels.evidence.planner')}</dt><dd>{run.planner?.planner_id || 'legacy-run-metadata'} · {run.planner?.selected_mode || run.proposal.candidate_mode}</dd></div>
            <div><dt>{t('irrigationWorldModelLabels.evidence.claim')}</dt><dd>{run.claim_boundary.claim}</dd></div>
            <div><dt>{t('irrigationWorldModelLabels.evidence.uncertainty')}</dt><dd>{run.claim_boundary.calibration}</dd></div>
          </dl>
          <div className="odiwm-audit-list"><div className="odiwm-audit-title"><ClipboardCheck size={13} />{t('irrigationWorldModel.evidence.audit')}</div>{auditEvents.slice(-5).map((event, index) => { const statusKey = auditStatusKey(event.status); return <div className="odiwm-audit-event" key={`${event.time}-${event.step}-${index}`}><span>{event.time}</span><strong>{event.step}</strong><em className={statusKey === 'passed' ? 'ok' : statusKey === 'review' ? 'wait' : ''}>{t(`irrigationWorldModel.auditStatus.${statusKey}`)}</em><small>{event.detail}</small></div>; })}</div>
        </div>
      </section>
    </div>
  );
}

function BranchNetwork({ branch, selectedNodeId, onSelect, result, nodeById }: { branch: 'east' | 'west'; selectedNodeId: string; onSelect: (id: string) => void; result: ScenarioResult; nodeById: Record<string, Node> }) {
  const ids = branch === 'east' ? ['C2', 'D1', 'F1', 'F2'] : ['C3', 'D2', 'F3', 'F4'];
  const label = branch === 'east' ? tx('irrigationWorldModel.network.eastBranch') : tx('irrigationWorldModel.network.westBranch');
  return (
    <div className={`odiwm-branch ${branch}`}>
      <div className="odiwm-branch-label"><span>{label}</span><small>{tx('irrigationWorldModel.network.allocation', { value: branch === 'east' ? `${format(result.branchRatio * 100, 1)}%` : `${format((1 - result.branchRatio) * 100, 1)}%` })}</small></div>
      <div className="odiwm-branch-chain">
        <button type="button" className={`odiwm-node odiwm-node-compact ${selectedNodeId === ids[0] ? 'selected' : ''}`} onClick={() => onSelect(ids[0])}><Waves size={14} /><span><strong>{ids[0]}</strong><small>{nodeById[ids[0]]?.label}</small></span><em>{valueForNode(ids[0], result)}</em></button>
        <span className="odiwm-branch-line"><ChevronRight size={15} /></span>
        <button type="button" className={`odiwm-node odiwm-node-compact ${selectedNodeId === ids[1] ? 'selected' : ''}`} onClick={() => onSelect(ids[1])}><Gauge size={14} /><span><strong>{ids[1]}</strong><small>{nodeById[ids[1]]?.label}</small></span><em>{valueForNode(ids[1], result)}</em></button>
      </div>
      <div className="odiwm-field-line"><span className="odiwm-field-stem" />{ids.slice(2).map(fieldId => <button type="button" key={fieldId} className={`odiwm-field-node ${selectedNodeId === fieldId ? 'selected' : ''}`} onClick={() => onSelect(fieldId)}><span>{fieldId}</span><small>{format(result.fields[fieldId].coverage * 100, 1)}% {tx('irrigationWorldModel.network.coverage')}</small></button>)}</div>
    </div>
  );
}

function DetailBody({ tab, node, nodeId, result, links, westShift, horizon, ontologyVersion }: { tab: DetailTab; node?: Node; nodeId: string; result: ScenarioResult; links: OntologyLink[]; westShift: number; horizon: Horizon; ontologyVersion: string }) {
  if (!node) return <div className="odiwm-detail-empty">{tx('irrigationWorldModel.detail.selectObject')}</div>;
  const incoming = links.filter(link => link.object === nodeId).map(link => `${link.subject} ${link.predicate} ${nodeId}`);
  const outgoing = links.filter(link => link.subject === nodeId).map(link => `${nodeId} ${link.predicate} ${link.object}`);
  if (tab === 'object') return <div className="odiwm-detail-body"><DetailRow label={tx('irrigationWorldModel.detail.stableId')} value={node.stable_id} /><DetailRow label={tx('irrigationWorldModel.detail.type')} value={node.type} /><DetailRow label={tx('irrigationWorldModel.detail.role')} value={node.role} /><DetailRow label={tx('irrigationWorldModel.detail.ontologyVersion')} value={ontologyVersion} /></div>;
  if (tab === 'link') return <div className="odiwm-detail-body"><DetailRow label={tx('irrigationWorldModel.detail.incoming')} value={incoming.join('；') || tx('irrigationWorldModel.detail.noBoundarySource')} /><DetailRow label={tx('irrigationWorldModel.detail.outgoing')} value={outgoing.join('；') || tx('irrigationWorldModel.common.none')} /><DetailRow label={tx('irrigationWorldModel.detail.authority')} value={links.find(link => link.subject === nodeId || link.object === nodeId)?.authority || tx('irrigationWorldModel.detail.unpublished')} /></div>;
  if (tab === 'state') return <div className="odiwm-detail-body"><DetailRow label={tx('irrigationWorldModel.detail.currentState')} value={node.state} /><DetailRow label={tx('irrigationWorldModel.detail.stateValue')} value={valueForNode(nodeId, result)} /><DetailRow label={tx('irrigationWorldModel.detail.timeWindow')} value={tx('irrigationWorldModelLabels.timeWindow', { start: 0, end: horizon })} /><DetailRow label={tx('irrigationWorldModel.detail.propagationDelay')} value={nodeId === 'C3' || nodeId === 'D2' ? tx('irrigationWorldModel.detail.assumptionDelay', { hours: result.westDelay }) : tx('irrigationWorldModel.detail.topologyComputed')} /><DetailRow label={tx('irrigationWorldModel.detail.qualityFlag')} value={tx('irrigationWorldModel.detail.syntheticUncalibrated')} tone="warning" /></div>;
  if (tab === 'action') return <div className="odiwm-detail-body"><DetailRow label={tx('irrigationWorldModel.detail.candidateAction')} value={nodeId === 'D2' || nodeId === 'C3' ? tx('irrigationWorldModel.detail.westShiftAction', { hours: westShift }) : nodeId === 'D1' || nodeId === 'C2' ? tx('irrigationWorldModel.detail.eastRatioAction', { ratio: format(result.branchRatio * 100, 1) }) : tx('irrigationWorldModel.detail.noChange')} /><DetailRow label={tx('irrigationWorldModel.detail.executionMethod')} value={tx('irrigationWorldModel.detail.proposalOnly')} /><DetailRow label={tx('irrigationWorldModel.detail.humanReview')} value={tx('irrigationWorldModel.detail.required')} /></div>;
  if (tab === 'constraint') return <div className="odiwm-detail-body"><DetailRow label={tx('irrigationWorldModel.detail.capacityLimit')} value={node.capacity ? `${format(node.capacity)} m³/d` : tx('irrigationWorldModel.detail.ruleConstrained')} /><DetailRow label={tx('irrigationWorldModel.detail.constraintResult')} value={node.capacity && (nodeId === 'C2' || nodeId === 'C3') ? (result.capacityViolations ? tx('irrigationWorldModel.detail.blockAndReview') : tx('irrigationWorldModel.detail.passed')) : tx('irrigationWorldModel.detail.passedPendingCalibration')} tone={result.capacityViolations ? 'warning' : 'ok'} /><DetailRow label={tx('irrigationWorldModel.detail.conservationResidual')} value={`${format(result.residual, 3)} m³/d`} /></div>;
  return <div className="odiwm-detail-body"><DetailRow label={tx('irrigationWorldModel.detail.evidenceType')} value={tx('irrigationWorldModel.detail.syntheticExplicit')} /><DetailRow label={tx('irrigationWorldModel.detail.sourceId')} value="synthetic_seed_dataset" /><DetailRow label={tx('irrigationWorldModel.detail.supportedConclusion')} value={tx('irrigationWorldModel.detail.modelConditionComparison')} /><DetailRow label={tx('irrigationWorldModel.detail.unsupportedConclusion')} value={tx('irrigationWorldModel.detail.realSchedulingCommitment')} /></div>;
}

function DetailRow({ label, value, tone }: { label: string; value: string; tone?: 'ok' | 'warning' }) {
  return <div className="odiwm-detail-row"><dt>{label}</dt><dd className={tone ? `tone-${tone}` : ''}>{value}</dd></div>;
}

function MetricRow({ label, values, activeMode, tone }: { label: string; values: string[]; activeMode: Mode; tone?: 'warning' | 'constraint' }) {
  return <tr><th>{label}</th>{values.map((value, index) => { const mode = (['baseline', 'candidateA', 'candidateB'] as Mode[])[index]; return <td key={mode} className={`${activeMode === mode ? 'active-col' : ''} ${tone ? `metric-${tone}` : ''}`}>{value}</td>; })}</tr>;
}
