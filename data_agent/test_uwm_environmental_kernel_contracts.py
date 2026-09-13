from data_agent.uwm.environmental_kernel.contracts import (
    BOUNDED_PROXY,
    OBSERVED_CALIBRATED,
    OBSERVED_CONTEXT,
    UNAVAILABLE,
    validate_environmental_action,
    validate_environmental_state,
    validate_rollout_result,
)


def test_contract_support_levels_are_explicit():
    assert {
        OBSERVED_CALIBRATED,
        OBSERVED_CONTEXT,
        BOUNDED_PROXY,
        UNAVAILABLE,
    } == {
        "observed_calibrated",
        "observed_context",
        "bounded_proxy",
        "unavailable",
    }


def test_state_requires_evidence_and_per_field_support():
    result = validate_environmental_state(
        {
            "schema": "uwm.environmental_state.v1",
            "spatial_nodes": [
                {
                    "node_id": "grid-1",
                    "pm25_ugm3": 18.0,
                    "pm25_support_level": "unknown",
                }
            ],
        }
    )

    assert result["valid"] is False
    assert "evidence_bundle_id is required" in result["errors"]
    assert "spatial_nodes[0].pm25_support_level is invalid" in result["errors"]


def test_unavailable_state_value_must_remain_null():
    result = validate_environmental_state(
        {
            "schema": "uwm.environmental_state.v1",
            "evidence_bundle_id": "evidence-1",
            "spatial_nodes": [
                {
                    "node_id": "grid-1",
                    "temperature_c": 0.0,
                    "temperature_support_level": UNAVAILABLE,
                }
            ],
        }
    )

    assert result["valid"] is False
    assert "spatial_nodes[0].temperature_c must be null when unavailable" in result["errors"]


def test_action_rejects_unsupported_causal_claim():
    result = validate_environmental_action(
        {
            "schema": "uwm.environmental_action.v1",
            "action_type": "increase_tree_canopy_proxy",
            "state_snapshot_digest": "state-1",
            "actor": "user-1",
            "causal_effect_estimate": True,
        }
    )

    assert result["valid"] is False
    assert "causal_effect_estimate must remain false" in result["errors"]


def test_rollout_requires_non_causal_boundary_and_mechanism_outputs():
    result = validate_rollout_result(
        {
            "schema": "uwm.environmental_rollout.v1",
            "baseline_trajectory": [],
            "intervention_trajectory": [],
            "not_a_causal_effect_estimate": False,
        }
    )

    assert result["valid"] is False
    assert "not_a_causal_effect_estimate must be true" in result["errors"]
    assert "mechanism_contributions is required" in result["errors"]
    assert "evidence_gate is required" in result["errors"]
