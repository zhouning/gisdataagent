"""Fail-closed K0 readiness assessment for the shared GWM Geospatial Kernel."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


GWM_K0_READINESS_CONTRACT_SCHEMA = (
    "gwm.geospatial_kernel.k0_readiness_contract.v1"
)
GWM_K0_READINESS_REPORT_SCHEMA = "gwm.geospatial_kernel.k0_readiness_report.v1"
K0_UWM_K1_REQUIRED_DIMENSIONS = frozenset(
    {
        "engineering_implementation",
        "development_benchmark_validity",
        "kernel_scientific_support",
        "domain_and_generalization_support",
    }
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_k0_contract(contract: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if contract.get("schema") != GWM_K0_READINESS_CONTRACT_SCHEMA:
        errors.append("schema_mismatch")
    if contract.get("aggregation") != "non_compensatory_all_required_dimensions":
        errors.append("aggregation_must_be_non_compensatory")
    required_dimensions = contract.get("uwm_k1_required_dimensions")
    if set(required_dimensions or []) != K0_UWM_K1_REQUIRED_DIMENSIONS:
        errors.append("uwm_k1_required_dimensions_mismatch")
    if not contract.get("evidence_artifacts"):
        errors.append("evidence_artifacts_required")
    thresholds = contract.get("thresholds") or {}
    if thresholds.get("required_seed_count") != 10:
        errors.append("required_seed_count_must_be_10")
    if thresholds.get("required_stability_pass_count") != 8:
        errors.append("required_stability_pass_count_must_be_8")
    return {"valid": not errors, "errors": errors}


def _verify_and_load_evidence(
    root: Path, contract: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    evidence: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, str]] = []
    for role, record in (contract.get("evidence_artifacts") or {}).items():
        if not isinstance(record, dict):
            failures.append({"role": role, "reason": "invalid_record"})
            continue
        relative_path = record.get("path")
        expected_hash = record.get("sha256")
        if not isinstance(relative_path, str) or not relative_path:
            failures.append({"role": role, "reason": "path_required"})
            continue
        path = (root / relative_path).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            failures.append({"role": role, "reason": "path_escapes_root"})
            continue
        if not path.is_file():
            failures.append({"role": role, "path": relative_path, "reason": "missing"})
            continue
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            failures.append(
                {
                    "role": role,
                    "path": relative_path,
                    "reason": "sha256_mismatch",
                    "expected": str(expected_hash),
                    "actual": actual_hash,
                }
            )
            continue
        try:
            evidence[role] = load_json(path)
        except (OSError, json.JSONDecodeError):
            failures.append(
                {"role": role, "path": relative_path, "reason": "invalid_json"}
            )
    return evidence, failures


def _dimension(checks: dict[str, bool], *, required_for_uwm_k1: bool) -> dict[str, Any]:
    blockers = [name for name, passed in checks.items() if passed is not True]
    return {
        "status": "pass" if not blockers else "fail",
        "required_for_uwm_k1": required_for_uwm_k1,
        "checks": checks,
        "blockers": blockers,
    }


def assess_gwm_geospatial_kernel_k0(
    *, root: Path, contract: dict[str, Any]
) -> dict[str, Any]:
    """Assess K0 without converting completion or release metadata into support."""

    root = root.resolve()
    contract_validation = validate_k0_contract(contract)
    evidence, artifact_failures = _verify_and_load_evidence(root, contract)
    evidence_integrity = contract_validation["valid"] and not artifact_failures

    completion = evidence.get("dam_gk_v0_1_completion", {})
    benchmark = evidence.get("gwm_bench_v0_2_readiness", {})
    stability = evidence.get("gwm_bench_v0_2_kernel_stability", {})
    action_v0_2 = evidence.get("dam_gk_action_transport_v0_2", {})
    forcing = evidence.get("gwm_bench_v0_3_forcing_admission", {})
    threshold = int((contract.get("thresholds") or {}).get(
        "required_stability_pass_count", 8
    ))

    engineering = _dimension(
        {
            "evidence_integrity": evidence_integrity,
            "engineering_baseline_complete": completion.get(
                "engineering_baseline", {}
            ).get("status")
            == "complete",
            "required_kernel_capabilities_implemented": completion.get(
                "engineering_baseline", {}
            ).get("checks", {}).get("required_kernel_capabilities_implemented")
            is True,
            "fail_closed_experiment_contract": completion.get(
                "engineering_baseline", {}
            ).get("checks", {}).get("experiment_contract_valid")
            is True,
        },
        required_for_uwm_k1=True,
    )

    readiness = benchmark.get("readiness_dimensions", {})
    evaluator = benchmark.get("hydro_evaluator_conformance", {})
    development_benchmark = _dimension(
        {
            "evidence_integrity": evidence_integrity,
            "protocol_integrity_ready": readiness.get("protocol_integrity_ready")
            is True,
            "benchmark_discriminability_ready": readiness.get(
                "benchmark_discriminability_ready"
            )
            is True,
            "evaluator_conformance_passed": evaluator.get("status")
            == "evaluator_conformance_passed",
            "internal_development_ready": readiness.get(
                "internal_development_ready"
            )
            is True,
        },
        required_for_uwm_k1=True,
    )

    hypotheses = stability.get("hypothesis_summary", {})

    def stable(name: str) -> bool:
        row = hypotheses.get(name, {})
        return (
            row.get("seed_count")
            == (contract.get("thresholds") or {}).get("required_seed_count")
            and isinstance(row.get("pass_count"), int)
            and row["pass_count"] >= threshold
            and row.get("meets_required_pass_rate") is True
        )

    research_release = completion.get("research_claim_release", {})
    action_disposition = action_v0_2.get("disposition", {})
    action_boundary = action_v0_2.get("claim_boundary", {})
    scientific_support = _dimension(
        {
            "evidence_integrity": evidence_integrity,
            "positive_preregistered_kernel_release": research_release.get("status")
            == "complete_supported",
            "high_standard_kernel_supported": research_release.get(
                "high_standard_kernel_supported"
            )
            is True,
            "kernel_beats_reference_stably": stable(
                "full_kernel_passes_existing_core_reference_gate"
            ),
            "action_channel_contributes_stably": stable(
                "full_kernel_beats_no_action_mean_core_nmae"
            ),
            "topology_rewrite_contributes_stably": stable(
                "full_kernel_beats_no_topology_rewrite_mean_core_nmae"
            ),
            "action_transport_independently_confirmed": action_boundary.get(
                "independent_hidden_confirmation"
            )
            is True,
        },
        required_for_uwm_k1=True,
    )

    forcing_gate_statuses = forcing.get("gate_statuses", {})
    domain_support = _dimension(
        {
            "evidence_integrity": evidence_integrity,
            "forcing_inputs_admitted": forcing.get("model_input_admitted") is True,
            "forcing_gates_all_pass": bool(forcing_gate_statuses)
            and all(value == "pass" for value in forcing_gate_statuses.values()),
            "action_transport_stable_across_all_systems_and_horizons": (
                action_disposition.get("stable_across_all_systems_and_horizons")
                is True
            ),
            "multiple_domains_have_positive_kernel_support": research_release.get(
                "supported_hypothesis_count"
            )
            not in (None, 0),
            "independent_hidden_or_prospective_confirmation": action_boundary.get(
                "independent_hidden_confirmation"
            )
            is True,
        },
        required_for_uwm_k1=True,
    )

    public_release = _dimension(
        {
            "evidence_integrity": evidence_integrity,
            "public_release_ready": readiness.get("public_release_ready") is True,
            "public_multi_domain_suite_ready": benchmark.get(
                "claim_boundary", {}
            ).get("public_multi_domain_suite_ready")
            is True,
            "license_latency_and_external_hidden_labels_cleared": not benchmark.get(
                "public_blockers"
            ),
        },
        required_for_uwm_k1=False,
    )

    dimensions = {
        "engineering_implementation": engineering,
        "development_benchmark_validity": development_benchmark,
        "kernel_scientific_support": scientific_support,
        "domain_and_generalization_support": domain_support,
        "public_and_operational_release": public_release,
    }
    required = contract.get("uwm_k1_required_dimensions") or []
    k0_pass = evidence_integrity and all(
        dimensions[name]["status"] == "pass" for name in required
    )

    forcing_nonpass = [
        name for name, status in forcing_gate_statuses.items() if status != "pass"
    ]
    return {
        "schema": GWM_K0_READINESS_REPORT_SCHEMA,
        "contract_id": contract.get("contract_id"),
        "candidate_id": contract.get("candidate_id"),
        "assessment_scope": contract.get("assessment_scope"),
        "contract_validation": contract_validation,
        "evidence_integrity": {
            "status": "pass" if evidence_integrity else "fail",
            "artifact_failures": artifact_failures,
        },
        "dimensions": dimensions,
        "decision": {
            "k0_scientific_readiness_pass": k0_pass,
            "uwm_k1_admitted": k0_pass,
            "public_release_ready": public_release["status"] == "pass",
            "general_gwm_claim_permitted": False,
            "causal_policy_claim_permitted": False,
            "paper_experimenter_admitted": False,
            "status": "pass_for_uwm_k1" if k0_pass else "fail_closed",
        },
        "observed_negative_evidence": {
            "dam_gk_v0_1_research_status": research_release.get("status"),
            "dam_gk_v0_1_supported_hypothesis_count": research_release.get(
                "supported_hypothesis_count"
            ),
            "dam_gk_v0_2_reference_gate_pass_count": hypotheses.get(
                "full_kernel_passes_existing_core_reference_gate", {}
            ).get("pass_count"),
            "dam_gk_v0_2_reference_gate_seed_count": hypotheses.get(
                "full_kernel_passes_existing_core_reference_gate", {}
            ).get("seed_count"),
            "action_transport_v0_2_independent_hidden_confirmation": (
                action_boundary.get("independent_hidden_confirmation")
            ),
            "action_transport_v0_2_stable_across_all_systems": (
                action_disposition.get("stable_across_all_systems_and_horizons")
            ),
            "forcing_admission_status": forcing.get("certificate_status"),
        },
        "first_legitimately_closable_gap": {
            "id": "K0-DATA-FORCING-ADMISSION",
            "status": "blocked",
            "why_first": (
                "A forcing-aware kernel evaluation cannot be preregistered or run "
                "until its natural-forcing inputs pass non-compensatory admission."
            ),
            "current_certificate": (
                contract.get("evidence_artifacts", {})
                .get("gwm_bench_v0_3_forcing_admission", {})
                .get("path")
            ),
            "nonpass_gates": forcing_nonpass,
            "after_closure": [
                "freeze a new versioned forcing-aware kernel protocol before labels are inspected",
                "evaluate persistence and strong non-spatial baselines on a genuinely unused system or time window",
                "run action, forcing, graph, topology and temporal negative controls",
                "obtain positive support in more than one domain before certifying shared-kernel generalization",
            ],
        },
        "claim_ceiling": {
            "current": (
                "engineering-complete shared-kernel research implementation with a "
                "valid internal development benchmark and bounded component-level "
                "action-transport evidence"
            ),
            "forbidden": [
                "GWM Geospatial Kernel scientifically ready",
                "general or foundation GWM validated",
                "UWM shared-kernel experiment ready",
                "causal urban policy effects identified",
                "public or operational benchmark ready",
            ],
        },
        "immutability": {
            "dam_gk_v0_1_negative_result_must_be_preserved": True,
            "gwm_bench_v0_2_frozen_results_must_be_preserved": True,
            "future_support_requires_new_versioned_protocol": True,
        },
        "source_artifacts": contract.get("evidence_artifacts"),
    }


def is_valid_k0_readiness_certificate(payload: dict[str, Any]) -> bool:
    """Return whether a K0 report semantically admits K1.

    Public release is deliberately not required: it is a separate release dimension,
    while every scientific dimension declared as required must pass.
    """

    if payload.get("schema") != GWM_K0_READINESS_REPORT_SCHEMA:
        return False
    if payload.get("evidence_integrity", {}).get("status") != "pass":
        return False
    source_artifacts = payload.get("source_artifacts")
    if not isinstance(source_artifacts, dict) or not source_artifacts:
        return False
    for record in source_artifacts.values():
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("path"), str)
            or not record["path"]
            or not isinstance(record.get("sha256"), str)
            or len(record["sha256"]) != 64
        ):
            return False
    dimensions = payload.get("dimensions")
    if not isinstance(dimensions, dict) or not dimensions:
        return False
    required_names = {
        name
        for name, row in dimensions.items()
        if isinstance(row, dict) and row.get("required_for_uwm_k1") is True
    }
    if required_names != K0_UWM_K1_REQUIRED_DIMENSIONS:
        return False
    if any(dimensions[name].get("status") != "pass" for name in required_names):
        return False
    decision = payload.get("decision", {})
    return (
        decision.get("k0_scientific_readiness_pass") is True
        and decision.get("uwm_k1_admitted") is True
        and decision.get("paper_experimenter_admitted") is False
        and decision.get("status") == "pass_for_uwm_k1"
    )


def validate_k0_certificate_file(*, root: Path, path: Path) -> bool:
    """Validate K0 semantics and every source artifact hash from disk."""

    root = root.resolve()
    path = path.resolve()
    try:
        path.relative_to(root)
        payload = load_json(path)
    except (ValueError, OSError, json.JSONDecodeError):
        return False
    if not is_valid_k0_readiness_certificate(payload):
        return False
    for record in payload["source_artifacts"].values():
        artifact = (root / record["path"]).resolve()
        try:
            artifact.relative_to(root)
        except ValueError:
            return False
        if not artifact.is_file() or sha256_file(artifact) != record["sha256"]:
            return False
    return True
