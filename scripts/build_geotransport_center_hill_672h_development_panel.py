#!/usr/bin/env python3
"""Compile the bounded 672-hour Center Hill development panel without imputation."""

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
    load_public_data_registry,
)
if __package__:
    from scripts.build_geotransport_center_hill_smoke_panel import (
        M3_PER_FT3,
        _cwms_temporal_support,
        _parse_cwms_hourly,
    )
else:
    from build_geotransport_center_hill_smoke_panel import (
        M3_PER_FT3,
        _cwms_temporal_support,
        _parse_cwms_hourly,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ACQUISITION_MANIFEST = (
    REPO_ROOT
    / "data/geotransport_v0_1/center_hill_672h/acquisition_manifest.json"
)
DEFAULT_NWM_MANIFEST = (
    REPO_ROOT
    / "data/geotransport_v0_1/nwm_q_lateral_672h/extraction_manifest.json"
)
DEFAULT_TRAVEL_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_travel_time_prior_report.json"
)
DEFAULT_PANEL = (
    REPO_ROOT
    / "data/geotransport_v0_1/panels/center_hill_672h_development.csv"
)
DEFAULT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_672h_development_panel_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_672h_development_panel.v1"
START = datetime(2021, 12, 9, 1, tzinfo=timezone.utc)
END = datetime(2022, 1, 6, 1, tzinfo=timezone.utc)
HOUR_COUNT = 672
WARMUP_HOURS = 168


