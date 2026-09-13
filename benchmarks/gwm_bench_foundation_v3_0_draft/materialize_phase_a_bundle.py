#!/usr/bin/env python3
"""Materialize the V3 lockbox input bundle without target labels."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
PROTOCOL_PATH = DRAFT_ROOT / "suite_protocol.json"
REGION_PATH = DRAFT_ROOT / "lockbox_regions.json"
INPUT_ARTIFACT_MANIFEST = DRAFT_ROOT / "phase_a_input_artifact_manifest.json"
DEFAULT_OUTPUT_ROOT = DRAFT_ROOT / "phase_a_bundle"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(payload: Any) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _node_id(row: int, column: int) -> str:
    return f"r{row:05d}_c{column:05d}"


def _read_band(path: Path) -> tuple[np.ndarray, Any, Any, float | None]:
    with rasterio.open(path) as dataset:
        return dataset.read(1), dataset.transform, dataset.crs, dataset.nodata


def _valid(values: np.ndarray, nodata: float | None) -> np.ndarray:
    result = np.isfinite(values)
    if nodata is not None:
        result &= values != nodata
    return result


def materialize(output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    protocol = _load_json(PROTOCOL_PATH)
    lockbox = _load_json(REGION_PATH)
    input_artifacts = _load_json(INPUT_ARTIFACT_MANIFEST)
    input_root = (REPO_ROOT / protocol["dataset"]["phase_a_input_root"]).resolve()
    source_manifest_path = input_root / "manifest.json"
    source_manifest = _load_json(source_manifest_path)
    target_root = (REPO_ROOT / protocol["dataset"]["phase_c_target_root"]).resolve()
    if target_root.exists() and any(path.is_file() for path in target_root.rglob("*")):
        raise RuntimeError("refusing_bundle_materialization_after_target_acquisition")

    expected_region_ids = [row["region_id"] for row in lockbox["regions"]]
    source_region_ids = [row["region_id"] for row in source_manifest["regions"]]
    if source_region_ids != expected_region_ids:
        raise ValueError("phase_a_manifest_region_order_mismatch")
    years = protocol["dataset"]["allowed_input_years"]
    target_years = protocol["dataset"]["lockbox_target_years"]
    step = int(protocol["dataset"]["node_sampling"]["row_step_pixels"])

    input_rows: list[dict[str, Any]] = []
    history_rows: list[dict[str, Any]] = []
    edge_rows: list[dict[str, Any]] = []
    submission_rows: list[dict[str, Any]] = []
    region_rows: list[dict[str, Any]] = []

    for region in source_manifest["regions"]:
        region_id = region["region_id"]
        land: dict[int, np.ndarray] = {}
        reference: tuple[Any, ...] | None = None
        valid_mask: np.ndarray | None = None
        for row in region["raster_stack"]:
            year = int(row["year"])
            path = input_root / row["path"]
            values, transform, crs, nodata = _read_band(path)
            grid = (values.shape, transform, crs)
            if reference is None:
                reference = grid
            elif grid != reference:
                raise ValueError(f"grid_mismatch:{region_id}:{year}")
            current_valid = _valid(values, nodata) & (values >= 0) & (values <= 8)
            valid_mask = (
                current_valid.copy()
                if valid_mask is None
                else valid_mask & current_valid
            )
            land[year] = values.astype(np.int16, copy=False)

        drivers: dict[str, np.ndarray] = {}
        for row in region["driver_layers"]:
            path = input_root / row["path"]
            values, transform, crs, nodata = _read_band(path)
            if reference is None or (values.shape, transform, crs) != reference:
                raise ValueError(f"driver_grid_mismatch:{region_id}:{row['name']}")
            current_valid = _valid(values, nodata)
            valid_mask = valid_mask & current_valid if valid_mask is not None else current_valid
            drivers[row["name"]] = values.astype(np.float32, copy=False)

        if reference is None or valid_mask is None:
            raise ValueError(f"missing_phase_a_inputs:{region_id}")
        shape, transform, crs = reference
        cells = [
            (row, column)
            for row in range(0, shape[0], step)
            for column in range(0, shape[1], step)
            if bool(valid_mask[row, column])
        ]
        if not cells:
            raise ValueError(f"no_valid_nodes:{region_id}")
        cell_set = set(cells)
        for row, column in cells:
            node_id = _node_id(row, column)
            x, y = transform * (column + 0.5, row + 0.5)
            shared = {
                "region_id": region_id,
                "node_id": node_id,
                "raster_row": row,
                "raster_column": column,
                "x_3857": float(x),
                "y_3857": float(y),
            }
            input_rows.append(
                {
                    **shared,
                    **{
                        f"land_class_{year}": int(land[year][row, column])
                        for year in years
                    },
                    "srtm_elevation": float(drivers["srtm_elevation"][row, column]),
                    "srtm_slope": float(drivers["srtm_slope"][row, column]),
                    "viirs_nightlight_mean_2017_2022": float(
                        drivers["viirs_nightlight_mean"][row, column]
                    ),
                }
            )
            for year in years:
                history_rows.append(
                    {
                        **shared,
                        "year": year,
                        "land_class": int(land[year][row, column]),
                    }
                )
            for target_year in target_years:
                submission_rows.append(
                    {
                        "region_id": region_id,
                        "node_id": node_id,
                        "target_year": target_year,
                    }
                )

        directions = (
            (-step, 0, "north"),
            (0, step, "east"),
            (step, 0, "south"),
            (0, -step, "west"),
        )
        for row, column in cells:
            source = _node_id(row, column)
            for delta_row, delta_column, direction in directions:
                target_cell = (row + delta_row, column + delta_column)
                if target_cell not in cell_set:
                    continue
                target = _node_id(*target_cell)
                edge_rows.append(
                    {
                        "region_id": region_id,
                        "edge_id": f"{source}->{target}",
                        "source_node_id": source,
                        "target_node_id": target,
                        "direction": direction,
                        "distance_m": float(step * 100),
                    }
                )
        region_rows.append(
            {
                "region_id": region_id,
                "width": int(shape[1]),
                "height": int(shape[0]),
                "crs": str(crs),
                "sample_stride_pixels": step,
                "node_count": len(cells),
                "directed_edge_count": sum(
                    row["region_id"] == region_id for row in edge_rows
                ),
                "node_selection_uses_target_labels": False,
            }
        )

    tables = {
        "observed_inputs.parquet": pd.DataFrame(input_rows).sort_values(
            ["region_id", "node_id"], kind="mergesort"
        ),
        "observed_state_history.parquet": pd.DataFrame(history_rows).sort_values(
            ["region_id", "node_id", "year"], kind="mergesort"
        ),
        "observed_edges.parquet": pd.DataFrame(edge_rows).sort_values(
            ["region_id", "edge_id"], kind="mergesort"
        ),
        "submission_keys.parquet": pd.DataFrame(submission_rows).sort_values(
            ["region_id", "node_id", "target_year"], kind="mergesort"
        ),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, dict[str, Any]] = {}
    for name, frame in tables.items():
        path = output_root / name
        frame.to_parquet(path, index=False)
        artifacts[name] = {
            "path": str(path.relative_to(REPO_ROOT)),
            "row_count": len(frame),
            "columns": list(frame.columns),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }

    region_metadata_path = output_root / "region_metadata.json"
    region_metadata_path.write_text(
        json.dumps(
            {
                "schema": "gwm_bench.foundation_v3_phase_a_regions.v1",
                "regions": region_rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    artifacts["region_metadata.json"] = {
        "path": str(region_metadata_path.relative_to(REPO_ROOT)),
        "row_count": len(region_rows),
        "size_bytes": region_metadata_path.stat().st_size,
        "sha256": _sha256(region_metadata_path),
    }

    manifest = {
        "schema": "gwm_bench.foundation_v3_phase_a_bundle.v1",
        "suite_id": protocol["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PHASE_A_BUNDLE_MATERIALIZED",
        "label_boundary": {
            "maximum_input_year": max(years),
            "target_years": target_years,
            "target_labels_in_bundle": False,
            "target_pixels_read": False,
        },
        "source_commitments": {
            "protocol_sha256": _sha256(PROTOCOL_PATH),
            "lockbox_region_manifest_sha256": _sha256(REGION_PATH),
            "input_artifact_manifest_sha256": _sha256(
                INPUT_ARTIFACT_MANIFEST
            ),
            "input_dataset_fingerprint": input_artifacts["dataset_fingerprint"],
        },
        "counts": {
            "region_count": len(region_rows),
            "node_count": len(tables["observed_inputs.parquet"]),
            "state_history_row_count": len(
                tables["observed_state_history.parquet"]
            ),
            "directed_edge_count": len(tables["observed_edges.parquet"]),
            "submission_key_count": len(tables["submission_keys.parquet"]),
        },
        "artifacts": artifacts,
    }
    manifest["bundle_fingerprint"] = _fingerprint(
        {
            "suite_id": manifest["suite_id"],
            "label_boundary": manifest["label_boundary"],
            "source_commitments": manifest["source_commitments"],
            "counts": manifest["counts"],
            "artifacts": manifest["artifacts"],
        }
    )
    manifest_path = output_root / "bundle_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("GWM-Bench V3 Phase A bundle: PHASE_A_BUNDLE_MATERIALIZED")
    print(f"Bundle manifest: {manifest_path}")
    return manifest


if __name__ == "__main__":
    materialize()
