from __future__ import annotations

import json
from pathlib import Path

from scripts import assess_geospatial_kernel_traditional_routing_baseline_readiness as assess


def test_two_system_data_are_ready_but_existing_troute_runtimes_are_not() -> None:
    report = assess.assess_readiness()

    assert report["assessment_integrity_passed"] is True
    assert report["status"] == "blocked_professional_runtime_semantics"
    assert report["decision"] == {
        "two_system_data_ready": True,
        "professional_runtime_ready": False,
        "historical_posthoc_execution_ready": False,
        "fresh_validation_on_existing_window_permitted": False,
        "recommended_next_action": (
            "freeze_and_validate_an_independent_professional_muskingum_cunge_runtime_"
            "before_executing_the_matched_two_system_posthoc_comparison"
        ),
        "generic_muskingum_cunge_family_rejected": False,
        "geospatial_kernel_validated": False,
        "runtime_default_enabled": False,
    }
    assert set(report["systems"]) == {"center_hill", "j_percy_priest"}
    assert all(value["data_ready"] for value in report["systems"].values())
    assert all(all(value["gates"].values()) for value in report["systems"].values())
    official = report["runtime_candidates"]["official_fixed_commit"]
    assert official["build_and_artifact_identity_valid"] is True
    assert official["execution_semantics_audit_valid"] is True
    assert official["fixed_commit_initialization_gate_passed"] is False
    assert official["professional_baseline_eligible"] is False
    derived = report["runtime_candidates"]["derived_initialized_diagnostic"]
    assert derived["build_and_artifact_identity_valid"] is True
    assert derived["negative_lobe_gate_passed"] is False
    assert derived["timestep_stability_gate_passed"] is False
    assert derived["professional_baseline_eligible"] is False
    assert report["evaluation_exposure"]["new_comparator_on_this_window_is_posthoc_only"] is True
    assert report["execution_boundary"] == {
        "network_requests_performed": False,
        "outcome_value_artifacts_opened": False,
        "post_outcome_score_summary_read": True,
        "traditional_routing_predictions_executed": False,
        "predictions_scored": False,
        "candidate_parameters_fitted": False,
    }


def test_bound_source_report_tampering_fails_before_readiness_claim(
    tmp_path: Path,
) -> None:
    payload = json.loads(assess.DEFAULT_EXECUTION_AUDIT.read_text(encoding="utf-8"))
    payload["claim_boundary"]["fixed_commit_kernel_initialization_gate_passed"] = True
    tampered = tmp_path / "execution_semantics.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    report = assess.assess_readiness(execution_audit_path=tampered)

    assert report["assessment_integrity_passed"] is False
    assert report["status"] == "blocked_source_identity_failure"
    assert report["source_artifacts"]["execution_audit"]["identity_matches"] is False
    assert report["decision"]["historical_posthoc_execution_ready"] is False


def test_declared_dynamic_artifact_hash_is_recomputed(tmp_path: Path) -> None:
    artifact = tmp_path / "values.bin"
    artifact.write_bytes(b"original")
    descriptor = {
        "path": artifact.relative_to(tmp_path).as_posix(),
        "sha256": "0" * 64,
        "size_bytes": len(b"original"),
    }

    result = assess._verify_descriptor(descriptor, root=tmp_path)

    assert result["actual_sha256"] != descriptor["sha256"]
    assert result["identity_matches"] is False
