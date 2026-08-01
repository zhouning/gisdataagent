#!/usr/bin/env python3
"""Acquire both USGS outcomes only after the joint kinematic prediction seal."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode

from data_agent.uwm.geospatial_kernel_v2 import (
    DEFAULT_REGISTRY_PATH,
    load_public_data_registry,
)

if __package__:
    from scripts.acquire_geotransport_center_hill_v2_d3_inputs import _opener
    from scripts.acquire_geotransport_v2_blind_validation_outcomes import (
        _fetch_usgs,
        _outcome_csv,
        _parse_usgs_native_hourly,
    )
    from scripts.freeze_geotransport_kinematic_wave_holdout_v1 import (
        END,
        HOUR_COUNT,
        SCHEMA as PROTOCOL_SCHEMA,
        START,
        SYSTEM_IDS,
    )
    from scripts.run_geotransport_kinematic_wave_holdout_v1_outcome_free import (
        SCHEMA as ROLLOUT_SCHEMA,
        _seal_payload,
    )
else:
    from acquire_geotransport_center_hill_v2_d3_inputs import _opener
    from acquire_geotransport_v2_blind_validation_outcomes import (
        _fetch_usgs,
        _outcome_csv,
        _parse_usgs_native_hourly,
    )
    from freeze_geotransport_kinematic_wave_holdout_v1 import (
        END,
        HOUR_COUNT,
        SCHEMA as PROTOCOL_SCHEMA,
        START,
        SYSTEM_IDS,
    )
    from run_geotransport_kinematic_wave_holdout_v1_outcome_free import (
        SCHEMA as ROLLOUT_SCHEMA,
        _seal_payload,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v1_protocol.json"
)
DEFAULT_ROLLOUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v1_rollout_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/kinematic_wave_holdout_v1/outcomes"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v1_outcomes_report.json"
)
SCHEMA = "gwm.geotransport.kinematic_wave_holdout_outcomes.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--rollout", type=Path, default=DEFAULT_ROLLOUT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=4)
    return parser.parse_args()


def acquire(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    rollout_path: Path = DEFAULT_ROLLOUT,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    output_root: Path = DEFAULT_OUTPUT,
    proxy: str = "http://127.0.0.1:7897",
    timeout_seconds: float = 180.0,
    retries: int = 4,
) -> tuple[dict[str, bytes], dict[str, bytes], dict[str, Any]]:
    protocol_body, protocol = _load_json(protocol_path)
    rollout_body, rollout = _load_json(rollout_path)
    _validate_joint_seal(protocol_body, protocol, rollout)
    _verify_frozen_code(protocol)
    _verify_sealed_predictions(protocol_body, rollout)

    registry = load_public_data_registry(registry_path)
    registry_systems = {
        row["system_id"]: row for row in registry.payload["systems"]
    }
    support_starts = tuple(
        START - timedelta(hours=1) + timedelta(hours=index)
        for index in range(HOUR_COUNT + 1)
    )
    support_ends = tuple(value + timedelta(hours=1) for value in support_starts)
    allowed_cadences = set(
        int(value)
        for value in protocol["scoring_lock"]["allowed_native_cadence_seconds"]
    )
    opener = _opener(proxy)
    raw_bodies: dict[str, bytes] = {}
    csv_bodies: dict[str, bytes] = {}
    system_reports: dict[str, dict[str, Any]] = {}
    for system_id in SYSTEM_IDS:
        lock = protocol["systems"][system_id]["outcome"]
        query = urlencode(
            {
                "format": "json",
                "sites": lock["site_id"],
                "parameterCd": lock["parameter_code"],
                "startDT": lock["request_start"],
                "endDT": lock["request_end"],
                "siteStatus": "all",
            }
        )
        url = f"https://waterservices.usgs.gov/nwis/iv/?{query}"
        body, retrieval = _fetch_usgs(
            url,
            opener=opener,
            timeout_seconds=timeout_seconds,
            retries=retries,
            maximum_bytes=5_000_000,
        )
        outcomes, qualifiers, counts, cadence = _parse_usgs_native_hourly(
            json.loads(body),
            system=registry_systems[system_id],
            support_starts=support_starts,
            support_ends=support_ends,
        )
        if cadence not in allowed_cadences:
            raise ValueError(
                f"kinematic_holdout_{system_id}_native_cadence_not_predeclared"
            )
        prior = outcomes[START]
        if prior is None:
            raise ValueError(
                f"kinematic_holdout_{system_id}_persistence_prior_missing"
            )
        csv_body = _outcome_csv(support_ends, outcomes)
        raw_bodies[system_id] = body
        csv_bodies[system_id] = csv_body
        target_values = [outcomes[value] for value in support_ends[1:]]
        system_reports[system_id] = {
            "system_id": system_id,
            "site_id": lock["site_id"],
            "parameter_code": lock["parameter_code"],
            "variable_role": "independent_observation",
            "source": retrieval,
            "raw_outcome": {
                "path": _display(output_root / f"raw/{system_id}.json"),
                "sha256": hashlib.sha256(body).hexdigest(),
                "size_bytes": len(body),
            },
            "outcome_values": {
                "path": _display(output_root / f"values/{system_id}.csv"),
                "sha256": hashlib.sha256(csv_body).hexdigest(),
                "size_bytes": len(csv_body),
            },
            "prior_observation_support_end_utc": _iso(START),
            "prior_observation_m3s": float(prior),
            "quality": {
                "target_hour_count": HOUR_COUNT,
                "native_sample_cadence_seconds": cadence,
                "native_cadence_predeclared": True,
                "expected_native_samples_per_complete_hour": 3600 // cadence,
                "target_complete_hour_count": sum(
                    value is not None for value in target_values
                ),
                "target_missing_hour_count": sum(
                    value is None for value in target_values
                ),
                "all_support_complete_hour_count": sum(
                    value is not None for value in outcomes.values()
                ),
                "qualifiers": sorted(
                    {value for value in qualifiers.values() if value}
                ),
                "sample_counts": sorted(set(counts.values())),
                "missing_values_imputed": False,
                "hourly_aggregation": (
                    "mean_of_every_complete_approved_native_sample_on_(t-1h,t]"
                ),
            },
        }

    _verify_sealed_predictions(protocol_body, rollout)
    report = {
        "schema": SCHEMA,
        "status": "two_system_outcomes_acquired_after_joint_seal",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "start_inclusive": _iso(START),
            "end_exclusive": _iso(END),
            "hour_count": HOUR_COUNT,
        },
        "sealed_artifacts": {
            "protocol": _artifact(protocol_path, protocol_body),
            "rollout_report": _artifact(rollout_path, rollout_body),
            "joint_seal_sha256": rollout["joint_seal"]["sha256"],
            "predictions": {
                system_id: rollout["systems"][system_id]["prediction_artifact"]
                for system_id in SYSTEM_IDS
            },
        },
        "systems": system_reports,
        "ordering_audit": {
            "both_predictions_verified_before_first_outcome_request": True,
            "joint_seal_recomputed_before_first_outcome_request": True,
            "both_predictions_reverified_after_last_outcome_response": True,
            "prediction_content_changed_during_outcome_access": False,
            "outcome_access_phase_compliant": True,
        },
        "claim_boundary": {
            "outcomes_acquired": True,
            "outcome_values_imputed": False,
            "predictions_scored": False,
            "operator_form_admitted": False,
            "predictive_validation_complete": False,
            "geospatial_kernel_validated": False,
        },
    }
    return raw_bodies, csv_bodies, report


def _validate_joint_seal(
    protocol_body: bytes,
    protocol: Mapping[str, Any],
    rollout: Mapping[str, Any],
) -> None:
    if (
        protocol.get("schema") != PROTOCOL_SCHEMA
        or protocol.get("status")
        != "frozen_before_dynamic_input_and_outcome_access"
        or rollout.get("schema") != ROLLOUT_SCHEMA
        or rollout.get("status") != "joint_outcome_free_predictions_sealed"
        or rollout.get("input_artifacts", {}).get("protocol", {}).get("sha256")
        != hashlib.sha256(protocol_body).hexdigest()
        or (rollout.get("joint_seal") or {}).get("sealed_system_ids")
        != list(SYSTEM_IDS)
        or (rollout.get("joint_seal") or {}).get("algorithm")
        != "sha256_canonical_json"
        or (rollout.get("joint_seal") or {}).get("all_predictions_present")
        is not True
        or (rollout.get("joint_seal") or {}).get("all_execution_gates_passed")
        is not True
        or (rollout.get("data_isolation") or {}).get("outcome_values_loaded")
        is not False
    ):
        raise ValueError("kinematic_holdout_outcome_joint_seal_invalid")


def _verify_sealed_predictions(
    protocol_body: bytes, rollout: Mapping[str, Any]
) -> None:
    input_descriptor = rollout["input_artifacts"]["input_report"]
    _read_verified(input_descriptor)
    predictions = {
        system_id: rollout["systems"][system_id]["prediction_artifact"]
        for system_id in SYSTEM_IDS
    }
    for descriptor in predictions.values():
        _read_verified(descriptor)
    seal_payload = _seal_payload(
        protocol_sha256=hashlib.sha256(protocol_body).hexdigest(),
        input_report_sha256=str(input_descriptor["sha256"]),
        predictions=predictions,
    )
    if hashlib.sha256(seal_payload).hexdigest() != rollout["joint_seal"]["sha256"]:
        raise ValueError("kinematic_holdout_joint_seal_hash_mismatch")


def _verify_frozen_code(protocol: Mapping[str, Any]) -> None:
    descriptors = protocol.get("frozen_code") or {}
    if not descriptors:
        raise ValueError("kinematic_holdout_frozen_code_missing")
    for descriptor in descriptors.values():
        _read_verified(descriptor)


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("kinematic_holdout_outcome_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("kinematic_holdout_outcome_artifact_identity_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


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
    except ValueError:
        return resolved.as_posix()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    if args.output.exists() or args.report.exists():
        raise ValueError("kinematic_holdout_outcomes_refuse_overwrite")
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("kinematic_holdout_positive_outcome_request_limits_required")
    raw, values, report = acquire(
        protocol_path=args.protocol,
        rollout_path=args.rollout,
        registry_path=args.registry,
        output_root=args.output,
        proxy=args.proxy,
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
    )
    for system_id in SYSTEM_IDS:
        raw_path = args.output / f"raw/{system_id}.json"
        value_path = args.output / f"values/{system_id}.csv"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        value_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw[system_id])
        value_path.write_bytes(values[system_id])
    _write_json(args.report, report)
    print(args.report)
    for system_id in SYSTEM_IDS:
        quality = report["systems"][system_id]["quality"]
        print(
            f"{system_id}_complete_target_hours="
            f"{quality['target_complete_hour_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