@dataclass(frozen=True)
class CompiledDevelopmentPanel:
    csv_body: bytes
    report: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument(
        "--acquisition-manifest", type=Path, default=DEFAULT_ACQUISITION_MANIFEST
    )
    parser.add_argument("--nwm-manifest", type=Path, default=DEFAULT_NWM_MANIFEST)
    parser.add_argument("--travel-report", type=Path, default=DEFAULT_TRAVEL_REPORT)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_panel(
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    acquisition_manifest_path: Path = DEFAULT_ACQUISITION_MANIFEST,
    nwm_manifest_path: Path = DEFAULT_NWM_MANIFEST,
    travel_report_path: Path = DEFAULT_TRAVEL_REPORT,
    panel_path: Path = DEFAULT_PANEL,
) -> CompiledDevelopmentPanel:
    registry = load_public_data_registry(registry_path)
    system = next(
        row for row in registry.payload["systems"] if row["system_id"] == "center_hill"
    )
    acquisition_body = acquisition_manifest_path.read_bytes()
    acquisition = json.loads(acquisition_body)
    nwm_body = nwm_manifest_path.read_bytes()
    nwm = json.loads(nwm_body)
    travel_body = travel_report_path.read_bytes()
    travel = json.loads(travel_body)
    _validate_manifests(
        registry_sha256=registry.sha256,
        acquisition=acquisition,
        nwm=nwm,
        nwm_body=nwm_body,
        nwm_path=nwm_manifest_path,
        travel=travel,
    )

    raw_by_role: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for descriptor in acquisition["artifacts"]:
        body = _read_verified_artifact(descriptor)
        raw_by_role[descriptor["variable_role"]] = (
            json.loads(body),
            _artifact_from_descriptor(descriptor, body),
        )
    if set(raw_by_role) != {
        "boundary_action",
        "stock",
        "context_not_independent_forcing",
        "independent_observation",
    }:
        raise ValueError("development_panel_companion_role_set_mismatch")

    support_starts = tuple(START + timedelta(hours=index) for index in range(HOUR_COUNT))
    support_ends = tuple(value + timedelta(hours=1) for value in support_starts)
    action_field = system["action"]
    stock_field = next(
        row for row in system["state_context"] if row["role"] == "stock"
    )
    inflow_field = next(
        row
        for row in system["state_context"]
        if row["role"] == "context_not_independent_forcing"
    )
    action, action_quality = _parse_cwms_hourly(
        raw_by_role["boundary_action"][0],
        field=action_field,
        expected_timestamps=support_ends,
    )
    storage, storage_quality = _parse_cwms_hourly(
        raw_by_role["stock"][0],
        field=stock_field,
        expected_timestamps=support_starts + (support_ends[-1],),
    )
    inflow, inflow_quality = _parse_cwms_hourly(
        raw_by_role["context_not_independent_forcing"][0],
        field=inflow_field,
        expected_timestamps=support_ends,
    )
    outcomes, outcome_qualifiers, outcome_counts = _parse_usgs_with_gaps(
        raw_by_role["independent_observation"][0],
        system=system,
        support_starts=support_starts,
        support_ends=support_ends,
    )

    linear_path = travel["linear_referenced_path"]
    effective_lengths = tuple(
        float(value) for value in linear_path["effective_lengths_m"]
    )
    active_ids = tuple(
        feature_id
        for feature_id, length in zip(
            system["forcing"]["feature_ids"], effective_lengths, strict=True
        )
        if length > 1e-6
    )
    q_descriptor = (nwm.get("value_artifacts") or [None])[0]
    q_body = _read_verified_artifact(q_descriptor)
    q_sum = _parse_active_reach_sum(
        q_body,
        expected_timestamps=support_starts,
        expected_feature_ids=tuple(system["forcing"]["feature_ids"]),
        active_feature_ids=active_ids,
    )
    travel_descriptor = travel["source_artifacts"]["advective_travel_time"]
    travel_time_body = _read_verified_artifact(travel_descriptor)
    residence = _parse_residence_time(
        travel_time_body,
        expected_timestamps=support_starts,
    )

    rows: list[dict[str, Any]] = []
    for index, (support_start, support_end) in enumerate(
        zip(support_starts, support_ends, strict=True)
    ):
        outcome = outcomes[support_end]
        rows.append(
            {
                "support_start_utc": _iso(support_start),
                "support_end_utc": _iso(support_end),
                "split_role": "warmup" if index < WARMUP_HOURS else "development",
                "action_timestamp_utc": _iso(support_end),
                "nwm_valid_time_utc": _iso(support_start),
                "action_release_m3s": action[support_end],
                "storage_start_m3": storage[support_start],
                "storage_end_m3": storage[support_end],
                "storage_change_m3": storage[support_end] - storage[support_start],
                "inflow_context_m3s": inflow[support_end],
                "nwm_q_lateral_active_reach_sum_m3s": q_sum[support_start],
                "nwm_velocity_proxy_residence_time_seconds": residence[support_start],
                "outcome_discharge_interval_sample_mean_m3s": outcome,
                "outcome_half_hour_sample_count": outcome_counts[support_end],
                "outcome_available": outcome is not None,
                "cwms_action_quality_code": action_quality[support_end],
                "cwms_storage_start_quality_code": storage_quality[support_start],
                "cwms_storage_end_quality_code": storage_quality[support_end],
                "cwms_inflow_quality_code": inflow_quality[support_end],
                "usgs_qualifier": outcome_qualifiers[support_end],
            }
        )
    missing_outcome_ends = [
        row["support_end_utc"] for row in rows if not row["outcome_available"]
    ]
    if any(
        row[key] is None
        for row in rows
        for key in (
            "action_release_m3s",
            "storage_start_m3",
            "storage_end_m3",
            "storage_change_m3",
            "inflow_context_m3s",
            "nwm_q_lateral_active_reach_sum_m3s",
            "nwm_velocity_proxy_residence_time_seconds",
        )
    ):
        raise ValueError("development_panel_input_channel_missing")
    csv_body = _encode_csv(rows)
    report = {
        "schema": SCHEMA,
        "status": "compiled_with_observation_gap_not_admitted",
        "registry_sha256": registry.sha256,
        "source_manifests": {
            "companion_values": _artifact(
                acquisition_manifest_path, acquisition_body
            ),
            "nwm_q_lateral_672h": _artifact(nwm_manifest_path, nwm_body),
            "travel_time_prior": _artifact(travel_report_path, travel_body),
        },
        "source_artifacts": {
            role: artifact for role, (_, artifact) in raw_by_role.items()
        }
        | {
            "nwm_q_lateral_selected_values": _artifact_from_descriptor(
                q_descriptor, q_body
            ),
            "nwm_advective_travel_time": _artifact_from_descriptor(
                travel_descriptor, travel_time_body
            ),
        },
        "window": {
            "start_inclusive": _iso(START),
            "end_exclusive": _iso(END),
            "time_step": "PT1H",
            "row_count": len(rows),
            "warmup_hours": WARMUP_HOURS,
            "development_hours": HOUR_COUNT - WARMUP_HOURS,
            "evaluation_hours": 0,
        },
        "panel_artifact": {
            "path": _display(panel_path),
            "sha256": hashlib.sha256(csv_body).hexdigest(),
            "size_bytes": len(csv_body),
        },
        "temporal_supports": {
            "action_release_m3s": _cwms_temporal_support(
                action_field, expected_type="Ave"
            ).as_dict(),
            "storage_m3": _cwms_temporal_support(
                stock_field, expected_type="Inst"
            ).as_dict(),
            "inflow_context_m3s": _cwms_temporal_support(
                inflow_field, expected_type="Ave"
            ).as_dict(),
            "outcome_discharge_interval_sample_mean_m3s": {
                "schema": "gwm.geospatial_kernel.temporal_support.v1",
                "kind": "interval_sample_mean",
                "duration_seconds": 3600.0,
                "timestamp_position": "end",
                "provenance_id": "USGS:03424860:00060:IV:open-left-closed-right-hour",
                "evidence_level": "derived",
            },
        },
        "quality_summary": {
            "input_channel_missing_value_count": 0,
            "outcome_available_hour_count": sum(
                bool(row["outcome_available"]) for row in rows
            ),
            "outcome_missing_hour_count": len(missing_outcome_ends),
            "outcome_missing_support_end_utc": missing_outcome_ends,
            "outcome_missing_sample_counts": [
                row["outcome_half_hour_sample_count"]
                for row in rows
                if not row["outcome_available"]
            ],
            "outcome_imputed_hour_count": 0,
            "usgs_all_returned_target_samples_approved": all(
                row["usgs_qualifier"] in {"", "A"} for row in rows
            ),
            "warmup_outcome_missing_hour_count": sum(
                not row["outcome_available"]
                for row in rows
                if row["split_role"] == "warmup"
            ),
            "development_outcome_missing_hour_count": sum(
                not row["outcome_available"]
                for row in rows
                if row["split_role"] == "development"
            ),
        },
        "value_summary": {
            key: _summary(
                [float(row[key]) for row in rows if row[key] is not None]
            )
            for key in (
                "action_release_m3s",
                "storage_change_m3",
                "inflow_context_m3s",
                "nwm_q_lateral_active_reach_sum_m3s",
                "nwm_velocity_proxy_residence_time_seconds",
                "outcome_discharge_interval_sample_mean_m3s",
            )
        },
        "checks": {
            "all_input_channels_cover_672_supports": True,
            "cwms_eop_semantics_preserved": True,
            "nwm_valid_time_kept_at_support_start": True,
            "first_168_hours_frozen_as_warmup": True,
            "usgs_observation_gap_preserved": True,
            "outcome_missing_values_not_imputed": True,
            "source_artifact_hashes_verified": True,
        },
        "claim_boundary": {
            "bounded_672h_development_panel_compiled": True,
            "input_channels_complete": True,
            "outcome_channel_complete": False,
            "warmup_window_frozen": True,
            "outcome_values_imputed": False,
            "training_or_evaluation_panel_ready": False,
            "benchmark_validated": False,
            "flood_wave_transport_admitted": False,
            "geospatial_kernel_validated": False,
        },
    }
    return CompiledDevelopmentPanel(csv_body=csv_body, report=report)


