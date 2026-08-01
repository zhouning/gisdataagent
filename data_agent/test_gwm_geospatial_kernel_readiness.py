from __future__ import annotations

import copy
import json
from pathlib import Path

from data_agent.uwm.gwm_geospatial_kernel_readiness import (
    GWM_K0_READINESS_REPORT_SCHEMA,
    assess_gwm_geospatial_kernel_k0,
    is_valid_k0_readiness_certificate,
    validate_k0_certificate_file,
    validate_k0_contract,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT
    / "docs/research/GWM_GEOSPATIAL_KERNEL_K0_READINESS_CONTRACT_2026-07-20.json"
)


def _contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_current_k0_fails_without_conflating_engineering_and_scientific_readiness():
    contract = _contract()
    report = assess_gwm_geospatial_kernel_k0(root=ROOT, contract=contract)

    assert validate_k0_contract(contract) == {"valid": True, "errors": []}
    assert report["schema"] == GWM_K0_READINESS_REPORT_SCHEMA
    assert report["dimensions"]["engineering_implementation"]["status"] == "pass"
    assert report["dimensions"]["development_benchmark_validity"]["status"] == "pass"
    assert report["dimensions"]["kernel_scientific_support"]["status"] == "fail"
    assert report["dimensions"]["domain_and_generalization_support"][
        "status"
    ] == "fail"
    assert report["dimensions"]["public_and_operational_release"]["status"] == "fail"
    assert report["decision"]["k0_scientific_readiness_pass"] is False
    assert report["decision"]["uwm_k1_admitted"] is False
    assert is_valid_k0_readiness_certificate(report) is False


def test_negative_completion_and_nonhidden_variant_cannot_be_promoted_to_k0_pass():
    report = assess_gwm_geospatial_kernel_k0(root=ROOT, contract=_contract())
    observed = report["observed_negative_evidence"]

    assert observed["dam_gk_v0_1_research_status"] == "complete_negative"
    assert observed["dam_gk_v0_1_supported_hypothesis_count"] == 0
    assert observed["dam_gk_v0_2_reference_gate_pass_count"] == 0
    assert observed["dam_gk_v0_2_reference_gate_seed_count"] == 10
    assert observed["action_transport_v0_2_independent_hidden_confirmation"] is False
    assert observed["action_transport_v0_2_stable_across_all_systems"] is False
    assert observed["forcing_admission_status"] == "fail"


def test_first_closable_gap_is_forcing_admission_not_uwm_experiment_execution():
    report = assess_gwm_geospatial_kernel_k0(root=ROOT, contract=_contract())
    gap = report["first_legitimately_closable_gap"]

    assert gap["id"] == "K0-DATA-FORCING-ADMISSION"
    assert gap["status"] == "blocked"
    assert gap["nonpass_gates"] == [
        "temporal_resolution_and_coverage",
        "action_outcome_independence",
        "input_time_availability",
        "spatial_role_and_topology",
        "license_and_access",
        "normalization_and_split",
    ]
    assert report["decision"]["paper_experimenter_admitted"] is False


def test_artifact_hash_mismatch_fails_every_evidence_dependent_decision():
    contract = copy.deepcopy(_contract())
    contract["evidence_artifacts"]["dam_gk_v0_1_completion"]["sha256"] = "0" * 64
    report = assess_gwm_geospatial_kernel_k0(root=ROOT, contract=contract)

    assert report["evidence_integrity"]["status"] == "fail"
    assert report["evidence_integrity"]["artifact_failures"][0]["reason"] == (
        "sha256_mismatch"
    )
    assert report["decision"]["uwm_k1_admitted"] is False


def test_public_release_is_separate_from_a_semantically_valid_k0_certificate():
    report = {
        "schema": GWM_K0_READINESS_REPORT_SCHEMA,
        "evidence_integrity": {"status": "pass"},
        "dimensions": {
            name: {"status": "pass", "required_for_uwm_k1": True}
            for name in (
                "engineering_implementation",
                "development_benchmark_validity",
                "kernel_scientific_support",
                "domain_and_generalization_support",
            )
        }
        | {
            "public_and_operational_release": {
                "status": "fail",
                "required_for_uwm_k1": False,
            }
        },
        "decision": {
            "k0_scientific_readiness_pass": True,
            "uwm_k1_admitted": True,
            "public_release_ready": False,
            "paper_experimenter_admitted": False,
            "status": "pass_for_uwm_k1",
        },
        "source_artifacts": {
            "fixture": {"path": "fixture.json", "sha256": "a" * 64}
        },
    }

    assert is_valid_k0_readiness_certificate(report) is True


def test_certificate_requires_the_named_k1_dimensions_and_cannot_admit_paper_execution():
    report = {
        "schema": GWM_K0_READINESS_REPORT_SCHEMA,
        "evidence_integrity": {"status": "pass"},
        "dimensions": {
            name: {"status": "pass", "required_for_uwm_k1": True}
            for name in (
                "engineering_implementation",
                "development_benchmark_validity",
                "kernel_scientific_support",
                "domain_and_generalization_support",
            )
        },
        "decision": {
            "k0_scientific_readiness_pass": True,
            "uwm_k1_admitted": True,
            "paper_experimenter_admitted": False,
            "status": "pass_for_uwm_k1",
        },
        "source_artifacts": {
            "fixture": {"path": "fixture.json", "sha256": "a" * 64}
        },
    }

    assert is_valid_k0_readiness_certificate(report) is True

    substituted = copy.deepcopy(report)
    substituted["dimensions"].pop("kernel_scientific_support")
    substituted["dimensions"]["self_attested_support"] = {
        "status": "pass",
        "required_for_uwm_k1": True,
    }
    assert is_valid_k0_readiness_certificate(substituted) is False

    paper_execution = copy.deepcopy(report)
    paper_execution["decision"]["paper_experimenter_admitted"] = True
    assert is_valid_k0_readiness_certificate(paper_execution) is False

    missing_paper_boundary = copy.deepcopy(report)
    missing_paper_boundary["decision"].pop("paper_experimenter_admitted")
    assert is_valid_k0_readiness_certificate(missing_paper_boundary) is False


def test_certificate_file_revalidates_source_artifact_hashes(tmp_path):
    source = tmp_path / "source.json"
    source.write_text('{"source":true}\n', encoding="utf-8")
    from data_agent.uwm.gwm_geospatial_kernel_readiness import sha256_file

    payload = {
        "schema": GWM_K0_READINESS_REPORT_SCHEMA,
        "evidence_integrity": {"status": "pass"},
        "dimensions": {
            name: {"status": "pass", "required_for_uwm_k1": True}
            for name in (
                "engineering_implementation",
                "development_benchmark_validity",
                "kernel_scientific_support",
                "domain_and_generalization_support",
            )
        },
        "decision": {
            "k0_scientific_readiness_pass": True,
            "uwm_k1_admitted": True,
            "paper_experimenter_admitted": False,
            "status": "pass_for_uwm_k1",
        },
        "source_artifacts": {
            "fixture": {"path": "source.json", "sha256": sha256_file(source)}
        },
    }
    certificate = tmp_path / "certificate.json"
    certificate.write_text(json.dumps(payload), encoding="utf-8")
    assert validate_k0_certificate_file(root=tmp_path, path=certificate) is True

    source.write_text('{"source":false}\n', encoding="utf-8")
    assert validate_k0_certificate_file(root=tmp_path, path=certificate) is False
