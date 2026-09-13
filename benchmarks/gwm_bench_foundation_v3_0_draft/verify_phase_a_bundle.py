#!/usr/bin/env python3
"""Independently verify the V3 Phase A bundle against source rasters."""

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
BUNDLE_ROOT = DRAFT_ROOT / "phase_a_bundle"
BUNDLE_MANIFEST_PATH = BUNDLE_ROOT / "bundle_manifest.json"
DEFAULT_OUTPUT = DRAFT_ROOT / "phase_a_bundle_verification.json"


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


def _read(path: Path) -> tuple[np.ndarray, Any]:
    with rasterio.open(path) as dataset:
        return dataset.read(1), dataset.transform


def verify(output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    protocol = _load_json(PROTOCOL_PATH)
    lockbox = _load_json(REGION_PATH)
    input_artifacts = _load_json(INPUT_ARTIFACT_MANIFEST)
    bundle_manifest = _load_json(BUNDLE_MANIFEST_PATH)
    input_root = (REPO_ROOT / protocol["dataset"]["phase_a_input_root"]).resolve()
    source_manifest = _load_json(input_root / "manifest.json")
    target_root = (REPO_ROOT / protocol["dataset"]["phase_c_target_root"]).resolve()

    artifact_checks: dict[str, bool] = {}
    for name, artifact in bundle_manifest["artifacts"].items():
        path = REPO_ROOT / artifact["path"]
        artifact_checks[name] = (
            path.is_file()
            and path.stat().st_size == artifact["size_bytes"]
            and _sha256(path) == artifact["sha256"]
        )

    inputs = pd.read_parquet(BUNDLE_ROOT / "observed_inputs.parquet")
    history = pd.read_parquet(BUNDLE_ROOT / "observed_state_history.parquet")
    edges = pd.read_parquet(BUNDLE_ROOT / "observed_edges.parquet")
    keys = pd.read_parquet(BUNDLE_ROOT / "submission_keys.parquet")
    region_metadata = _load_json(BUNDLE_ROOT / "region_metadata.json")["regions"]

    expected_input_columns = [
        "region_id",
        "node_id",
        "raster_row",
        "raster_column",
        "x_3857",
        "y_3857",
        "land_class_2017",
        "land_class_2018",
        "land_class_2019",
        "land_class_2020",
        "land_class_2021",
        "land_class_2022",
        "srtm_elevation",
        "srtm_slope",
        "viirs_nightlight_mean_2017_2022",
    ]
    expected_history_columns = [
        "region_id",
        "node_id",
        "raster_row",
        "raster_column",
        "x_3857",
        "y_3857",
        "year",
        "land_class",
    ]
    expected_edge_columns = [
        "region_id",
        "edge_id",
        "source_node_id",
        "target_node_id",
        "direction",
        "distance_m",
    ]
    expected_key_columns = ["region_id", "node_id", "target_year"]
    expected_region_ids = [row["region_id"] for row in lockbox["regions"]]

    value_comparisons = 0
    source_values_match = True
    coordinates_match = True
    history_matches_inputs = True
    for region in source_manifest["regions"]:
        region_id = region["region_id"]
        frame = inputs[inputs["region_id"] == region_id].sort_values(
            "node_id", kind="mergesort"
        )
        rows = frame["raster_row"].to_numpy(dtype=np.int64)
        columns = frame["raster_column"].to_numpy(dtype=np.int64)

        for row in region["raster_stack"]:
            year = int(row["year"])
            values, transform = _read(input_root / row["path"])
            observed = values[rows, columns].astype(np.int64)
            bundled = frame[f"land_class_{year}"].to_numpy(dtype=np.int64)
            source_values_match = source_values_match and np.array_equal(
                observed, bundled
            )
            value_comparisons += len(frame)
            if year == 2017:
                expected_x = np.array(
                    [transform * (column + 0.5, row_index + 0.5) for row_index, column in zip(rows, columns)]
                )
                coordinates_match = coordinates_match and np.allclose(
                    frame["x_3857"].to_numpy(dtype=np.float64),
                    expected_x[:, 0],
                    atol=0.0,
                    rtol=0.0,
                ) and np.allclose(
                    frame["y_3857"].to_numpy(dtype=np.float64),
                    expected_x[:, 1],
                    atol=0.0,
                    rtol=0.0,
                )
                value_comparisons += 2 * len(frame)

        driver_column = {
            "srtm_elevation": "srtm_elevation",
            "srtm_slope": "srtm_slope",
            "viirs_nightlight_mean": "viirs_nightlight_mean_2017_2022",
        }
        for row in region["driver_layers"]:
            values, _ = _read(input_root / row["path"])
            observed = values[rows, columns].astype(np.float64)
            bundled = frame[driver_column[row["name"]]].to_numpy(
                dtype=np.float64
            )
            source_values_match = source_values_match and np.allclose(
                observed, bundled, atol=0.0, rtol=0.0
            )
            value_comparisons += len(frame)

        region_history = history[history["region_id"] == region_id]
        wide_history = region_history.pivot(
            index="node_id", columns="year", values="land_class"
        ).sort_index()
        for year in protocol["dataset"]["allowed_input_years"]:
            history_matches_inputs = history_matches_inputs and np.array_equal(
                wide_history[year].to_numpy(dtype=np.int64),
                frame.set_index("node_id")[f"land_class_{year}"].to_numpy(
                    dtype=np.int64
                ),
            )
            value_comparisons += len(frame)

    reconstructed_edges: list[dict[str, Any]] = []
    step = int(protocol["dataset"]["node_sampling"]["row_step_pixels"])
    directions = (
        (-step, 0, "north"),
        (0, step, "east"),
        (step, 0, "south"),
        (0, -step, "west"),
    )
    for region_id, frame in inputs.groupby("region_id", sort=True):
        cells = {
            (int(row.raster_row), int(row.raster_column))
            for row in frame.itertuples(index=False)
        }
        for row, column in sorted(cells):
            source = _node_id(row, column)
            for delta_row, delta_column, direction in directions:
                target_cell = (row + delta_row, column + delta_column)
                if target_cell not in cells:
                    continue
                target = _node_id(*target_cell)
                reconstructed_edges.append(
                    {
                        "region_id": region_id,
                        "edge_id": f"{source}->{target}",
                        "source_node_id": source,
                        "target_node_id": target,
                        "direction": direction,
                        "distance_m": float(step * 100),
                    }
                )
    reconstructed_edge_frame = pd.DataFrame(reconstructed_edges).sort_values(
        ["region_id", "edge_id"], kind="mergesort"
    ).reset_index(drop=True)
    bundled_edge_frame = edges.sort_values(
        ["region_id", "edge_id"], kind="mergesort"
    ).reset_index(drop=True)

    expected_keys = inputs[["region_id", "node_id"]].merge(
        pd.DataFrame(
            {"target_year": protocol["dataset"]["lockbox_target_years"]}
        ),
        how="cross",
    ).sort_values(["region_id", "node_id", "target_year"], kind="mergesort")
    bundled_keys = keys.sort_values(
        ["region_id", "node_id", "target_year"], kind="mergesort"
    ).reset_index(drop=True)
    expected_keys = expected_keys.reset_index(drop=True)

    calculated_bundle_fingerprint = _fingerprint(
        {
            "suite_id": bundle_manifest["suite_id"],
            "label_boundary": bundle_manifest["label_boundary"],
            "source_commitments": bundle_manifest["source_commitments"],
            "counts": bundle_manifest["counts"],
            "artifacts": bundle_manifest["artifacts"],
        }
    )
    target_files = (
        [path for path in target_root.rglob("*") if path.is_file()]
        if target_root.exists()
        else []
    )
    checks = {
        "all_bundle_artifact_hashes_match": all(artifact_checks.values()),
        "bundle_fingerprint_matches": calculated_bundle_fingerprint
        == bundle_manifest["bundle_fingerprint"],
        "source_commitments_match_current_phase_a": bundle_manifest[
            "source_commitments"
        ]["protocol_sha256"]
        == _sha256(PROTOCOL_PATH)
        and bundle_manifest["source_commitments"][
            "lockbox_region_manifest_sha256"
        ]
        == _sha256(REGION_PATH)
        and bundle_manifest["source_commitments"][
            "input_artifact_manifest_sha256"
        ]
        == _sha256(INPUT_ARTIFACT_MANIFEST)
        and bundle_manifest["source_commitments"]["input_dataset_fingerprint"]
        == input_artifacts["dataset_fingerprint"],
        "table_schemas_are_exact": list(inputs.columns)
        == expected_input_columns
        and list(history.columns) == expected_history_columns
        and list(edges.columns) == expected_edge_columns
        and list(keys.columns) == expected_key_columns,
        "table_counts_are_exact": len(inputs) == 1227
        and len(history) == 7362
        and len(edges) == 4278
        and len(keys) == 3681
        and len(region_metadata) == 20,
        "table_keys_are_unique": not inputs.duplicated(
            ["region_id", "node_id"]
        ).any()
        and not history.duplicated(["region_id", "node_id", "year"]).any()
        and not edges.duplicated(["region_id", "edge_id"]).any()
        and not keys.duplicated(expected_key_columns).any(),
        "region_ids_match_lockbox": sorted(inputs["region_id"].unique())
        == sorted(expected_region_ids),
        "node_ids_match_raster_positions": all(
            row.node_id == _node_id(int(row.raster_row), int(row.raster_column))
            for row in inputs.itertuples(index=False)
        ),
        "source_raster_values_match_bundle": source_values_match,
        "source_coordinates_match_bundle": coordinates_match,
        "state_history_matches_wide_inputs": history_matches_inputs,
        "edges_equal_exact_reconstructed_graph": bundled_edge_frame.equals(
            reconstructed_edge_frame
        ),
        "submission_keys_equal_node_year_cross_product": bundled_keys.equals(
            expected_keys
        ),
        "bundle_contains_no_target_label_columns": not any(
            "target_class" in column or "observed_2023" in column
            for frame in (inputs, history, edges, keys)
            for column in frame.columns
        ),
        "bundle_maximum_input_year_is_2022": int(history["year"].max())
        == 2022
        and bundle_manifest["label_boundary"]["maximum_input_year"] == 2022,
        "target_directory_contains_no_files": not target_files,
        "target_pixels_read_by_verifier_is_false": True,
    }
    passed = all(checks.values())
    report = {
        "schema": "gwm_bench.foundation_v3_phase_a_bundle_verification.v1",
        "suite_id": protocol["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_PHASE_A_BUNDLE_VERIFIED" if passed else "FAIL",
        "check_count": len(checks),
        "checks": checks,
        "artifact_checks": artifact_checks,
        "value_comparison_count": value_comparisons,
        "counts": bundle_manifest["counts"],
        "bundle_fingerprint": bundle_manifest["bundle_fingerprint"],
        "target_file_count": len(target_files),
        "target_pixels_read_by_verifier": False,
        "next_permitted_action": (
            "Freeze Runtime-R2 submission and evaluator contracts; do not acquire targets."
            if passed
            else "Repair Phase A bundle without acquiring targets."
        ),
    }
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"GWM-Bench V3 Phase A bundle: {report['status']}")
    print(f"Verification report: {output_path}")
    return report


if __name__ == "__main__":
    result = verify()
    raise SystemExit(
        0 if result["status"] == "PASS_PHASE_A_BUNDLE_VERIFIED" else 1
    )