def _validate_manifests(
    *,
    registry_sha256: str,
    acquisition: Mapping[str, Any],
    nwm: Mapping[str, Any],
    nwm_body: bytes,
    nwm_path: Path,
    travel: Mapping[str, Any],
) -> None:
    if (
        acquisition.get("schema") != "gwm.geotransport.acquisition_manifest.v1"
        or acquisition.get("mode") != "values"
        or acquisition.get("registry_sha256") != registry_sha256
        or acquisition.get("request_count") != 4
        or acquisition.get("artifact_count") != 4
    ):
        raise ValueError("development_panel_acquisition_manifest_invalid")
    descriptor = acquisition.get("nwm_extraction_manifest") or {}
    if (
        descriptor.get("path") != _display(nwm_path)
        or descriptor.get("sha256") != hashlib.sha256(nwm_body).hexdigest()
        or descriptor.get("size_bytes") != len(nwm_body)
    ):
        raise ValueError("development_panel_nwm_dependency_mismatch")
    if (
        nwm.get("schema") != "gwm.geotransport.nwm_q_lateral_extract.v1"
        or nwm.get("mode") != "values"
        or nwm.get("registry_sha256") != registry_sha256
        or _parse_utc(nwm["start_inclusive"]) != START
        or _parse_utc(nwm["end_exclusive"]) != END
        or (nwm.get("results") or [{}])[0].get("time_count") != HOUR_COUNT
        or (nwm.get("results") or [{}])[0].get("fill_value_count") != 0
        or (nwm.get("claim_boundary") or {}).get(
            "raw_chunks_reused_without_download"
        )
        is not True
    ):
        raise ValueError("development_panel_nwm_manifest_invalid")
    if (
        travel.get("schema")
        != "gwm.geotransport.center_hill_travel_time_prior.v1"
        or (travel.get("velocity_window") or {}).get("time_count") != HOUR_COUNT
        or (travel.get("claim_boundary") or {}).get(
            "flood_wave_travel_time_admitted"
        )
        is not False
    ):
        raise ValueError("development_panel_travel_prior_invalid")


