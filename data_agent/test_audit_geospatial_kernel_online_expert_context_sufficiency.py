from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from scripts import audit_geospatial_kernel_online_expert_context_sufficiency as audit

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_online_expert_context_sufficiency_audit.json"
)


def test_frozen_context_sufficiency_audit_recomputes_exactly() -> None:
    frozen = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    report = audit.compile_online_expert_context_sufficiency_audit(
        generated_at=datetime.fromisoformat(frozen["generated_at"]),
    )

    assert report == frozen
    descriptor = frozen["implementation_artifacts"]["auditor"]
    body = (REPO_ROOT / descriptor["path"]).read_bytes()
    assert hashlib.sha256(body).hexdigest() == descriptor["sha256"]
    assert len(body) == descriptor["size_bytes"]


def test_current_artifacts_do_not_support_a_context_gate() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    interpretation = report["diagnostic_interpretation"]
    availability = report["explicit_hydrologic_context_availability"]

    assert interpretation["j_percy_priest_comparison_target_degenerate"] is True
    assert interpretation["explicit_context_absent_from_prediction_artifacts"] is True
    assert interpretation["historical_release_and_nwm_forcing_available_separately"] is True
    assert availability["prediction_artifacts"]["reservoir_release"] is False
    assert availability["prediction_artifacts"]["nwm_lateral_inflow"] is False
    assert availability["separately_bound_historical_inputs"]["reservoir_release"] is True
    assert availability["separately_bound_historical_inputs"]["nwm_lateral_inflow"] is True
    assert availability["operational_issue_time_vintages_verified"] is False
    assert interpretation["existing_prediction_artifacts_sufficient_for_context_gate"] is False
    assert interpretation["context_gate_candidate_identified"] is False
    assert interpretation["new_model_version_created"] is False
    assert interpretation["prospective_primary_candidate_changed"] is False
    assert report["claim_boundary"]["context_conditioned_gate_validated"] is False


def test_retrospective_hydrologic_context_does_not_add_transferable_signal() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    interpretation = report["diagnostic_interpretation"]
    center = report["retrospective_context_transfer_diagnostics"]["center_hill"]
    jpp = report["retrospective_context_transfer_diagnostics"]["j_percy_priest"]

    assert interpretation["center_hill_context_same_sign_estimable_count"] == 7
    assert interpretation[
        "center_hill_context_maximum_minimum_absolute_correlation"
    ] == pytest.approx(0.040242, abs=1e-6)
    assert interpretation[
        "center_hill_prediction_derived_maximum_minimum_absolute_correlation"
    ] == pytest.approx(0.040403, abs=1e-6)
    assert (
        interpretation[
            "historical_context_strengthens_cross_window_signal_over_prediction_derived_features"
        ]
        is False
    )
    assert center["retrospective_hydrologic_context"]["any_association_estimable"] is True
    assert jpp["retrospective_hydrologic_context"]["any_association_estimable"] is False

    windows = report["windows"]
    assert windows["center_hill_primary"]["retrospective_context_path_feature_count"] == 26
    assert windows["j_percy_priest_primary"]["retrospective_context_path_feature_count"] == 5
    assert all(value["retrospective_context_input_hour_count"] == 672 for value in windows.values())


def test_replication_only_signal_is_not_misreported_as_transfer_evidence() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    primary = report["windows"]["center_hill_primary"]["loss_association_by_horizon"]
    replication = report["windows"]["center_hill_replication"]["loss_association_by_horizon"]

    assert primary["12"]["pearson_correlation_selector_minus_v5_squared_loss"][
        "expert_delta_scaled"
    ] == pytest.approx(0.0018, abs=1e-4)
    assert replication["12"]["pearson_correlation_selector_minus_v5_squared_loss"][
        "expert_delta_scaled"
    ] == pytest.approx(0.3254, abs=1e-4)
    assert (
        report["diagnostic_interpretation"][
            "maximum_absolute_candidate_feature_correlation_center_hill_primary"
        ]
        < 0.067
    )
