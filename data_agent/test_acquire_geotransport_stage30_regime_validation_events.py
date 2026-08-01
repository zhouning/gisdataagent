from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from scripts import acquire_geotransport_stage30_regime_validation_events as acquire


def test_stage30_plan_freezes_regime_rule_and_four_strata():
    plan = acquire.compile_selection_plan()

    assert plan["mode"] == "selection_plan"
    assert plan["development_evidence"]["event_best_lags_hours"] == [5, 6, 6]
    assert plan["frozen_regime_lag_rule"] == {
        "antecedent_support_hours": 24,
        "antecedent_window": "24_real_hours_strictly_before_step",
        "high_flow_threshold_m3s": 200.0,
        "high_flow_predicted_lag_hours": 5,
        "low_flow_predicted_lag_hours": 6,
        "release_direction_used_for_stratification_only": True,
        "step_magnitude_used_for_stratification_only": True,
        "outcome_values_used": False,
    }
    selection = plan["predeclared_event_selection"]
    assert selection["required_strata_in_selection_order"] == [
        "high_increase",
        "high_decrease",
        "low_increase",
        "low_decrease",
    ]
    assert selection["minimum_event_separation_days"] == 180
    assert selection["step_magnitude_classes"]["large"].startswith(
        "absolute_step_greater"
    )
    assert plan["predeclared_transfer_test"][
        "retuning_after_observation_values"
    ] is False


def test_stage30_selection_phase_has_no_observation_value_urls():
    plan = acquire.compile_selection_plan(values_mode=True)

    assert len(plan["sources"]) == 1
    assert plan["sources"][0]["source"] == "usace_cwms"
    assert plan["request_boundary"][
        "downstream_or_tributary_observation_values_requested"
    ] is False
    assert plan["request_boundary"]["workspace_or_private_data_sent"] is False


def test_stage30_observation_sources_are_event_frozen_and_bounded():
    events = []
    for index, stratum in enumerate(acquire.STRATUM_ORDER):
        events.append(
            {
                "event_id": f"event_{index}",
                "start_utc": f"202{index + 1}-01-01T00:00:00Z",
                "end_utc": f"202{index + 1}-01-04T00:00:00Z",
                "selection_stratum": stratum,
                "role": "blind_regime_validation",
                "selected_without_observation_values": True,
                "rule_frozen_without_observation_values": True,
            }
        )

    sources = acquire._observation_sources(events)

    assert len(sources) == 8
    assert {value["site_id"] for value in sources} == {
        "USGS-03424860",
        "USGS-03424730",
    }
    assert {value["event_id"] for value in sources} == {
        "event_0",
        "event_1",
        "event_2",
        "event_3",
    }
    assert all("T12%3A00%3A00Z" in value["url"] for value in sources)


def test_stage30_release_selection_is_deterministic_and_stratified():
    start = datetime(2021, 1, 1, tzinfo=timezone.utc)
    rows = []
    high = [(100, 250.0, 200.0), (350, 300.0, -200.0)]
    low = [(600, 50.0, 200.0), (850, 75.0, -200.0)]
    events = high + low
    for hour in range(1100 * 24 + 1):
        value = 100.0
        for day, base, step in events:
            if day * 24 - 24 <= hour < day * 24:
                value = base
            elif day * 24 <= hour < day * 24 + 48:
                value = base + step
        rows.append(
            [
                int((start + timedelta(hours=hour)).timestamp() * 1000),
                value,
                0,
            ]
        )

    _, selected = acquire._select_events({"values": rows})

    assert [value["selection_stratum"] for value in selected] == list(
        acquire.STRATUM_ORDER
    )
    assert [value["predicted_lag_hours"] for value in selected] == [5, 5, 6, 6]
    assert all(value["selected_without_observation_values"] for value in selected)
    assert {value["step_magnitude_class"] for value in selected} <= {
        "large",
        "moderate",
    }


def test_stage30_requires_exact_frozen_plan(tmp_path):
    path = tmp_path / "selection_plan.json"
    with pytest.raises(ValueError, match="stage30_plan_must_be_frozen"):
        acquire._load_exact_plan(path, acquire.compile_selection_plan())
    path.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
    with pytest.raises(ValueError, match="stage30_frozen_plan_mismatch"):
        acquire._load_exact_plan(path, acquire.compile_selection_plan())