def _parse_usgs_with_gaps(
    payload: Mapping[str, Any],
    *,
    system: Mapping[str, Any],
    support_starts: tuple[datetime, ...],
    support_ends: tuple[datetime, ...],
) -> tuple[
    dict[datetime, float | None],
    dict[datetime, str],
    dict[datetime, int],
]:
    series = (payload.get("value") or {}).get("timeSeries") or []
    if len(series) != 1:
        raise ValueError("development_panel_usgs_single_series_required")
    row = series[0]
    site_codes = {
        value.get("value")
        for value in (row.get("sourceInfo") or {}).get("siteCode") or []
    }
    variable = row.get("variable") or {}
    variable_codes = {
        value.get("value") for value in variable.get("variableCode") or []
    }
    if (
        system["outcome"]["site_id"] not in site_codes
        or system["outcome"]["parameter_code"] not in variable_codes
        or (variable.get("unit") or {}).get("unitCode") != "ft3/s"
    ):
        raise ValueError("development_panel_usgs_identity_or_unit_mismatch")
    groups = row.get("values") or []
    if len(groups) != 1:
        raise ValueError("development_panel_usgs_single_value_group_required")
    samples: dict[datetime, list[float]] = {value: [] for value in support_ends}
    qualifiers: dict[datetime, set[str]] = {value: set() for value in support_ends}
    seen: set[datetime] = set()
    for sample in groups[0].get("value") or []:
        timestamp = _parse_utc(sample["dateTime"])
        if not support_starts[0] < timestamp <= support_ends[-1]:
            continue
        if timestamp in seen:
            raise ValueError("development_panel_usgs_duplicate_timestamp")
        seen.add(timestamp)
        if timestamp.minute not in {0, 30} or timestamp.second != 0:
            raise ValueError("development_panel_usgs_unexpected_sample_interval")
        support_end = timestamp.replace(minute=0, second=0, microsecond=0)
        if timestamp.minute == 30:
            support_end += timedelta(hours=1)
        samples[support_end].append(float(sample["value"]) * M3_PER_FT3)
        qualifiers[support_end].update(sample.get("qualifiers") or [])
    if any(len(values) > 2 for values in samples.values()):
        raise ValueError("development_panel_usgs_more_than_two_samples_per_hour")
    if any(values and qualifiers[key] != {"A"} for key, values in samples.items()):
        raise ValueError("development_panel_usgs_returned_sample_not_approved")
    outcomes = {
        key: float(np.mean(values)) if len(values) == 2 else None
        for key, values in samples.items()
    }
    qualifier_labels = {
        key: "A" if qualifiers[key] == {"A"} else "" for key in support_ends
    }
    counts = {key: len(samples[key]) for key in support_ends}
    return outcomes, qualifier_labels, counts


