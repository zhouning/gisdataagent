#!/usr/bin/env python3
"""Validate the V6 definition and report activation readiness without data download."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
PROTOCOL_PATH = DRAFT_ROOT / "suite_protocol.json"
ADMISSION_PATH = DRAFT_ROOT / "candidate_admission_contract.json"
REGISTRY_PATH = DRAFT_ROOT / "candidate_registry.json"
OUTPUT_PATH = DRAFT_ROOT / "definition_validation_report.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    protocol = load_json(PROTOCOL_PATH)
    admission = load_json(ADMISSION_PATH)
    registry = load_json(REGISTRY_PATH)

    checks: dict[str, bool] = {}
    checks["protocol_schema"] = (
        protocol.get("schema") == "gwm_bench.foundation_v6_suite_protocol.v1"
    )
    checks["admission_schema"] = (
        admission.get("schema")
        == "gwm_bench.foundation_v6_candidate_admission_contract.v1"
    )
    checks["registry_schema"] = (
        registry.get("schema") == "gwm_bench.foundation_v6_candidate_registry.v1"
    )
    suite_ids = {protocol.get("suite_id"), admission.get("suite_id"), registry.get("suite_id")}
    checks["suite_ids_match"] = len(suite_ids) == 1
    checks["protocol_not_activated"] = (
        protocol.get("status") == "DEFINED_CANDIDATE_ADMISSION_OPEN_NOT_ACTIVATED"
    )
    checks["admission_frozen_before_outcomes"] = (
        admission.get("status") == "FROZEN_BEFORE_CANDIDATE_OUTCOME_ACQUISITION"
    )

    action = protocol["canonical_action_contract"]
    checks["six_action_dimensions"] = (
        action["dimension_count"] == 6
        and len(action["columns"]) == 6
        and len(set(action["columns"])) == 6
    )
    activation = protocol["activation_gate"]
    checks["six_development_events_required"] = (
        activation["minimum_total_development_events"] == 6
        and activation["minimum_additional_development_events_beyond_v5"] == 2
    )
    checks["two_hidden_events_required"] = activation["minimum_hidden_test_events"] == 2
    checks["eight_total_events_required"] = activation["minimum_total_events"] == 8
    checks["fixed_52_12_windows"] = (
        activation["pre_action_weeks"] == 52
        and activation["post_action_weeks"] == 12
    )
    checks["single_frozen_hidden_model"] = (
        activation["single_model_package_across_hidden_events"] is True
        and activation["model_update_after_first_hidden_target_reveal_permitted"] is False
    )
    checks["hidden_input_publication_rule_defined"] = (
        protocol["hidden_newness_contract"].get(
            "policy_documents_and_pre_action_inputs_may_be_public"
        )
        is True
    )
    checks["completion_independent_of_model_win"] = (
        protocol["completion_definition"]["model_win_required"] is False
    )
    checks["runtime_r5_requires_shared_kernel"] = (
        protocol["runtime_r5"]["benchmark_specific_duplicate_runtime_permitted"] is False
    )
    checks["eight_frozen_result_conditions"] = (
        len(protocol["evaluation"]["action_transfer_gate"]["conditions"]) == 8
    )

    for name, artifact in protocol["v5_foundation"].items():
        if not isinstance(artifact, dict) or "path" not in artifact:
            continue
        path = REPO_ROOT / artifact["path"]
        checks[f"v5_artifact_exists::{name}"] = path.is_file()
        checks[f"v5_artifact_hash::{name}"] = (
            path.is_file() and sha256_file(path) == artifact["sha256"]
        )

    evidence_ok = True
    for artifact in registry["evidence_dependencies"]:
        path = REPO_ROOT / artifact["path"]
        evidence_ok = evidence_ok and path.is_file() and sha256_file(path) == artifact["sha256"]
    checks["registry_evidence_dependencies_bound"] = evidence_ok

    required_fields = set(admission["required_candidate_fields"])
    required_admission_checks = set(admission["admission_checks"])
    allowed_roles = set(admission["allowed_roles"])
    allowed_statuses = set(admission["allowed_statuses"])
    candidates = registry["candidates"]
    candidates_by_id = {
        candidate.get("candidate_id"): candidate for candidate in candidates
    }
    candidate_ids = [candidate.get("candidate_id") for candidate in candidates]
    checks["candidate_ids_unique"] = len(candidate_ids) == len(set(candidate_ids))
    checks["candidate_fields_complete"] = all(
        required_fields.issubset(candidate) for candidate in candidates
    )
    checks["candidate_roles_valid"] = all(
        candidate.get("requested_role") in allowed_roles for candidate in candidates
    )
    checks["candidate_statuses_valid"] = all(
        candidate.get("status") in allowed_statuses for candidate in candidates
    )
    checks["candidate_check_keys_complete"] = all(
        required_admission_checks == set(candidate.get("admission_checks", {}))
        for candidate in candidates
    )

    action_evidence_ok = True
    for candidate in candidates:
        for artifact in candidate.get("official_action_evidence", []):
            path = REPO_ROOT / artifact["path"]
            action_evidence_ok = (
                action_evidence_ok
                and path.is_file()
                and sha256_file(path) == artifact["sha256"]
            )
    checks["candidate_official_action_evidence_bound"] = action_evidence_ok

    screening_dependencies = []
    for artifact in registry["evidence_dependencies"]:
        path = REPO_ROOT / artifact["path"]
        if path.is_file():
            payload = load_json(path)
            if payload.get("schema") == "gwm_bench.foundation_v6_prospective_candidate_screening.v1":
                screening_dependencies.append(payload)
    checks["prospective_screening_report_bound"] = len(screening_dependencies) == 1
    screening = screening_dependencies[0] if screening_dependencies else {}
    screening_assets = screening.get("asset_audit", {}).get("assets", [])
    checks["prospective_screening_asset_integrity"] = bool(screening_assets) and all(
        (REPO_ROOT / artifact["path"]).is_file()
        and sha256_file(REPO_ROOT / artifact["path"]) == artifact["sha256"]
        and (REPO_ROOT / artifact["path"]).stat().st_size == artifact["bytes"]
        for artifact in screening_assets
    )
    access_boundary = screening.get("access_boundary", {})
    checks["prospective_outcome_boundary_preserved"] = (
        access_boundary.get("outcome_rows_downloaded") is False
        and access_boundary.get("post_action_target_rows_opened") is False
    )
    prospective_findings = screening.get("candidate_findings", {})
    checks["prospective_candidates_registered_not_admitted"] = bool(
        prospective_findings
    ) and all(
        candidate_id in candidates_by_id
        and finding.get("decision") == "screened_not_admitted"
        and candidates_by_id[candidate_id].get("status") == "screened_not_admitted"
        for candidate_id, finding in prospective_findings.items()
    )
    screening_decision = screening.get("decision", {})
    checks["prospective_screening_decision_preserves_gate"] = (
        screening.get("asset_audit", {}).get("integrity_pass") is True
        and screening_decision.get("candidates_added") == len(prospective_findings)
        and screening_decision.get("candidates_admitted") == 0
        and screening_decision.get("outcome_download_authorized") is False
    )
    protocol_freeze_date = datetime.fromisoformat(protocol["created_at"]).date()
    checks["prospective_effective_dates_after_protocol_freeze"] = bool(
        prospective_findings
    ) and all(
        datetime.fromisoformat(finding["effective_date"]).date() > protocol_freeze_date
        and candidates_by_id[candidate_id].get("effective_date")
        == finding["effective_date"]
        for candidate_id, finding in prospective_findings.items()
        if candidate_id in candidates_by_id
    ) and set(prospective_findings).issubset(candidates_by_id)

    v5_event_ids = set(protocol["v5_foundation"]["event_ids"])
    checks["no_candidate_reuses_v5_event_id"] = not (set(candidate_ids) & v5_event_ids)
    admitted = [candidate for candidate in candidates if candidate["status"].startswith("admitted_")]
    checks["admitted_candidates_have_all_checks_true"] = all(
        all(candidate["admission_checks"].values()) for candidate in admitted
    )
    hidden_requested = [
        candidate for candidate in candidates if candidate["requested_role"] == "hidden_test"
    ]
    checks["screened_hidden_outcomes_remain_unopened"] = all(
        candidate["outcome_access"].get("post_action_trip_rows_opened") is False
        for candidate in hidden_requested
    )

    admitted_development = [
        candidate for candidate in admitted if candidate["status"] == "admitted_development"
    ]
    admitted_hidden = [
        candidate for candidate in admitted if candidate["status"] == "admitted_hidden_test"
    ]
    admitted_development_ids = {
        candidate["candidate_id"] for candidate in admitted_development
    }
    admitted_hidden_ids = {candidate["candidate_id"] for candidate in admitted_hidden}
    checks["registry_admitted_ids_match_evidence"] = (
        set(registry["admitted_development_event_ids"]) == admitted_development_ids
        and set(registry["admitted_hidden_test_event_ids"]) == admitted_hidden_ids
    )
    base_count = protocol["v5_foundation"]["development_event_count"]
    total_development = base_count + len(admitted_development)
    heterogeneous_hidden = sum(
        bool(candidate.get("spatially_heterogeneous_action")) for candidate in admitted_hidden
    )
    total_events = total_development + len(admitted_hidden)
    activation_checks = {
        "minimum_total_development_events": (
            total_development >= activation["minimum_total_development_events"]
        ),
        "minimum_additional_development_events": (
            len(admitted_development)
            >= activation["minimum_additional_development_events_beyond_v5"]
        ),
        "minimum_hidden_test_events": (
            len(admitted_hidden) >= activation["minimum_hidden_test_events"]
        ),
        "minimum_total_events": total_events >= activation["minimum_total_events"],
        "heterogeneous_hidden_action_present": (
            heterogeneous_hidden
            >= activation["minimum_hidden_events_with_heterogeneous_spatial_exposure"]
        ),
    }

    registry_state = registry["activation_state"]
    checks["registry_counts_match_evidence"] = (
        registry_state["v5_foundation_development_events"] == base_count
        and registry_state["additional_development_events"] == len(admitted_development)
        and registry_state["total_development_events"] == total_development
        and registry_state["hidden_test_events"] == len(admitted_hidden)
        and registry_state["hidden_events_with_heterogeneous_spatial_exposure"]
        == heterogeneous_hidden
    )

    computed_activation_ready = all(activation_checks.values())
    checks["registry_ready_flag_matches_evidence"] = (
        registry_state["ready"] is computed_activation_ready
    )

    definition_valid = all(checks.values())
    activation_ready = definition_valid and all(activation_checks.values())
    if not definition_valid:
        status = "FAIL_V6_DEFINITION_VALIDATION"
    elif activation_ready:
        status = "PASS_V6_ACTIVATION_GATE_READY_FOR_RUNTIME_R5_FREEZE"
    else:
        status = "PASS_V6_DEFINITION_VALIDATED_NOT_ACTIVATED"

    report = {
        "schema": "gwm_bench.foundation_v6_definition_validation.v1",
        "suite_id": protocol["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "definition_valid": definition_valid,
        "activation_ready": activation_ready,
        "check_count": len(checks),
        "passed_check_count": sum(checks.values()),
        "failed_checks": [name for name, value in checks.items() if not value],
        "checks": checks,
        "activation_checks": activation_checks,
        "candidate_counts": {
            "screened": len(candidates),
            "admitted_development": len(admitted_development),
            "admitted_hidden_test": len(admitted_hidden),
            "total_development_including_v5": total_development,
            "total_events": total_events,
        },
        "candidate_blockers": {
            candidate["candidate_id"]: candidate["blockers"]
            for candidate in candidates
            if candidate["status"] == "screened_not_admitted"
        },
        "artifacts": {
            "protocol": {
                "path": str(PROTOCOL_PATH.relative_to(REPO_ROOT)),
                "sha256": sha256_file(PROTOCOL_PATH),
            },
            "admission_contract": {
                "path": str(ADMISSION_PATH.relative_to(REPO_ROOT)),
                "sha256": sha256_file(ADMISSION_PATH),
            },
            "candidate_registry": {
                "path": str(REGISTRY_PATH.relative_to(REPO_ROOT)),
                "sha256": sha256_file(REGISTRY_PATH),
            },
            "prospective_candidate_screening": {
                "path": str(
                    (DRAFT_ROOT / "prospective_candidate_screening_2026-07-24.json")
                    .relative_to(REPO_ROOT)
                ),
                "sha256": sha256_file(
                    DRAFT_ROOT / "prospective_candidate_screening_2026-07-24.json"
                ),
            },
        },
        "next_permitted_action": (
            "Freeze Runtime-R5 and the hidden evaluator before any hidden outcome access."
            if activation_ready
            else "Close candidate admission evidence only; V6 data build and model execution remain prohibited."
        ),
    }
    OUTPUT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"GWM-Bench Foundation V6.0 definition: {status}")
    print(f"Definition checks: {report['passed_check_count']}/{report['check_count']}")
    print(f"Activation ready: {activation_ready}")
    print(f"Report: {OUTPUT_PATH}")
    return 0 if definition_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
