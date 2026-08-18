import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { createPortal } from 'react-dom';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Database,
  ExternalLink,
  FlaskConical,
  Gauge,
  GitCompareArrows,
  Layers3,
  Map,
  Maximize2,
  Minimize2,
  Network,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Workflow,
  XCircle,
} from 'lucide-react';
import { formatDate, formatNumber, getLocaleHeaders } from '../../i18n';

type TwmDestination = 'overview' | 'operate' | 'data';
type TwmMapStage = 'locate' | 'risk' | 'plan';
type Row = Record<string, any>;

interface TwmExecutiveDemoPanelProps {
  onNavigate: (destination: TwmDestination) => void;
  onMapStage: (stage: TwmMapStage) => void;
}

const rows = <T = Row,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];

const signed = (value: unknown, digits = 3) => {
  const number = Number(value || 0);
  return `${number > 0 ? '+' : ''}${number.toFixed(digits)}`;
};

const compactNumber = (value: unknown) => formatNumber(Number(value || 0));

const statusLabel = (value: unknown, t: (key: string) => string) => {
  const status = String(value || 'review');
  if (status === 'verified_offline_run') return t('territoryWorldModel.briefing.status.verified');
  if (status === 'engineering_ready') return t('territoryWorldModel.briefing.status.engineeringReady');
  if (status === 'compiled_not_admitted') return t('territoryWorldModel.briefing.status.compiledNotAdmitted');
  if (status === 'not_admitted') return t('territoryWorldModel.briefing.status.notAdmitted');
  return t('territoryWorldModel.briefing.status.review');
};

const statusTone = (value: unknown) => {
  const status = String(value || 'review');
  if (status === 'verified_offline_run') return 'verified';
  if (status === 'engineering_ready') return 'ready';
  if (status === 'compiled_not_admitted' || status === 'not_admitted') return 'blocked';
  return 'review';
};

