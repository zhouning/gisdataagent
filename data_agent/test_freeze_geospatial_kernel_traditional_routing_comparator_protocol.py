from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import freeze_geospatial_kernel_traditional_routing_comparator_protocol as freeze

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_traditional_routing_comparator_protocol.json"
)


def test_traditional_routing_comparator_protocol_is_identity_frozen() -> None:
    frozen = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))

    assert frozen == freeze.compile_protocol()
    assert frozen["status"] == "frozen_before_independent_runtime_selection"
    assert frozen["method_scope"]["candidate_selected"] is False
    assert frozen["admission_decision"]["runtime_admitted"] is False
    assert frozen["admission_decision"]["matched_posthoc_execution_permitted"] is False
    assert frozen["claim_boundary"]["new_runtime_acquired_or_built"] is False
    assert frozen["claim_boundary"]["outcome_values_opened_by_this_freeze"] is False


def test_protocol_seal_and_all_bound_artifact_hashes_match() -> None:
    frozen = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    seal = frozen.pop("protocol_seal")
    canonical = json.dumps(
        frozen,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    assert seal["sha256"] == hashlib.sha256(canonical).hexdigest()
    descriptors = list(frozen["bound_evidence"].values()) + list(
        frozen["frozen_code"].values()
    )
    for descriptor in descriptors:
        body = (REPO_ROOT / descriptor["path"]).read_bytes()
        assert descriptor["sha256"] == hashlib.sha256(body).hexdigest()
        assert descriptor["size_bytes"] == len(body)


def test_protocol_freezes_professional_semantic_and_scientific_gates() -> None:
    frozen = freeze.compile_protocol()
    gates = frozen["synthetic_conformance_suite"]["mandatory_gates"]

    assert all(gates.values())
    assert gates["all_required_carry_and_output_values_initialized_before_read"] is True
    assert gates["zero_state_zero_boundary_zero_lateral_produces_zero_state_and_output"] is True
    assert gates["all_impulse_and_step_incremental_responses_are_nonnegative"] is True
    assert gates["timestep_response_quantiles_pass_frozen_stability_tolerances"] is True
    assert gates["branching_dag_and_confluence_mass_accounting_pass"] is True
    assert gates["long_window_input_equals_output_plus_storage_change"] is True
    assert frozen["candidate_identity_contract"]["independence"][
        "no_import_or_call_into_learned_innovation_operators"
    ] is True
    assert "outcome_values" in frozen["forbidden_executor_inputs"]


def test_protocol_binds_same_two_system_axes_and_keeps_window_posthoc_only() -> None:
    frozen = freeze.compile_protocol()
    execution = frozen["matched_execution_contract"]

    assert execution["hour_count"] == 672
    assert execution["systems"]["center_hill"]["feature_count"] == 435
    assert execution["systems"]["j_percy_priest"]["feature_count"] == 43
    assert execution["same_feature_axis_for_all_comparators"] is True
    assert execution["same_action_axis_for_all_comparators"] is True
    assert execution["same_lateral_forcing_axis_for_all_comparators"] is True
    assert execution["same_initial_discharge_axis_for_all_comparators"] is True
    policy = frozen["evaluation_policy"]
    assert policy["existing_672_hour_window"] == "historical_posthoc_comparison_only"
    assert policy["existing_window_may_tune_or_select_candidate"] is False
    assert policy["existing_window_may_be_called_fresh_validation"] is False
    assert policy["fresh_validation_requires_unexposed_window"] is True


def test_tampered_readiness_evidence_is_rejected(tmp_path: Path) -> None:
    payload = json.loads((REPO_ROOT / freeze.READINESS_REPORT).read_text(encoding="utf-8"))
    payload["decision"]["professional_runtime_ready"] = True
    tampered = tmp_path / "tampered_readiness.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="traditional_routing_readiness_report_identity_mismatch",
    ):
        freeze._load_bound_readiness(tampered, root=tmp_path)
