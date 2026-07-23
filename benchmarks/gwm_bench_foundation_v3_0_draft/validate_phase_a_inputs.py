#!/usr/bin/env python3
"""Validate and hash V3 Phase A inputs without touching lockbox targets."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
PROTOCOL_PATH = DRAFT_ROOT / "suite_protocol.json"
REGION_PATH = DRAFT_ROOT / "lockbox_regions.json"
DEFAULT_REPORT = DRAFT_ROOT / "phase_a_input_validation_report.json"
DEFAULT_ARTIFACT_MANIFEST = DRAFT_ROOT / "phase_a_input_artifact_manifest.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_path(value: str) -> Path:
    return (REPO_ROOT / value).resolve()


def _json_fingerprint(payload: Any) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _raster_artifact(
    path: Path,
    *,
    region_id: str,
    kind: str,
    year: int | None = None,
    name: str | None = None,
) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    with rasterio.open(path) as dataset:
        values = dataset.read(1)
        valid_mask = values != dataset.nodata
        finite_valid = bool(np.isfinite(values[valid_mask]).all())
        artifact = {
            "path": str(path.relative_to(REPO_ROOT)),
            "region_id": region_id,
            "kind": kind,
            "year": year,
            "name": name,
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "width": dataset.width,
            "height": dataset.height,
            "band_count": dataset.count,
            "dtype": dataset.dtypes[0],
            "nodata": dataset.nodata,
            "crs": str(dataset.crs),
            "resolution": [abs(dataset.transform.a), abs(dataset.transform.e)],
            "transform": list(dataset.transform)[:6],
            "valid_pixel_count": int(valid_mask.sum()),
            "valid_fraction": float(valid_mask.mean()),
            "finite_valid_values": finite_valid,
        }
        if kind == "annual_land_state":
            artifact["observed_classes"] = sorted(
                int(value) for value in np.unique(values[valid_mask])
            )
        return artifact, values, valid_mask


def _sampled_graph_counts(valid_mask: np.ndarray, step: int) -> tuple[int, int]:
    sampled = valid_mask[0::step, 0::step]
    node_count = int(sampled.sum())
    horizontal_pairs = int((sampled[:, :-1] & sampled[:, 1:]).sum())
    vertical_pairs = int((sampled[:-1, :] & sampled[1:, :]).sum())
    directed_edge_count = 2 * (horizontal_pairs + vertical_pairs)
    return node_count, directed_edge_count


def validate_phase_a_inputs(
    report_path: Path = DEFAULT_REPORT,
    artifact_manifest_path: Path = DEFAULT_ARTIFACT_MANIFEST,
) -> dict[str, Any]:
    protocol = _load_json(PROTOCOL_PATH)
    lockbox = _load_json(REGION_PATH)
    input_root = _repo_path(protocol["dataset"]["phase_a_input_root"])
    target_root = _repo_path(protocol["dataset"]["phase_c_target_root"])
    source_manifest_path = input_root / "manifest.json"
    download_status_path = input_root / "download_status.json"
    source_manifest = _load_json(source_manifest_path)
    download_status = _load_json(download_status_path)

    expected_years = protocol["dataset"]["allowed_input_years"]
    expected_region_ids = [row["region_id"] for row in lockbox["regions"]]
    source_regions = source_manifest["regions"]
    source_region_ids = [row["region_id"] for row in source_regions]
    source_by_id = {row["region_id"]: row for row in source_regions}
    expected_driver_names = {
        "srtm_elevation",
        "srtm_slope",
        "viirs_nightlight_mean",
    }
    sample_step = int(protocol["dataset"]["node_sampling"]["row_step_pixels"])

    artifacts: list[dict[str, Any]] = []
    region_summaries: list[dict[str, Any]] = []
    missing_paths: list[str] = []
    grids_aligned = True
    land_classes_valid = True
    raster_contract_valid = True
    all_valid_values_finite = True
    per_region_years_valid = True
    per_region_drivers_valid = True

    for region_id in expected_region_ids:
        source_region = source_by_id.get(region_id)
        if source_region is None:
            continue
        annual_rows = source_region["raster_stack"]
        driver_rows = source_region["driver_layers"]
        per_region_years_valid = per_region_years_valid and [
            int(row["year"]) for row in annual_rows
        ] == expected_years
        per_region_drivers_valid = per_region_drivers_valid and {
            row["name"] for row in driver_rows
        } == expected_driver_names

        reference_grid: tuple[Any, ...] | None = None
        combined_valid_mask: np.ndarray | None = None
        region_artifacts: list[dict[str, Any]] = []
        for row in annual_rows:
            path = input_root / row["path"]
            if not path.is_file():
                missing_paths.append(str(path.relative_to(REPO_ROOT)))
                continue
            artifact, _, valid_mask = _raster_artifact(
                path,
                region_id=region_id,
                kind="annual_land_state",
                year=int(row["year"]),
            )
            region_artifacts.append(artifact)
            combined_valid_mask = (
                valid_mask.copy()
                if combined_valid_mask is None
                else combined_valid_mask & valid_mask
            )
            grid = (
                artifact["width"],
                artifact["height"],
                artifact["crs"],
                tuple(artifact["resolution"]),
                tuple(artifact["transform"]),
            )
            if reference_grid is None:
                reference_grid = grid
            grids_aligned = grids_aligned and grid == reference_grid
            land_classes_valid = land_classes_valid and set(
                artifact["observed_classes"]
            ).issubset(set(range(9)))
            raster_contract_valid = raster_contract_valid and (
                artifact["band_count"] == 1
                and artifact["dtype"] == "int16"
                and artifact["nodata"] == -32768.0
                and artifact["crs"] == "EPSG:3857"
                and artifact["resolution"] == [100.0, 100.0]
                and artifact["valid_pixel_count"] > 0
            )
            all_valid_values_finite = (
                all_valid_values_finite and artifact["finite_valid_values"]
            )

        for row in driver_rows:
            path = input_root / row["path"]
            if not path.is_file():
                missing_paths.append(str(path.relative_to(REPO_ROOT)))
                continue
            artifact, _, valid_mask = _raster_artifact(
                path,
                region_id=region_id,
                kind="driver",
                name=row["name"],
            )
            region_artifacts.append(artifact)
            combined_valid_mask = (
                valid_mask.copy()
                if combined_valid_mask is None
                else combined_valid_mask & valid_mask
            )
            grid = (
                artifact["width"],
                artifact["height"],
                artifact["crs"],
                tuple(artifact["resolution"]),
                tuple(artifact["transform"]),
            )
            grids_aligned = grids_aligned and grid == reference_grid
            raster_contract_valid = raster_contract_valid and (
                artifact["band_count"] == 1
                and artifact["dtype"] == "float32"
                and artifact["nodata"] == -32768.0
                and artifact["crs"] == "EPSG:3857"
                and artifact["resolution"] == [100.0, 100.0]
                and artifact["valid_pixel_count"] > 0
            )
            all_valid_values_finite = (
                all_valid_values_finite and artifact["finite_valid_values"]
            )

        artifacts.extend(region_artifacts)
        if combined_valid_mask is not None and reference_grid is not None:
            node_count, directed_edge_count = _sampled_graph_counts(
                combined_valid_mask, sample_step
            )
            region_summaries.append(
                {
                    "region_id": region_id,
                    "width": int(reference_grid[0]),
                    "height": int(reference_grid[1]),
                    "input_valid_pixel_count": int(combined_valid_mask.sum()),
                    "sampled_node_count": node_count,
                    "directed_four_neighbor_edge_count": directed_edge_count,
                }
            )

    target_files = (
        sorted(path for path in target_root.rglob("*") if path.is_file())
        if target_root.exists()
        else []
    )
    paths_contain_only_allowed_years = all(
        artifact["year"] in expected_years
        for artifact in artifacts
        if artifact["kind"] == "annual_land_state"
    )
    checks = {
        "download_status_passed": download_status["status"] == "pass"
        and download_status["downloaded_region_count"] == 20
        and download_status["downloaded_raster_count"] == 120
        and download_status["downloaded_driver_count"] == 60,
        "source_manifest_schema_valid": source_manifest["schema"]
        == "territory_world_model.public_landcover_manifest.v1",
        "source_identity_valid": source_manifest["source"]["collection"]
        == "GOOGLE/DYNAMICWORLD/V1"
        and source_manifest["source"]["project"] == "ee-zn19860115"
        and source_manifest["source"]["scale_m"] == 100
        and source_manifest["source"]["crs"] == "EPSG:3857",
        "manifest_years_are_exactly_2017_2022": source_manifest["years"]
        == expected_years
        == list(range(2017, 2023)),
        "manifest_region_ids_match_lockbox": source_region_ids
        == expected_region_ids,
        "all_region_year_sets_are_exact": per_region_years_valid,
        "all_region_driver_sets_are_exact": per_region_drivers_valid,
        "all_180_raster_files_exist": not missing_paths
        and len(artifacts) == 180,
        "all_rasters_follow_type_crs_nodata_resolution_contract": raster_contract_valid,
        "all_rasters_align_within_each_region": grids_aligned,
        "all_land_classes_are_in_0_8": land_classes_valid,
        "all_valid_values_are_finite": all_valid_values_finite,
        "all_regions_have_sampled_nodes": len(region_summaries) == 20
        and all(row["sampled_node_count"] > 0 for row in region_summaries),
        "artifact_paths_contain_only_allowed_years": paths_contain_only_allowed_years,
        "target_directory_contains_no_files": not target_files,
        "target_pixels_read_by_validator_is_false": True,
    }
    artifact_payload = {
        "schema": "gwm_bench.foundation_v3_phase_a_artifacts.v1",
        "suite_id": protocol["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PHASE_A_INPUT_ARTIFACTS_HASHED"
        if all(checks.values())
        else "FAIL",
        "protocol_sha256": _sha256(PROTOCOL_PATH),
        "lockbox_region_manifest_sha256": _sha256(REGION_PATH),
        "source_manifest_sha256": _sha256(source_manifest_path),
        "download_status_sha256": _sha256(download_status_path),
        "artifact_count": len(artifacts),
        "total_artifact_bytes": sum(row["size_bytes"] for row in artifacts),
        "artifacts": sorted(
            artifacts,
            key=lambda row: (
                row["region_id"],
                row["kind"],
                row["year"] or 0,
                row["name"] or "",
            ),
        ),
    }
    artifact_payload["dataset_fingerprint"] = _json_fingerprint(
        {
            "suite_id": artifact_payload["suite_id"],
            "protocol_sha256": artifact_payload["protocol_sha256"],
            "lockbox_region_manifest_sha256": artifact_payload[
                "lockbox_region_manifest_sha256"
            ],
            "source_manifest_sha256": artifact_payload[
                "source_manifest_sha256"
            ],
            "artifacts": artifact_payload["artifacts"],
        }
    )
    artifact_manifest_path.write_text(
        json.dumps(artifact_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    passed = all(checks.values())
    report = {
        "schema": "gwm_bench.foundation_v3_phase_a_validation.v1",
        "suite_id": protocol["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_PHASE_A_INPUTS_VALIDATED" if passed else "FAIL",
        "check_count": len(checks),
        "checks": checks,
        "missing_paths": missing_paths,
        "summary": {
            "region_count": len(region_summaries),
            "annual_land_state_raster_count": sum(
                row["kind"] == "annual_land_state" for row in artifacts
            ),
            "driver_raster_count": sum(
                row["kind"] == "driver" for row in artifacts
            ),
            "total_artifact_bytes": artifact_payload["total_artifact_bytes"],
            "sampled_node_count": sum(
                row["sampled_node_count"] for row in region_summaries
            ),
            "directed_edge_count": sum(
                row["directed_four_neighbor_edge_count"]
                for row in region_summaries
            ),
            "target_file_count": len(target_files),
        },
        "region_summaries": region_summaries,
        "artifact_manifest": str(artifact_manifest_path.relative_to(REPO_ROOT)),
        "artifact_manifest_sha256": _sha256(artifact_manifest_path),
        "dataset_fingerprint": artifact_payload["dataset_fingerprint"],
        "target_pixels_read_by_validator": False,
        "next_permitted_action": (
            "Materialize fixed nodes and graphs from Phase A inputs; do not acquire targets."
            if passed
            else "Repair Phase A inputs without acquiring targets."
        ),
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"GWM-Bench V3 Phase A inputs: {report['status']}")
    print(f"Validation report: {report_path}")
    return report


if __name__ == "__main__":
    result = validate_phase_a_inputs()
    raise SystemExit(
        0 if result["status"] == "PASS_PHASE_A_INPUTS_VALIDATED" else 1
    )
