import csv
import hashlib
import io
from datetime import UTC, datetime

import pytest

from scripts.audit_geospatial_kernel_counterfactual_action_response import (
    WINDOW_NAMES,
    compile_counterfactual_action_response_posthoc,
)


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    output_path = tmp_path_factory.mktemp("counterfactual-response") / "responses.csv"
    return compile_counterfactual_action_response_posthoc(
        output_path=output_path,
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def test_four_window_audit_separates_structure_from_causal_validity(compiled) -> None:
    body, report = compiled
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))

    assert tuple(report["windows"]) == WINDOW_NAMES
    assert len(rows) == 38_464
    assert report["aggregate_gate"]["four_window_structural_response_gate_passed"] is True
    assert report["aggregate_gate"]["four_window_numerical_usability_gate_passed"] is False
    assert report["aggregate_gate"]["interventional_causal_validation_gate_passed"] is False
    assert report["aggregate_gate"]["counterfactual_interface_promotion_gate_passed"] is False
    assert report["claim_boundary"]["counterfactual_release_effect_causally_validated"] is False
    assert report["claim_boundary"]["prospective_v5_changed"] is False
    assert (
        report["information_boundary"]["future_outcome_used_inside_counterfactual_rollout"] is False
    )
    assert all(row["future_outcome_observation_used"] == "False" for row in rows)
    assert report["outputs"]["responses"]["sha256"] == hashlib.sha256(body).hexdigest()


def test_four_window_audit_exposes_clipping_and_preserves_frozen_gain(compiled) -> None:
    _, report = compiled
    windows = report["windows"]

    assert (
        windows["center_hill_primary"]["numerical_usability_gate"][
            "numerical_usability_gate_passed"
        ]
        is True
    )
    for name in WINDOW_NAMES[1:]:
        assert windows[name]["structural_gate"]["structural_response_gate_passed"] is True
        assert windows[name]["numerical_usability_gate"]["numerical_usability_gate_passed"] is False
    assert windows["center_hill_replication"]["execution"][
        "scenario_clipped_step_fraction"
    ] == pytest.approx(0.06134969325153374)
    assert windows["j_percy_priest_primary"]["execution"][
        "scenario_clipped_step_fraction"
    ] == pytest.approx(0.2377560710894044)
    assert windows["j_percy_priest_replication"]["execution"][
        "scenario_clipped_step_fraction"
    ] == pytest.approx(0.28035868625756266)

    for window in windows.values():
        for delta in ("-50.0", "-10.0", "10.0", "50.0"):
            for horizon in ("6", "12"):
                median_gain = window["metrics_by_release_delta_and_horizon"][delta][horizon][
                    "median_response_per_effective_release_unit"
                ]
                assert median_gain == pytest.approx(0.32988884570396676)
