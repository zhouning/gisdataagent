#!/usr/bin/env python3
"""Reopen and exactly recompute one prospective issue evidence chain."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_runtime import REPO_ROOT
from data_agent.uwm.geospatial_kernel_v2.action_innovation_uncertainty_shadow_runtime import (
    DEFAULT_UNCERTAINTY_FREEZE_PATH,
)

if __package__:
    from scripts.verify_geospatial_kernel_action_innovation_uncertainty_shadow import (
        compile_prospective_verification,
    )
else:
    from verify_geospatial_kernel_action_innovation_uncertainty_shadow import (
        compile_prospective_verification,
    )

AUDIT_SCHEMA = "gwm.geospatial_kernel.action_innovation_prospective_evidence_audit.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast-receipt", type=Path, required=True)
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--observation-batch", type=Path, required=True)
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument(
        "--uncertainty-freeze",
        type=Path,
        default=DEFAULT_UNCERTAINTY_FREEZE_PATH,
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def compile_prospective_evidence_audit(
    *,
    forecast_receipt_path: Path,
    outcome_path: Path,
    observation_batch_path: Path,
    verification_path: Path,
    uncertainty_freeze_path: Path = DEFAULT_UNCERTAINTY_FREEZE_PATH,
    repository_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    paths = {
        "forecast_receipt": forecast_receipt_path,
        "outcomes": outcome_path,
        "observation_batch": observation_batch_path,
        "verification": verification_path,
        "uncertainty_freeze": uncertainty_freeze_path,
    }
    bodies = {name: path.read_bytes() for name, path in paths.items()}
    return compile_prospective_evidence_audit_from_bodies(
        forecast_receipt_body=bodies["forecast_receipt"],
        forecast_receipt_path=paths["forecast_receipt"],
        outcome_body=bodies["outcomes"],
        outcome_path=paths["outcomes"],
        observation_batch_body=bodies["observation_batch"],
        observation_batch_path=paths["observation_batch"],
        verification_body=bodies["verification"],
        verification_path=paths["verification"],
        uncertainty_freeze_body=bodies["uncertainty_freeze"],
        uncertainty_freeze_path=paths["uncertainty_freeze"],
        repository_root=repository_root,
    )


def compile_prospective_evidence_audit_from_bodies(
    *,
    forecast_receipt_body: bytes,
    forecast_receipt_path: Path,
    outcome_body: bytes,
    outcome_path: Path,
    observation_batch_body: bytes,
    observation_batch_path: Path,
    verification_body: bytes,
    verification_path: Path,
    uncertainty_freeze_body: bytes,
    uncertainty_freeze_path: Path,
    repository_root: Path = REPO_ROOT,
    audit_time: datetime | None = None,
) -> dict[str, Any]:
    paths = {
        "forecast_receipt": forecast_receipt_path,
        "outcomes": outcome_path,
        "observation_batch": observation_batch_path,
        "verification": verification_path,
        "uncertainty_freeze": uncertainty_freeze_path,
    }
    bodies = {
        "forecast_receipt": forecast_receipt_body,
        "outcomes": outcome_body,
        "observation_batch": observation_batch_body,
        "verification": verification_body,
        "uncertainty_freeze": uncertainty_freeze_body,
    }
    if any(not isinstance(body, bytes) or not body for body in bodies.values()):
        raise ValueError(
            "action_innovation_prospective_evidence_audit_artifact_body_invalid"
        )
    if uncertainty_freeze_path.read_bytes() != uncertainty_freeze_body:
        raise ValueError(
            "action_innovation_prospective_evidence_audit_freeze_body_mismatch"
        )
    verification = _json_mapping(
        bodies["verification"],
        "action_innovation_prospective_evidence_audit_verification_json_invalid",
    )
    verification_time = _time(
        verification.get("generated_at"),
        "verification_generated",
    )
    generated_at = audit_time if audit_time is not None else _now()
    if (
        not isinstance(generated_at, datetime)
        or generated_at.tzinfo is None
        or generated_at.utcoffset() is None
        or verification_time > generated_at
    ):
        raise ValueError(
            "action_innovation_prospective_evidence_audit_time_ordering_invalid"
        )
    recomputed = compile_prospective_verification(
        bodies["forecast_receipt"],
        bodies["outcomes"],
        bodies["observation_batch"],
        uncertainty_freeze_path=uncertainty_freeze_path,
        repository_root=repository_root,
        verified_at=verification_time,
    )
    if verification != recomputed:
        raise ValueError(
            "action_innovation_prospective_evidence_audit_verification_mismatch"
        )
    return {
        "schema": AUDIT_SCHEMA,
        "status": "prospective_issue_source_chain_recomputed_not_admitted",
        "generated_at": generated_at.isoformat(),
        "source_artifacts": {
            name: _artifact_path(path, bodies[name], repository_root)
            for name, path in paths.items()
        },
        "request_identity": dict(verification["request_identity"]),
        "frozen_candidate_identity": dict(verification["frozen_candidate_identity"]),
        "checks": {
            "all_source_artifacts_reopened": True,
            "all_source_artifact_hashes_verified": True,
            "verification_report_recomputed_exactly": True,
            "score_recomputed_from_exact_forecast_and_observations": True,
        },
        "claim_boundary": {
            "trusted_external_timestamp_verified": False,
            "independent_timestamped_prospective_validation": False,
            "multi_issue_uncertainty_validated": False,
            "multi_system_uncertainty_validated": False,
            "runtime_default_enabled": False,
            "uncertainty_candidate_admitted": False,
        },
    }


def load_and_recompute_prospective_evidence_audit(
    audit_path: Path,
    *,
    repository_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    audit_body = audit_path.read_bytes()
    audit = _json_mapping(
        audit_body,
        "action_innovation_prospective_evidence_audit_json_invalid",
    )
    _validate_audit_contract(audit)
    source = audit["source_artifacts"]
    paths = {
        name: _resolve_artifact_path(descriptor["path"], repository_root)
        for name, descriptor in source.items()
    }
    bodies = {name: path.read_bytes() for name, path in paths.items()}
    for name, descriptor in source.items():
        if descriptor != _artifact_path(paths[name], bodies[name], repository_root):
            raise ValueError(
                "action_innovation_prospective_evidence_audit_artifact_mismatch"
            )
    verification = _json_mapping(
        bodies["verification"],
        "action_innovation_prospective_evidence_audit_verification_json_invalid",
    )
    verification_time = _time(
        verification.get("generated_at"),
        "verification_generated",
    )
    audit_time = _time(audit["generated_at"], "audit_generated")
    if verification_time > audit_time or audit_time > _now():
        raise ValueError(
            "action_innovation_prospective_evidence_audit_time_ordering_invalid"
        )
    recomputed = compile_prospective_verification(
        bodies["forecast_receipt"],
        bodies["outcomes"],
        bodies["observation_batch"],
        uncertainty_freeze_path=paths["uncertainty_freeze"],
        repository_root=repository_root,
        verified_at=verification_time,
    )
    if (
        verification != recomputed
        or audit["request_identity"] != verification["request_identity"]
        or audit["frozen_candidate_identity"]
        != verification["frozen_candidate_identity"]
    ):
        raise ValueError(
            "action_innovation_prospective_evidence_audit_verification_mismatch"
        )
    return {
        "audit_path": audit_path,
        "audit_body": audit_body,
        "audit": audit,
        "verification_path": paths["verification"],
        "verification_body": bodies["verification"],
        "verification": verification,
    }


def _validate_audit_contract(audit: Mapping[str, Any]) -> None:
    if set(audit) != {
        "schema",
        "status",
        "generated_at",
        "source_artifacts",
        "request_identity",
        "frozen_candidate_identity",
        "checks",
        "claim_boundary",
    }:
        raise ValueError("action_innovation_prospective_evidence_audit_fields_invalid")
    source = audit.get("source_artifacts") or {}
    if (
        audit.get("schema") != AUDIT_SCHEMA
        or audit.get("status")
        != "prospective_issue_source_chain_recomputed_not_admitted"
        or set(source)
        != {
            "forecast_receipt",
            "outcomes",
            "observation_batch",
            "verification",
            "uncertainty_freeze",
        }
        or any(not _descriptor(value) for value in source.values())
        or audit.get("checks")
        != {
            "all_source_artifacts_reopened": True,
            "all_source_artifact_hashes_verified": True,
            "verification_report_recomputed_exactly": True,
            "score_recomputed_from_exact_forecast_and_observations": True,
        }
        or audit.get("claim_boundary")
        != {
            "trusted_external_timestamp_verified": False,
            "independent_timestamped_prospective_validation": False,
            "multi_issue_uncertainty_validated": False,
            "multi_system_uncertainty_validated": False,
            "runtime_default_enabled": False,
            "uncertainty_candidate_admitted": False,
        }
        or not isinstance(audit.get("request_identity"), Mapping)
        or not isinstance(audit.get("frozen_candidate_identity"), Mapping)
    ):
        raise ValueError("action_innovation_prospective_evidence_audit_invalid")


def _descriptor(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {"path", "sha256", "size_bytes"}
        and isinstance(value.get("path"), str)
        and bool(value["path"].strip())
        and _valid_sha256(value.get("sha256"))
        and isinstance(value.get("size_bytes"), int)
        and not isinstance(value.get("size_bytes"), bool)
        and value["size_bytes"] > 0
    )


def _artifact_path(
    path: Path,
    body: bytes,
    repository_root: Path,
) -> dict[str, object]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(repository_root.resolve()).as_posix()
    except ValueError:
        display = resolved.as_posix()
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _resolve_artifact_path(value: object, repository_root: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("action_innovation_prospective_evidence_audit_path_invalid")
    path = Path(value)
    return path if path.is_absolute() else repository_root / path


def _json_mapping(body: bytes, error: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(error) from exc
    if not isinstance(payload, Mapping):
        raise ValueError(error)
    return payload


def _time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(
            f"action_innovation_prospective_evidence_audit_{name}_time_invalid"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"action_innovation_prospective_evidence_audit_{name}_time_invalid"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(
            f"action_innovation_prospective_evidence_audit_{name}_time_invalid"
        )
    return parsed


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise ValueError("action_innovation_prospective_evidence_audit_refuses_overwrite")
    audit = compile_prospective_evidence_audit(
        forecast_receipt_path=args.forecast_receipt,
        outcome_path=args.outcomes,
        observation_batch_path=args.observation_batch,
        verification_path=args.verification,
        uncertainty_freeze_path=args.uncertainty_freeze,
    )
    _write(args.output, audit)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
