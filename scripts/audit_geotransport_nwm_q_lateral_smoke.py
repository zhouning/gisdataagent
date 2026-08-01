#!/usr/bin/env python3
"""Audit the bounded Center Hill NWM q_lateral value smoke end to end."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    DEFAULT_REGISTRY_PATH,
    build_nwm_q_lateral_plan,
    extract_nwm_q_lateral,
    load_nwm_zarr_schema,
    load_public_data_registry,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METADATA_ROOT = REPO_ROOT / "data/geotransport_v0_1/metadata"
DEFAULT_MANIFEST = (
    REPO_ROOT / "data/geotransport_v0_1/nwm_q_lateral/extraction_manifest.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/nwm_q_lateral_smoke_report.json"
)
SMOKE_REPORT_SCHEMA = "gwm.geotransport.nwm_q_lateral_smoke_audit.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--metadata-root", type=Path, default=DEFAULT_METADATA_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def audit(
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    registry = load_public_data_registry(registry_path)
    schema = load_nwm_zarr_schema(metadata_root)
    manifest_body = manifest_path.read_bytes()
    manifest = json.loads(manifest_body)
    if manifest.get("schema") != "gwm.geotransport.nwm_q_lateral_extract.v1":
        raise ValueError("nwm_smoke_manifest_schema_mismatch")
    if manifest.get("mode") != "values":
        raise ValueError("nwm_smoke_values_manifest_required")
    input_registry_hash = manifest.get("registry_sha256")
    referenced_registry_hashes = {
        registry.sha256,
        registry.payload.get("parent_registry_sha256"),
        (registry.payload.get("nwm_q_lateral_smoke_evidence") or {}).get(
            "parent_registry_sha256"
        ),
    }
    if input_registry_hash not in referenced_registry_hashes:
        raise ValueError("nwm_smoke_registry_lineage_mismatch")
    expected_semantics = {
        "source": "noaa_nwm_v3_retrospective",
        "variable": "q_lateral",
        "role": "modeled_forcing",
        "modeled": True,
        "ground_truth": False,
        "streamflow_used": False,
        "units": "m3 s-1",
    }
    if manifest.get("source_semantics") != expected_semantics:
        raise ValueError("nwm_smoke_source_semantics_mismatch")
    claim = manifest.get("claim_boundary") or {}
    if (
        claim.get("modeled_forcing_values_acquired") is not True
        or claim.get("observed_forcing_acquired") is not False
        or claim.get("benchmark_validated") is not False
        or claim.get("geospatial_kernel_validated") is not False
    ):
        raise ValueError("nwm_smoke_claim_boundary_invalid")
    systems = manifest.get("systems") or []
    if len(systems) != 1 or systems[0].get("system_id") != "center_hill":
        raise ValueError("center_hill_only_smoke_required")
    plan = build_nwm_q_lateral_plan(
        registry,
        schema,
        system_id="center_hill",
        start=manifest["start_inclusive"],
        end=manifest["end_exclusive"],
    )
    _validate_plan_payload(plan, systems[0])
    if plan.time_count != 24 or plan.q_chunk_keys != ((559, 63),):
        raise ValueError("nwm_smoke_plan_boundary_mismatch")

    raw_descriptors = manifest.get("raw_chunk_artifacts") or []
    by_variable = {descriptor.get("variable"): descriptor for descriptor in raw_descriptors}
    if set(by_variable) != {"time", "q_lateral"}:
        raise ValueError("nwm_smoke_raw_artifact_set_mismatch")
    time_body, time_artifact = _read_artifact(by_variable["time"])
    q_body, q_artifact = _read_artifact(by_variable["q_lateral"])
    result = extract_nwm_q_lateral(
        plan,
        schema,
        time_chunks={559: time_body},
        q_chunks={(559, 63): q_body},
    )

    value_descriptors = manifest.get("value_artifacts") or []
    if len(value_descriptors) != 1:
        raise ValueError("nwm_smoke_value_artifact_required")
    csv_body, value_artifact = _read_artifact(value_descriptors[0])
    csv_values, csv_timestamps, csv_feature_ids, csv_roles = _parse_value_csv(
        csv_body
    )
    expected_timestamps = tuple(
        timestamp
        for timestamp in result.timestamps
        for _ in result.feature_ids
    )
    expected_feature_ids = result.feature_ids * len(result.timestamps)
    if csv_timestamps != expected_timestamps or csv_feature_ids != expected_feature_ids:
        raise ValueError("nwm_smoke_csv_axis_order_mismatch")
    if set(csv_roles) != {"modeled_forcing"}:
        raise ValueError("nwm_smoke_csv_role_mismatch")
    expected_values = result.values_m3s.reshape(-1)
    if not np.allclose(csv_values, expected_values, rtol=0.0, atol=5e-9, equal_nan=True):
        raise ValueError("nwm_smoke_csv_value_mismatch")
    summary_rows = manifest.get("results") or []
    if summary_rows != [
        {
            "system_id": "center_hill",
            "time_count": 24,
            "feature_count": 27,
            "value_count": 648,
            "fill_value_count": result.fill_value_count,
            "output_path": value_descriptors[0]["path"],
        }
    ]:
        raise ValueError("nwm_smoke_manifest_result_mismatch")
    finite = result.values_m3s[np.isfinite(result.values_m3s)]
    checks = {
        "input_registry_lineage_verified": True,
        "official_nwm_source_and_modeled_forcing_semantics_verified": True,
        "single_system_24_hour_chunk_boundary_verified": True,
        "time_coordinate_contiguous_and_hourly": True,
        "registry_feature_order_reconstructed": True,
        "packed_fill_value_masked_before_scaling": True,
        "csv_reproduces_raw_zarr_selection": True,
        "raw_and_value_artifact_hashes_verified": True,
    }
    return {
        "schema": SMOKE_REPORT_SCHEMA,
        "status": "pass",
        "input_registry_sha256": input_registry_hash,
        "extraction_manifest": {
            "path": _display(manifest_path),
            "sha256": hashlib.sha256(manifest_body).hexdigest(),
            "size_bytes": len(manifest_body),
        },
        "source_semantics": expected_semantics,
        "window": {
            "start_inclusive": result.timestamps[0],
            "end_exclusive": manifest["end_exclusive"].replace("+00:00", "Z"),
            "time_count": len(result.timestamps),
        },
        "spatial_selection": {
            "system_id": result.system_id,
            "feature_count": len(result.feature_ids),
            "feature_ids": list(result.feature_ids),
            "time_chunk_indices": list(plan.time_chunk_indices),
            "feature_chunk_indices": list(plan.feature_chunk_indices),
            "q_chunk_keys": [list(key) for key in plan.q_chunk_keys],
        },
        "artifacts": {
            "time_chunk": time_artifact,
            "q_lateral_chunk": q_artifact,
            "selected_values": value_artifact,
        },
        "value_summary": {
            "value_count": int(result.values_m3s.size),
            "finite_value_count": int(finite.size),
            "fill_value_count": result.fill_value_count,
            "nonzero_value_count": int(np.count_nonzero(finite)),
            "minimum_m3s": float(finite.min()),
            "maximum_m3s": float(finite.max()),
            "sum_over_reach_hours_m3s": float(finite.sum()),
            "hourly_path_sum_m3s": [
                float(value) for value in np.nansum(result.values_m3s, axis=1)
            ],
        },
        "checks": checks,
        "claim_boundary": {
            "bounded_nwm_q_lateral_value_smoke_verified": True,
            "action_state_or_outcome_values_acquired": False,
            "training_or_evaluation_panel_ready": False,
            "benchmark_validated": False,
            "geospatial_kernel_validated": False,
        },
    }


def _validate_plan_payload(plan: Any, payload: Mapping[str, Any]) -> None:
    expected = {
        "system_id": plan.system_id,
        "time_count": plan.time_count,
        "start_time_index": plan.start_time_index,
        "end_time_index": plan.end_time_index,
        "feature_ids": list(plan.feature_ids),
        "feature_indices": list(plan.feature_indices),
        "time_chunk_indices": list(plan.time_chunk_indices),
        "feature_chunk_indices": list(plan.feature_chunk_indices),
        "q_chunk_keys": [list(key) for key in plan.q_chunk_keys],
    }
    if payload != expected:
        raise ValueError("nwm_smoke_manifest_plan_mismatch")


def _read_artifact(descriptor: Mapping[str, Any]) -> tuple[bytes, dict[str, Any]]:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("nwm_smoke_artifact_outside_repository") from exc
    body = path.read_bytes()
    actual_hash = hashlib.sha256(body).hexdigest()
    if actual_hash != descriptor.get("sha256") or len(body) != descriptor.get(
        "size_bytes"
    ):
        raise ValueError(f"nwm_smoke_artifact_identity_mismatch:{descriptor.get('path')}")
    return body, {
        "path": _display(path),
        "sha256": actual_hash,
        "size_bytes": len(body),
        "source_url": descriptor.get("url"),
        "http_status": descriptor.get("http_status"),
        "retrieved_at": descriptor.get("retrieved_at"),
    }


def _parse_value_csv(
    body: bytes,
) -> tuple[np.ndarray, tuple[str, ...], tuple[int, ...], tuple[str, ...]]:
    text = body.decode("utf-8").splitlines()
    reader = csv.reader(text)
    header = next(reader)
    if header != ["timestamp_utc", "feature_id", "q_lateral_m3s", "source_role"]:
        raise ValueError("nwm_smoke_csv_header_mismatch")
    timestamps: list[str] = []
    feature_ids: list[int] = []
    values: list[float] = []
    roles: list[str] = []
    for row in reader:
        if len(row) != 4:
            raise ValueError("nwm_smoke_csv_row_width_mismatch")
        timestamps.append(row[0])
        feature_ids.append(int(row[1]))
        values.append(float("nan") if row[2] == "" else float(row[2]))
        roles.append(row[3])
    return (
        np.asarray(values, dtype=np.float64),
        tuple(timestamps),
        tuple(feature_ids),
        tuple(roles),
    )


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def main() -> int:
    args = parse_args()
    report = audit(
        registry_path=args.registry,
        metadata_root=args.metadata_root,
        manifest_path=args.manifest,
    )
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
