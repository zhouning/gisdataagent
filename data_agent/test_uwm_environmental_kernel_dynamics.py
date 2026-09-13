from copy import deepcopy

from data_agent.test_uwm_environmental_kernel_actions import built_state, green_request
from data_agent.test_uwm_environmental_kernel_evidence_gate import evidence_input
from data_agent.uwm.environmental_kernel.actions import bind_environmental_action
from data_agent.uwm.environmental_kernel.dynamics import step_environmental_state
from data_agent.uwm.environmental_kernel.evidence_gate import build_environmental_evidence_gate


def temporal_pm25_step(*, node, forcing, channel_gate):
    if node.get("pm25_ugm3") is None:
        return None
    return {
        "value": node["pm25_ugm3"] + forcing["pm25_background_delta"],
        "support_level": channel_gate["support_level"],
        "coefficient_source": channel_gate["coefficient_source"],
    }


def test_step_separates_temporal_direct_and_spatial_mechanisms():
    state = built_state()
    action = bind_environmental_action(green_request(), state, actor="server-user")
    gate = build_environmental_evidence_gate(evidence_input())

    result = step_environmental_state(
        state=state,
        action=action,
        forcing={"forcing_id": "forcing-1", "pm25_background_delta": 2.0},
        evidence_gate=gate,
        temporal_channel_steps={"pm25": temporal_pm25_step},
    )

    assert set(result["mechanism_contributions"]) == {
        "temporal",
        "direct_action",
        "spatial_propagation",
    }
    assert result["mechanism_contributions"]["temporal"]["grid-a"]["pm25_delta"] == 2.0
    assert result["mechanism_contributions"]["direct_action"]["grid-a"]["vegetation_fraction_delta"] == 0.2
    assert result["mechanism_contributions"]["direct_action"]["grid-a"]["pm25_delta"] is None


def test_temporal_pm25_change_does_not_create_action_benefit():
    state = built_state()
    no_action = bind_environmental_action(
        {
            "action_type": "no_intervention",
            "target_node_ids": ["grid-a"],
            "state_snapshot_digest": state["snapshot_digest"],
        },
        state,
        actor="server-user",
    )
    gate = build_environmental_evidence_gate(evidence_input())
    result = step_environmental_state(
        state=state,
        action=no_action,
        forcing={"forcing_id": "forcing-1", "pm25_background_delta": 3.0},
        evidence_gate=gate,
        temporal_channel_steps={"pm25": temporal_pm25_step},
    )

    assert result["state"]["spatial_nodes"][1]["pm25_ugm3"] == 21.0
    assert result["mechanism_contributions"]["direct_action"]["grid-a"] == {}


def test_unavailable_action_channels_remain_null_not_zero():
    state = built_state()
    action = bind_environmental_action(green_request(), state, actor="server-user")
    gate = build_environmental_evidence_gate(evidence_input())
    result = step_environmental_state(
        state=state,
        action=action,
        forcing={"forcing_id": "forcing-1", "pm25_background_delta": 0.0},
        evidence_gate=gate,
        temporal_channel_steps={"pm25": temporal_pm25_step},
    )

    direct = result["mechanism_contributions"]["direct_action"]["grid-a"]
    assert direct["pm25_delta"] is None
    assert direct["temperature_delta"] is None
    assert direct["pm25_support_level"] == "unavailable"


def test_spatial_channels_have_distinct_sources_and_disabled_channels_emit_no_delta():
    payload = evidence_input()
    payload["spatial_channels"]["pm25"] = {
        "proxy_bound": [-0.2, 0.0],
        "coefficient_source": "pm25_decay_v1",
    }
    payload["spatial_channels"]["temperature"] = {
        "proxy_bound": [-0.1, 0.0],
        "coefficient_source": "thermal_decay_v1",
    }
    gate = build_environmental_evidence_gate(payload)
    state = built_state()
    action = bind_environmental_action(green_request(), state, actor="server-user")
    result = step_environmental_state(
        state=state,
        action=action,
        forcing={"forcing_id": "forcing-1", "pm25_background_delta": 0.0},
        evidence_gate=gate,
        temporal_channel_steps={"pm25": temporal_pm25_step},
    )

    messages = result["propagation_messages"]
    sources = {message["effect_channel"]: message["coefficient_source"] for message in messages}
    assert sources["pm25"] == "pm25_decay_v1"
    assert sources["temperature"] == "thermal_decay_v1"
    assert sources["vegetation"] == "adjacency_distance_decay_v1"

    closed_gate = build_environmental_evidence_gate(evidence_input())
    closed = step_environmental_state(
        state=state,
        action=action,
        forcing={"forcing_id": "forcing-1", "pm25_background_delta": 0.0},
        evidence_gate=closed_gate,
        temporal_channel_steps={"pm25": temporal_pm25_step},
    )
    assert all(message["effect_channel"] != "pm25" for message in closed["propagation_messages"])


def test_step_does_not_mutate_inputs():
    state = built_state()
    action = bind_environmental_action(green_request(), state, actor="server-user")
    gate = build_environmental_evidence_gate(evidence_input())
    before = deepcopy((state, action, gate))
    step_environmental_state(
        state=state,
        action=action,
        forcing={"forcing_id": "forcing-1", "pm25_background_delta": 0.0},
        evidence_gate=gate,
        temporal_channel_steps={"pm25": temporal_pm25_step},
    )
    assert (state, action, gate) == before