def _parse_active_reach_sum(
    body: bytes,
    *,
    expected_timestamps: tuple[datetime, ...],
    expected_feature_ids: tuple[int, ...],
    active_feature_ids: tuple[int, ...],
) -> dict[datetime, float]:
    values: dict[datetime, list[tuple[int, float]]] = {}
    for row in csv.DictReader(io.StringIO(body.decode("utf-8"))):
        timestamp = _parse_utc(row["timestamp_utc"])
        if row["source_role"] != "modeled_forcing" or row["q_lateral_m3s"] == "":
            raise ValueError("development_panel_q_lateral_semantics_invalid")
        values.setdefault(timestamp, []).append(
            (int(row["feature_id"]), float(row["q_lateral_m3s"]))
        )
    if tuple(values) != expected_timestamps or any(
        tuple(feature_id for feature_id, _ in values[timestamp])
        != expected_feature_ids
        for timestamp in expected_timestamps
    ):
        raise ValueError("development_panel_q_lateral_axis_mismatch")
    active = set(active_feature_ids)
    return {
        timestamp: float(
            sum(value for feature_id, value in values[timestamp] if feature_id in active)
        )
        for timestamp in expected_timestamps
    }


def _parse_residence_time(
    body: bytes,
    *,
    expected_timestamps: tuple[datetime, ...],
) -> dict[datetime, float]:
    values: dict[datetime, float] = {}
    for row in csv.DictReader(io.StringIO(body.decode("utf-8"))):
        timestamp = _parse_utc(row["timestamp_utc"])
        if row["valid"] != "true" or row["advective_travel_time_seconds"] == "":
            raise ValueError("development_panel_residence_time_invalid")
        values[timestamp] = float(row["advective_travel_time_seconds"])
    if tuple(values) != expected_timestamps:
        raise ValueError("development_panel_residence_time_axis_mismatch")
    return values


def _read_verified_artifact(descriptor: Mapping[str, Any] | None) -> bytes:
    if not isinstance(descriptor, Mapping):
        raise ValueError("development_panel_artifact_descriptor_required")
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("development_panel_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError(f"development_panel_artifact_identity_mismatch:{path}")
    return body


def _artifact_from_descriptor(
    descriptor: Mapping[str, Any], body: bytes
) -> dict[str, Any]:
    return {
        "path": str(descriptor["path"]),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "source": descriptor.get("source"),
        "source_url": descriptor.get("url"),
        "retrieved_at": descriptor.get("retrieved_at"),
    }


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _encode_csv(rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: (
                    ""
                    if value is None
                    else format(value, ".12g")
                    if isinstance(value, float)
                    else str(value).lower()
                    if isinstance(value, bool)
                    else value
                )
                for key, value in row.items()
            }
        )
    return output.getvalue().encode("utf-8")


def _summary(values: list[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=float)
    return {
        "minimum": float(array.min()),
        "maximum": float(array.max()),
        "mean": float(array.mean()),
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
        travel_report_path=args.travel_report,
        panel_path=args.panel,
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
