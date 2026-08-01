#!/usr/bin/env python3
"""Build a receipt-bound outcome document from an offline observation batch."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.action_innovation_prospective_verification import (
    ACTION_INNOVATION_AUTHORITATIVE_OBSERVATION_BATCH_SCHEMA,
    ActionInnovationProspectiveOutcomeDocument,
    ProspectiveOutletObservation,
    action_innovation_authoritative_observation_batch_from_dict,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_runtime import REPO_ROOT
from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_uncertainty_shadow_runtime import (
    DEFAULT_UNCERTAINTY_FREEZE_PATH,
    load_frozen_action_innovation_uncertainty_shadow_runtime,
)

if __package__:
    from scripts.verify_geospatial_kernel_action_innovation_uncertainty_shadow import (
        MAXIMUM_ISSUE_LATENCY,
        _validate_receipt_contract,
    )
else:
    from verify_geospatial_kernel_action_innovation_uncertainty_shadow import (
        MAXIMUM_ISSUE_LATENCY,
        _validate_receipt_contract,
    )

OBSERVATION_BATCH_SCHEMA = ACTION_INNOVATION_AUTHORITATIVE_OBSERVATION_BATCH_SCHEMA


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast-receipt", type=Path, required=True)
    parser.add_argument("--observation-batch", type=Path, required=True)
    parser.add_argument(
        "--uncertainty-freeze",
        type=Path,
        default=DEFAULT_UNCERTAINTY_FREEZE_PATH,
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def compile_prospective_outcomes(
    forecast_receipt_body: bytes,
    observation_batch_body: bytes,
    *,
    uncertainty_freeze_path: Path = DEFAULT_UNCERTAINTY_FREEZE_PATH,
    repository_root: Path = REPO_ROOT,
    evaluated_at: datetime | None = None,
) -> ActionInnovationProspectiveOutcomeDocument:
    receipt = _json_mapping(
        forecast_receipt_body,
        "action_innovation_prospective_outcome_forecast_receipt_json_invalid",
    )
    batch_payload = _json_mapping(
        observation_batch_body,
        "action_innovation_prospective_observation_batch_json_invalid",
    )
    _validate_receipt_contract(receipt)
    batch = action_innovation_authoritative_observation_batch_from_dict(batch_payload)

    runtime = load_frozen_action_innovation_uncertainty_shadow_runtime(
        uncertainty_freeze_path=uncertainty_freeze_path,
        repository_root=repository_root,
        enabled=False,
    )
    execution = receipt["execution_identity"]
    result = receipt["result"]
    point_shadow = result["point_shadow_forecast"]
    interval = result["interval_forecast"]
    point = interval["point_forecast"]
    request_identity = receipt["request_identity"]
    frozen_network_id = runtime.point_runtime.parameters.support.network_id
    if (
        execution["uncertainty_freeze_sha256"] != runtime.uncertainty_freeze_sha256
        or execution["uncertainty_parameter_sha256"]
        != runtime.uncertainty_parameter_sha256
        or execution["point_freeze_sha256"] != runtime.point_runtime.freeze_sha256
        or execution["point_parameter_sha256"]
        != runtime.point_runtime.parameter_sha256
        or execution["uncertainty_runtime_sha256"]
        != runtime.uncertainty_runtime_sha256
        or execution["point_runtime_sha256"] != runtime.point_runtime.runtime_sha256
    ):
        raise ValueError("action_innovation_prospective_outcome_frozen_identity_mismatch")
    if (
        request_identity["network_id"] != frozen_network_id
        or batch.network_id != frozen_network_id
        or result["network_id"] != frozen_network_id
        or point_shadow["network_id"] != frozen_network_id
        or point_shadow["input_attestation"]["network_id"] != frozen_network_id
        or point_shadow["freeze_sha256"] != execution["point_freeze_sha256"]
        or point_shadow["parameter_sha256"] != execution["point_parameter_sha256"]
        or point_shadow["runtime_sha256"] != execution["point_runtime_sha256"]
        or interval["parameters"] != runtime.uncertainty_parameters.as_dict()
        or point["parameters"] != runtime.point_runtime.parameters.as_dict()
        or point_shadow["forecast"] != point
    ):
        raise ValueError("action_innovation_prospective_outcome_network_or_runtime_mismatch")

    issue_time = _time(point["issue_time"], "forecast_issue")
    attested_issue_time = _time(
        point_shadow["input_attestation"]["issue_time"],
        "attestation_issue",
    )
    targets = tuple(_time(value, "forecast_target") for value in point["target_valid_times"])
    expected_targets = tuple(
        issue_time + timedelta(hours=horizon)
        for horizon in ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS
    )
    generated_at = _time(receipt["generated_at"], "forecast_generated")
    freeze = _json_mapping(
        uncertainty_freeze_path.read_bytes(),
        "action_innovation_prospective_outcome_freeze_json_invalid",
    )
    frozen_at = _time(freeze.get("frozen_at"), "uncertainty_frozen")
    if (
        attested_issue_time != issue_time
        or targets != expected_targets
        or issue_time < frozen_at
        or generated_at < max(issue_time, frozen_at)
        or generated_at > issue_time + MAXIMUM_ISSUE_LATENCY
        or generated_at >= min(targets)
    ):
        raise ValueError("action_innovation_prospective_outcome_forecast_ordering_invalid")

    retrieved_at = batch.retrieved_at
    evaluation_time = evaluated_at if evaluated_at is not None else _now()
    if (
        not isinstance(evaluation_time, datetime)
        or evaluation_time.tzinfo is None
        or evaluation_time.utcoffset() is None
    ):
        raise ValueError(
            "action_innovation_prospective_observation_batch_evaluation_time_invalid"
        )
    by_target: dict[datetime, ProspectiveOutletObservation] = {
        value.target_valid_time: value for value in batch.observations
    }
    if set(by_target) != set(targets):
        raise ValueError("action_innovation_prospective_observation_batch_axis_invalid")
    if any(
        value.observation_available_at > evaluation_time
        for value in batch.observations
    ):
        raise ValueError(
            "action_innovation_prospective_observation_batch_availability_invalid"
        )
    if (
        retrieved_at <= generated_at
        or retrieved_at < max(targets)
        or retrieved_at > evaluation_time
    ):
        raise ValueError("action_innovation_prospective_observation_batch_ordering_invalid")

    return ActionInnovationProspectiveOutcomeDocument(
        request_id=request_identity["request_id"],
        forecast_receipt_sha256=hashlib.sha256(forecast_receipt_body).hexdigest(),
        source_observation_artifact_sha256=hashlib.sha256(
            observation_batch_body
        ).hexdigest(),
        source_observation_artifact_size_bytes=len(observation_batch_body),
        outcomes_available_at=retrieved_at,
        outlet_observation_provenance_id=batch.outlet_observation_provenance_id,
        outlet_observation_evidence_level="authoritative",
        observations=tuple(by_target[target] for target in targets),
    )
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
        raise ValueError(f"action_innovation_prospective_outcome_{name}_time_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"action_innovation_prospective_outcome_{name}_time_invalid"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"action_innovation_prospective_outcome_{name}_time_invalid")
    return parsed
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
        raise ValueError("action_innovation_prospective_outcomes_refuses_overwrite")
    outcomes = compile_prospective_outcomes(
        args.forecast_receipt.read_bytes(),
        args.observation_batch.read_bytes(),
        uncertainty_freeze_path=args.uncertainty_freeze,
    )
    _write(args.output, outcomes.as_dict())
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