export default function TwmExecutiveDemoPanel({ onNavigate, onMapStage }: TwmExecutiveDemoPanelProps) {
  const { t } = useTranslation();
  const [report, setReport] = useState<Row | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [presentationMode, setPresentationMode] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/twm/executive-demo-report', { credentials: 'include', headers: getLocaleHeaders() });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || t('territoryWorldModel.briefing.errors.unavailable'));
      setReport(payload);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : t('territoryWorldModel.briefing.errors.unavailable'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPresentationMode(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const positioning = report?.positioning || {};
  const gwmDefinition = report?.gwm_definition || {};
  const simulator = report?.simulator || {};
  const architecture = report?.architecture || {};
  const paper9 = report?.paper9v2 || {};
  const foundation = report?.twm_foundation || {};
  const eventCompilation = report?.natural_resource_event_compilation || {};
  const benchmark = report?.gwm_benchmark || {};
  const claimBoundary = report?.claim_boundary || {};
  const geososComparison = report?.geosos_flus_comparison || {};
  const generatedAt = useMemo(() => {
    if (!report?.generated_at) return '-';
    const value = new Date(report.generated_at);
    return Number.isNaN(value.getTime()) ? '-' : formatDate(value, { dateStyle: 'medium', timeStyle: 'short', hour12: false });
  }, [report?.generated_at]);

  const openMapStory = () => {
    onNavigate('overview');
    onMapStage('locate');
  };

  if (loading && !report) {
    return <div className="twm-briefing-loading" aria-live="polite"><RefreshCw size={17} className="spin" />{t('territoryWorldModel.briefing.loading')}</div>;
  }

  const content = (
    <div className={`twm-briefing ${presentationMode ? 'presentation' : ''}`} data-testid="twm-executive-demo">
      <section className="twm-briefing-verdict">
        <div className="twm-briefing-verdict-icon"><ShieldCheck size={22} /></div>
        <div>
          <span className="twm-briefing-eyebrow">{t('territoryWorldModel.briefing.evidenceStatus')}</span>
          <h3>{positioning.verdict || t('territoryWorldModel.briefing.pendingVerification')}</h3>
          <p>{positioning.title || t('territoryWorldModel.briefing.title')}</p>
        </div>
        <div className="twm-briefing-verdict-meta">
          <span className="twm-briefing-status controlled">{t('territoryWorldModel.briefing.controlledDemo')}</span>
          <span className="twm-briefing-status production-blocked">{t('territoryWorldModel.briefing.productionClaimsClosed')}</span>
          <small>{t('territoryWorldModel.briefing.evidenceRefresh', { time: generatedAt })}</small>
          <button type="button" className="twm-briefing-icon-button" onClick={load} disabled={loading} title={t('territoryWorldModel.briefing.recheckEvidence')}>
            <RefreshCw size={14} className={loading ? 'spin' : ''} />
          </button>
          <button
            type="button"
            className="twm-briefing-icon-button"
            onClick={() => setPresentationMode(value => !value)}
            title={presentationMode ? t('territoryWorldModel.briefing.exitPresentation') : t('territoryWorldModel.briefing.enterPresentation')}
            aria-label={presentationMode ? t('territoryWorldModel.briefing.exitPresentation') : t('territoryWorldModel.briefing.enterPresentation')}
          >
            {presentationMode ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
        </div>
      </section>

      {error && <div className="twm-briefing-message error"><AlertTriangle size={16} />{error}</div>}

      <section className="twm-briefing-section twm-briefing-opening">
        <div className="twm-briefing-section-head">
          <Workflow size={17} />
          <div><h4>{t('territoryWorldModel.briefing.openingTitle')}</h4><p>{t('territoryWorldModel.briefing.openingDescription')}</p></div>
        </div>
        <div className="twm-briefing-story" aria-label={t('territoryWorldModel.briefing.decisionLoopAria')}>
          {rows(report?.decision_story).map((item, index, items) => (
            <div className="twm-briefing-story-step" key={item.id}>
              <span>{index + 1}</span>
              <strong>{item.label}</strong>
              <small>{item.detail}</small>
              {index < items.length - 1 && <ArrowRight size={15} aria-hidden="true" />}
            </div>
          ))}
        </div>
      </section>

      <section className="twm-briefing-section">
        <div className="twm-briefing-section-head">
          <Sparkles size={17} />
          <div><h4>{t('territoryWorldModel.briefing.worldModelPositionTitle')}</h4><p>{t('territoryWorldModel.briefing.worldModelPositionDescription')}</p></div>
        </div>
        <div className="twm-briefing-world-grid">
          {rows(report?.world_model_positioning).map(item => (
            <div key={item.family}>
              <strong>{item.family}</strong>
              <span>{item.focus}</span>
              <p>{item.gwm_difference}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="twm-briefing-section" data-testid="twm-gwm-definition">
        <div className="twm-briefing-section-head">
          <Network size={17} />
          <div><h4>{t('territoryWorldModel.briefing.formalDefinitionTitle')}</h4><p>{gwmDefinition.formal_definition}</p></div>
        </div>
        <p className="twm-briefing-boundary"><ShieldAlert size={14} />{gwmDefinition.not_coordinate_appendage}</p>
        <div className="twm-briefing-world-grid">
          {rows(gwmDefinition.fusion_dimensions).map(item => (
            <div key={item.dimension}>
              <strong>{item.dimension}</strong>
              <span>{item.geospatial_capability}</span>
              <p>{item.runtime_effect}</p>
            </div>
          ))}
        </div>
        <p className="twm-briefing-boundary"><CheckCircle2 size={14} />{gwmDefinition.distinctive_value}</p>
      </section>

      <section className="twm-briefing-section" data-testid="twm-simulator-mechanism">
        <div className="twm-briefing-section-head">
          <Workflow size={17} />
          <div><h4>{t('territoryWorldModel.briefing.simulatorTitle')}</h4><p>{simulator.definition}</p></div>
          <code>{simulator.transition_equation}</code>
        </div>
        <div className="twm-briefing-story" aria-label={t('territoryWorldModel.briefing.simulatorPipelineAria')}>
          {rows(simulator.pipeline).map((item, index, items) => (
            <div className="twm-briefing-story-step" key={item.id}>
              <span>{index + 1}</span>
              <strong>{item.label}</strong>
              <small>{item.detail}</small>
              {index < items.length - 1 && <ArrowRight size={15} aria-hidden="true" />}
            </div>
          ))}
        </div>
        <div className="twm-briefing-case-table-wrap">
          <table className="twm-briefing-table comparison">
            <thead><tr><th>{t('territoryWorldModel.briefing.transitionSource')}</th><th>{t('territoryWorldModel.briefing.applicableVariables')}</th><th>{t('territoryWorldModel.briefing.requiredTrace')}</th></tr></thead>
            <tbody>{rows(simulator.transition_sources).map(item => <tr key={item.source}><td><strong>{item.source}</strong></td><td>{item.use_for}</td><td>{item.trace}</td></tr>)}</tbody>
          </table>
        </div>
        <div className="twm-briefing-section-head">
          <GitCompareArrows size={17} />
          <div><h4>{t('territoryWorldModel.briefing.simulatorComparisonTitle')}</h4><p>{t('territoryWorldModel.briefing.simulatorComparisonDescription')}</p></div>
        </div>
        <div className="twm-briefing-case-table-wrap">
          <table className="twm-briefing-table comparison">
            <thead><tr><th>{t('territoryWorldModel.briefingExtras.simulator')}</th><th>{t('territoryWorldModel.briefing.state')}</th><th>{t('territoryWorldModel.briefing.action')}</th><th>{t('territoryWorldModel.briefing.output')}</th><th>{t('territoryWorldModel.briefing.gwmBoundary')}</th></tr></thead>
            <tbody>{rows(simulator.comparison).map(item => <tr key={item.family}><td><strong>{item.family}</strong></td><td>{item.state}</td><td>{item.action}</td><td>{item.output}</td><td>{item.gwm_difference}</td></tr>)}</tbody>
          </table>
        </div>
        <p className="twm-briefing-boundary"><ShieldAlert size={14} />{simulator.claim_boundary}</p>
      </section>

      <section className="twm-briefing-section">
        <div className="twm-briefing-section-head">
          <Network size={17} />
          <div><h4>{t('territoryWorldModel.briefing.architectureTitle')}</h4><p>{t('territoryWorldModel.briefing.architectureDescription')}</p></div>
        </div>
        <div className="twm-briefing-architecture">
          <div className="twm-briefing-architecture-lane kernel">
            <span>{t('territoryWorldModel.briefingExtras.geospatialKernel')}</span>
            <strong>DAM-GK</strong>
            <p>{architecture.dam_definition}</p>
            <div>{rows<string>(architecture.geospatial_kernel).map(item => <small key={item}>{item}</small>)}</div>
          </div>
          <ArrowRight size={22} className="twm-briefing-architecture-arrow" />
          <div className="twm-briefing-architecture-lane runtime">
            <span>{t('territoryWorldModel.briefingExtras.runtimeKernel')}</span>
            <strong>{t('territoryWorldModel.briefingExtras.runtimeStages')}</strong>
            <p>{architecture.boundary}</p>
            <div>{rows<string>(architecture.runtime_kernel).map(item => <small key={item}>{item}</small>)}</div>
          </div>
          <ArrowRight size={22} className="twm-briefing-architecture-arrow" />
          <div className="twm-briefing-architecture-lane domain">
            <span>{t('territoryWorldModel.briefing.domainInstance')}</span>
            <strong>TWM</strong>
            <p>{positioning.gwm_twm_relationship}</p>
            <div>{rows<string>(foundation.supported_chain).map(item => <small key={item}>{item}</small>)}</div>
          </div>
        </div>
      </section>

      <section className="twm-briefing-section" data-testid="twm-paper9-evidence">
        <div className="twm-briefing-section-head">
          <Gauge size={17} />
          <div><h4>{t('territoryWorldModel.briefing.paper9Title')}</h4><p>{t('territoryWorldModel.briefing.paper9Description')}</p></div>
          <div className="twm-briefing-source-status">
            <span className={`twm-briefing-status ${statusTone(paper9.status)}`}>{statusLabel(paper9.status, t)}</span>
            <small>{paper9.source_mode === 'live_offline_artifacts' ? t('territoryWorldModel.briefing.liveOffline') : t('territoryWorldModel.briefing.validationSnapshot', { date: paper9.source_date || '2026-06-27' })}</small>
          </div>
        </div>
        <div className="twm-briefing-paper9-layout">
          <div className="twm-briefing-problem">
            <strong>{t('territoryWorldModel.briefing.conventionalLimitations')}</strong>
            <p>{paper9.question}</p>
            <ul>{rows<string>(paper9.why_conventional_methods_are_insufficient).map(item => <li key={item}>{item}</li>)}</ul>
            <div className="twm-briefing-gates">
              {rows(paper9.hard_gates).map(gate => <span className={gate.passed ? 'pass' : 'fail'} key={gate.id}>{gate.passed ? <CheckCircle2 size={14} /> : <XCircle size={14} />}{gate.label}</span>)}
            </div>
          </div>
          <div className="twm-briefing-case-table-wrap">
            <table className="twm-briefing-table">
            <thead><tr><th>{t('territoryWorldModel.briefing.offlineCase')}</th><th>{t('territoryWorldModel.briefing.cultivatedArea')}</th><th>{t('territoryWorldModel.briefing.slope')}</th><th>{t('territoryWorldModel.briefing.contiguity')}</th><th>{t('territoryWorldModel.briefing.swaps')}</th></tr></thead>
              <tbody>{rows(paper9.cases).map(item => (
                <tr key={item.id}>
                  <td><strong>{item.label}</strong><small>{item.hard_constraint_passed ? t('territoryWorldModel.briefing.constraintsPassed') : t('territoryWorldModel.briefing.status.review')}</small></td>
                  <td className="positive">{signed(item.cultivated_area_change_ha)} ha</td>
                  <td className="positive">{signed(item.slope_change_pct)}%</td>
                  <td className="positive">{signed(item.contiguity_change, 4)}</td>
                  <td>{t('territoryWorldModel.briefing.swapCount', { count: compactNumber(item.swaps_completed) })}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </div>
        <p className="twm-briefing-boundary"><ShieldAlert size={14} />{paper9.claim_boundary}</p>
      </section>

      <section className="twm-briefing-section">
        <div className="twm-briefing-section-head">
          <GitCompareArrows size={17} />
          <div><h4>{t('territoryWorldModel.briefing.geososTitle')}</h4><p>{geososComparison.benchmark_role}</p></div>
        </div>
        <div className="twm-briefing-case-table-wrap">
          <table className="twm-briefing-table comparison">
            <thead><tr><th>{t('territoryWorldModel.briefing.comparisonDimension')}</th><th>GeoSOS-FLUS</th><th>TWM / GWM</th></tr></thead>
            <tbody>{rows(geososComparison.dimensions).map(item => <tr key={item.dimension}><td><strong>{item.dimension}</strong></td><td>{item.geosos_flus}</td><td>{item.twm}</td></tr>)}</tbody>
          </table>
        </div>
        <p className="twm-briefing-boundary"><ShieldAlert size={14} />{geososComparison.verdict}</p>
      </section>

      <section className="twm-briefing-section" data-testid="twm-foundation-evidence">
        <div className="twm-briefing-section-head">
          <Database size={17} />
          <div><h4>{t('territoryWorldModel.briefing.foundationTitle')}</h4><p>{t('territoryWorldModel.briefing.foundationDescription')}</p></div>
          <span className={`twm-briefing-status ${statusTone(foundation.status)}`}>{statusLabel(foundation.status, t)}</span>
        </div>
        <div className="twm-briefing-kpis">
          <div><span>{t('territoryWorldModel.briefing.controlledRecords')}</span><strong>{compactNumber(foundation.record_count)}</strong><small>{foundation.dataset_id}</small></div>
          <div><span>{t('territoryWorldModel.briefing.spatialFeatures')}</span><strong>{compactNumber(foundation.spatial_feature_count)}</strong><small>{t('territoryWorldModel.briefing.objectRelationBase')}</small></div>
          <div><span>{t('territoryWorldModel.briefing.syntheticTimeSeries')}</span><strong>{compactNumber(foundation.synthetic_experiment?.row_count)}</strong><small>{t('territoryWorldModel.briefing.pairRegionCount', { pairs: foundation.synthetic_experiment?.pair_count || 0, regions: foundation.synthetic_experiment?.region_count || 0 })}</small></div>
          <div className="blocked"><span>{t('territoryWorldModel.briefing.productionHistory')}</span><strong>{compactNumber(foundation.production_observed_history_rows)}</strong><small>{t('territoryWorldModel.briefing.provincialPilotRequired')}</small></div>
          <div className="blocked"><span>{t('territoryWorldModel.briefing.productionActionHistory')}</span><strong>{compactNumber(foundation.production_policy_history_rows)}</strong><small>{t('territoryWorldModel.briefing.actionCalibrationBlocker')}</small></div>
        </div>
        <p className="twm-briefing-boundary"><ShieldAlert size={14} />{foundation.claim_boundary}</p>
      </section>

      <section className="twm-briefing-section" data-testid="twm-event-compilation">
        <div className="twm-briefing-section-head">
          <Layers3 size={17} />
          <div><h4>{t('territoryWorldModel.briefing.eventCompilationTitle')}</h4><p>{t('territoryWorldModel.briefing.eventCompilationDescription')}</p></div>
          <span className={`twm-briefing-status ${statusTone(eventCompilation.status)}`}>{statusLabel(eventCompilation.status, t)}</span>
        </div>
        <div className="twm-briefing-event-chain">
          {rows(eventCompilation.pipeline).map((item, index, items) => <div key={item.id}><span>{item.label}</span><strong>{compactNumber(item.count)}</strong>{index < items.length - 1 && <ArrowRight size={15} />}</div>)}
        </div>
        <div className="twm-briefing-gate-strip">
          <span className={eventCompilation.spatial_sampling_ready ? 'pass' : 'fail'}>{eventCompilation.spatial_sampling_ready ? <CheckCircle2 size={14} /> : <XCircle size={14} />}{t('territoryWorldModel.briefing.spatialSampling')}</span>
          <span className={eventCompilation.comparison_candidate_ready ? 'pass' : 'fail'}>{eventCompilation.comparison_candidate_ready ? <CheckCircle2 size={14} /> : <XCircle size={14} />}{t('territoryWorldModel.briefing.comparisonCandidate')}</span>
          <span className={eventCompilation.comparison_design_complete ? 'pass' : 'fail'}>{eventCompilation.comparison_design_complete ? <CheckCircle2 size={14} /> : <XCircle size={14} />}{t('territoryWorldModel.briefing.comparisonDesign')}</span>
          <span className={eventCompilation.training_admission ? 'pass' : 'fail'}>{eventCompilation.training_admission ? <CheckCircle2 size={14} /> : <XCircle size={14} />}{t('territoryWorldModel.briefing.trainingAdmission')}</span>
        </div>
        <p className="twm-briefing-boundary"><ShieldAlert size={14} />{eventCompilation.claim_boundary}</p>
      </section>

      <section className="twm-briefing-section" data-testid="twm-benchmark-evidence">
        <div className="twm-briefing-section-head">
          <FlaskConical size={17} />
          <div><h4>{t('territoryWorldModel.briefing.benchmarkTitle')}</h4><p>{t('territoryWorldModel.briefing.benchmarkDescription')}</p></div>
          <span className={`twm-briefing-status ${statusTone(benchmark.status)}`}>{statusLabel(benchmark.status, t)}</span>
        </div>
        <div className="twm-briefing-benchmark-layout">
          <div className="twm-briefing-benchmark-matrix">
            {rows(benchmark.matrix).map(item => <div key={item.id} className={item.passed ? 'pass' : 'fail'}><span>{item.direction}</span><strong>{item.label}</strong><em>{item.pass_count}/{item.seed_count}</em></div>)}
          </div>
          <div className="twm-briefing-v03">
            <span>{t('territoryWorldModel.briefing.v03Snapshot')}</span>
            <strong>{benchmark.candidate_v03?.status === 'synchronized_snapshot_incomplete' ? t('territoryWorldModel.briefing.snapshotIncomplete') : benchmark.candidate_v03?.status ? t(`statusLabels.${benchmark.candidate_v03.status}`, { defaultValue: benchmark.candidate_v03.status }) : t('territoryWorldModel.briefing.pendingVerification')}</strong>
            <dl>
              <div><dt>{t('territoryWorldModel.briefing.compiledObjects')}</dt><dd>{compactNumber(benchmark.candidate_v03?.compiled_object_count)}</dd></div>
              <div><dt>{t('territoryWorldModel.briefingExtras.forcingCertificate')}</dt><dd className="fail">{benchmark.candidate_v03?.forcing_certificate || '-'}</dd></div>
              <div><dt>{t('territoryWorldModel.briefingExtras.topologyCertificate')}</dt><dd className="fail">{benchmark.candidate_v03?.topology_certificate || '-'}</dd></div>
              <div><dt>{t('territoryWorldModel.briefing.trainingInputAdmission')}</dt><dd className="fail">{benchmark.candidate_v03?.training_input_admitted ? t('territoryWorldModel.briefing.pass') : t('territoryWorldModel.briefing.fail')}</dd></div>
            </dl>
          </div>
        </div>
        <p className="twm-briefing-boundary"><ShieldAlert size={14} />{benchmark.claim_boundary}</p>
      </section>

      <section className="twm-briefing-section">
        <div className="twm-briefing-section-head">
          <ShieldCheck size={17} />
          <div><h4>{t('territoryWorldModel.briefing.claimBoundaryTitle')}</h4><p>{t('territoryWorldModel.briefing.claimBoundaryDescription')}</p></div>
        </div>
        <div className="twm-briefing-claim-grid">
          <div className="can"><strong><CheckCircle2 size={16} />{t('territoryWorldModel.briefing.canDemonstrate')}</strong>{rows<string>(claimBoundary.can_demonstrate).map(item => <p key={item}>{item}</p>)}</div>
          <div className="cannot"><strong><XCircle size={16} />{t('territoryWorldModel.briefing.cannotClaim')}</strong>{rows<string>(claimBoundary.cannot_claim).map(item => <p key={item}>{item}</p>)}</div>
        </div>
      </section>

      <section className="twm-briefing-section">
        <div className="twm-briefing-section-head">
          <Database size={17} />
          <div><h4>{t('territoryWorldModel.briefing.pilotTitle')}</h4><p>{t('territoryWorldModel.briefing.pilotDescription')}</p></div>
        </div>
        <div className="twm-briefing-case-table-wrap">
          <table className="twm-briefing-table pilot">
            <thead><tr><th>{t('territoryWorldModel.briefing.priority')}</th><th>{t('territoryWorldModel.briefing.data')}</th><th>{t('territoryWorldModel.briefing.minimumScope')}</th><th>{t('territoryWorldModel.briefing.unlocks')}</th></tr></thead>
            <tbody>{rows(report?.pilot_data_requirements).map(item => <tr key={`${item.priority}-${item.data}`}><td><strong>{item.priority}</strong></td><td>{item.data}</td><td>{item.minimum}</td><td>{item.unlocks}</td></tr>)}</tbody>
          </table>
        </div>
      </section>

      <section className="twm-briefing-conclusion">
        <div><strong>{t('territoryWorldModel.briefing.platformFormula')}</strong><p>{positioning.llm_wm_relationship}</p></div>
        <div className="twm-briefing-actions">
          <button type="button" onClick={openMapStory}><Map size={15} />{t('territoryWorldModel.briefing.goMap')}</button>
          <button type="button" onClick={() => onNavigate('operate')}><ExternalLink size={15} />{t('territoryWorldModel.briefing.goOperate')}</button>
          <button type="button" onClick={() => onNavigate('data')}><Database size={15} />{t('territoryWorldModel.briefing.goData')}</button>
        </div>
      </section>
    </div>
  );
  return presentationMode ? createPortal(content, document.body) : content;
}
