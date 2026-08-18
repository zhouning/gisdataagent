import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Brain,
  Database,
  GitBranch,
  Network,
  RefreshCw,
  Shield,
  Target,
} from 'lucide-react';
import UwmLivabilityS2Panel from './UwmLivabilityS2Panel';
import UwmLivabilityEnvironmentalKernelPanel from './UwmLivabilityEnvironmentalKernelPanel';
import UwmLivabilityDemand7Panel from './UwmLivabilityDemand7Panel';
import { formatNumber, getLocaleHeaders } from '../../i18n';

type AnyRecord = Record<string, any>;

function isRecord(value: unknown): value is AnyRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function asArray<T = AnyRecord>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function fmt(value: unknown, digits = 6): string {
  const num = Number(value);
  return Number.isFinite(num)
    ? formatNumber(num, { minimumFractionDigits: digits, maximumFractionDigits: digits })
    : '-';
}

function fmtInt(value: unknown): string {
  const num = Number(value);
  return Number.isFinite(num)
    ? formatNumber(Math.round(num), { maximumFractionDigits: 0 })
    : '-';
}

function fmtP(value: unknown): string {
  const num = Number(value);
  return Number.isFinite(num)
    ? formatNumber(num, { minimumFractionDigits: 6, maximumFractionDigits: 6 })
    : '-';
}

