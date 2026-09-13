from copy import deepcopy

import pytest

from data_agent.test_uwm_environmental_kernel_state import state_input
from data_agent.uwm.environmental_kernel.actions import bind_environmental_action
from data_agent.uwm.environmental_kernel.state import build_environmental_state


def built_state():
    return build_environmental_state(state_input())


def green_request(**overrides):
    request = {
        "action_type": "increase_tree_canopy_proxy",
        "target_node_ids": ["grid-a"],
        "declared_area_m2": 40.0,
        "vegetation_fraction_delta": 0.2,
        "implementation_stage": "scenario",
        "rationale": "test action",
        "state_snapshot_digest": built_state()["snapshot_digest"],
        "actor": "client-forged",
    }
    request.update(overrides)
    return request


def test_action_binds_server_actor_and_has_stable_digest():
    state = built_state()
    first = bind_environmental_action(green_request(), state, actor="server-user")
    second_request = green_request(target_node_ids=["grid-a"])
    second = bind_environmental_action(second_request, state, actor="server-user")

    assert first["actor"] == "server-user"
    assert first["client_actor_accepted"] is False
    assert first["causal_effect_estimate"] is False
    assert first["action_digest"] == second["action_digest"]


def test_no_intervention_is_bound_to_state():
    state = built_state()
    action = bind_environmental_action(
        {
            "action_type": "no_intervention",
            "target_node_ids": ["grid-a", "grid-b"],
            "state_snapshot_digest": state["snapshot_digest"],
        },
        state,
        actor="server-user",
    )

    assert action["target_node_ids"] == ["grid-a", "grid-b"]
    assert action["vegetation_fraction_delta"] == 0.0


@pytest.mark.parametrize(
    ("request_factory", "message"),
    [
        (lambda state: green_request(state_snapshot_digest="stale"), "stale_state_snapshot"),
        (lambda state: green_request(target_node_ids=["missing"]), "unknown_target_node"),
        (lambda state: green_request(declared_area_m2=101.0), "declared_area_exceeds_target_geometry"),
        (lambda state: green_request(vegetation_fraction_delta=1.1), "vegetation_fraction_delta_out_of_range"),
        (lambda state: green_request(action_type="invented_green_action"), "unsupported_environmental_action"),
    ],
)
def test_action_rejects_invalid_requests(request_factory, message):
    state = built_state()

    with pytest.raises(ValueError, match=message):
        bind_environmental_action(request_factory(state), state, actor="server-user")


def test_parcel_conversion_requires_matching_s2_artifact():
    state = built_state()
    request = green_request(action_type="convert_declared_parcel_to_green_proxy")

    with pytest.raises(ValueError, match="s2_transition_artifact_required"):
        bind_environmental_action(request, state, actor="server-user")

    artifact = {
        "schema": "uwm.livability_s2_rollout.v1",
        "state_snapshot_digest": state["snapshot_digest"],
        "transition_status": "allowed",
        "artifact_digest": "sha256:s2",
    }
    action = bind_environmental_action(request, state, actor="server-user", s2_artifact=artifact)
    assert action["s2_transition_artifact_digest"] == "sha256:s2"


def test_action_does_not_mutate_request_or_state():
    state = built_state()
    request = green_request()
    state_before = deepcopy(state)
    request_before = deepcopy(request)

    bind_environmental_action(request, state, actor="server-user")

    assert state == state_before
    assert request == request_before
