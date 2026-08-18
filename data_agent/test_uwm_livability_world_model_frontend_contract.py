import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_PANEL = ROOT / "frontend" / "src" / "components" / "DataPanel.tsx"
UWM_TAB = (
    ROOT
    / "frontend"
    / "src"
    / "components"
    / "datapanel"
    / "LivabilityWorldModelTab.tsx"
)


def test_uwm_livability_tab_is_registered_after_traditional_baseline():
    text = DATA_PANEL.read_text(encoding="utf-8")

    assert "LivabilityWorldModelTab" in text
    assert "uwm_livability" in text
    assert "城市宜居性分析（UWM）" in text
    assert "{activeTab === 'uwm_livability' && <LivabilityWorldModelTab />}" in text
    assert text.index("{ key: 'traditional_livability'") < text.index(
        "{ key: 'uwm_livability'"
    )


def test_uwm_livability_tab_exposes_world_model_decision_contract():
    text = UWM_TAB.read_text(encoding="utf-8")
    translations = json.loads(
        (ROOT / "frontend/src/i18n/locales/zh-CN/common.json").read_text(encoding="utf-8")
    )["uwmLivability"]
    localized_text = json.dumps(translations, ensure_ascii=False)

    assert "/api/uwm/livability-decision" in text
    assert "/api/uwm/livability-data-catalog" in text
    assert "/api/uwm/livability-data-catalog/sync" in text
    assert "renderer" in text
    assert "simulator" in text
    assert "planner" in text
    assert "反事实决策包" in localized_text
    assert "推荐行动序列" in localized_text
    assert "空间外溢" in localized_text
    assert "风险校正收益" in localized_text
    assert "endpoint_aligned_advantage_over_static" in text
    assert "risk_adjusted_advantage_over_static" in text
    assert "neighbor_livability_delta_advantage" in text
    assert "spatial_spillover_kernel_evidence" in text
    assert "rl_training_evidence" in text
    assert "Dyna-Q 训练证据" in localized_text
    assert "graph_drl_training_evidence" in text
    assert "GraphDQN 神经价值网络" in localized_text
    assert "advantage_over_traditional_static" in text
    assert "trained_model_based_q_agent_completed" in text
    assert "graph_policy_or_value_network_trained" in text
    assert "data_calibrated_spatial_spillover_kernel" in text
    assert "directional_edge_count" in text
    assert "uses_shared_boundary_length" in text
    assert "empirical_one_sided_p_value" in text
    assert "observed_policy_outcome_superiority_claim" in text
    assert "complete_mmfe_managed_pipeline" in text
    assert "agent_data_assets" in text
    assert "shadow_catalog" in text
    assert "model_based_rl_training_completed" in text
    assert "policy_or_value_network_trained" in text
    assert "数据治理与训练边界" in localized_text
    assert "生产治理绑定门控" in localized_text
    assert "production_governance_binding_evidence" in text
    assert "planner_governance_binding_ready" in text
    assert "production_planner_binding_blocked" in text
    assert "production_governance_binding_blocking_gate_count" in text
    assert "spatial_causal_question_registry_evidence" in text
    assert "world_model_evidence_readiness" in text
    assert "空间因果问题契约" in localized_text
    assert "spatial_causal_question_registry_ready" in text
    assert "active_causal_question_count" in text
    assert "underidentified_policy_effect_question_count" in text
    assert "identified_policy_effect_question_count" in text
    assert "ready_authoritative_table_count" in text
    assert "spatial_causal_questions" in text
    assert "policy_outcome_claim" in text
    assert "full_admin_action_inventory_evidence" in text
    assert "spatial_causal_feasible_action_count" in text
    assert "spatial_causal_attached_action_count" in text
    assert "spatial_causal_missing_contract_action_count" in text
    assert "spatial_causal_underidentified_policy_effect_action_count" in text
    assert "spatial_causal_policy_outcome_claim_action_count" in text
    assert "动作因果契约" in localized_text
    assert "causal_question_id" in text
    assert "causal_query" in text
    assert "primary_outcome" in text
    assert "identification_status" in text
    assert "required_authoritative_tables" in text
    assert "policy_outcome_claim_allowed" in text
    assert "同一数据" in localized_text
    assert "useTranslation" in text
    assert "getLocaleHeaders" in text
    assert "formatNumber" in text