export default function LivabilityWorldModelTab() {
  const { t, i18n } = useTranslation('common');
  const [payload, setPayload] = useState<AnyRecord | null>(null);
  const [catalogPayload, setCatalogPayload] = useState<AnyRecord | null>(null);
  const [syncResult, setSyncResult] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState('');

  const loadDecision = async () => {
    setLoading(true);
    setError('');
    try {
      const [decisionResp, catalogResp] = await Promise.all([
        fetch('/api/uwm/livability-decision', {
          credentials: 'include',
          headers: getLocaleHeaders(),
        }),
        fetch('/api/uwm/livability-data-catalog', {
          credentials: 'include',
          headers: getLocaleHeaders(),
        }),
      ]);
      const decisionData = await decisionResp.json();
      const catalogData = await catalogResp.json();
      if (!decisionResp.ok || decisionData.error) {
        setError(decisionData.error || t('uwmLivability.errors.decision'));
        return;
      }
      if (!catalogResp.ok || catalogData.error) {
        setError(catalogData.error || t('uwmLivability.errors.catalog'));
        return;
      }
      setPayload(decisionData);
      setCatalogPayload(catalogData);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t('uwmLivability.errors.decision'));
    } finally {
      setLoading(false);
    }
  };

  const syncCatalog = async () => {
    setSyncing(true);
    setError('');
    try {
      const resp = await fetch('/api/uwm/livability-data-catalog/sync', {
        method: 'POST',
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        setError(data.error || t('uwmLivability.errors.sync'));
        return;
      }
      setSyncResult(data);
      await loadDecision();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t('uwmLivability.errors.sync'));
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    loadDecision();
  }, [i18n.resolvedLanguage]);

  const decision = isRecord(payload?.decision_package) ? payload.decision_package : {};
  const fullAdminDecision = isRecord(payload?.full_admin_decision_package)
    ? payload.full_admin_decision_package
    : {};
  const fullAdminGuard = isRecord(fullAdminDecision.full_data_guard)
    ? fullAdminDecision.full_data_guard
    : {};
  const fullAdminComparison = isRecord(fullAdminDecision.comparison_against_traditional_static_baselines)
    ? fullAdminDecision.comparison_against_traditional_static_baselines
    : {};
  const governanceBinding = isRecord(payload?.production_governance_binding_evidence)
    ? payload.production_governance_binding_evidence
    : isRecord(fullAdminDecision.production_governance_binding_evidence)
      ? fullAdminDecision.production_governance_binding_evidence
      : {};
  const fullAdminActionInventory = isRecord(payload?.full_admin_action_inventory_evidence)
    ? payload.full_admin_action_inventory_evidence
    : {};
  const spatialCausalRegistry = isRecord(payload?.spatial_causal_question_registry_evidence)
    ? payload.spatial_causal_question_registry_evidence
    : {};
  const worldModelReadiness = isRecord(payload?.world_model_evidence_readiness)
    ? payload.world_model_evidence_readiness
    : {};
  const readinessArchitecture = isRecord(worldModelReadiness.architecture_evidence)
    ? worldModelReadiness.architecture_evidence
    : {};
  const spatialCausalReadiness = isRecord(readinessArchitecture.spatial_causal_questions)
    ? readinessArchitecture.spatial_causal_questions
    : {};
  const comparison = isRecord(decision.comparison_against_traditional_static_heuristic)
    ? decision.comparison_against_traditional_static_heuristic
    : {};
  const replay = isRecord(decision.replay_baseline_suite) ? decision.replay_baseline_suite : {};
  const spatialKernel = isRecord(decision.spatial_spillover_kernel_evidence)
    ? decision.spatial_spillover_kernel_evidence
    : {};
  const rlTraining = isRecord(decision.rl_training_evidence)
    ? decision.rl_training_evidence
    : {};
  const graphDrl = isRecord(decision.graph_drl_training_evidence)
    ? decision.graph_drl_training_evidence
    : {};
  const actionPortfolio = isRecord(decision.action_portfolio) ? decision.action_portfolio : {};
  const finalOutputs = isRecord(decision.final_outputs) ? decision.final_outputs : {};
  const fullAdminFinalOutputs = isRecord(fullAdminDecision.final_outputs)
    ? fullAdminDecision.final_outputs
    : {};
  const fullAdminActionSequences = [
    {
      source: 'planner_replay',
      label: 'planner',
      sequence: isRecord(fullAdminFinalOutputs.planner_recommended_sequence)
        ? fullAdminFinalOutputs.planner_recommended_sequence
        : {},
    },
    {
      source: 'graph_dqn',
      label: 'GraphDQN',
      sequence: isRecord(fullAdminFinalOutputs.graph_dqn_recommended_sequence)
        ? fullAdminFinalOutputs.graph_dqn_recommended_sequence
        : {},
    },
    {
      source: 'learned_rollout',
      label: 'learned rollout',
      sequence: isRecord(fullAdminFinalOutputs.learned_rollout_recommended_sequence)
        ? fullAdminFinalOutputs.learned_rollout_recommended_sequence
        : {},
    },
  ];
  const fullAdminCausalActions: AnyRecord[] = fullAdminActionSequences.flatMap(item =>
    asArray<AnyRecord>(item.sequence.action_sequence).map(action => ({
      ...(action as AnyRecord),
      sequence_source: item.source,
      sequence_label: item.label,
    })),
  );
  const priorityUnits = asArray<AnyRecord>(finalOutputs.priority_admin_units);
  const shared = isRecord(payload?.shared_data_contract) ? payload.shared_data_contract : {};
  const traditional = isRecord(payload?.traditional_method_output) ? payload.traditional_method_output : {};
  const uwm = isRecord(payload?.uwm_output) ? payload.uwm_output : {};
  const capability = isRecord(payload?.capability_delta) ? payload.capability_delta : {};
  const claim = isRecord(payload?.claim_boundary) ? payload.claim_boundary : {};
  const dataCatalog = isRecord(catalogPayload?.data_catalog) ? catalogPayload.data_catalog : {};
  const mmfe = isRecord(dataCatalog.mmfe_readiness) ? dataCatalog.mmfe_readiness : {};
  const catalogIntegration = isRecord(dataCatalog.data_agent_catalog_integration)
    ? dataCatalog.data_agent_catalog_integration
    : {};
  const registrationPlan = isRecord(catalogIntegration.registration_plan)
    ? catalogIntegration.registration_plan
    : {};
  const rlBoundary = isRecord(dataCatalog.model_based_rl_boundary) ? dataCatalog.model_based_rl_boundary : {};
  const components = asArray<string>(payload?.world_model_components_used);
  const actions = asArray<AnyRecord>(actionPortfolio.actions);
  const observedClaim = Boolean(payload?.observed_policy_outcome_superiority_claim);
  const plannerGovernanceBindingReady = Boolean(payload?.planner_governance_binding_ready);
  const actionLabel = (actionType: unknown) => {
    const key = String(actionType || '');
    return key ? t(`uwmLivability.actions.${key}`, { defaultValue: key }) : '-';
  };
  const booleanLabel = (value: unknown) =>
    t(`uwmLivability.boolean.${Boolean(value) ? 'true' : 'false'}`);
  const unitLabel = (value: unknown) => {
    const raw = String(value || '-');
    if ((i18n.resolvedLanguage || i18n.language).startsWith('zh')) return raw.replace(/\|/g, ' · ');
    const parts = raw.split('|');
    return parts.length > 1
      ? t('uwmLivability.labels.unitId', { id: parts[parts.length - 1] })
      : raw;
  };

  return (
    <div className="uwm-livability-tab">
      <UwmLivabilityDemand7Panel />
      <UwmLivabilityEnvironmentalKernelPanel />
      <UwmLivabilityS2Panel />
      <div className="datapanel-section-header">
        <div>
          <h3>{t('uwmLivability.header.title')}</h3>
          <p>{t('uwmLivability.header.subtitle')}</p>
        </div>
        <button className="secondary-button" onClick={loadDecision} disabled={loading}>
          <RefreshCw size={14} />
          {t('uwmLivability.header.refresh')}
        </button>
      </div>

      {error && <div className="uwm-livability-message error"><AlertTriangle size={15} />{error}</div>}
      {loading && !payload && <div className="uwm-livability-empty">{t('uwmLivability.header.loading')}</div>}

      {payload && (
        <>
          <div className="uwm-livability-kpi-grid">
            <div className="uwm-livability-kpi">
              <span>{t('uwmLivability.kpis.recommendedActions')}</span>
              <strong>{fmtInt(actionPortfolio.action_count)}</strong>
            </div>
            <div className="uwm-livability-kpi">
              <span>{t('uwmLivability.kpis.targetUnits')}</span>
              <strong>{fmtInt(actionPortfolio.target_unit_count)}</strong>
            </div>
            <div className="uwm-livability-kpi">
              <span>{t('uwmLivability.kpis.riskAdjustedBenefit')}</span>
              <strong>{fmt(comparison.risk_adjusted_advantage_over_static)}</strong>
            </div>
            <div className="uwm-livability-kpi">
              <span>p-value</span>
              <strong>{fmtP(replay.empirical_one_sided_p_value)}</strong>
            </div>
          </div>

          <div className="uwm-livability-panel">
            <div className="uwm-livability-panel-title">
              <Brain size={15} />
              <strong>{t('uwmLivability.sections.worldModelChain')}</strong>
            </div>
            <div className="uwm-component-row">
              {['renderer', 'simulator', 'planner'].map(component => (
                <div key={component} className={components.includes(component) ? 'active' : ''}>
                  <span>{component}</span>
                  <strong>{t(`uwmLivability.component.${components.includes(component) ? 'used' : 'unused'}`)}</strong>
                </div>
              ))}
            </div>
          </div>

          <div className="uwm-livability-two-col">
            <div className="uwm-livability-panel">
              <div className="uwm-livability-panel-title">
                <GitBranch size={15} />
                <strong>{t('uwmLivability.sections.fullAdmin')}</strong>
              </div>
              <div className="uwm-evidence-grid">
                <div>
                  <span>active_decision_package_scope</span>
                  <strong>{String(payload.active_decision_package_scope || fullAdminDecision.experiment_scope || '-')}</strong>
                </div>
                <div>
                  <span>graph_node_count</span>
                  <strong>{fmtInt(fullAdminGuard.graph_node_count)}</strong>
                </div>
                <div>
                  <span>graph_edge_count</span>
                  <strong>{fmtInt(fullAdminGuard.graph_edge_count)}</strong>
                </div>
                <div>
                  <span>available_action_count</span>
                  <strong>{fmtInt(fullAdminGuard.available_action_count)}</strong>
                </div>
                <div>
                  <span>transition_count</span>
                  <strong>{fmtInt(fullAdminGuard.transition_count)}</strong>
                </div>
                <div>
                  <span>planner_advantage_over_static</span>
                  <strong>{fmt(fullAdminComparison.planner_advantage_over_static)}</strong>
                </div>
                <div>
                  <span>graph_dqn_advantage_over_static</span>
                  <strong>{fmt(fullAdminComparison.graph_dqn_advantage_over_static)}</strong>
                </div>
                <div>
                  <span>learned_rollout_advantage_over_static</span>
                  <strong>{fmt(fullAdminComparison.learned_rollout_advantage_over_static)}</strong>
                </div>
              </div>
            </div>

            <div className="uwm-livability-panel">
              <div className="uwm-livability-panel-title">
                <Shield size={15} />
                <strong>{t('uwmLivability.sections.governanceGate')}</strong>
              </div>
              <div className="uwm-boundary-grid">
                <div>
                  <span>production_governance_binding_evidence</span>
                  <strong>{booleanLabel(governanceBinding.production_governance_binding_gate_ready)}</strong>
                </div>
                <div>
                  <span>planner_governance_binding_ready</span>
                  <strong>{booleanLabel(plannerGovernanceBindingReady)}</strong>
                </div>
                <div>
                  <span>production_planner_binding_blocked</span>
                  <strong>{booleanLabel(governanceBinding.production_planner_binding_blocked)}</strong>
                </div>
                <div>
                  <span>production_governance_binding_blocking_gate_count</span>
                  <strong>{fmtInt(governanceBinding.blocking_gate_count)}</strong>
                </div>
                <div>
                  <span>missing_table_count</span>
                  <strong>{fmtInt(governanceBinding.missing_table_count)}</strong>
                </div>
                <div>
                  <span>accepted_authoritative_row_count</span>
                  <strong>{fmtInt(governanceBinding.accepted_authoritative_row_count)}</strong>
                </div>
              </div>
            </div>

            <div className="uwm-livability-panel">
              <div className="uwm-livability-panel-title">
                <Brain size={15} />
                <strong>{t('uwmLivability.sections.spatialCausalContract')}</strong>
              </div>
              <div className="uwm-boundary-grid">
                <div>
                  <span>spatial_causal_question_registry_evidence</span>
                  <strong>{booleanLabel(spatialCausalRegistry.spatial_causal_question_registry_ready)}</strong>
                </div>
                <div>
                  <span>world_model_evidence_readiness.spatial_causal_questions</span>
                  <strong>{booleanLabel(spatialCausalReadiness.ready)}</strong>
                </div>
                <div>
                  <span>spatial_causal_question_registry_ready</span>
                  <strong>{booleanLabel(spatialCausalRegistry.spatial_causal_question_registry_ready)}</strong>
                </div>
                <div>
                  <span>active_causal_question_count</span>
                  <strong>{fmtInt(spatialCausalRegistry.active_causal_question_count)}</strong>
                </div>
                <div>
                  <span>underidentified_policy_effect_question_count</span>
                  <strong>{fmtInt(spatialCausalRegistry.underidentified_policy_effect_question_count)}</strong>
                </div>
                <div>
                  <span>identified_policy_effect_question_count</span>
                  <strong>{fmtInt(spatialCausalRegistry.identified_policy_effect_question_count)}</strong>
                </div>
                <div>
                  <span>ready_authoritative_table_count</span>
                  <strong>{fmtInt(spatialCausalRegistry.ready_authoritative_table_count)}</strong>
                </div>
                <div>
                  <span>policy_outcome_claim</span>
                  <strong>{booleanLabel(spatialCausalReadiness.policy_outcome_claim)}</strong>
                </div>
                <div>
                  <span>full_admin_action_inventory_evidence</span>
                  <strong>{booleanLabel(fullAdminActionInventory.full_admin_action_inventory_ready)}</strong>
                </div>
                <div>
                  <span>spatial_causal_feasible_action_count</span>
                  <strong>{fmtInt(fullAdminActionInventory.spatial_causal_feasible_action_count)}</strong>
                </div>
                <div>
                  <span>spatial_causal_attached_action_count</span>
                  <strong>{fmtInt(fullAdminActionInventory.spatial_causal_attached_action_count)}</strong>
                </div>
                <div>
                  <span>spatial_causal_missing_contract_action_count</span>
                  <strong>{fmtInt(fullAdminActionInventory.spatial_causal_missing_contract_action_count)}</strong>
                </div>
                <div>
                  <span>spatial_causal_underidentified_policy_effect_action_count</span>
                  <strong>{fmtInt(fullAdminActionInventory.spatial_causal_underidentified_policy_effect_action_count)}</strong>
                </div>
                <div>
                  <span>spatial_causal_policy_outcome_claim_action_count</span>
                  <strong>{fmtInt(fullAdminActionInventory.spatial_causal_policy_outcome_claim_action_count)}</strong>
                </div>
              </div>
            </div>
          </div>

          <div className="uwm-livability-two-col">
            <div className="uwm-livability-panel">
              <div className="uwm-livability-panel-title">
                <BarChart3 size={15} />
                <strong>{t('uwmLivability.sections.sameDataComparison')}</strong>
              </div>
              <div className="uwm-compare-grid">
                <div>
                  <span>{t('uwmLivability.labels.scene')}</span>
                  <strong>{shared.scene_id || '-'}</strong>
                </div>
                <div>
                  <span>{t('uwmLivability.labels.adminUnits')}</span>
                  <strong>{fmtInt(shared.admin_unit_count)}</strong>
                </div>
                <div>
                  <span>{t('uwmLivability.labels.traditionalOutput')}</span>
                  <strong>{traditional.final_output_type || '-'}</strong>
                </div>
                <div>
                  <span>{t('uwmLivability.labels.uwmOutput')}</span>
                  <strong>{uwm.final_output_type || '-'}</strong>
                </div>
              </div>
            </div>

            <div className="uwm-livability-panel">
              <div className="uwm-livability-panel-title">
                <Activity size={15} />
                <strong>{t('uwmLivability.sections.comparativeEvidence')}</strong>
              </div>
              <div className="uwm-evidence-grid">
                <div>
                  <span>endpoint_aligned_advantage_over_static</span>
                  <strong>{fmt(comparison.endpoint_aligned_advantage_over_static)}</strong>
                </div>
                <div>
                  <span>risk_adjusted_advantage_over_static</span>
                  <strong>{fmt(comparison.risk_adjusted_advantage_over_static)}</strong>
                </div>
                <div>
                  <span>neighbor_livability_delta_advantage</span>
                  <strong>{fmt(comparison.neighbor_livability_delta_advantage)}</strong>
                </div>
                <div>
                  <span>empirical_one_sided_p_value</span>
                  <strong>{fmtP(replay.empirical_one_sided_p_value)}</strong>
                </div>
              </div>
            </div>
          </div>

          <div className="uwm-livability-panel">
            <div className="uwm-livability-panel-title">
              <Target size={15} />
              <strong>{t('uwmLivability.sections.recommendedSequence')}</strong>
            </div>
            <div className="uwm-action-list">
              {actions.map((action, index) => (
                <div key={action.action_id || index}>
                  <b>{index + 1}</b>
                  <div>
                    <strong>{actionLabel(action.action_type)}</strong>
                    <span>{asArray<string>(action.target_units).map(unitLabel).join(t('uwmLivability.listSeparator')) || '-'}</span>
                  </div>
                  <em>{fmt(action.intensity, 2)}</em>
                </div>
              ))}
            </div>
          </div>

          <div className="uwm-livability-panel">
            <div className="uwm-livability-panel-title">
              <Brain size={15} />
              <strong>{t('uwmLivability.sections.actionCausalContract')}</strong>
            </div>
            <div className="uwm-priority-table-wrap">
              <table className="uwm-priority-table">
                <thead>
                  <tr>
                    <th>{t('uwmLivability.labels.sequence')}</th>
                    <th>{t('uwmLivability.labels.action')}</th>
                    <th>causal_question_id</th>
                    <th>primary_outcome</th>
                    <th>identification_status</th>
                    <th>policy_outcome_claim_allowed</th>
                    <th>required_authoritative_tables</th>
                    <th>causal_query</th>
                  </tr>
                </thead>
                <tbody>
                  {fullAdminCausalActions.map((action, index) => (
                    <tr key={`${action.sequence_source}-${action.action_id || index}`}>
                      <td>{action.sequence_label || '-'}</td>
                      <td>{actionLabel(action.action_type)}</td>
                      <td>{action.causal_question_id || '-'}</td>
                      <td>{action.primary_outcome || '-'}</td>
                      <td>{action.identification_status || '-'}</td>
                      <td>{booleanLabel(action.policy_outcome_claim_allowed)}</td>
                      <td>{asArray<string>(action.required_authoritative_tables).join(', ') || '-'}</td>
                      <td>{action.causal_query || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="uwm-livability-panel">
            <div className="uwm-livability-panel-title">
              <Network size={15} />
              <strong>{t('uwmLivability.sections.counterfactualSpillover')}</strong>
            </div>
            <div className="uwm-priority-table-wrap">
              <table className="uwm-priority-table">
                <thead>
                  <tr>
                    <th>{t('uwmLivability.labels.adminUnit')}</th>
                    <th>{t('uwmLivability.labels.livabilityDelta')}</th>
                    <th>{t('uwmLivability.labels.equityDelta')}</th>
                    <th>{t('uwmLivability.labels.pollutionDelta')}</th>
                    <th>{t('uwmLivability.labels.serviceDelta')}</th>
                  </tr>
                </thead>
                <tbody>
                  {priorityUnits.slice(0, 10).map(row => (
                    <tr key={row.admin_unit_id}>
                      <td>{unitLabel(row.admin_unit_id)}</td>
                      <td>{fmt(row.livability_delta)}</td>
                      <td>{fmt(row.equity_delta)}</td>
                      <td>{fmt(row.air_pollution_exposure_delta)}</td>
                      <td>{fmt(row.service_accessibility_delta)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="uwm-livability-panel">
            <div className="uwm-livability-panel-title">
              <Network size={15} />
              <strong>{t('uwmLivability.sections.spatialKernel')}</strong>
            </div>
            <div className="uwm-evidence-grid">
              <div>
                <span>data_calibrated_spatial_spillover_kernel</span>
                <strong>{booleanLabel(spatialKernel.ready)}</strong>
              </div>
              <div>
                <span>directional_edge_count</span>
                <strong>{fmtInt(spatialKernel.directional_edge_count)}</strong>
              </div>
              <div>
                <span>kernel_source_unit_count</span>
                <strong>{fmtInt(spatialKernel.kernel_source_unit_count)}</strong>
              </div>
              <div>
                <span>max_spillover_factor</span>
                <strong>{fmt(spatialKernel.max_spillover_factor)}</strong>
              </div>
              <div>
                <span>mean_spillover_factor</span>
                <strong>{fmt(spatialKernel.mean_spillover_factor)}</strong>
              </div>
              <div>
                <span>uses_shared_boundary_length</span>
                <strong>{booleanLabel(spatialKernel.uses_shared_boundary_length)}</strong>
              </div>
              <div>
                <span>uses_admin_livability_need</span>
                <strong>{booleanLabel(spatialKernel.uses_admin_livability_need)}</strong>
              </div>
              <div>
                <span>uses_admin_exposure_priority</span>
                <strong>{booleanLabel(spatialKernel.uses_admin_exposure_priority)}</strong>
              </div>
            </div>
          </div>

          <div className="uwm-livability-panel">
            <div className="uwm-livability-panel-title">
              <Brain size={15} />
              <strong>{t('uwmLivability.sections.dynaQ')}</strong>
            </div>
            <div className="uwm-evidence-grid">
              <div>
                <span>rl_training_evidence</span>
                <strong>{booleanLabel(rlTraining.ready)}</strong>
              </div>
              <div>
                <span>algorithm</span>
                <strong>{rlTraining.algorithm || '-'}</strong>
              </div>
              <div>
                <span>episode_count</span>
                <strong>{fmtInt(rlTraining.episode_count)}</strong>
              </div>
              <div>
                <span>real_data_graph_node_count</span>
                <strong>{fmtInt(rlTraining.real_data_graph_node_count)}</strong>
              </div>
              <div>
                <span>available_action_count</span>
                <strong>{fmtInt(rlTraining.available_action_count)}</strong>
              </div>
              <div>
                <span>spatial_spillover_directional_edge_count</span>
                <strong>{fmtInt(rlTraining.spatial_spillover_directional_edge_count)}</strong>
              </div>
              <div>
                <span>learned_policy_cumulative_reward</span>
                <strong>{fmt(rlTraining.learned_policy_cumulative_reward)}</strong>
              </div>
              <div>
                <span>advantage_over_traditional_static</span>
                <strong>{fmt(rlTraining.advantage_over_traditional_static)}</strong>
              </div>
            </div>
          </div>

          <div className="uwm-livability-panel">
            <div className="uwm-livability-panel-title">
              <Brain size={15} />
              <strong>{t('uwmLivability.sections.graphDqn')}</strong>
            </div>
            <div className="uwm-evidence-grid">
              <div>
                <span>graph_drl_training_evidence</span>
                <strong>{booleanLabel(graphDrl.ready)}</strong>
              </div>
              <div>
                <span>algorithm</span>
                <strong>{graphDrl.algorithm || '-'}</strong>
              </div>
              <div>
                <span>is_deep_rl</span>
                <strong>{booleanLabel(graphDrl.is_deep_rl)}</strong>
              </div>
              <div>
                <span>uses_graph_message_passing</span>
                <strong>{booleanLabel(graphDrl.uses_graph_message_passing)}</strong>
              </div>
              <div>
                <span>policy_or_value_network_trained</span>
                <strong>{booleanLabel(graphDrl.policy_or_value_network_trained)}</strong>
              </div>
              <div>
                <span>training_sample_count</span>
                <strong>{fmtInt(graphDrl.training_sample_count)}</strong>
              </div>
              <div>
                <span>q_return_mae</span>
                <strong>{fmt(graphDrl.q_return_mae)}</strong>
              </div>
              <div>
                <span>train_mean_return_mae</span>
                <strong>{fmt(graphDrl.train_mean_return_mae)}</strong>
              </div>
              <div>
                <span>advantage_over_traditional_static</span>
                <strong>{fmt(graphDrl.advantage_over_traditional_static)}</strong>
              </div>
            </div>
          </div>

          <div className="uwm-livability-two-col">
            <div className="uwm-livability-panel">
              <div className="uwm-livability-panel-title">
                <GitBranch size={15} />
                <strong>{t('uwmLivability.sections.uwmOnly')}</strong>
              </div>
              <div className="uwm-capability-tags">
                {asArray<string>(capability.uwm_only_outputs).map(item => (
                  <span key={item}>{item}</span>
                ))}
              </div>
            </div>

            <div className="uwm-livability-panel">
              <div className="uwm-livability-panel-title">
                <Shield size={15} />
                <strong>{t('uwmLivability.sections.evidenceBoundary')}</strong>
              </div>
              <div className="uwm-boundary-grid">
                <div>
                  <span>{t('uwmLivability.labels.claimLevel')}</span>
                  <strong>{claim.max_claim_level || '-'}</strong>
                </div>
                <div>
                  <span>observed_policy_outcome_superiority_claim</span>
                <strong>{booleanLabel(observedClaim)}</strong>
                </div>
              </div>
            </div>
          </div>

          <div className="uwm-livability-panel">
            <div className="uwm-livability-panel-title">
              <Database size={15} />
              <strong>{t('uwmLivability.sections.dataGovernance')}</strong>
              <button className="secondary-button" onClick={syncCatalog} disabled={syncing}>
                <GitBranch size={14} />
                {t('uwmLivability.actionsUi.syncCatalog')}
              </button>
            </div>
            <div className="uwm-evidence-grid">
              <div>
                <span>source_of_truth_table</span>
                <strong>{catalogIntegration.source_of_truth_table || 'agent_data_assets'}</strong>
              </div>
              <div>
                <span>shadow_catalog</span>
                <strong>{booleanLabel(catalogIntegration.shadow_catalog)}</strong>
              </div>
              <div>
                <span>registration_plan.asset_count</span>
                <strong>{fmtInt(registrationPlan.asset_count)}</strong>
              </div>
              <div>
                <span>registration_plan.lineage_edge_count</span>
                <strong>{fmtInt(registrationPlan.lineage_edge_count)}</strong>
              </div>
              <div>
                <span>complete_mmfe_managed_pipeline</span>
                <strong>{booleanLabel(mmfe.complete_mmfe_managed_pipeline)}</strong>
              </div>
              <div>
                <span>mmfe_state_input_asset_count</span>
                <strong>{fmtInt(mmfe.mmfe_state_input_asset_count)}</strong>
              </div>
              <div>
                <span>model_based_rl_training_completed</span>
                <strong>{booleanLabel(rlBoundary.model_based_rl_training_completed)}</strong>
              </div>
              <div>
                <span>trained_model_based_q_agent_completed</span>
                <strong>{booleanLabel(rlBoundary.trained_model_based_q_agent_completed)}</strong>
              </div>
              <div>
                <span>policy_or_value_network_trained</span>
                <strong>{booleanLabel(rlBoundary.policy_or_value_network_trained)}</strong>
              </div>
              <div>
                <span>graph_policy_or_value_network_trained</span>
                <strong>{booleanLabel(rlBoundary.graph_policy_or_value_network_trained)}</strong>
              </div>
              <div>
                <span>current_planning_mode</span>
                <strong>{rlBoundary.current_planning_mode || '-'}</strong>
              </div>
              <div>
                <span>sync.registered_asset_count</span>
                <strong>{syncResult ? fmtInt(syncResult.registered_asset_count) : '-'}</strong>
              </div>
              <div>
                <span>sync.lineage_edge_count</span>
                <strong>{syncResult ? fmtInt(syncResult.lineage_edge_count) : '-'}</strong>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
