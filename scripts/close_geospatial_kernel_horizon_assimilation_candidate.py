#!/usr/bin/env python3
"""Close the failed horizon-assimilation candidate without reopening its score."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.horizon_assimilation_policy import (
    HORIZON_ASSIMILATION_CANDIDATE_ID,
    HorizonAssimilationPolicy,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_FREEZE = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_policy_freeze.json"
)
DEFAULT_SCORING_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_scoring_protocol.json"
)
DEFAULT_SCORE = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_score.json"
)
DEFAULT_VERIFICATION = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_score_verification.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_candidate_disposition.json"
)
POLICY_SOURCE = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/horizon_assimilation_policy.py"
)
ROLLOUT_SOURCE = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/horizon_assimilation_rollout.py"
)
PRODUCTION_SCAN_ROOTS = (
    REPO_ROOT / "data_agent/api",
    REPO_ROOT / "data_agent/toolsets",
    REPO_ROOT / "frontend/src",
)
PRODUCTION_SCAN_FILES = (
    REPO_ROOT / "data_agent/app.py",
    REPO_ROOT / "data_agent/agent.py",
    REPO_ROOT / "data_agent/frontend_api.py",
)
SCHEMA = "gwm.geotransport.horizon_assimilation_candidate_disposition.v1"
POLICY_FREEZE_SCHEMA = "gwm.geotransport.horizon_assimilation_policy_freeze.v1"
SCORING_PROTOCOL_SCHEMA = (
    "gwm.geotransport.horizon_assimilation_holdout_scoring_protocol.v1"
)
SCORE_SCHEMA = "gwm.geotransport.horizon_assimilation_holdout_score.v1"
VERIFICATION_SCHEMA = (
    "gwm.geotransport.horizon_assimilation_holdout_score_verification.v1"
)
SOURCE_SUFFIXES = {".py", ".ts", ".tsx"}
RUNTIME_TOKEN = "horizon_assimilation"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-freeze", type=Path, default=DEFAULT_POLICY_FREEZE)
    parser.add_argument(
        "--scoring-protocol", type=Path, default=DEFAULT_SCORING_PROTOCOL
    )
    parser.add_argument("--score", type=Path, default=DEFAULT_SCORE)
    parser.add_argument("--verification", type=Path, default=DEFAULT_VERIFICATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_disposition(
    *,
    policy_freeze_path: Path = DEFAULT_POLICY_FREEZE,
    scoring_protocol_path: Path = DEFAULT_SCORING_PROTOCOL,
    score_path: Path = DEFAULT_SCORE,
    verification_path: Path = DEFAULT_VERIFICATION,
    generated_at: datetime | None = None,
    scan_roots: Sequence[Path] = PRODUCTION_SCAN_ROOTS,
    scan_files: Sequence[Path] = PRODUCTION_SCAN_FILES,
) -> dict[str, Any]:
    policy_body, policy_freeze = _load_json(policy_freeze_path)
    protocol_body, scoring_protocol = _load_json(scoring_protocol_path)
    score_body, score = _load_json(score_path)
    verification_body, verification = _load_json(verification_path)
    policy = _validate_evidence(
        policy_freeze=policy_freeze,
        scoring_protocol=scoring_protocol,
        score=score,
        score_body=score_body,
        verification=verification,
    )
    runtime_audit = _audit_runtime_reachability(
        scan_roots=scan_roots,
        scan_files=scan_files,
    )
    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("horizon_candidate_disposition_time_must_be_aware")
    aggregate = score["aggregate_gate"]
    reconstruction = verification["score_reconstruction"]
    structural_ties = list(reconstruction["structural_tie_groups"])
    return {
        "schema": SCHEMA,
        "status": "candidate_rejected_after_verified_historical_holdout",
        "generated_at": now.astimezone(UTC).isoformat(),
        "candidate": {
            "candidate_id": policy.candidate_id,
            "policy_sha256": policy_freeze["policy_sha256"],
            "selected_mode_by_horizon_hours": policy.as_dict()[
                "selected_mode_by_horizon_hours"
            ],
            "admitted": False,
            "runtime_default_enabled": False,
        },
        "evidence_chain": {
            "policy_freeze": _artifact(policy_freeze_path, policy_body),
            "scoring_protocol": _artifact(scoring_protocol_path, protocol_body),
            "single_score": _artifact(score_path, score_body),
            "independent_score_verification": _artifact(
                verification_path, verification_body
            ),
            "policy_source": _artifact(POLICY_SOURCE, POLICY_SOURCE.read_bytes()),
            "rollout_source": _artifact(
                ROLLOUT_SOURCE, ROLLOUT_SOURCE.read_bytes()
            ),
        },
        "decision": {
            "disposition": "rejected_for_promotion",
            "final_for_candidate_id": True,
            "formal_support_gate_passed": False,
            "passed_group_count": aggregate["passed_group_count"],
            "failed_group_count": aggregate["failed_group_count"],
            "structural_self_comparison_groups": structural_ties,
            "reason_codes": [
                "formal_noncompensatory_support_gate_failed",
                "performance_not_stable_across_both_systems_and_all_horizons",
                "three_hour_candidate_equals_fixed_quadratic_comparator",
            ],
        },
        "runtime_containment": {
            "policy_deserialization_enforces_admitted_false": True,
            "policy_deserialization_enforces_runtime_default_false": True,
            "production_entrypoint_scan": runtime_audit,
            "production_runtime_reachable": False,
        },
        "post_score_controls": {
            "formal_score_execution_count": verification["execution_audit"][
                "formal_score_execution_count"
            ],
            "outcomes_imputed": False,
            "post_score_tuning_performed": False,
            "same_holdout_rescore_permitted": False,
            "same_candidate_id_reopen_permitted": False,
            "failed_gate_reinterpretation_as_promotion_permitted": False,
        },
        "allowed_future_use": {
            "offline_diagnostic_or_comparator": True,
            "production_prediction": False,
            "new_model_requires_new_candidate_id": True,
            "new_claim_requires_new_predeclared_gate_and_unused_window": True,
            "current_exposed_outcomes_may_select_future_rules": False,
        },
        "scientific_boundary": {
            "historical_holdout_not_real_time_prospective": True,
            "nwm_retrospective": True,
            "cwms_actions_archived": True,
            "historical_usgs_publication_latency_verified": False,
            "geospatial_kernel_stage": 2,
            "functional_evidence_level": "L2",
            "overall_evidence_level": "L1-L2",
            "trl": "3-4",
        },
        "claim_boundary": {
            "candidate_disposition_finalized": True,
            "candidate_support_gate_passed": False,
            "candidate_promoted": False,
            "runtime_default_enabled": False,
            "geospatial_kernel_validated": False,
            "superiority_claim_supported": False,
        },
    }


def _validate_evidence(
    *,
    policy_freeze: Mapping[str, Any],
    scoring_protocol: Mapping[str, Any],
    score: Mapping[str, Any],
    score_body: bytes,
    verification: Mapping[str, Any],
) -> HorizonAssimilationPolicy:
    if (
        policy_freeze.get("schema") != POLICY_FREEZE_SCHEMA
        or scoring_protocol.get("schema") != SCORING_PROTOCOL_SCHEMA
        or score.get("schema") != SCORE_SCHEMA
        or score.get("status")
        != "holdout_scored_exactly_once_no_post_score_tuning"
        or verification.get("schema") != VERIFICATION_SCHEMA
        or verification.get("status")
        != "pass_single_score_independent_reconstruction"
    ):
        raise ValueError("horizon_candidate_disposition_evidence_status_invalid")
    score_claims = score.get("claim_boundary") or {}
    score_audit = score.get("score_execution_audit") or {}
    verification_claims = verification.get("claim_boundary") or {}
    verification_audit = verification.get("execution_audit") or {}
    reconstruction = verification.get("score_reconstruction") or {}
    if (
        score.get("aggregate_gate", {}).get("candidate_support_gate_passed")
        is not False
        or score.get("aggregate_gate", {}).get("passed_group_count") != 3
        or score.get("aggregate_gate", {}).get("failed_group_count") != 5
        or score_claims.get("candidate_promoted") is not False
        or score_claims.get("runtime_default_enabled") is not False
        or score_audit.get("score_execution_count") != 1
        or score_audit.get("post_score_tuning_performed") is not False
        or verification_claims.get("candidate_support_gate_passed") is not False
        or verification_claims.get("candidate_promoted") is not False
        or verification_audit.get("formal_score_execution_count") != 1
        or verification_audit.get("post_score_tuning_performed") is not False
        or reconstruction.get("formal_candidate_support_gate_passed") is not False
        or reconstruction.get("structural_tie_groups")
        != ["center_hill:3h", "j_percy_priest:3h"]
        or verification.get("verified_artifacts", {})
        .get("score_report", {})
        .get("sha256")
        != hashlib.sha256(score_body).hexdigest()
    ):
        raise ValueError("horizon_candidate_disposition_failed_gate_not_verified")
    for descriptor in scoring_protocol.get("frozen_artifacts", {}).values():
        _read_verified(descriptor)
    policy_payload = policy_freeze.get("policy")
    if not isinstance(policy_payload, Mapping):
        raise ValueError("horizon_candidate_disposition_policy_missing")
    policy = HorizonAssimilationPolicy.from_dict(policy_payload)
    if (
        policy.candidate_id != HORIZON_ASSIMILATION_CANDIDATE_ID
        or policy.admitted is not False
        or policy.runtime_default_enabled is not False
    ):
        raise ValueError("horizon_candidate_disposition_policy_not_fail_closed")
    return policy


def _audit_runtime_reachability(
    *, scan_roots: Sequence[Path], scan_files: Sequence[Path]
) -> dict[str, Any]:
    files = set(scan_files)
    for root in scan_roots:
        files.update(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix in SOURCE_SUFFIXES
        )
    matches = []
    scanned = []
    for path in sorted(files):
        resolved = path.resolve()
        try:
            display = resolved.relative_to(REPO_ROOT).as_posix()
        except ValueError as exc:
            raise ValueError(
                "horizon_candidate_disposition_scan_outside_repository"
            ) from exc
        body = resolved.read_text(encoding="utf-8")
        scanned.append(display)
        if RUNTIME_TOKEN in body.lower():
            matches.append(display)
    if matches:
        raise ValueError(
            f"horizon_candidate_disposition_runtime_reference_found:{matches}"
        )
    return {
        "scan_roots": [_display(path) for path in scan_roots],
        "explicit_entry_files": [_display(path) for path in scan_files],
        "source_file_count": len(scanned),
        "matching_source_files": matches,
        "no_production_entrypoint_reference_found": True,
    }


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("horizon_candidate_disposition_artifact_outside_repo") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("horizon_candidate_disposition_artifact_hash_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("horizon_candidate_disposition_json_required")
    return body, payload


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("horizon_candidate_disposition_artifact_outside_repo") from exc


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise ValueError("horizon_candidate_disposition_already_exists")
    report = compile_disposition(
        policy_freeze_path=args.policy_freeze,
        scoring_protocol_path=args.scoring_protocol,
        score_path=args.score,
        verification_path=args.verification,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(f"disposition={report['decision']['disposition']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
