#!/usr/bin/env python3
"""Finalize one matured prospective issue into outcomes, verification, and audit."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_runtime import REPO_ROOT
from data_agent.uwm.geospatial_kernel_v2.action_innovation_uncertainty_shadow_runtime import (
    DEFAULT_UNCERTAINTY_FREEZE_PATH,
)

if __package__:
    from scripts.audit_geospatial_kernel_action_innovation_prospective_evidence import (
        compile_prospective_evidence_audit_from_bodies,
    )
    from scripts.build_geospatial_kernel_action_innovation_prospective_outcomes import (
        compile_prospective_outcomes,
    )
    from scripts.verify_geospatial_kernel_action_innovation_uncertainty_shadow import (
        compile_prospective_verification,
    )
else:
    from audit_geospatial_kernel_action_innovation_prospective_evidence import (
        compile_prospective_evidence_audit_from_bodies,
    )
    from build_geospatial_kernel_action_innovation_prospective_outcomes import (
        compile_prospective_outcomes,
    )
    from verify_geospatial_kernel_action_innovation_uncertainty_shadow import (
        compile_prospective_verification,
    )

OUTCOME_FILENAME = "outcomes.json"
VERIFICATION_FILENAME = "verification.json"
EVIDENCE_AUDIT_FILENAME = "evidence-audit.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast-receipt", type=Path, required=True)
    parser.add_argument("--observation-batch", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument(
        "--uncertainty-freeze",
        type=Path,
        default=DEFAULT_UNCERTAINTY_FREEZE_PATH,
    )
    return parser.parse_args()


def finalize_prospective_issue(
    *,
    forecast_receipt_path: Path,
    observation_batch_path: Path,
    output_directory: Path,
    uncertainty_freeze_path: Path = DEFAULT_UNCERTAINTY_FREEZE_PATH,
    repository_root: Path = REPO_ROOT,
    finalized_at: datetime | None = None,
) -> dict[str, Path]:
    if output_directory.exists():
        raise ValueError(
            "action_innovation_prospective_issue_finalizer_refuses_existing_directory"
        )
    finalization_time = finalized_at if finalized_at is not None else _now()
    if (
        not isinstance(finalization_time, datetime)
        or finalization_time.tzinfo is None
        or finalization_time.utcoffset() is None
    ):
        raise ValueError(
            "action_innovation_prospective_issue_finalizer_time_invalid"
        )

    forecast_body = forecast_receipt_path.read_bytes()
    observation_body = observation_batch_path.read_bytes()
    freeze_body = uncertainty_freeze_path.read_bytes()
    output_paths = {
        "outcomes": output_directory / OUTCOME_FILENAME,
        "verification": output_directory / VERIFICATION_FILENAME,
        "evidence_audit": output_directory / EVIDENCE_AUDIT_FILENAME,
    }
    outcomes = compile_prospective_outcomes(
        forecast_body,
        observation_body,
        uncertainty_freeze_path=uncertainty_freeze_path,
        repository_root=repository_root,
        evaluated_at=finalization_time,
    )
    outcome_body = _json_bytes(outcomes.as_dict())
    verification = compile_prospective_verification(
        forecast_body,
        outcome_body,
        observation_body,
        uncertainty_freeze_path=uncertainty_freeze_path,
        repository_root=repository_root,
        verified_at=finalization_time,
    )
    verification_body = _json_bytes(verification)
    audit = compile_prospective_evidence_audit_from_bodies(
        forecast_receipt_body=forecast_body,
        forecast_receipt_path=forecast_receipt_path,
        outcome_body=outcome_body,
        outcome_path=output_paths["outcomes"],
        observation_batch_body=observation_body,
        observation_batch_path=observation_batch_path,
        verification_body=verification_body,
        verification_path=output_paths["verification"],
        uncertainty_freeze_body=freeze_body,
        uncertainty_freeze_path=uncertainty_freeze_path,
        repository_root=repository_root,
        audit_time=finalization_time,
    )
    audit_body = _json_bytes(audit)

    output_directory.mkdir(parents=True, exist_ok=False)
    output_paths["outcomes"].write_bytes(outcome_body)
    output_paths["verification"].write_bytes(verification_body)
    output_paths["evidence_audit"].write_bytes(audit_body)
    return output_paths


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def _now() -> datetime:
    return datetime.now(UTC)


def main() -> int:
    args = parse_args()
    outputs = finalize_prospective_issue(
        forecast_receipt_path=args.forecast_receipt,
        observation_batch_path=args.observation_batch,
        output_directory=args.output_directory,
        uncertainty_freeze_path=args.uncertainty_freeze,
    )
    print(outputs["evidence_audit"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
