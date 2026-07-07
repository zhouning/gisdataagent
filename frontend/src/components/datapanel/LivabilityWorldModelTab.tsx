import { useEffect, useState } from 'react';
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

type AnyRecord = Record<string, any>;

function isRecord(value: unknown): value is AnyRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function asArray<T = AnyRecord>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function fmt(value: unknown, digits = 6): string {
  const num = Number(value);
  return Number.isFinite(num) ? num.toFixed(digits) : '-';
}

function fmtInt(value: unknown): string {
  const num = Number(value);
  return Number.isFinite(num) ? String(Math.round(num)) : '-';
}

function fmtP(value: unknown): string {
  const num = Number(value);
  return Number.isFinite(num) ? num.toFixed(6) : '-';
}

function actionLabel(actionType: unknown): string {
  const text = String(actionType || '');
  const labels: Record<string, string> = {
    increase_green_infrastructure: '增加绿色基础设施',
    add_community_service: '补充社区公共服务',
    traffic_emission_control: '交通减排治理',
    building_cooling_retrofit: '建筑降温改造',
  };
  return labels[text] || text || '-';
}

function unitLabel(value: unknown): string {
  return String(value || '-').replace(/\|/g, ' · ');
}

export default function LivabilityWorldModelTab() {
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
        }),
        fetch('/api/uwm/livability-data-catalog', {
          credentials: 'include',
        }),
      ]);
      const decisionData = await decisionResp.json();
      const catalogData = await catalogResp.json();
      if (!decisionResp.ok || decisionData.error) {
        setError(decisionData.error || 'UWM 宜居性决策包加载失败');
        return;
      }
      if (!catalogResp.ok || catalogData.error) {
        setError(catalogData.error || 'UWM 宜居性数据目录加载失败');
        return;
      }
      setPayload(decisionData);
      setCatalogPayload(catalogData);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'UWM 宜居性决策包加载失败');
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
      });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        setError(data.error || 'UWM 统一资产目录同步失败');
        return;
      }
      setSyncResult(data);
      await loadDecision();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'UWM 统一资产目录同步失败');
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    loadDecision();
  }, []);

  const decision = isRecord(payload?.decision_package) ? payload.decision_package : {};
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

  return (
    <div className="uwm-livability-tab">
      <div className="datapanel-section-header">
        <div>
          <h3>城市宜居性分析（UWM）</h3>
          <p>同一数据基础上的 renderer / simulator / planner 反事实决策包。</p>
        </div>
        <button className="secondary-button" onClick={loadDecision} disabled={loading}>
          <RefreshCw size={14} />
          刷新
        </button>
      </div>

      {error && <div className="uwm-livability-message error"><AlertTriangle size={15} />{error}</div>}
      {loading && !payload && <div className="uwm-livability-empty">正在加载 UWM 决策包...</div>}

      {payload && (
        <>
          <div className="uwm-livability-kpi-grid">
            <div className="uwm-livability-kpi">
              <span>推荐动作</span>
              <strong>{fmtInt(actionPortfolio.action_count)}</strong>
            </div>
            <div className="uwm-livability-kpi">
              <span>目标单元</span>
              <strong>{fmtInt(actionPortfolio.target_unit_count)}</strong>
            </div>
            <div className="uwm-livability-kpi">
              <span>风险校正收益</span>
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
              <strong>世界模型链路</strong>
            </div>
            <div className="uwm-component-row">
              {['renderer', 'simulator', 'planner'].map(component => (
                <div key={component} className={components.includes(component) ? 'active' : ''}>
                  <span>{component}</span>
                  <strong>{components.includes(component) ? '已使用' : '未使用'}</strong>
                </div>
              ))}
            </div>
          </div>

          <div className="uwm-livability-two-col">
            <div className="uwm-livability-panel">
              <div className="uwm-livability-panel-title">
                <BarChart3 size={15} />
                <strong>同一数据对照</strong>
              </div>
              <div className="uwm-compare-grid">
                <div>
                  <span>场景</span>
                  <strong>{shared.scene_id || '-'}</strong>
                </div>
                <div>
                  <span>行政单元</span>
                  <strong>{fmtInt(shared.admin_unit_count)}</strong>
                </div>
                <div>
                  <span>传统最终输出</span>
                  <strong>{traditional.final_output_type || '-'}</strong>
                </div>
                <div>
                  <span>UWM 最终输出</span>
                  <strong>{uwm.final_output_type || '-'}</strong>
                </div>
              </div>
            </div>

            <div className="uwm-livability-panel">
              <div className="uwm-livability-panel-title">
                <Activity size={15} />
                <strong>强于传统方法的证据</strong>
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
              <strong>推荐行动序列</strong>
            </div>
            <div className="uwm-action-list">
              {actions.map((action, index) => (
                <div key={action.action_id || index}>
                  <b>{index + 1}</b>
                  <div>
                    <strong>{actionLabel(action.action_type)}</strong>
                    <span>{asArray<string>(action.target_units).map(unitLabel).join('；') || '-'}</span>
                  </div>
                  <em>{fmt(action.intensity, 2)}</em>
                </div>
              ))}
            </div>
          </div>

          <div className="uwm-livability-panel">
            <div className="uwm-livability-panel-title">
              <Network size={15} />
              <strong>反事实状态变化与空间外溢</strong>
            </div>
            <div className="uwm-priority-table-wrap">
              <table className="uwm-priority-table">
                <thead>
                  <tr>
                    <th>行政单元</th>
                    <th>宜居变化</th>
                    <th>公平性变化</th>
                    <th>污染暴露变化</th>
                    <th>服务变化</th>
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
              <strong>数据校准空间传播核</strong>
            </div>
            <div className="uwm-evidence-grid">
              <div>
                <span>data_calibrated_spatial_spillover_kernel</span>
                <strong>{String(Boolean(spatialKernel.ready))}</strong>
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
                <strong>{String(Boolean(spatialKernel.uses_shared_boundary_length))}</strong>
              </div>
              <div>
                <span>uses_admin_livability_need</span>
                <strong>{String(Boolean(spatialKernel.uses_admin_livability_need))}</strong>
              </div>
              <div>
                <span>uses_admin_exposure_priority</span>
                <strong>{String(Boolean(spatialKernel.uses_admin_exposure_priority))}</strong>
              </div>
            </div>
          </div>

          <div className="uwm-livability-panel">
            <div className="uwm-livability-panel-title">
              <Brain size={15} />
              <strong>Dyna-Q 训练证据</strong>
            </div>
            <div className="uwm-evidence-grid">
              <div>
                <span>rl_training_evidence</span>
                <strong>{String(Boolean(rlTraining.ready))}</strong>
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
              <strong>GraphDQN 神经价值网络</strong>
            </div>
            <div className="uwm-evidence-grid">
              <div>
                <span>graph_drl_training_evidence</span>
                <strong>{String(Boolean(graphDrl.ready))}</strong>
              </div>
              <div>
                <span>algorithm</span>
                <strong>{graphDrl.algorithm || '-'}</strong>
              </div>
              <div>
                <span>is_deep_rl</span>
                <strong>{String(Boolean(graphDrl.is_deep_rl))}</strong>
              </div>
              <div>
                <span>uses_graph_message_passing</span>
                <strong>{String(Boolean(graphDrl.uses_graph_message_passing))}</strong>
              </div>
              <div>
                <span>policy_or_value_network_trained</span>
                <strong>{String(Boolean(graphDrl.policy_or_value_network_trained))}</strong>
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
                <strong>UWM-only 输出</strong>
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
                <strong>证据边界</strong>
              </div>
              <div className="uwm-boundary-grid">
                <div>
                  <span>claim level</span>
                  <strong>{claim.max_claim_level || '-'}</strong>
                </div>
                <div>
                  <span>observed_policy_outcome_superiority_claim</span>
                <strong>{String(observedClaim)}</strong>
                </div>
              </div>
            </div>
          </div>

          <div className="uwm-livability-panel">
            <div className="uwm-livability-panel-title">
              <Database size={15} />
              <strong>数据治理与训练边界</strong>
              <button className="secondary-button" onClick={syncCatalog} disabled={syncing}>
                <GitBranch size={14} />
                同步统一目录
              </button>
            </div>
            <div className="uwm-evidence-grid">
              <div>
                <span>source_of_truth_table</span>
                <strong>{catalogIntegration.source_of_truth_table || 'agent_data_assets'}</strong>
              </div>
              <div>
                <span>shadow_catalog</span>
                <strong>{String(Boolean(catalogIntegration.shadow_catalog))}</strong>
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
                <strong>{String(Boolean(mmfe.complete_mmfe_managed_pipeline))}</strong>
              </div>
              <div>
                <span>mmfe_state_input_asset_count</span>
                <strong>{fmtInt(mmfe.mmfe_state_input_asset_count)}</strong>
              </div>
              <div>
                <span>model_based_rl_training_completed</span>
                <strong>{String(Boolean(rlBoundary.model_based_rl_training_completed))}</strong>
              </div>
              <div>
                <span>trained_model_based_q_agent_completed</span>
                <strong>{String(Boolean(rlBoundary.trained_model_based_q_agent_completed))}</strong>
              </div>
              <div>
                <span>policy_or_value_network_trained</span>
                <strong>{String(Boolean(rlBoundary.policy_or_value_network_trained))}</strong>
              </div>
              <div>
                <span>graph_policy_or_value_network_trained</span>
                <strong>{String(Boolean(rlBoundary.graph_policy_or_value_network_trained))}</strong>
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
