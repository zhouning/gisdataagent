"""Tests for TWM deployment punch-list report helpers."""

from __future__ import annotations

from data_agent.territory_world_model.deployment_punch_list import build_deployment_punch_list


def test_build_deployment_punch_list_maps_missing_readiness_gates_to_actions():
    punch_list = build_deployment_punch_list(
        schema="territory_world_model.validation_bundle_deployment_punch_list.v1",
        status="review",
        readiness_gate={
            "required": False,
            "missing": ["production_observed_history_preflight_pass", "production_scale_readiness_pass"],
            "checks": [
                {
                    "gate": "production_observed_history_preflight_pass",
                    "status": "review",
                    "observed": "not_provided",
                    "requirement": "real observed-history schema and policy-history alignment must pass",
                },
                {
                    "gate": "production_scale_readiness_pass",
                    "status": "review",
                    "observed": "not_provided",
                    "requirement": "production scale profile must pass readiness gates",
                },
            ],
        },
    )

    assert punch_list["schema"] == "territory_world_model.validation_bundle_deployment_punch_list.v1"
    assert punch_list["status"] == "review"
    assert punch_list["required"] is False
    assert punch_list["open_action_count"] == 2
    assert punch_list["blocking_action_count"] == 0
    actions = {item["gate"]: item for item in punch_list["actions"]}
    assert actions["production_observed_history_preflight_pass"]["phase"] == "observed_history"
    assert actions["production_scale_readiness_pass"]["phase"] == "production_scale"
    assert actions["production_scale_readiness_pass"]["blocks_current_run"] is False


def test_build_deployment_punch_list_marks_actions_blocking_when_status_is_blocked():
    punch_list = build_deployment_punch_list(
        schema="territory_world_model.production_onboarding_punch_list.v1",
        status="blocked",
        readiness_gate={
            "required": True,
            "missing": ["claim_ladder_deployable"],
            "checks": [
                {
                    "gate": "claim_ladder_deployable",
                    "status": "review",
                    "observed": "L1",
                    "requirement": "claim ladder must reach L4 deployable GIS support",
                }
            ],
        },
    )

    assert punch_list["status"] == "blocked"
    assert punch_list["required"] is True
    assert punch_list["blocking_action_count"] == 1
    assert punch_list["actions"] == [
        {
            "gate": "claim_ladder_deployable",
            "phase": "claim_ladder",
            "status": "blocked",
            "observed_status": "review",
            "observed": "L1",
            "requirement": "claim ladder must reach L4 deployable GIS support",
            "resolution": "Promote the claim ladder to L4 only after deployable GIS support evidence is available.",
            "blocks_current_run": True,
        }
    ]
