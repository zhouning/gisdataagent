#!/usr/bin/env python3
"""Compile the frozen Center Hill temporal-holdout panel without imputation."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping

from data_agent.uwm.geospatial_kernel_v2 import (
    DEFAULT_REGISTRY_PATH,
    load_public_data_registry,
)

if __package__:
    from scripts.build_geotransport_center_hill_672h_development_panel import (
        _parse_usgs_with_gaps,
    )
    from scripts.build_geotransport_center_hill_smoke_panel import (
        _cwms_temporal_support,
        _parse_cwms_hourly,
    )
else:
    from build_geotransport_center_hill_672h_development_panel import (
        _parse_usgs_with_gaps,
    )
    from build_geotransport_center_hill_smoke_panel import (
        _cwms_temporal_support,
        _parse_cwms_hourly,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_temporal_holdout_protocol_v1.json"
)
DEFAULT_COMPANION_MANIFEST = (
    REPO_ROOT
    / "data/geotransport_v0_1/center_hill_evaluation/companion/acquisition_manifest.json"
)
DEFAULT_NWM_MANIFEST = (
    REPO_ROOT
    / "data/geotransport_v0_1/center_hill_evaluation/nwm/acquisition_manifest.json"
)
DEFAULT_TRAVEL_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_travel_time_prior_report.json"
)
DEFAULT_PANEL = (
    REPO_ROOT
    / "data/geotransport_v0_1/center_hill_evaluation/panel/center_hill_temporal_holdout.csv"
)
DEFAULT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_temporal_holdout_panel_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_temporal_holdout_panel.v1"
START = datetime(2022, 1, 6, 1, tzinfo=timezone.utc)
SCORED_START = datetime(2022, 1, 13, 1, tzinfo=timezone.utc)
END = datetime(2022, 2, 3, 1, tzinfo=timezone.utc)
HOUR_COUNT = 672
WARMUP_HOURS = 168


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument(
        "--companion-manifest", type=Path, default=DEFAULT_COMPANION_MANIFEST
    )
    parser.add_argument("--nwm-manifest", type=Path, default=DEFAULT_NWM_MANIFEST)
    parser.add_argument("--travel-report", type=Path, default=DEFAULT_TRAVEL_REPORT)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_panel(
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    protocol_path: Path = DEFAULT_PROTOCOL,
    companion_manifest_path: Path = DEFAULT_COMPANION_MANIFEST,
    nwm_manifest_path: Path = DEFAULT_NWM_MANIFEST,
    travel_report_path: Path = DEFAULT_TRAVEL_REPORT,
    panel_path: Path = DEFAULT_PANEL,
) -> tuple[bytes, dict[str, Any]]:
    registry = load_public_data_registry(registry_path)
    system = next(
        row for row in registry.payload["systems"] if row["system_id"] == "center_hill"
    )
    protocol_body, protocol = _load_json(protocol_path)
    companion_body, companion = _load_json(companion_manifest_path)
    nwm_body, nwm = _load_json(nwm_manifest_path)
    travel_body, travel = _load_json(travel_report_path)
    _validate_manifests(
        registry_sha256=registry.sha256,
        protocol=protocol,
        protocol_body=protocol_body,
        protocol_path=protocol_path,
        companion=companion,
        nwm=nwm,
        nwm_body=nwm_body,
        nwm_path=nwm_manifest_path,
        travel=travel,
    )

    raw_by_role: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for descriptor in companion["artifacts"]:
        body = _read_verified_artifact(descriptor)
        raw_by_role[descriptor["variable_role"]] = (
            json.loads(body),
            _artifact_from_descriptor(descriptor, body),
        )
    expected_roles = {
        "boundary_action",
        "stock",
        "context_not_independent_forcing",
        "independent_observation",
    }
    if set(raw_by_role) != expected_roles:
        raise ValueError("evaluation_panel_companion_role_set_mismatch")

    support_starts = tuple(START + timedelta(hours=index) for index in range(HOUR_COUNT))
    support_ends = tuple(value + timedelta(hours=1) for value in support_starts)
    action_field = system["action"]
    stock_field = next(row for row in system["state_context"] if row["role"] == "stock")
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
    inflow, inflow_quality = _parse_cwms_hourly_with_gaps(
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

    effective_lengths = {
        int(feature_id): float(length)
        for feature_id, length in zip(
            travel["linear_referenced_path"]["feature_ids"],
            travel["linear_referenced_path"]["effective_lengths_m"],
            strict=True,
        )
    }
    active_ids = tuple(
        feature_id
        for feature_id in system["forcing"]["feature_ids"]
        if effective_lengths[feature_id] > 1e-6
    )
    q_descriptor = nwm["value_artifacts"]["q_lateral"]
    velocity_descriptor = nwm["value_artifacts"]["velocity"]
    q_values = _parse_reach_values(
        _read_verified_artifact(q_descriptor),
        expected_timestamps=support_starts,
        expected_feature_ids=tuple(system["forcing"]["feature_ids"]),
        value_column="q_lateral_m3s",
        expected_role="modeled_forcing",
    )
    velocity_values = _parse_reach_values(
        _read_verified_artifact(velocity_descriptor),
        expected_timestamps=support_starts,
        expected_feature_ids=tuple(system["forcing"]["feature_ids"]),
        value_column="velocity_ms",
        expected_role="modeled_state_context",
    )

    rows: list[dict[str, Any]] = []
    for index, (support_start, support_end) in enumerate(
        zip(support_starts, support_ends, strict=True)
    ):
        q_sum = float(sum(q_values[support_start][feature_id] for feature_id in active_ids))
        residence = float(
            sum(
                effective_lengths[feature_id]
                / velocity_values[support_start][feature_id]
                for feature_id in active_ids
            )
        )
        outcome = outcomes[support_end]
        rows.append(
            {
                "support_start_utc": _iso(support_start),
                "support_end_utc": _iso(support_end),
                "split_role": (
                    "evaluation_warmup" if index < WARMUP_HOURS else "evaluation"
                ),
                "action_timestamp_utc": _iso(support_end),
                "nwm_valid_time_utc": _iso(support_start),
                "action_release_m3s": action[support_end],
                "storage_start_m3": storage[support_start],
                "storage_end_m3": storage[support_end],
                "storage_change_m3": storage[support_end] - storage[support_start],
                "inflow_context_m3s": inflow[support_end],
                "nwm_q_lateral_active_reach_sum_m3s": q_sum,
                "nwm_velocity_proxy_residence_time_seconds": residence,
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
    missing = [row for row in rows if not row["outcome_available"]]
    csv_body = _encode_csv(rows)
    report = {
        "schema": SCHEMA,
        "status": "compiled_from_frozen_protocol_not_scored",
        "registry_sha256": registry.sha256,
        "source_manifests": {
            "evaluation_protocol": _artifact(protocol_path, protocol_body),
            "companion_values": _artifact(companion_manifest_path, companion_body),
            "nwm_inputs": _artifact(nwm_manifest_path, nwm_body),
            "travel_time_prior": _artifact(travel_report_path, travel_body),
        },
        "source_artifacts": {
            role: artifact for role, (_, artifact) in raw_by_role.items()
        }
        | {
            "nwm_q_lateral_values": _artifact_from_descriptor(
                q_descriptor, _read_verified_artifact(q_descriptor)
            ),
            "nwm_velocity_values": _artifact_from_descriptor(
                velocity_descriptor, _read_verified_artifact(velocity_descriptor)
            ),
        },
        "window": {
            "start_inclusive": _iso(START),
            "scored_start_inclusive": _iso(SCORED_START),
            "end_exclusive": _iso(END),
            "time_step": "PT1H",
            "row_count": len(rows),
            "evaluation_warmup_hours": WARMUP_HOURS,
            "maximum_scored_hours": HOUR_COUNT - WARMUP_HOURS,
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
            "outcome_discharge_interval_sample_mean_m3s": protocol[
                "outcome_support_lock"
            ],
        },
        "quality_summary": {
            "operator_input_missing_value_count": 0,
            "auxiliary_context_missing_value_count": sum(
                row["inflow_context_m3s"] is None for row in rows
            ),
            "auxiliary_context_missing_support_end_utc": [
                row["support_end_utc"]
                for row in rows
                if row["inflow_context_m3s"] is None
            ],
            "outcome_available_hour_count": sum(
                bool(row["outcome_available"]) for row in rows
            ),
            "outcome_missing_hour_count": len(missing),
            "outcome_missing_support_end_utc": [
                row["support_end_utc"] for row in missing
            ],
            "outcome_missing_sample_counts": [
                row["outcome_half_hour_sample_count"] for row in missing
            ],
            "outcome_imputed_hour_count": 0,
            "evaluation_warmup_outcome_missing_hour_count": sum(
                not row["outcome_available"]
                for row in rows
                if row["split_role"] == "evaluation_warmup"
            ),
            "scored_window_outcome_missing_hour_count": sum(
                not row["outcome_available"]
                for row in rows
                if row["split_role"] == "evaluation"
            ),
            "usgs_all_returned_target_samples_approved": all(
                row["usgs_qualifier"] in {"", "A"} for row in rows
            ),
            "cwms_all_target_quality_codes_zero": all(
                row[key] == 0
                for row in rows
                for key in (
                    "cwms_action_quality_code",
                    "cwms_storage_start_quality_code",
                    "cwms_storage_end_quality_code",
                    "cwms_inflow_quality_code",
                )
            ),
        },
        "checks": {
            "frozen_protocol_lineage_verified": True,
            "nwm_and_companion_windows_match_protocol": True,
            "operator_inputs_cover_672_supports": True,
            "auxiliary_context_gap_preserved_without_imputation": True,
            "first_168_hours_reserved_for_evaluation_warmup": True,
            "outcome_missing_values_not_imputed": True,
            "source_artifact_hashes_verified": True,
        },
        "claim_boundary": {
            "evaluation_values_acquired": True,
            "evaluation_panel_compiled": True,
            "evaluation_scored": False,
            "operator_inputs_complete": True,
            "auxiliary_context_complete": False,
            "outcome_values_imputed": False,
            "flood_wave_transport_admitted": False,
            "benchmark_validated": False,
            "multi_system_generalization_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    return csv_body, report


def _parse_cwms_hourly_with_gaps(
    payload: Mapping[str, Any],
    *,
    field: Mapping[str, Any],
    expected_timestamps: tuple[datetime, ...],
) -> tuple[dict[datetime, float | None], dict[datetime, int]]:
    if (
        payload.get("name") != field["series_id"]
        or payload.get("office-id") != field["office"]
        or payload.get("units") != field["native_unit"]
        or payload.get("interval") != "PT1H"
    ):
        raise ValueError(
            f"evaluation_panel_cwms_semantics_mismatch:{field['series_id']}"
        )
    expected = set(expected_timestamps)
    values: dict[datetime, float | None] = {}
    quality: dict[datetime, int] = {}
    for row in payload.get("values") or []:
        if not isinstance(row, list) or len(row) < 3:
            raise ValueError("evaluation_panel_cwms_value_row_invalid")
        timestamp = datetime.fromtimestamp(row[0] / 1000.0, tz=timezone.utc)
        if timestamp in expected:
            values[timestamp] = None if row[1] is None else float(row[1])
            quality[timestamp] = int(row[2])
    if tuple(values) != expected_timestamps:
        raise ValueError(
            f"evaluation_panel_cwms_hourly_axis_mismatch:{field['series_id']}"
        )
    return values, quality


def _validate_manifests(
    *,
    registry_sha256: str,
    protocol: Mapping[str, Any],
    protocol_body: bytes,
    protocol_path: Path,
    companion: Mapping[str, Any],
    nwm: Mapping[str, Any],
    nwm_body: bytes,
    nwm_path: Path,
    travel: Mapping[str, Any],
) -> None:
    protocol_artifact = _artifact(protocol_path, protocol_body)
    if (
        protocol.get("schema")
        != "gwm.geotransport.center_hill_temporal_holdout_protocol.v1"
        or protocol.get("status")
        != "frozen_before_evaluation_outcome_acquisition"
    ):
        raise ValueError("evaluation_panel_protocol_invalid")
    if (
        companion.get("schema") != "gwm.geotransport.acquisition_manifest.v1"
        or companion.get("mode") != "values"
        or companion.get("registry_sha256") != registry_sha256
        or companion.get("request_count") != 4
        or companion.get("artifact_count") != 4
        or companion.get("evaluation_protocol") != protocol_artifact
    ):
        raise ValueError("evaluation_panel_companion_manifest_invalid")
    if (
        nwm.get("schema") != "gwm.geotransport.center_hill_evaluation_nwm.v1"
        or nwm.get("mode") != "values"
        or nwm.get("evaluation_protocol") != protocol_artifact
        or (nwm.get("result") or {}).get("time_count") != HOUR_COUNT
        or (nwm.get("result") or {}).get("q_lateral_fill_value_count") != 0
        or (nwm.get("result") or {}).get("velocity_fill_value_count") != 0
    ):
        raise ValueError("evaluation_panel_nwm_manifest_invalid")
    if companion.get("nwm_extraction_manifest") != _artifact(nwm_path, nwm_body):
        raise ValueError("evaluation_panel_nwm_lineage_mismatch")
    if (
        travel.get("schema")
        != "gwm.geotransport.center_hill_travel_time_prior.v1"
        or (travel.get("claim_boundary") or {}).get(
            "flood_wave_travel_time_admitted"
        )
        is not False
    ):
        raise ValueError("evaluation_panel_travel_prior_invalid")


def _parse_reach_values(
    body: bytes,
    *,
    expected_timestamps: tuple[datetime, ...],
    expected_feature_ids: tuple[int, ...],
    value_column: str,
    expected_role: str,
) -> dict[datetime, dict[int, float]]:
    values: dict[datetime, dict[int, float]] = {}
    for row in csv.DictReader(io.StringIO(body.decode("utf-8"))):
        timestamp = _parse_utc(row["timestamp_utc"])
        if row["source_role"] != expected_role or row[value_column] == "":
            raise ValueError("evaluation_panel_nwm_value_semantics_invalid")
        values.setdefault(timestamp, {})[int(row["feature_id"])] = float(
            row[value_column]
        )
    if tuple(values) != expected_timestamps or any(
        tuple(values[timestamp]) != expected_feature_ids
        for timestamp in expected_timestamps
    ):
        raise ValueError("evaluation_panel_nwm_value_axis_mismatch")
    if value_column == "velocity_ms" and any(
        value <= 0.0
        for timestamp in expected_timestamps
        for feature_id, value in values[timestamp].items()
        if feature_id != expected_feature_ids[0]
    ):
        raise ValueError("evaluation_panel_active_velocity_nonpositive")
    return values


def _read_verified_artifact(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("evaluation_panel_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError(f"evaluation_panel_artifact_identity_mismatch:{path}")
    return body


def _artifact_from_descriptor(
    descriptor: Mapping[str, Any], body: bytes
) -> dict[str, Any]:
    return {
        "path": str(descriptor["path"]),
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


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("evaluation_panel_timezone_aware_timestamp_required")
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
    csv_body, report = compile_panel(
        registry_path=args.registry,
        protocol_path=args.protocol,
        companion_manifest_path=args.companion_manifest,
        nwm_manifest_path=args.nwm_manifest,
        travel_report_path=args.travel_report,
        panel_path=args.panel,
    )
    args.panel.parent.mkdir(parents=True, exist_ok=True)
    args.panel.write_bytes(csv_body)
    output_report = dict(report)
    output_report["generated_at"] = datetime.now(timezone.utc).isoformat()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(output_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
