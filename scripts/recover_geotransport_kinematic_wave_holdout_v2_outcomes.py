#!/usr/bin/env python3
"""Recover v2 outcomes under the frozen omit-without-imputation policy."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from data_agent.uwm.geospatial_kernel_v2 import (
    DEFAULT_REGISTRY_PATH,
    load_public_data_registry,
)

if __package__:
    import scripts.acquire_geotransport_kinematic_wave_holdout_v1_outcomes as base
    from scripts.acquire_geotransport_kinematic_wave_holdout_v2_outcomes import (
        DEFAULT_OUTPUT,
        DEFAULT_PROTOCOL,
        DEFAULT_REPORT,
        DEFAULT_ROLLOUT,
        SCHEMA,
        _v2_context,
    )
    from scripts.freeze_geotransport_kinematic_wave_holdout_v2 import (
        END,
        HOUR_COUNT,
        START,
        SYSTEM_IDS,
    )
else:
    import acquire_geotransport_kinematic_wave_holdout_v1_outcomes as base
    from acquire_geotransport_kinematic_wave_holdout_v2_outcomes import (
        DEFAULT_OUTPUT,
        DEFAULT_PROTOCOL,
        DEFAULT_REPORT,
        DEFAULT_ROLLOUT,
        SCHEMA,
        _v2_context,
    )
    from freeze_geotransport_kinematic_wave_holdout_v2 import (
        END,
        HOUR_COUNT,
        START,
        SYSTEM_IDS,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
RECOVERY_ADR = REPO_ROOT / (
    "docs/architecture-decisions/"
    "adr-034-kinematic-wave-holdout-v2-outcome-missingness-recovery.md"
)


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
    protocol_path: Path,
    rollout_path: Path,
    registry_path: Path,
    output_root: Path,
    proxy: str,
    timeout_seconds: float,
    retries: int,
) -> tuple[dict[str, bytes], dict[str, bytes], dict[str, Any]]:
    protocol_body, protocol = base._load_json(protocol_path)
    rollout_body, rollout = base._load_json(rollout_path)
    with _v2_context():
        base._validate_joint_seal(protocol_body, protocol, rollout)
        base._verify_frozen_code(protocol)
        base._verify_sealed_predictions(protocol_body, rollout)
    if protocol["scoring_lock"]["missing_outcome_policy"] != "omit_without_imputation":
        raise ValueError("kinematic_holdout_v2_recovery_policy_not_frozen")

    registry = load_public_data_registry(registry_path)
    registry_systems = {
        row["system_id"]: row for row in registry.payload["systems"]
    }
    support_starts = tuple(
        START - timedelta(hours=1) + timedelta(hours=index)
        for index in range(HOUR_COUNT + 1)
    )
    support_ends = tuple(value + timedelta(hours=1) for value in support_starts)
    allowed_cadences = {
        int(value)
        for value in protocol["scoring_lock"]["allowed_native_cadence_seconds"]
    }
    opener = base._opener(proxy)
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
        body, retrieval = base._fetch_usgs(
            url,
            opener=opener,
            timeout_seconds=timeout_seconds,
            retries=retries,
            maximum_bytes=5_000_000,
        )
        outcomes, qualifiers, counts, cadence = base._parse_usgs_native_hourly(
            json.loads(body),
            system=registry_systems[system_id],
            support_starts=support_starts,
            support_ends=support_ends,
        )
        if cadence not in allowed_cadences:
            raise ValueError(
                f"kinematic_holdout_v2_{system_id}_native_cadence_not_predeclared"
            )
        csv_body = base._outcome_csv(support_ends, outcomes)
        raw_bodies[system_id] = body
        csv_bodies[system_id] = csv_body
        target_values = [outcomes[value] for value in support_ends[1:]]
        prior = outcomes[START]
        system_reports[system_id] = {
            "system_id": system_id,
            "site_id": lock["site_id"],
            "parameter_code": lock["parameter_code"],
            "variable_role": "independent_observation",
            "source": retrieval,
            "raw_outcome": {
                "path": base._display(output_root / f"raw/{system_id}.json"),
                "sha256": hashlib.sha256(body).hexdigest(),
                "size_bytes": len(body),
            },
            "outcome_values": {
                "path": base._display(output_root / f"values/{system_id}.csv"),
                "sha256": hashlib.sha256(csv_body).hexdigest(),
                "size_bytes": len(csv_body),
            },
            "prior_observation_support_end_utc": base._iso(START),
            "prior_observation_m3s": None if prior is None else float(prior),
            "prior_observation_complete": prior is not None,
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

    with _v2_context():
        base._verify_sealed_predictions(protocol_body, rollout)
    report = {
        "schema": SCHEMA,
        "status": "two_system_outcomes_acquired_after_joint_seal",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "start_inclusive": base._iso(START),
            "end_exclusive": base._iso(END),
            "hour_count": HOUR_COUNT,
        },
        "sealed_artifacts": {
            "protocol": base._artifact(protocol_path, protocol_body),
            "rollout_report": base._artifact(rollout_path, rollout_body),
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
        "acquisition_recovery": {
            "initial_frozen_attempt_failed_after_first_outcome_response": True,
            "initial_error": (
                "kinematic_holdout_center_hill_persistence_prior_missing"
            ),
            "initial_attempt_wrote_outcome_artifacts": False,
            "recovery_decision": base._artifact(
                RECOVERY_ADR, RECOVERY_ADR.read_bytes()
            ),
            "recovery_code_frozen_before_first_outcome_access": False,
            "protocol_missingness_policy_changed": False,
            "outcome_values_imputed": False,
            "prediction_or_score_gate_changed": False,
            "pristine_frozen_code_confirmatory_process": False,
        },
        "claim_boundary": {
            "outcomes_acquired": True,
            "outcome_values_imputed": False,
            "predictions_scored": False,
            "operator_form_admitted": False,
            "strict_end_to_end_protocol_conformance": False,
            "predictive_validation_complete": False,
            "geospatial_kernel_validated": False,
        },
    }
    return raw_bodies, csv_bodies, report


def main() -> int:
    args = parse_args()
    if args.output.exists() or args.report.exists():
        raise ValueError("kinematic_holdout_v2_recovery_refuses_overwrite")
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("kinematic_holdout_v2_positive_recovery_limits_required")
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
    base._write_json(args.report, report)
    print(args.report)
    for system_id in SYSTEM_IDS:
        system = report["systems"][system_id]
        print(
            f"{system_id}_complete_target_hours="
            f"{system['quality']['target_complete_hour_count']}"
        )
        print(
            f"{system_id}_prior_complete="
            f"{system['prior_observation_complete']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
