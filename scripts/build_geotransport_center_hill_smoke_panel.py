#!/usr/bin/env python3
"""Compile and audit the bounded Center Hill GeoTransport-H smoke panel."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    DEFAULT_REGISTRY_PATH,
    TemporalSupport,
    load_public_data_registry,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ACQUISITION_MANIFEST = (
    REPO_ROOT / "data/geotransport_v0_1/acquisition_manifest.json"
)
DEFAULT_NWM_MANIFEST = (
    REPO_ROOT / "data/geotransport_v0_1/nwm_q_lateral/extraction_manifest.json"
)
DEFAULT_PANEL = (
    REPO_ROOT / "data/geotransport_v0_1/panels/center_hill_20220101.csv"
)
DEFAULT_REPORT = (
    REPO_ROOT / "benchmarks/geotransport_v0_1/center_hill_smoke_panel_report.json"
)
DEFAULT_TRAVEL_PRIOR_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_travel_time_prior_report.json"
)
PANEL_REPORT_SCHEMA = "gwm.geotransport.center_hill_smoke_panel.v2"
M3_PER_FT3 = 0.028316846592
CWMS_TIME_PROVENANCE = (
    "USACE/cwms-data-api@beb8d507c9da8ec074d444117bda7d7daf69e5ee:"
    "docs/source/data/timeseries.rst#L97-L118"
)


@dataclass(frozen=True)
class CompiledPanel:
    csv_body: bytes
    report: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument(
        "--acquisition-manifest", type=Path, default=DEFAULT_ACQUISITION_MANIFEST
    )
    parser.add_argument("--nwm-manifest", type=Path, default=DEFAULT_NWM_MANIFEST)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--travel-prior-report", type=Path, default=DEFAULT_TRAVEL_PRIOR_REPORT
    )
    return parser.parse_args()


def compile_panel(
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    acquisition_manifest_path: Path = DEFAULT_ACQUISITION_MANIFEST,
    nwm_manifest_path: Path = DEFAULT_NWM_MANIFEST,
    panel_path: Path = DEFAULT_PANEL,
    travel_prior_report_path: Path = DEFAULT_TRAVEL_PRIOR_REPORT,
) -> CompiledPanel:
    registry = load_public_data_registry(registry_path)
    system = next(
        system
        for system in registry.payload["systems"]
        if system["system_id"] == "center_hill"
    )
    acquisition_body = acquisition_manifest_path.read_bytes()
    acquisition = json.loads(acquisition_body)
    nwm_body = nwm_manifest_path.read_bytes()
    nwm = json.loads(nwm_body)
    start = _parse_utc("2022-01-01T00:00:00Z")
    end = _parse_utc("2022-01-02T00:00:00Z")
    travel_prior_body = travel_prior_report_path.read_bytes()
    travel_prior = json.loads(travel_prior_body)
    _validate_travel_prior(travel_prior, registry=registry)
    report_parent_hash = travel_prior["input_registry_sha256"]
    _validate_manifests(
        registry,
        acquisition,
        nwm,
        nwm_manifest_body=nwm_body,
        nwm_manifest_path=nwm_manifest_path,
        start=start,
        end=end,
    )

    raw_by_role: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for descriptor in acquisition.get("artifacts") or []:
        payload, artifact = _read_json_artifact(descriptor)
        raw_by_role[descriptor["variable_role"]] = (payload, artifact)
    required_roles = {
        "boundary_action",
        "stock",
        "context_not_independent_forcing",
        "independent_observation",
    }
    if set(raw_by_role) != required_roles:
        raise ValueError("center_hill_companion_role_set_mismatch")

    action_field = system["action"]
    stock_field = next(field for field in system["state_context"] if field["role"] == "stock")
    inflow_field = next(
        field
        for field in system["state_context"]
        if field["role"] == "context_not_independent_forcing"
    )
    action_support = _cwms_temporal_support(action_field, expected_type="Ave")
    storage_support = _cwms_temporal_support(stock_field, expected_type="Inst")
    inflow_support = _cwms_temporal_support(inflow_field, expected_type="Ave")
    outcome_support = TemporalSupport(
        kind="interval_sample_mean",
        duration_seconds=3600.0,
        timestamp_position="end",
        provenance_id="USGS:03424860:00060:IV:two-approved-samples-in-open-left-closed-right-hour",
        evidence_level="derived",
    )
    nwm_support = TemporalSupport(
        kind="instantaneous",
        duration_seconds=0.0,
        timestamp_position="instant",
        provenance_id="NOAA:NWM-v3-retrospective:valid-output-time",
        evidence_level="derived",
    )
    support_starts = tuple(start + timedelta(hours=index) for index in range(24))
    support_ends = tuple(timestamp + timedelta(hours=1) for timestamp in support_starts)
    action, action_quality = _parse_cwms_hourly(
        raw_by_role["boundary_action"][0],
        field=action_field,
        expected_timestamps=support_ends,
    )
    storage_all, storage_quality_all = _parse_cwms_hourly(
        raw_by_role["stock"][0],
        field=stock_field,
        expected_timestamps=support_starts + (support_ends[-1],),
    )
    inflow, inflow_quality = _parse_cwms_hourly(
        raw_by_role["context_not_independent_forcing"][0],
        field=inflow_field,
        expected_timestamps=support_ends,
    )
    outcome, outcome_qualifiers, outcome_counts = _parse_usgs_hourly_mean(
        raw_by_role["independent_observation"][0],
        system=system,
        support_starts=support_starts,
        support_ends=support_ends,
    )
    linear_path = travel_prior["linear_referenced_path"]
    effective_lengths = tuple(float(value) for value in linear_path["effective_lengths_m"])
    nwm_values, nwm_artifact = _parse_nwm_path_sum(
        nwm,
        system=system,
        start=start,
        end=end,
        included_feature_ids=tuple(
            feature_id
            for feature_id, length in zip(
                system["forcing"]["feature_ids"], effective_lengths, strict=True
            )
            if length > 1e-6
        ),
    )

    if (
        tuple(action) != support_ends
        or tuple(inflow) != support_ends
        or tuple(outcome) != support_ends
        or tuple(nwm_values) != support_starts
    ):
        raise ValueError("center_hill_panel_channel_axis_mismatch")
    rows: list[dict[str, Any]] = []
    for support_start, support_end in zip(support_starts, support_ends, strict=True):
        rows.append(
            {
                "support_start_utc": _iso(support_start),
                "support_end_utc": _iso(support_end),
                "action_timestamp_utc": _iso(support_end),
                "nwm_valid_time_utc": _iso(support_start),
                "action_release_m3s": action[support_end],
                "storage_start_m3": storage_all[support_start],
                "storage_end_m3": storage_all[support_end],
                "storage_change_m3": (
                    storage_all[support_end] - storage_all[support_start]
                ),
                "inflow_context_m3s": inflow[support_end],
                "nwm_q_lateral_full_reach_overlap_sum_m3s": nwm_values[support_start],
                "outcome_discharge_interval_sample_mean_m3s": outcome[support_end],
                "outcome_half_hour_sample_count": outcome_counts[support_end],
                "cwms_action_quality_code": action_quality[support_end],
                "cwms_storage_start_quality_code": storage_quality_all[support_start],
                "cwms_storage_end_quality_code": storage_quality_all[support_end],
                "cwms_inflow_quality_code": inflow_quality[support_end],
                "usgs_qualifier": outcome_qualifiers[support_end],
            }
        )
    csv_body = _encode_csv(rows)
    report = {
        "schema": PANEL_REPORT_SCHEMA,
        "status": "compiled_not_admitted",
        "registry_sha256": report_parent_hash,
        "source_manifests": {
            "companion_values": _local_artifact(
                acquisition_manifest_path, acquisition_body
            ),
            "nwm_q_lateral": _local_artifact(nwm_manifest_path, nwm_body),
            "travel_time_prior": _local_artifact(
                travel_prior_report_path, travel_prior_body
            ),
        },
        "source_artifacts": {
            role: artifact for role, (_, artifact) in raw_by_role.items()
        }
        | {"nwm_selected_values": nwm_artifact},
        "window": {
            "start_inclusive": _iso(start),
            "end_exclusive": _iso(end),
            "row_count": len(rows),
            "time_step": "PT1H",
            "row_support": "[support_start_utc,support_end_utc]",
            "row_label": "support_end_utc",
        },
        "panel_artifact": {
            "path": _display(panel_path),
            "sha256": hashlib.sha256(csv_body).hexdigest(),
            "size_bytes": len(csv_body),
        },
        "channel_semantics": {
            "action_release_m3s": "CWMS EOP hourly average boundary action over the row support",
            "storage_start_m3": "CWMS instantaneous stock at support start",
            "storage_end_m3": "CWMS instantaneous stock at support end",
            "storage_change_m3": "support-end stock minus support-start stock",
            "inflow_context_m3s": "CWMS EOP hourly average context; not independent forcing",
            "nwm_q_lateral_full_reach_overlap_sum_m3s": (
                "modeled point value at support start summed over 26 reaches with nonzero "
                "linear-reference overlap; final partial reach remains a full-reach approximation"
            ),
            "outcome_discharge_interval_sample_mean_m3s": (
                "mean of two approved USGS IV point samples in (support_start,support_end]"
            ),
        },
        "temporal_supports": {
            "action_release_m3s": action_support.as_dict(),
            "storage_start_m3": storage_support.as_dict(),
            "storage_end_m3": storage_support.as_dict(),
            "inflow_context_m3s": inflow_support.as_dict(),
            "nwm_q_lateral_full_reach_overlap_sum_m3s": nwm_support.as_dict(),
            "outcome_discharge_interval_sample_mean_m3s": outcome_support.as_dict(),
        },
        "spatial_support": {
            "path_id": linear_path["path_id"],
            "full_reach_feature_count": len(linear_path["feature_ids"]),
            "nonzero_overlap_feature_count": sum(
                length > 1e-6 for length in effective_lengths
            ),
            "full_reach_path_length_m": sum(linear_path["full_lengths_m"]),
            "linear_referenced_path_length_m": linear_path["total_effective_length_m"],
            "zero_overlap_action_reach_excluded": True,
            "partial_gauge_reach_included_as_full_reach_for_q_lateral": True,
        },
        "quality_summary": {
            "cwms_action_quality_codes": sorted(set(action_quality.values())),
            "cwms_storage_quality_codes": sorted(set(storage_quality_all.values())),
            "cwms_inflow_quality_codes": sorted(set(inflow_quality.values())),
            "usgs_qualifiers": sorted(set(outcome_qualifiers.values())),
            "usgs_all_samples_approved": set(outcome_qualifiers.values()) == {"A"},
            "missing_panel_value_count": 0,
        },
        "value_summary": {
            key: _summary([float(row[key]) for row in rows])
            for key in (
                "action_release_m3s",
                "storage_start_m3",
                "storage_end_m3",
                "storage_change_m3",
                "inflow_context_m3s",
                "nwm_q_lateral_full_reach_overlap_sum_m3s",
                "outcome_discharge_interval_sample_mean_m3s",
            )
        },
        "checks": {
            "current_registry_and_manifest_lineage_verified": True,
            "four_companion_artifact_hashes_verified": True,
            "nwm_selected_value_hash_verified": True,
            "cwms_eop_labels_mapped_to_preceding_hour_support": True,
            "all_interval_channels_cover_same_24_utc_supports": True,
            "nwm_valid_time_kept_distinct_from_interval_end_label": True,
            "usgs_half_hour_samples_aggregated_open_left_closed_right": True,
            "linear_referenced_zero_overlap_action_reach_excluded": True,
            "native_units_explicitly_normalized_to_si": True,
            "source_quality_fields_preserved": True,
            "missing_panel_value_count_is_zero": True,
        },
        "claim_boundary": {
            "bounded_multisource_smoke_panel_compiled": True,
            "cwms_interval_timestamp_semantics_admitted": True,
            "linear_referenced_path_compiled": True,
            "bounded_nwm_velocity_prior_compiled": True,
            "nwm_q_lateral_partial_gauge_reach_resolved": False,
            "flood_wave_travel_time_admitted": False,
            "travel_time_or_lag_calibrated": False,
            "training_or_evaluation_panel_ready": False,
            "benchmark_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    return CompiledPanel(csv_body=csv_body, report=report)


def _validate_manifests(
    registry: Any,
    acquisition: Mapping[str, Any],
    nwm: Mapping[str, Any],
    *,
    nwm_manifest_body: bytes,
    nwm_manifest_path: Path,
    start: datetime,
    end: datetime,
) -> None:
    if (
        acquisition.get("schema") != "gwm.geotransport.acquisition_manifest.v1"
        or acquisition.get("mode") != "values"
        or acquisition.get("request_count") != 4
        or acquisition.get("artifact_count") != 4
    ):
        raise ValueError("center_hill_acquisition_manifest_invalid")
    panel_evidence = registry.payload.get("center_hill_smoke_panel_evidence") or {}
    admitted_registry_hashes = {
        registry.sha256,
        panel_evidence.get("parent_registry_sha256"),
        panel_evidence.get("acquisition_registry_sha256"),
    }
    if acquisition.get("registry_sha256") not in admitted_registry_hashes:
        raise ValueError("center_hill_acquisition_registry_lineage_mismatch")
    if acquisition.get("selected_systems") != ["center_hill"]:
        raise ValueError("center_hill_only_acquisition_required")
    acquisition_claim = acquisition.get("claim_boundary") or {}
    if (
        acquisition_claim.get("time_series_acquired") is not True
        or acquisition_claim.get("source_values_are_provisional") is not True
        or acquisition_claim.get("benchmark_validated") is not False
    ):
        raise ValueError("center_hill_acquisition_claim_boundary_invalid")
    if (
        nwm.get("schema") != "gwm.geotransport.nwm_q_lateral_extract.v1"
        or nwm.get("mode") != "values"
        or _parse_utc(nwm["start_inclusive"]) != start
        or _parse_utc(nwm["end_exclusive"]) != end
    ):
        raise ValueError("center_hill_nwm_manifest_invalid")
    nwm_descriptor = acquisition.get("nwm_extraction_manifest") or {}
    if (
        nwm_descriptor.get("path") != _display(nwm_manifest_path)
        or nwm_descriptor.get("sha256")
        != hashlib.sha256(nwm_manifest_body).hexdigest()
        or nwm_descriptor.get("size_bytes") != len(nwm_manifest_body)
    ):
        raise ValueError("center_hill_nwm_manifest_dependency_mismatch")


def _parse_cwms_hourly(
    payload: Mapping[str, Any],
    *,
    field: Mapping[str, Any],
    expected_timestamps: tuple[datetime, ...],
) -> tuple[dict[datetime, float], dict[datetime, int]]:
    if (
        payload.get("name") != field["series_id"]
        or payload.get("office-id") != field["office"]
        or payload.get("units") != field["native_unit"]
        or payload.get("interval") != "PT1H"
    ):
        raise ValueError(f"cwms_value_semantics_mismatch:{field['series_id']}")
    values: dict[datetime, float] = {}
    quality: dict[datetime, int] = {}
    for row in payload.get("values") or []:
        if not isinstance(row, list) or len(row) < 3:
            raise ValueError("cwms_value_row_invalid")
        timestamp = datetime.fromtimestamp(row[0] / 1000.0, tz=timezone.utc)
        if timestamp in expected_timestamps:
            if row[1] is None:
                raise ValueError("cwms_value_missing")
            values[timestamp] = float(row[1])
            quality[timestamp] = int(row[2])
    if tuple(values) != expected_timestamps:
        raise ValueError(f"cwms_hourly_axis_mismatch:{field['series_id']}")
    return values, quality


def _parse_usgs_hourly_mean(
    payload: Mapping[str, Any],
    *,
    system: Mapping[str, Any],
    support_starts: tuple[datetime, ...],
    support_ends: tuple[datetime, ...],
) -> tuple[dict[datetime, float], dict[datetime, str], dict[datetime, int]]:
    series = (payload.get("value") or {}).get("timeSeries") or []
    if len(series) != 1:
        raise ValueError("usgs_single_time_series_required")
    row = series[0]
    source = row.get("sourceInfo") or {}
    variable = row.get("variable") or {}
    site_codes = {item.get("value") for item in source.get("siteCode") or []}
    variable_codes = {item.get("value") for item in variable.get("variableCode") or []}
    if (
        system["outcome"]["site_id"] not in site_codes
        or system["outcome"]["parameter_code"] not in variable_codes
        or (variable.get("unit") or {}).get("unitCode") != "ft3/s"
    ):
        raise ValueError("usgs_outcome_identity_or_unit_mismatch")
    samples_by_hour: dict[datetime, list[float]] = {}
    qualifiers_by_hour: dict[datetime, set[str]] = {}
    value_groups = row.get("values") or []
    if len(value_groups) != 1:
        raise ValueError("usgs_single_value_group_required")
    for sample in value_groups[0].get("value") or []:
        timestamp = _parse_utc(sample["dateTime"])
        if not support_starts[0] < timestamp <= support_ends[-1]:
            continue
        if timestamp.minute not in {0, 30} or timestamp.second != 0:
            raise ValueError("usgs_unexpected_sample_interval")
        value = float(sample["value"])
        if value == float(variable.get("noDataValue")):
            raise ValueError("usgs_outcome_missing_value")
        support_end = timestamp.replace(minute=0, second=0, microsecond=0)
        if timestamp.minute == 30:
            support_end += timedelta(hours=1)
        samples_by_hour.setdefault(support_end, []).append(value * M3_PER_FT3)
        qualifiers_by_hour.setdefault(support_end, set()).update(
            sample.get("qualifiers") or []
        )
    if tuple(samples_by_hour) != support_ends or any(
        len(samples_by_hour[timestamp]) != 2 for timestamp in support_ends
    ):
        raise ValueError("usgs_target_window_half_hour_coverage_mismatch")
    if any(qualifiers_by_hour[timestamp] != {"A"} for timestamp in support_ends):
        raise ValueError("usgs_target_window_samples_not_all_approved")
    means = {
        timestamp: float(np.mean(samples_by_hour[timestamp]))
        for timestamp in support_ends
    }
    qualifiers = {timestamp: "A" for timestamp in support_ends}
    counts = {
        timestamp: len(samples_by_hour[timestamp]) for timestamp in support_ends
    }
    return means, qualifiers, counts


def _parse_nwm_path_sum(
    manifest: Mapping[str, Any],
    *,
    system: Mapping[str, Any],
    start: datetime,
    end: datetime,
    included_feature_ids: tuple[int, ...],
) -> tuple[dict[datetime, float], dict[str, Any]]:
    descriptors = manifest.get("value_artifacts") or []
    if len(descriptors) != 1:
        raise ValueError("nwm_selected_value_artifact_required")
    descriptor = descriptors[0]
    body, artifact = _read_artifact(descriptor)
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    expected_ids = tuple(system["forcing"]["feature_ids"])
    values_by_time: dict[datetime, list[tuple[int, float]]] = {}
    for row in reader:
        timestamp = _parse_utc(row["timestamp_utc"])
        if not start <= timestamp < end:
            raise ValueError("nwm_selected_value_outside_target_window")
        if row["source_role"] != "modeled_forcing" or row["q_lateral_m3s"] == "":
            raise ValueError("nwm_selected_value_semantics_or_fill_invalid")
        values_by_time.setdefault(timestamp, []).append(
            (int(row["feature_id"]), float(row["q_lateral_m3s"]))
        )
    expected_times = tuple(start + timedelta(hours=index) for index in range(24))
    if tuple(values_by_time) != expected_times or any(
        tuple(feature_id for feature_id, _ in values_by_time[timestamp]) != expected_ids
        for timestamp in expected_times
    ):
        raise ValueError("nwm_selected_value_axis_mismatch")
    return (
        {
            timestamp: float(
                sum(
                    value
                    for feature_id, value in values_by_time[timestamp]
                    if feature_id in included_feature_ids
                )
            )
            for timestamp in expected_times
        },
        artifact,
    )


def _cwms_temporal_support(
    field: Mapping[str, Any], *, expected_type: str
) -> TemporalSupport:
    parts = str(field["series_id"]).split(".")
    if len(parts) != 6 or parts[2] != expected_type or parts[3] != "1Hour":
        raise ValueError(f"unsupported_cwms_temporal_tsid:{field['series_id']}")
    if expected_type == "Inst":
        if parts[4] != "0":
            raise ValueError("cwms_instantaneous_duration_must_be_zero")
        return TemporalSupport(
            kind="instantaneous",
            duration_seconds=0.0,
            timestamp_position="instant",
            provenance_id=CWMS_TIME_PROVENANCE,
            evidence_level="authoritative",
        )
    if parts[4] != "1Hour":
        raise ValueError("cwms_hourly_average_duration_must_be_1Hour_eop")
    return TemporalSupport(
        kind="interval_mean",
        duration_seconds=3600.0,
        timestamp_position="end",
        provenance_id=CWMS_TIME_PROVENANCE,
        evidence_level="authoritative",
    )


def _validate_travel_prior(
    payload: Mapping[str, Any], *, registry: Any
) -> None:
    if (
        payload.get("schema") != "gwm.geotransport.center_hill_travel_time_prior.v1"
        or payload.get("status") != "candidate_advective_prior_not_flood_wave_lag"
    ):
        raise ValueError("center_hill_travel_time_prior_report_invalid")
    parent = payload.get("input_registry_sha256")
    evidence = registry.payload.get("center_hill_travel_time_prior_evidence") or {}
    if parent not in {registry.sha256, evidence.get("parent_registry_sha256")}:
        raise ValueError("center_hill_travel_time_prior_registry_lineage_mismatch")
    claim = payload.get("claim_boundary") or {}
    if (
        claim.get("cwms_interval_timestamp_semantics_admitted") is not True
        or claim.get("linear_referenced_path_compiled") is not True
        or claim.get("bounded_nwm_velocity_prior_compiled") is not True
        or claim.get("flood_wave_travel_time_admitted") is not False
        or claim.get("travel_time_or_lag_calibrated") is not False
        or claim.get("training_or_evaluation_panel_ready") is not False
    ):
        raise ValueError("center_hill_travel_time_prior_claim_boundary_invalid")


def _encode_csv(rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: format(value, ".12g") if isinstance(value, float) else value
                for key, value in row.items()
            }
        )
    return output.getvalue().encode("utf-8")


def _summary(values: list[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "minimum": float(array.min()),
        "maximum": float(array.max()),
        "mean": float(array.mean()),
    }


def _read_json_artifact(
    descriptor: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    body, artifact = _read_artifact(descriptor)
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("center_hill_json_artifact_object_required")
    return payload, artifact


def _read_artifact(
    descriptor: Mapping[str, Any]
) -> tuple[bytes, dict[str, Any]]:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("center_hill_artifact_outside_repository") from exc
    body = path.read_bytes()
    sha256 = hashlib.sha256(body).hexdigest()
    if sha256 != descriptor.get("sha256") or len(body) != descriptor.get("size_bytes"):
        raise ValueError(f"center_hill_artifact_identity_mismatch:{descriptor.get('path')}")
    return body, {
        "path": _display(path),
        "sha256": sha256,
        "size_bytes": len(body),
        "source": descriptor.get("source"),
        "source_url": descriptor.get("url"),
        "retrieved_at": descriptor.get("retrieved_at"),
    }


def _local_artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone_aware_timestamp_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def main() -> int:
    args = parse_args()
    compiled = compile_panel(
        registry_path=args.registry,
        acquisition_manifest_path=args.acquisition_manifest,
        nwm_manifest_path=args.nwm_manifest,
        panel_path=args.panel,
        travel_prior_report_path=args.travel_prior_report,
    )
    args.panel.parent.mkdir(parents=True, exist_ok=True)
    args.panel.write_bytes(compiled.csv_body)
    report = dict(compiled.report)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
