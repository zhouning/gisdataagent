from data_agent.uwm.world_model_evidence_readiness import (
    UWM_WORLD_MODEL_EVIDENCE_READINESS_SCHEMA,
    build_world_model_evidence_readiness,
)


def test_world_model_evidence_readiness_downgrades_when_transition_gate_missing():
    gate = {
        "observed_state_prediction_superiority_claim": True,
        "external_temporal_transition_superiority_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "supported_claims": [
            {
                "claim": "observed_temporal_state_prediction_advantage_over_static_baseline_suite",
                "scope": "observed_temporal_state_prediction_not_policy_outcome",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
            }
        ],
        "evidence_slices": {
            "openaq_observed_temporal_state": {
                "source_artifact_exists": True,
                "claim_level": "bounded_support",
                "overall_holdout_win_rate": 0.833333,
                "temporal_order_negative_control_passed": True,
            },
            "tap_external_temporal_transition": {
                "source_artifact_exists": False,
                "claim_level": "not_for_claim",
            },
            "learned_world_model_rollout": {
                "source_artifact_exists": True,
                "claim_level": "bounded_support",
                "holdout_reward_mae": 0.1,
                "train_mean_reward_mae": 0.2,
                "imagined_advantage_over_static": 0.1,
                "imagined_advantage_over_one_step": 0.1,
            },
            "livability_intervention_package": {
                "source_artifact_exists": True,
                "claim_level": "exploratory_only",
                "predicted_delta": {"livability_delta": 0.1},
            },
            "admin_spatial_adjacency_graph": {
                "source_artifact_exists": True,
                "claim_level": "bounded_support",
                "node_count": 10,
            },
            "local_planning_data_foundation": {
                "source_artifact_exists": True,
                "claim_level": "fragile",
            },
        },
        "remaining_gates": ["observed_policy_outcome_required"],
    }

    readiness = build_world_model_evidence_readiness(gate)

    assert readiness["schema"] == UWM_WORLD_MODEL_EVIDENCE_READINESS_SCHEMA
    assert readiness["traditional_method_comparison_ready"] is False
    assert readiness["system_level_superiority_summary"] == "no_system_level_superiority_claim_supported"
    assert readiness["policy_outcome_superiority_ready"] is False
    assert readiness["architecture_evidence"]["simulator"]["ready"] is False
    assert readiness["architecture_evidence"]["simulator"]["external_temporal_transition_ready"] is False
    assert "observed_policy_outcome_superiority" in readiness["forbidden_claims"]


def test_world_model_evidence_readiness_exposes_spatial_causal_question_contracts():
    gate = {
        "observed_state_prediction_superiority_claim": True,
        "external_temporal_transition_superiority_claim": True,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "supported_claims": [
            {
                "claim": "spatial_causal_question_contracts_define_do_queries_and_block_policy_overclaims",
                "scope": "spatial_causal_question_contract_not_policy_outcome",
                "claim_level": "spatial_causal_question_contract_only",
                "policy_outcome_claim": False,
            }
        ],
        "evidence_slices": {
            "spatial_causal_question_registry": {
                "source_artifact_exists": True,
                "spatial_causal_question_registry_ready": True,
                "claim_level": "spatial_causal_question_contract_only",
                "active_causal_question_count": 3,
                "underidentified_policy_effect_question_count": 3,
                "identified_policy_effect_question_count": 0,
                "authoritative_required_table_count": 5,
                "ready_authoritative_table_count": 0,
                "algorithmic_causal_diagnostic_ready": True,
                "observed_outcome_panel_ready": False,
                "causal_effect_calibration_ready": False,
                "active_action_types": [
                    "increase_green_infrastructure",
                    "traffic_emission_control",
                    "add_community_service",
                ],
                "observed_policy_outcome_superiority_claim": False,
            },
            "openaq_observed_temporal_state": {
                "source_artifact_exists": True,
                "claim_level": "bounded_support",
                "overall_holdout_win_rate": 0.833333,
                "temporal_order_negative_control_passed": True,
            },
            "tap_external_temporal_transition": {
                "source_artifact_exists": True,
                "claim_level": "bounded_support",
                "supported_claim": "tap_external_temporal_dynamics_advantage_without_spatial_claim",
                "series_count": 10000,
                "holdout_count": 40000,
                "best_transition_mae": 7.003808,
                "best_traditional_static_mae": 9.309192,
                "best_non_spatial_dynamic_mae": 7.011689,
                "paired_win_rate_vs_best_non_spatial_dynamic": 0.5077,
                "temporal_order_negative_control_passed": True,
                "future_label_leakage_guard_passed": True,
                "spatial_negative_control_passed": False,
            },
        },
        "remaining_gates": ["observed_policy_outcome_required"],
    }

    readiness = build_world_model_evidence_readiness(gate)

    spatial_causal = readiness["architecture_evidence"]["spatial_causal_questions"]
    assert spatial_causal["ready"] is True
    assert spatial_causal["claim_level"] == "spatial_causal_question_contract_only"
    assert spatial_causal["active_causal_question_count"] == 3
    assert spatial_causal["underidentified_policy_effect_question_count"] == 3
    assert spatial_causal["identified_policy_effect_question_count"] == 0
    assert spatial_causal["active_action_types"] == [
        "increase_green_infrastructure",
        "traffic_emission_control",
        "add_community_service",
    ]
    assert spatial_causal["policy_outcome_claim"] is False
    assert "build_spatial_causal_question_registry" not in readiness["next_actions"]
    assert "collect_observed_policy_outcome_validation_data" in readiness["next_actions"]
