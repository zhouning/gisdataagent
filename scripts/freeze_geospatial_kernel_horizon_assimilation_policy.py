#!/usr/bin/env python3
"""Freeze a calibration-only horizon assimilation policy for a future window."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.horizon_assimilation_policy import (
    HORIZON_ASSIMILATION_CANDIDATE_ID,
    HORIZON_ASSIMILATION_MODES,
    HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS,
    HorizonAssimilationPolicy,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PARENT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_distance_localized_assimilation_posthoc_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_policy_freeze.json"
)
ROLLOUT_CORE_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/horizon_assimilation_rollout.py"
)
PARENT_SCHEMA = "gwm.geotransport.distance_localized_assimilation_posthoc.v1"
SCHEMA = "gwm.geotransport.horizon_assimilation_policy_freeze.v1"
SELECTION_SCOPE = "joint_two_system_calibration_split_per_horizon_only"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-report", type=Path, default=DEFAULT_PARENT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_horizon_assimilation_policy_freeze(
    *,
    parent_report_path: Path = DEFAULT_PARENT_REPORT,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    parent_body, parent = _load_json(parent_report_path)
    _validate_parent(parent)
    _verify_parent_artifacts(parent)

    scores = _calibration_scores(parent)
    selected_modes = tuple(
        min(
            HORIZON_ASSIMILATION_MODES,
            key=lambda mode: (
                scores[str(horizon)][mode],
                HORIZON_ASSIMILATION_MODES.index(mode),
            ),
        )
        for horizon in HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS
    )
    policy = HorizonAssimilationPolicy(
        candidate_id=HORIZON_ASSIMILATION_CANDIDATE_ID,
        supported_forecast_horizons_hours=(
            HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS
        ),
        selected_modes=selected_modes,
        selection_scope=SELECTION_SCOPE,
    )
    policy_payload = policy.as_dict()
    policy_body = _canonical_json(policy_payload)
    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("horizon_assimilation_policy_freeze_generated_at_must_be_aware")

    calibration_indices = parent["design"]["calibration_issue_indices"]
    validation_indices = parent["design"]["validation_issue_indices"]
    return {
        "schema": SCHEMA,
        "status": "horizon_assimilation_candidate_frozen_awaiting_unused_window",
        "frozen_at": now.astimezone(UTC).isoformat(),
        "scientific_role": (
            "freeze a calibration-derived horizon router after the current validation "
            "outcomes were exposed; this is candidate identity, not validation"
        ),
        "parent_evidence": {
            "distance_localized_assimilation_report": _input_artifact(
                parent_report_path,
                parent_body,
            ),
            "parent_selected_single_mode": parent[
                "selected_mode_from_joint_calibration"
            ],
            "parent_candidate_promoted": parent["aggregate_gates"][
                "candidate_promotion_gate_passed"
            ],
        },
        "implementation_artifacts": {
            "policy_contract": _artifact(
                REPO_ROOT
                / "data_agent/uwm/geospatial_kernel_v2/"
                "horizon_assimilation_policy.py",
            ),
            "outcome_free_rollout_core": _artifact(ROLLOUT_CORE_PATH),
            "freezer": _artifact(Path(__file__)),
        },
        "selection": {
            "scope": SELECTION_SCOPE,
            "objective": (
                "minimum equal-system mean prediction MSE independently at each "
                "registered horizon"
            ),
            "tie_break_order": list(HORIZON_ASSIMILATION_MODES),
            "systems": list(parent["design"]["systems"]),
            "calibration_issue_indices": list(calibration_indices),
            "calibration_issue_count": len(calibration_indices),
            "validation_issue_indices_used_for_selection": [],
            "calibration_equal_system_mse_m6s2_by_horizon": scores,
        },
        "policy": policy_payload,
        "policy_sha256": hashlib.sha256(policy_body).hexdigest(),
        "future_evaluation_contract": {
            "required_window": "genuinely_unused_after_frozen_at",
            "required_systems": list(parent["design"]["systems"]),
            "required_horizons_hours": list(
                HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS
            ),
            "current_parent_validation_issue_indices": list(validation_indices),
            "current_parent_validation_split_eligible_for_scoring": False,
            "policy_change_after_future_outcome_access_permitted": False,
            "same_policy_sha256_required": True,
            "all_system_all_horizon_gate_required": True,
        },
        "information_boundary": {
            "calibration_targets_used_for_selection": True,
            "validation_targets_used_for_selection": False,
            "parent_report_contains_exposed_validation_results": True,
            "validation_results_were_exposed_before_candidate_design": True,
            "fresh_prospective_window_consumed": False,
        },
        "claim_boundary": {
            "candidate_identity_frozen": True,
            "current_validation_can_validate_candidate": False,
            "geospatial_kernel_validated": False,
            "prospective_v5_changed": False,
            "candidate_promoted": False,
            "runtime_default_enabled": False,
        },
    }


def _calibration_scores(parent: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    systems = parent["design"]["systems"]
    if not isinstance(systems, list) or not systems:
        raise ValueError("horizon_assimilation_policy_parent_systems_invalid")
    result: dict[str, dict[str, float]] = {}
    for horizon in HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS:
        horizon_scores: dict[str, float] = {}
        for mode in HORIZON_ASSIMILATION_MODES:
            values: list[float] = []
            for system_id in systems:
                try:
                    raw = parent["systems"][system_id]["calibration_metrics"]["modes"][
                        mode
                    ]["metrics_by_horizon"][str(horizon)]["prediction"]["mse_m6s2"]
                    value = float(raw)
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(
                        "horizon_assimilation_policy_calibration_metric_missing"
                    ) from exc
                if not math.isfinite(value) or value < 0.0:
                    raise ValueError(
                        "horizon_assimilation_policy_calibration_metric_invalid"
                    )
                values.append(value)
            horizon_scores[mode] = sum(values) / len(values)
        result[str(horizon)] = horizon_scores
    return result


def _validate_parent(parent: Mapping[str, Any]) -> None:
    design = parent.get("design") or {}
    gates = parent.get("aggregate_gates") or {}
    claims = parent.get("claim_boundary") or {}
    if (
        parent.get("schema") != PARENT_SCHEMA
        or parent.get("status")
        != "historical_distance_localized_assimilation_complete_not_promoted"
        or tuple(design.get("horizons_hours") or ())
        != HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS
        or tuple(design.get("modes") or ()) != HORIZON_ASSIMILATION_MODES
        or len(design.get("calibration_issue_indices") or ()) == 0
        or len(design.get("validation_issue_indices") or ()) == 0
        or gates.get("candidate_promotion_gate_passed") is not False
        or gates.get("fresh_prospective_validation_passed") is not False
        or claims.get("prospective_v5_changed") is not False
        or claims.get("runtime_default_enabled") is not False
    ):
        raise ValueError("horizon_assimilation_policy_parent_invalid")


def _verify_parent_artifacts(parent: Mapping[str, Any]) -> None:
    descriptors: list[Mapping[str, Any]] = []
    for section_name in ("implementation_artifacts", "outputs"):
        section = parent.get(section_name)
        if not isinstance(section, Mapping):
            raise ValueError("horizon_assimilation_policy_parent_artifacts_missing")
        descriptors.extend(
            value for value in section.values() if isinstance(value, Mapping)
        )
    if not descriptors:
        raise ValueError("horizon_assimilation_policy_parent_artifacts_missing")
    for descriptor in descriptors:
        _read_verified(descriptor)


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("horizon_assimilation_policy_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("horizon_assimilation_policy_artifact_identity_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("horizon_assimilation_policy_json_document_required")
    return body, payload


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _artifact(path: Path, body: bytes | None = None) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("horizon_assimilation_policy_artifact_outside_repository") from exc
    fixed_body = resolved.read_bytes() if body is None else body
    return {
        "path": display,
        "sha256": hashlib.sha256(fixed_body).hexdigest(),
        "size_bytes": len(fixed_body),
    }


def _input_artifact(path: Path, body: bytes) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        display = resolved.as_posix()
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def main() -> int:
    args = parse_args()
    report = compile_horizon_assimilation_policy_freeze(
        parent_report_path=args.parent_report,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    for horizon, mode in report["policy"][
        "selected_mode_by_horizon_hours"
    ].items():
        print(f"{horizon}h={mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
