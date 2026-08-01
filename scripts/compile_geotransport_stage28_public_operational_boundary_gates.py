#!/usr/bin/env python3
"""Compile Stage 28 public operational-boundary evidence gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    public_operational_boundary_evidence as evidence,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "stage28_center_hill_operational_boundary_evidence"
)
DEFAULT_LEDGER_OUTPUT = DEFAULT_DATA_ROOT / (
    "operational_boundary_evidence_ledger.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage28_public_operational_boundary_gates.json"
)
SCHEMA = "gwm.geotransport.stage28_public_operational_boundary_gates.v1"

FROZEN_STAGE27_HASHES = {
    (
        "scripts/"
        "acquire_geotransport_stage27_public_spatial_boundary_evidence.py"
    ): "e9b549ebac145ab774357bec74ef5387021a47e4e9643815c32e6b6e8d3d7589",
    (
        "data_agent/"
        "test_acquire_geotransport_stage27_public_spatial_boundary_evidence.py"
    ): "ad43e30d95bb443aa403ee8feab1bb117d708b2e979f4af690e59f864ea7a56f",
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "public_spatial_boundary_evidence.py"
    ): "4bec90e7a8420cdccd79e4a972ba0c5fe0ab8f2b8b9106cfe4e48835cddb41c5",
    (
        "data_agent/"
        "test_geospatial_kernel_public_spatial_boundary_evidence.py"
    ): "562dfece893f24abb6dea07e654a1b11ac03efc23f09e4b1d6e4dce6879261c5",
    (
        "scripts/compile_geotransport_stage27_public_spatial_boundary_gates.py"
    ): "0c5e3611a49a1efd199c854751e918fdd377f212fbfdf6e30e0297f53268b532",
    (
        "data/geotransport_v0_1/"
        "stage27_center_hill_spatial_boundary_evidence/"
        "spatial_boundary_evidence_ledger.json"
    ): "d98fd049669181e698d0cfbf72c867c7bc3c7fac8cb857e43a9b719433a66db0",
    (
        "benchmarks/geotransport_v0_1/"
        "stage27_public_spatial_boundary_gates.json"
    ): "b4600f27e406849b8b07f20441bafe3e03728085d2f8a72e5ac8038ba138de47",
    (
        "docs/architecture-decisions/"
        "adr-068-public-spatial-boundary-evidence-ledger.md"
    ): "f25c003baf6bb795abbbc5217643bb040a713c56fcdfbd377879f8cc2ffd884e",
    (
        "data/geotransport_v0_1/"
        "stage27_center_hill_spatial_boundary_evidence/README.md"
    ): "de4a25c33123453f2d8fe3893e474012fa2c1e42c69880ccc53dcf502453a3c4",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger-output", type=Path, default=DEFAULT_LEDGER_OUTPUT
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ledger = evidence.compile_public_operational_boundary_evidence()
    artifact = _write_artifact(args.ledger_output, ledger.as_dict())
    report = compile_report(ledger=ledger, ledger_artifact=artifact)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_json_bytes(report))
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    return 0 if report["all_gates_passed"] else 1


def compile_report(
    *, ledger=None, ledger_artifact: dict[str, object] | None = None
) -> dict[str, Any]:
    if ledger is None:
        ledger = evidence.compile_public_operational_boundary_evidence()
    ledger_dict = ledger.as_dict()
    if ledger_artifact is None:
        ledger_artifact = _memory_artifact(
            DEFAULT_LEDGER_OUTPUT, ledger_dict
        )
    frozen_stage27 = _frozen_hash_report(FROZEN_STAGE27_HASHES)
    development = ledger.development_event
    transfer = ledger.transfer_event
    selected = development.lag_diagnostics[
        int(development.selected_lag_hours)
    ]
    refusals = _refusal_control(ledger)
    gates = {
        "stage27_artifacts_hash_frozen": all(
            value["matches"] for value in frozen_stage27.values()
        ),
        "acquisition_is_public_bounded_and_private_free": (
            ledger.request_boundary["workspace_or_private_data_sent"] is False
            and len(ledger.source_artifacts)
            <= ledger.request_boundary["maximum_request_count"]
            and sum(
                int(value["size_bytes"]) for value in ledger.source_artifacts
            )
            <= ledger.request_boundary["maximum_total_download_bytes"]
        ),
        "six_source_artifacts_are_hash_verified": (
            len(ledger.source_artifacts) == 6
            and all(
                len(str(value["sha256"])) == 64
                and value["hash_verified"] is True
                for value in ledger.source_artifacts
            )
        ),
        "lag_candidates_were_frozen_before_value_access": (
            ledger.acquisition_plan["sha256"]
            == "335cf57dad76c469e1f8e78cf9e93ccba2a606c38258cd69b45153f5ebc4d0bb"
            and ledger_dict["diagnostic_summary"]["lag_candidates_hours"]
            == list(range(13))
        ),
        "cwms_fixed_ip_fallback_retained_tls_verification": all(
            value["tls_hostname_verification_retained"] is True
            for value in ledger.source_artifacts
        ),
        "tailwater_location_is_bound_to_stage27_upstream_site_zone": (
            ledger.location_binding.cwms_location_id
            == evidence.CWMS_LOCATION_ID
            and ledger.location_binding.upstream_monitoring_location_id
            == evidence.UPSTREAM_SITE_ID
            and ledger.location_binding.within_upstream_site_zone
            and ledger.location_binding.coordinate_distance_m
            < ledger.location_binding.zone_radius_m
        ),
        "site_zone_binding_does_not_claim_sensor_identity": (
            ledger.location_binding.as_dict()[
                "same_sensor_or_measurement_process_admitted"
            ]
            is False
        ),
        "exact_cwms_release_catalog_and_aliases_are_bound": (
            ledger.series_catalog.name == evidence.CWMS_SERIES_ID
            and ledger.series_catalog.office == evidence.CWMS_OFFICE
            and ledger.series_catalog.units == "cms"
            and ledger.series_catalog.interval == "1Hour"
            and ledger.series_catalog.interval_offset_minutes == 0
            and ledger.series_catalog.as_dict()["outflow_alias_present"]
            is True
            and ledger.series_catalog.as_dict()["total_flow_alias_present"]
            is True
        ),
        "hour_average_end_support_semantics_are_preserved": (
            ledger.series_catalog.as_dict()["support_semantics"]
            == "one_hour_average_with_timestamp_at_support_end"
        ),
        "two_seventy_two_hour_release_windows_are_admitted": all(
            value.raw_release_value_count == 73
            and len(value.hourly_releases) == 72
            for value in ledger.events
        ),
        "usgs_half_hour_samples_are_aggregated_without_filling": all(
            value.raw_downstream_sample_count == 145
            and len(value.hourly_downstream) == 72
            and value.dropped_downstream_hour_count == 0
            and all(
                len(hour.sample_times_utc) == 2
                for hour in value.hourly_downstream
            )
            for value in ledger.events
        ),
        "all_downstream_samples_are_approved": all(
            value.downstream_fully_approved for value in ledger.events
        ),
        "cwms_quality_zero_is_preserved_not_relabelled_approved": (
            all(
                release.quality_code == 0
                for event in ledger.events
                for release in event.hourly_releases
            )
            and ledger_dict["claim_boundary"][
                "cwms_quality_code_zero_means_approved"
            ]
            is False
        ),
        "every_predeclared_lag_has_real_pairs": all(
            tuple(value.pair_count for value in event.lag_diagnostics)
            == tuple(72 - lag for lag in range(13))
            for event in ledger.events
        ),
        "development_event_has_nonzero_release_variance": (
            development.release_value_range_m3s > 0.0
            and all(
                value.release_standard_deviation_m3s > 0.0
                for value in development.lag_diagnostics
            )
        ),
        "development_six_hour_correlation_diagnostic_is_reproducible": (
            development.selected_lag_hours == 6
            and selected.pair_count == 66
            and abs(float(selected.pearson_r) - 0.9537370044069898) < 1e-12
            and abs(selected.rmse_m3s - 21.595624358061848) < 1e-12
        ),
        "transfer_zero_variance_refuses_lag_selection": (
            transfer.release_value_range_m3s == 0.0
            and transfer.selected_lag_hours is None
            and transfer.lag_selection_status
            == "release_variance_zero_lag_unidentifiable"
            and all(
                value.pearson_r is None
                for value in transfer.lag_diagnostics
            )
        ),
        "lag_stability_across_events_remains_unevaluable": (
            ledger_dict["diagnostic_summary"][
                "lag_stability_across_events_evaluable"
            ]
            is False
            and ledger_dict["diagnostic_summary"]["travel_time_identified"]
            is False
        ),
        "two_stage27_field_measurements_have_containing_release_support": (
            len(ledger.field_release_comparisons) == 2
            and all(
                value.field_approval_status == "Provisional"
                and value.release_support_start_utc
                < value.field_observation_time_utc.replace("+00:00", "Z")
                < value.release_support_end_utc
                for value in ledger.field_release_comparisons
            )
        ),
        "field_release_comparison_remains_consistency_only": all(
            value.as_dict()["comparison_role"]
            == "cross_source_consistency_diagnostic"
            and value.as_dict()["exact_sensor_crosswalk_claimed"] is False
            for value in ledger.field_release_comparisons
        ),
        "unsupported_operational_claims_fail_closed": all(
            refusals.values()
        ),
        "bounded_operational_evidence_is_admitted": (
            ledger_dict["decision"][
                "operational_boundary_evidence_admitted"
            ]
            is True
            and ledger_dict["decision"][
                "development_lag_diagnostic_admitted"
            ]
            is True
        ),
        "development_lag_is_not_relabelled_travel_time": (
            ledger_dict["decision"]["travel_time_admitted"] is False
        ),
        "observed_spatial_rollout_remains_unclaimed": (
            ledger_dict["decision"]["observed_spatial_rollout_completed"]
            is False
        ),
        "runtime_operator_remains_unadmitted": (
            ledger_dict["decision"]["runtime_operator_admitted"] is False
        ),
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "bounded_operational_boundaries_verified_"
            "transfer_lag_unidentifiable_rollout_pending"
        ),
        "ledger_artifact": ledger_artifact,
        "frozen_stage27_hashes": frozen_stage27,
        "location_binding": ledger.location_binding.as_dict(),
        "series_catalog": ledger.series_catalog.as_dict(),
        "event_summary": [
            {
                "event_id": value.event_id,
                "role": value.role,
                "release_value_range_m3s": value.release_value_range_m3s,
                "selected_lag_hours": value.selected_lag_hours,
                "lag_selection_status": value.lag_selection_status,
            }
            for value in ledger.events
        ],
        "field_release_comparisons": [
            value.as_dict() for value in ledger.field_release_comparisons
        ],
        "typed_refusals": refusals,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": ledger_dict["decision"],
        "claim_boundary": ledger_dict["claim_boundary"],
    }


def _refusal_control(ledger) -> dict[str, bool]:
    calls = {
        "exact_sensor_crosswalk": (
            ledger.require_exact_sensor_crosswalk,
            "public_operational_boundary_exact_sensor_crosswalk_unproven",
        ),
        "transfer_identified_lag": (
            ledger.require_transfer_identified_lag,
            "public_operational_boundary_transfer_release_variance_zero",
        ),
        "stable_travel_time": (
            ledger.require_stable_travel_time,
            "public_operational_boundary_two_event_travel_time_unidentified",
        ),
        "boundary_conditioned_rollout": (
            ledger.require_boundary_conditioned_rollout,
            "public_operational_boundary_diagnostic_is_not_rollout",
        ),
        "runtime_lag_operator": (
            ledger.promote_lag_to_runtime_operator,
            "public_operational_boundary_lag_operator_unadmitted",
        ),
    }
    results = {}
    for name, (call, message) in calls.items():
        try:
            call()
        except ValueError as exc:
            results[name] = str(exc) == message
        else:
            results[name] = False
    return results


def _frozen_hash_report(
    expected: dict[str, str],
) -> dict[str, dict[str, object]]:
    results = {}
    for relative, digest in expected.items():
        actual = _sha256(REPO_ROOT / relative)
        results[relative] = {
            "expected_sha256": digest,
            "actual_sha256": actual,
            "matches": digest == actual,
        }
    return results


def _write_artifact(path: Path, value: dict[str, Any]) -> dict[str, object]:
    body = _json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "size_bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _memory_artifact(path: Path, value: dict[str, Any]) -> dict[str, object]:
    body = _json_bytes(value)
    return {
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "size_bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
