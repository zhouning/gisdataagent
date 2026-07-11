from data_agent.uwm.environmental_kernel.evidence_gate import build_environmental_evidence_gate


def evidence_input(**overrides):
    payload = {
        "state_observation": {
            "ready": True,
            "support_level": "observed_context",
            "source_ids": ["environment-fusion-1"],
        },
        "temporal_channels": {
            "pm25": {
                "holdout_passed": True,
                "calibration_artifact_id": "tap-holdout-1",
                "coefficient_source": "tap_external_dynamics",
            },
            "temperature": {
                "holdout_passed": False,
                "calibration_artifact_id": None,
                "coefficient_source": None,
            },
        },
        "action_response_channels": {
            "pm25": {},
            "temperature": {},
            "vegetation": {
                "deterministic_state_edit": True,
                "coefficient_source": "declared_action_geometry",
            },
        },
        "spatial_channels": {
            "pm25": {},
            "temperature": {},
            "vegetation": {
                "proxy_bound": [0.0, 1.0],
                "coefficient_source": "adjacency_distance_decay_v1",
            },
        },
        "external_forcing": {
            "scene_aligned": True,
            "forcing_id": "forcing-1",
        },
    }
    payload.update(overrides)
    return payload


def test_temporal_calibration_does_not_promote_action_response():
    gate = build_environmental_evidence_gate(evidence_input())

    assert gate["temporal_calibration"]["pm25"]["support_level"] == "observed_calibrated"
    assert gate["direct_action_response"]["pm25"]["support_level"] == "unavailable"
    assert "pm25_action_response_unavailable" in gate["production_blockers"]


def test_channels_are_evaluated_independently():
    gate = build_environmental_evidence_gate(evidence_input())

    assert gate["temporal_calibration"]["temperature"]["support_level"] == "unavailable"
    assert gate["direct_action_response"]["vegetation"]["support_level"] == "observed_context"
    assert gate["spatial_propagation"]["vegetation"]["support_level"] == "bounded_proxy"
    assert gate["spatial_propagation"]["pm25"]["support_level"] == "unavailable"


def test_declared_bounded_proxy_requires_bound_and_source():
    payload = evidence_input()
    payload["action_response_channels"]["temperature"] = {
        "proxy_bound": [-1.0, 0.0],
        "coefficient_source": "published_transfer_range",
    }
    gate = build_environmental_evidence_gate(payload)
    assert gate["direct_action_response"]["temperature"]["support_level"] == "bounded_proxy"

    payload["action_response_channels"]["temperature"] = {"proxy_bound": [-1.0, 0.0]}
    gate = build_environmental_evidence_gate(payload)
    assert gate["direct_action_response"]["temperature"]["support_level"] == "unavailable"


def test_counterfactual_gate_requires_aligned_forcing_but_remains_non_causal():
    gate = build_environmental_evidence_gate(evidence_input())
    assert gate["counterfactual_comparison"]["ready"] is True
    assert gate["counterfactual_comparison"]["causal_effect_claim"] is False
    assert gate["max_claim_level"] == "bounded_action_conditioned_environmental_scenario"

    payload = evidence_input(external_forcing={"scene_aligned": False, "forcing_id": "forcing-1"})
    gate = build_environmental_evidence_gate(payload)
    assert gate["counterfactual_comparison"]["ready"] is False
    assert "external_forcing_not_scene_aligned" in gate["production_blockers"]


def test_gate_output_is_deterministic():
    first = build_environmental_evidence_gate(evidence_input())
    second = build_environmental_evidence_gate(evidence_input())
    assert first == second
    assert first["schema"] == "uwm.environmental_evidence_gate.v1"
