from __future__ import annotations

import json

import pytest

from scripts import acquire_geotransport_stage32_lag_support_events as acquire


def test_stage32_plan_freezes_both_operators_and_support_set_rule():
    plan = acquire.compile_selection_plan()

    assert set(plan["frozen_operator_artifacts"]) == {
        "release_excitation_identifiability",
        "empirical_lag_support",
    }
    assert all(
        len(value["sha256"]) == 64
        for value in plan["frozen_operator_artifacts"].values()
    )
    assert plan["frozen_empirical_lag_support"] == {
        "lag_candidates_hours": list(range(13)),
        "minimum_pearson_r": 0.8,
        "maximum_best_loss_pearson_r": 0.02,
        "minimum_pair_count": 60,
        "best_lag_must_be_interior": True,
        "output_type": "discrete_supported_lag_set",
        "outcome_values_used_during_event_selection": False,
        "physical_travel_time_admitted": False,
    }
    assert plan["predeclared_lag_support_test"][
        "retuning_after_observation_values"
    ] is False


def test_stage32_selection_phase_has_no_observation_values():
    plan = acquire.compile_selection_plan(values_mode=True)

    assert len(plan["sources"]) == 1
    assert plan["sources"][0]["source"] == "usace_cwms"
    assert plan["request_boundary"][
        "downstream_or_tributary_observation_values_requested"
    ] is False
    assert plan["request_boundary"]["workspace_or_private_data_sent"] is False


def test_stage32_observation_sources_are_frozen_and_extended():
    events = [
        {
            "event_id": f"event_{index}",
            "start_utc": f"202{index + 1}-01-01T00:00:00Z",
            "end_utc": f"202{index + 1}-01-04T00:00:00Z",
        }
        for index in range(4)
    ]

    sources = acquire._observation_sources(events)

    assert len(sources) == 8
    assert {value["site_id"] for value in sources} == {
        "USGS-03424860",
        "USGS-03424730",
    }
    assert all("T12%3A00%3A00Z" in value["url"] for value in sources)


def test_stage32_release_selection_is_deterministic_on_public_pool():
    path = acquire.REPO_ROOT / (
        "data/geotransport_v0_1/"
        "stage31_center_hill_identifiable_response_events/raw/"
        "cwms_release_candidate_pool.json"
    )
    payload = json.loads(path.read_bytes())

    candidates, selected = acquire._select_events(payload)

    assert len(candidates) == 401
    assert [value["event_id"] for value in selected] == [
        "release_step_20220202T1900Z",
        "release_step_20220919T1500Z",
        "release_step_20230911T1500Z",
        "release_step_20210625T1600Z",
    ]
    assert [value["release_direction"] for value in selected] == [
        "decrease",
        "increase",
        "increase",
        "increase",
    ]
    assert all(
        value["release_excitation_identifiability"][
            "blind_response_test_admissible"
        ]
        is True
        for value in selected
    )


def test_stage32_requires_exact_frozen_plan(tmp_path):
    path = tmp_path / "selection_plan.json"
    with pytest.raises(ValueError, match="stage32_plan_must_be_frozen"):
        acquire._load_exact_plan(path, acquire.compile_selection_plan())
    path.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
    with pytest.raises(ValueError, match="stage32_frozen_plan_mismatch"):
        acquire._load_exact_plan(path, acquire.compile_selection_plan())
