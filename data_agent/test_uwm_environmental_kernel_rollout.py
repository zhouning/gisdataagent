from copy import deepcopy

import pytest

from data_agent.test_uwm_environmental_kernel_actions import built_state, green_request
from data_agent.test_uwm_environmental_kernel_dynamics import temporal_pm25_step
from data_agent.test_uwm_environmental_kernel_evidence_gate import evidence_input
from data_agent.uwm.environmental_kernel.actions import bind_environmental_action
from data_agent.uwm.environmental_kernel.evidence_gate import build_environmental_evidence_gate
from data_agent.uwm.environmental_kernel.rollout import run_environmental_counterfactual


def rollout_inputs():
    state = built_state()
    intervention = bind_environmental_action(green_request(), state, actor="server-user")
    gate = build_environmental_evidence_gate(evidence_input())
    forcing = {
        "forcing_id": "forcing-1",
        "forcing_digest": "sha256:forcing",
        "steps": [
            {"forcing_id": "forcing-1-step-1", "pm25_background_delta": 1.0},
            {"forcing_id": "forcing-1-step-2", "pm25_background_delta": -0.5},
        ],
    }
    return state, intervention, gate, forcing


def test_rollout_pairs_identical_initial_state_forcing_horizon_and_seed():
    state, intervention, gate, forcing = rollout_inputs()
    result = run_environmental_counterfactual(
        state=state,
        intervention_action=intervention,
        forcing_package=forcing,
        evidence_gate=gate,
        horizon=2,
        random_seed=20260711,
        temporal_channel_steps={"pm25": temporal_pm25_step},
    )

    controls = result["comparison_controls"]
    assert controls["initial_state_digest"] == state["snapshot_digest"]
    assert controls["forcing_digest"] == "sha256:forcing"
    assert controls["horizon"] == 2
    assert controls["random_seed"] == 20260711
    assert len(result["baseline_trajectory"]) == 3
    assert len(result["intervention_trajectory"]) == 3


def test_rollout_keeps_mechanism_contributions_and_supported_deltas():
    state, intervention, gate, forcing = rollout_inputs()
    result = run_environmental_counterfactual(
        state=state,
        intervention_action=intervention,
        forcing_package=forcing,
        evidence_gate=gate,
        horizon=2,
        random_seed=7,
        temporal_channel_steps={"pm25": temporal_pm25_step},
    )

    assert len(result["mechanism_contributions"]["baseline"]) == 2
    assert len(result["mechanism_contributions"]["intervention"]) == 2
    first_delta = result["counterfactual_delta_by_step"][0]["nodes"]["grid-a"]
    assert first_delta["vegetation_fraction_delta"] == 0.2
    assert first_delta["pm25_delta"] == 0.0
    assert first_delta["temperature_delta"] is None
    assert result["not_a_causal_effect_estimate"] is True


def test_rollout_rejects_mismatched_forcing_or_horizon():
    state, intervention, gate, forcing = rollout_inputs()
    bad_forcing = deepcopy(forcing)
    bad_forcing["steps"] = bad_forcing["steps"][:1]

    with pytest.raises(ValueError, match="forcing_horizon_mismatch"):
        run_environmental_counterfactual(
            state=state,
            intervention_action=intervention,
            forcing_package=bad_forcing,
            evidence_gate=gate,
            horizon=2,
            random_seed=7,
            temporal_channel_steps={"pm25": temporal_pm25_step},
        )


def test_rollout_rejects_action_bound_to_other_state():
    state, intervention, gate, forcing = rollout_inputs()
    intervention["state_snapshot_digest"] = "stale"

    with pytest.raises(ValueError, match="intervention_state_mismatch"):
        run_environmental_counterfactual(
            state=state,
            intervention_action=intervention,
            forcing_package=forcing,
            evidence_gate=gate,
            horizon=2,
            random_seed=7,
            temporal_channel_steps={"pm25": temporal_pm25_step},
        )


def test_rollout_is_stable_and_does_not_mutate_inputs():
    state, intervention, gate, forcing = rollout_inputs()
    before = deepcopy((state, intervention, gate, forcing))
    first = run_environmental_counterfactual(
        state=state,
        intervention_action=intervention,
        forcing_package=forcing,
        evidence_gate=gate,
        horizon=2,
        random_seed=7,
        temporal_channel_steps={"pm25": temporal_pm25_step},
    )
    second = run_environmental_counterfactual(
        state=state,
        intervention_action=intervention,
        forcing_package=forcing,
        evidence_gate=gate,
        horizon=2,
        random_seed=7,
        temporal_channel_steps={"pm25": temporal_pm25_step},
    )
    assert first["rollout_digest"] == second["rollout_digest"]
    assert (state, intervention, gate, forcing) == before
