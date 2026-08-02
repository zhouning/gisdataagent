"""Fail-closed completion assessment for the DAM-GK research track."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .experiment_contract import (
    build_dam_gk_experiment_contract,
    validate_dam_gk_experiment_contract,
)


DAM_GK_COMPLETION_SCHEMA = "gwm.dam_gk.completion_contract.v1"
DAM_GK_COMPLETION_REPORT_SCHEMA = "gwm.dam_gk.completion_report.v1"

TERMINAL_HYPOTHESIS_DISPOSITIONS = {
    "supported",
    "rejected",
    "out_of_scope_for_this_release",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_completion_contract(contract: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if contract.get("schema") != DAM_GK_COMPLETION_SCHEMA:
        errors.append("schema_mismatch")
    if contract.get("release_id") != "dam-gk-v0.1-research-baseline":
        errors.append("release_id_mismatch")
    if not contract.get("frozen_artifacts"):
        errors.append("frozen_artifacts_required")
    if not contract.get("required_kernel_capabilities"):
        errors.append("required_kernel_capabilities_required")
    if set(contract.get("hypothesis_adjudications") or {}) != {
        f"H{index}" for index in range(1, 7)
    }:
        errors.append("all_hypothesis_adjudications_required")
    if contract.get("completion_policy", {}).get(
        "internet_exhaustion_is_completion_criterion"
    ) is not False:
        errors.append("internet_exhaustion_must_not_be_completion_criterion")
    return {"valid": not errors, "errors": errors}


def assess_dam_gk_completion(
    *, root: Path, contract: dict[str, Any]
) -> dict[str, Any]:
    """Assess engineering freeze and research-claim closure independently."""

    root = root.resolve()
    contract_validation = validate_completion_contract(contract)
    artifact_failures = _verify_artifacts(root, contract, "frozen_artifacts")
    research_artifact_failures = _verify_artifacts(
        root, contract, "research_frozen_artifacts"
    )
    experiment_contract = build_dam_gk_experiment_contract()
    experiment_validation = validate_dam_gk_experiment_contract(
        experiment_contract
    )

    capabilities = set(contract.get("implemented_kernel_capabilities") or [])
    required_capabilities = set(contract.get("required_kernel_capabilities") or [])
    required_baselines = set(experiment_contract["required_baselines"])
    frozen_baselines = set(contract.get("frozen_experiment_surface", {}).get(
        "required_baselines", []
    ))
    required_controls = set(experiment_contract["required_negative_controls"])
    frozen_controls = set(contract.get("frozen_experiment_surface", {}).get(
        "required_negative_controls", []
    ))

    evidence = _load_evidence(root, contract)
    shanghai = _assess_shanghai_track(evidence)
    hydro = _assess_hydro_track(evidence)
    adjudications = _assess_hypotheses(contract, evidence)
    adjudication_report = evidence.get("hypothesis_adjudication") or {}
    adjudication_complete = (
        adjudication_report.get("status") == "terminally_adjudicated"
        and adjudication_report.get("summary", {}).get(
            "pending_or_blocked_count"
        )
        == 0
    )
    supported_hypothesis_count = sum(
        row["disposition"] == "supported" for row in adjudications.values()
    )

    engineering_checks = {
        "completion_contract_valid": contract_validation["valid"],
        "frozen_artifacts_verified": not artifact_failures,
        "experiment_contract_valid": experiment_validation["valid"],
        "required_kernel_capabilities_implemented": (
            required_capabilities <= capabilities
        ),
        "mandatory_baseline_surface_frozen": required_baselines <= frozen_baselines,
        "negative_control_surface_frozen": required_controls <= frozen_controls,
        "unsupported_action_training_fails_closed": (
            shanghai["action_conditioned_training_admitted"] is False
        ),
        "engineering_and_research_release_separated": contract.get(
            "completion_policy", {}
        ).get("engineering_release_requires_all_hypotheses_supported")
        is False,
    }
    engineering_blockers = [
        name for name, passed in engineering_checks.items() if not passed
    ]
    engineering_status = (
        "complete" if not engineering_blockers else "incomplete"
    )

    research_checks = {
        "real_executed_action_track_available": hydro[
            "retrospective_action_track_ready"
        ],
        "dam_gk_hydro_adapter_frozen": bool(
            contract.get("research_execution", {}).get(
                "dam_gk_hydro_adapter_frozen"
            )
        ),
        "hypothesis_decisive_baselines_executed": bool(
            contract.get("research_execution", {}).get(
                "hypothesis_decisive_baselines_executed"
            )
        ),
        "mandatory_negative_controls_executed_across_claim_tracks": bool(
            contract.get("research_execution", {}).get(
                "mandatory_negative_controls_executed_across_claim_tracks"
            )
        ),
        "terminal_adjudication_report_valid": adjudication_complete,
        "research_artifacts_verified": not research_artifact_failures,
        "all_hypotheses_terminally_adjudicated": all(
            row["terminal"] for row in adjudications.values()
        ),
    }
    research_blockers = [
        name for name, passed in research_checks.items() if not passed
    ]
    if research_blockers:
        research_status = "incomplete"
    elif supported_hypothesis_count == len(adjudications):
        research_status = "complete_supported"
    else:
        research_status = "complete_negative"

    return {
        "schema": DAM_GK_COMPLETION_REPORT_SCHEMA,
        "release_id": contract.get("release_id"),
        "overall_status": (
            "complete_supported"
            if engineering_status == "complete"
            and research_status == "complete_supported"
            else "complete_with_negative_research_outcome"
            if engineering_status == "complete"
            and research_status == "complete_negative"
            else "engineering_complete_research_open"
            if engineering_status == "complete"
            else "incomplete"
        ),
        "engineering_baseline": {
            "status": engineering_status,
            "checks": engineering_checks,
            "blockers": engineering_blockers,
            "artifact_failures": artifact_failures,
            "contract_errors": contract_validation["errors"],
        },
        "research_claim_release": {
            "status": research_status,
            "checks": research_checks,
            "blockers": research_blockers,
            "supported_hypothesis_count": supported_hypothesis_count,
            "high_standard_kernel_supported": (
                supported_hypothesis_count == len(adjudications)
            ),
            "hypotheses": adjudications,
            "artifact_failures": research_artifact_failures,
        },
        "data_tracks": {
            "shanghai_parcel": shanghai,
            "hydrocontrol_hourly_v3": hydro,
        },
        "next_executable_milestone": contract.get(
            "next_executable_milestone"
        ),
        "claim_boundary": {
            "engineering_baseline_complete": engineering_status == "complete",
            "research_adjudication_complete": research_status.startswith(
                "complete_"
            ),
            "research_claim_release_supported": (
                research_status == "complete_supported"
            ),
            "public_or_operational_hydro_benchmark_required_for_internal_research": False,
            "identified_policy_causal_effect": False,
            "general_purpose_foundation_gwm": False,
        },
    }


def _verify_artifacts(
    root: Path, contract: dict[str, Any], field: str
) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for artifact in contract.get(field) or []:
        relative_path = artifact["path"]
        path = root / relative_path
        if not path.is_file():
            failures.append({"path": relative_path, "reason": "missing"})
            continue
        actual = sha256_file(path)
        if actual != artifact["sha256"]:
            failures.append(
                {
                    "path": relative_path,
                    "reason": "sha256_mismatch",
                    "expected": artifact["sha256"],
                    "actual": actual,
                }
            )
    return failures


def _load_evidence(
    root: Path, contract: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    return {
        name: load_json(root / path)
        for name, path in contract.get("evidence_artifacts", {}).items()
    }


def _assess_shanghai_track(
    evidence: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    panel = evidence["shanghai_parcel_action_panel"]
    protocol = evidence["shanghai_event_grid_protocol"]
    controls = evidence["shanghai_control_design"]
    inventory = evidence["shanghai_official_inventory"]
    return {
        "role": "spatial_evidence_protocol_validation",
        "formal_geometry_event_count": panel["summary"][
            "spatial_crosswalk_ready_count"
        ],
        "strict_temporal_window_event_count": panel["summary"][
            "strict_temporal_window_ready_count"
        ],
        "event_focused_primary_node_count": protocol["summary"][
            "event_focused_primary_node_count"
        ],
        "spatial_sampling_protocol_ready": protocol["summary"][
            "spatial_sampling_protocol_ready"
        ],
        "actual_construction_timing_observed": protocol["claim_boundary"][
            "actual_construction_timing_observed"
        ],
        "complete_event_inventory": bool(
            inventory["claim_boundary"]["complete_land_supply_inventory"]
            and inventory["claim_boundary"][
                "complete_construction_event_inventory"
            ]
        ),
        "confirmed_untreated_controls": controls["claim_boundary"][
            "confirmed_untreated_controls"
        ],
        "action_conditioned_training_admitted": controls["claim_boundary"][
            "training_admission"
        ],
        "disposition": "freeze_as_protocol_validation_track",
    }


def _assess_hydro_track(
    evidence: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    readiness = evidence["hydrocontrol_readiness"]
    candidate = evidence["hydrocontrol_candidate_contract"]
    release = evidence["hydrocontrol_release_readiness"]
    activation = candidate["activation_gates"]
    retrospective_ready = bool(
        readiness["hourly_data_gate_passed"]
        and readiness["strict_direct_system_count_at_least_three"]
        and activation["target_strictly_future_of_inputs"]
        and candidate["claim_boundary"][
            "retrospective_hourly_training_and_development_dataset_ready"
        ]
    )
    return {
        "role": "real_executed_action_internal_research_track",
        "retrospective_action_track_ready": retrospective_ready,
        "strict_direct_system_count": readiness["strict_direct_system_count"],
        "target_strictly_future_of_inputs": activation[
            "target_strictly_future_of_inputs"
        ],
        "action_value_demonstrated_at_3_to_24_hours": candidate[
            "claim_boundary"
        ]["action_value_demonstrated_at_3_to_24_hours"],
        "action_value_demonstrated_at_1_hour": candidate["claim_boundary"][
            "action_value_demonstrated_at_1_hour"
        ],
        "public_or_operational_release_ready": release["status"]
        == "release_ready",
        "public_release_blockers": release["blockers"],
        "dam_gk_experiment_executed": (
            evidence.get("hydrocontrol_h1_h5", {}).get("schema")
            == "gwm.dam_gk.hydrocontrol_h1_h5_benchmark.v1"
        ),
        "disposition": "admit_for_internal_h1_h5_kernel_experiments",
    }


def _assess_hypotheses(
    contract: dict[str, Any], evidence: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    source = contract.get("hypothesis_adjudications", {})
    adjudication = evidence.get("hypothesis_adjudication") or {}
    if adjudication.get("status") == "terminally_adjudicated":
        source = adjudication.get("hypotheses") or source
    rows: dict[str, dict[str, Any]] = {}
    for hypothesis_id, row in source.items():
        disposition = row.get("disposition")
        terminal = disposition in TERMINAL_HYPOTHESIS_DISPOSITIONS
        rows[hypothesis_id] = {
            **row,
            "terminal": terminal,
            "release_blocker": not terminal,
        }
    return rows
