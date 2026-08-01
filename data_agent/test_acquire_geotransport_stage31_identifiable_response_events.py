from __future__ import annotations

import json

import pytest

from scripts import (
    acquire_geotransport_stage31_identifiable_response_events as acquire,
)


def test_stage31_plan_freezes_operator_and_support_gate():
    plan = acquire.compile_selection_plan()

    assert len(plan["frozen_operator_artifact"]["sha256"]) == 64
    assert plan["frozen_release_support_gate"] == {
        "reference_support_offsets_hours": [-24, -6],
        "maximum_excursion_support_hours": 12,
        "excursion_step_fraction": 0.25,
        "minimum_excursion_support_hours": 3,
        "minimum_normalized_volume_step_hours": 3.0,
        "minimum_release_standard_deviation_m3s": 30.0,
        "maximum_absolute_lag_autocorrelation": 0.97,
        "maximum_lag_design_condition_number": 50.0,
        "lag_design_candidates_hours": list(range(13)),
        "outcome_values_used": False,
        "exact_lag_identified_by_input_gate": False,
    }
    assert plan["predeclared_response_test"][
        "retuning_after_observation_values"
    ] is False
    assert plan["development_evidence"]["stage31_outcomes_used"] is False


def test_stage31_selection_phase_has_no_observation_values():
    plan = acquire.compile_selection_plan(values_mode=True)

    assert len(plan["sources"]) == 1
    assert plan["sources"][0]["source"] == "usace_cwms"
    assert plan["request_boundary"][
        "downstream_or_tributary_observation_values_requested"
    ] is False
    assert plan["request_boundary"]["workspace_or_private_data_sent"] is False


def test_stage31_observation_sources_are_frozen_and_extended():
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


def test_stage31_release_selection_is_deterministic_on_public_pool():
    path = acquire.REPO_ROOT / (
        "data/geotransport_v0_1/"
        "stage30_center_hill_regime_validation_events/raw/"
        "cwms_release_candidate_pool.json"
    )
    payload = json.loads(path.read_bytes())

    candidates, selected = acquire._select_events(payload)

    assert len(candidates) == 1812
    assert [value["event_id"] for value in selected] == [
        "release_step_20250606T1600Z",
        "release_step_20210322T1200Z",
        "release_step_20220613T1300Z",
        "release_step_20240203T1300Z",
    ]
    assert [value["selection_stratum"] for value in selected] == list(
        acquire.STRATUM_ORDER
    )
    assert all(
        value["release_excitation_identifiability"][
            "blind_response_test_admissible"
        ]
        is True
        for value in selected
    )


def test_stage31_requires_exact_frozen_plan(tmp_path):
    path = tmp_path / "selection_plan.json"
    with pytest.raises(ValueError, match="stage31_plan_must_be_frozen"):
        acquire._load_exact_plan(path, acquire.compile_selection_plan())
    path.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
    with pytest.raises(ValueError, match="stage31_frozen_plan_mismatch"):
        acquire._load_exact_plan(path, acquire.compile_selection_plan())
