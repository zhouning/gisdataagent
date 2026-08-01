from __future__ import annotations

import hashlib

import pytest

from scripts import (
    freeze_geotransport_stage39_component_discharge_value_protocol as freeze,
)


def test_stage39_protocol_binds_stage34_and_stage38_evidence():
    inputs = freeze.build_protocol()["frozen_inputs"]

    assert set(inputs) == {
        "stage34_temporal_semantics_ledger",
        "stage34_temporal_semantics_gates",
        "stage38_catalog_ledger",
        "stage38_catalog_gates",
    }
    for artifact in inputs.values():
        assert artifact["sha256"] == freeze.FROZEN_HASHES[artifact["path"]]


def test_stage39_protocol_preserves_exact_four_component_identities():
    identities = freeze.build_protocol()["admitted_source_identities"]

    assert [value["component"] for value in identities] == list(freeze.COMPONENT_ORDER)
    assert [value["display_alias"] for value in identities] == [
        "Orifice Flow",
        "Sluice Gate Flow",
        "Spillway Flow",
        "Turbine Flow",
    ]
    assert all(
        value["office"] == "LRN"
        and value["unit"] == "cms"
        and value["catalog_interval"] == "1Hour"
        and value["evidence_role"] == "observed_component_discharge_boundary_flux"
        for value in identities
    )


def test_stage39_protocol_uses_authoritative_hourly_interval_semantics():
    semantics = freeze.build_protocol()["source_observation_semantics"]

    assert semantics["measurement_statistic"] == "one_hour_interval_average"
    assert semantics["cwms_composite_default_timestamp_position"] == "end"
    assert semantics["cwms_storage_time_basis"] == "UTC"
    assert semantics["source_time_support_offsets_minutes"] == [-60, 0]
    assert semantics["source_marker_is_release_actuation_instant"] is False


def test_stage39_protocol_freezes_exact_five_year_hourly_support():
    window = freeze.build_protocol()["frozen_value_window"]

    assert window["begin_utc"] == "2021-01-01T00:00:00Z"
    assert window["end_utc"] == "2026-01-01T00:00:00Z"
    assert window["annual_windows"] == [list(value) for value in freeze.YEAR_WINDOWS]
    assert window["expected_unique_inclusive_positions_per_component"] == 43_825
    assert window["expected_combined_component_positions"] == 175_300
    assert window["duplicate_boundary_policy"] == "require_identical_then_keep_one"


def test_stage39_total_requires_all_four_real_component_values():
    total = freeze.build_protocol()["synchronized_total_discharge_eligibility"]

    assert total["formula"] == "orifice+sluice+spillway+turbine"
    assert total["all_four_component_values_required_at_same_hour"] is True
    assert total["partial_component_sum_allowed"] is False
    assert total["missing_component_imputation_allowed"] is False
    assert total["negative_component_value_allowed"] is False
    assert total["total_discharge_values_compiled_during_stage39"] is False


def test_stage39_post_acquisition_scope_is_audit_only():
    assessment = freeze.build_protocol()["post_acquisition_assessment_boundary"]

    assert assessment["per_component_time_coverage_audit_allowed"] is True
    assert assessment["quality_code_inventory_allowed"] is True
    assert assessment["simultaneous_four_component_support_audit_allowed"] is True
    assert assessment["event_selection_allowed"] is False
    assert assessment["downstream_outcome_request_allowed"] is False
    assert assessment["model_fitting_or_scoring_allowed"] is False


def test_stage39_protocol_freeze_is_no_network_and_claims_no_values():
    protocol = freeze.build_protocol()
    boundary = protocol["data_boundary"]
    claims = protocol["claim_boundary"]

    assert boundary["network_requests_allowed_during_protocol_freeze"] is False
    assert boundary["component_values_acquired"] is False
    assert boundary["fresh_approval_required_for_component_value_acquisition"]
    assert claims["component_value_protocol_frozen"] is True
    assert claims["component_values_acquired"] is False
    assert claims["synchronized_total_discharge_admitted"] is False
    assert claims["gate_command_admitted"] is False
    assert claims["causal_intervention_admitted"] is False
    assert claims["runtime_operator_admitted"] is False


def test_stage39_protocol_serialization_is_deterministic():
    first = freeze.json_bytes(freeze.build_protocol())
    second = freeze.json_bytes(freeze.build_protocol())

    assert first == second
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
    assert b"generated_at" not in first


def test_stage39_frozen_artifact_drift_fails_closed(monkeypatch, tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("{}\n", encoding="utf-8")
    relative = "ledger.json"
    monkeypatch.setattr(freeze, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(freeze, "FROZEN_HASHES", {relative: "0" * 64})

    with pytest.raises(ValueError, match="stage39_frozen_artifact_drift"):
        freeze.artifact_record(relative)
