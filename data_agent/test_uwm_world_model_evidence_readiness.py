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
