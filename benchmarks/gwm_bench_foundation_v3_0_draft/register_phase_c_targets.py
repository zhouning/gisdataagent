#!/usr/bin/env python3
"""Validate and register V3 Phase C targets after prediction commitment."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio

from prediction_runtime import (
    BUNDLE_ROOT,
    DRAFT_ROOT,
    KEY_COLUMNS,
    PROTOCOL_PATH,
    REPO_ROOT,
    artifact,
    fingerprint,
    load_json,
    sha256_file,
    utc_now,
    write_json_atomic,
    write_parquet_atomic,
)


PREDICTION_ROOT = DRAFT_ROOT / "predictions"
COMMITMENT_PATH = PREDICTION_ROOT / "prediction_commitment.json"
COMMITMENT_VERIFICATION_PATH = (
    PREDICTION_ROOT / "prediction_commitment_verification.json"
)
TARGET_ROOT = (
    REPO_ROOT
    / "data/twm_public_landcover/gee_dynamic_world_v3_lockbox_targets_2023_2025"
)
TARGET_MANIFEST_PATH = TARGET_ROOT / "manifest.json"
TARGET_STATUS_PATH = TARGET_ROOT / "download_status.json"
PHASE_C_ROOT = DRAFT_ROOT / "phase_c_targets"
LABELS_PATH = PHASE_C_ROOT / "observed_targets.parquet"
REGISTRY_PATH = PHASE_C_ROOT / "target_registry.json"
DEFAULT_REPORT = PHASE_C_ROOT / "target_registration_report.json"
TARGET_YEARS = (2023, 2024, 2025)


def register(output_path: Path = DEFAULT_REPORT) -> dict[str, Any]:
    protocol = load_json(PROTOCOL_PATH)
    commitment = load_json(COMMITMENT_PATH)
    verification = load_json(COMMITMENT_VERIFICATION_PATH)
    if verification["status"] != (
        "PASS_RC2_PREDICTIONS_COMMITTED_TARGET_ACQUISITION_ALLOWED"
    ):
        raise ValueError("prediction_commitment_was_not_verified_before_targets")
    if verification["commitment"]["sha256"] != sha256_file(COMMITMENT_PATH):
        raise ValueError("prediction_commitment_changed_after_verification")
    if commitment["commitment_fingerprint"] != verification[
        "commitment_fingerprint"
    ]:
        raise ValueError("prediction_commitment_fingerprint_mismatch")

    target_manifest = load_json(TARGET_MANIFEST_PATH)
    download_status = load_json(TARGET_STATUS_PATH)
    phase_a_root = REPO_ROOT / protocol["dataset"]["phase_a_input_root"]
    phase_a_manifest = load_json(phase_a_root / "manifest.json")
    inputs = pd.read_parquet(BUNDLE_ROOT / "observed_inputs.parquet")
    expected_keys = pd.read_parquet(BUNDLE_ROOT / "submission_keys.parquet").sort_values(
        KEY_COLUMNS, kind="mergesort"
    ).reset_index(drop=True)

    target_regions = {
        row["region_id"]: row for row in target_manifest["regions"]
    }
    phase_a_regions = {
        row["region_id"]: row for row in phase_a_manifest["regions"]
    }
    expected_region_ids = sorted(inputs["region_id"].unique())
    checks: dict[str, bool] = {
        "prediction_commitment_precedes_target_registration": COMMITMENT_PATH.stat().st_mtime
        <= TARGET_MANIFEST_PATH.stat().st_mtime,
        "download_status_passed": download_status["status"] == "pass",
        "target_manifest_has_exact_years": target_manifest["years"]
        == list(TARGET_YEARS),
        "target_manifest_has_exact_regions": sorted(target_regions)
        == expected_region_ids,
        "phase_a_regions_match_targets": sorted(phase_a_regions)
        == expected_region_ids,
        "all_target_files_exist": True,
        "all_target_grids_match_phase_a": True,
        "all_target_pixels_are_valid_classes_at_fixed_nodes": True,
        "label_keys_match_submission_keys": True,
        "all_target_files_created_after_commitment": True,
    }

    artifact_rows = []
    label_rows = []
    class_counts = {str(index): 0 for index in range(9)}
    for region_id in expected_region_ids:
        target_by_year = {
            int(row["year"]): row for row in target_regions[region_id]["raster_stack"]
        }
        phase_a_by_year = {
            int(row["year"]): row for row in phase_a_regions[region_id]["raster_stack"]
        }
        region_inputs = inputs[inputs["region_id"] == region_id].sort_values(
            "node_id", kind="mergesort"
        )
        rows = region_inputs["raster_row"].to_numpy(dtype=np.int64)
        columns = region_inputs["raster_column"].to_numpy(dtype=np.int64)
        reference_path = phase_a_root / phase_a_by_year[2022]["path"]
        with rasterio.open(reference_path) as reference:
            reference_grid = (reference.shape, reference.transform, reference.crs)
        for year in TARGET_YEARS:
            row = target_by_year.get(year)
            if row is None:
                checks["all_target_files_exist"] = False
                continue
            path = TARGET_ROOT / row["path"]
            if not path.is_file():
                checks["all_target_files_exist"] = False
                continue
            checks["all_target_files_created_after_commitment"] = checks[
                "all_target_files_created_after_commitment"
            ] and path.stat().st_mtime >= COMMITMENT_PATH.stat().st_mtime
            with rasterio.open(path) as dataset:
                target_grid = (dataset.shape, dataset.transform, dataset.crs)
                values = dataset.read(1)
            checks["all_target_grids_match_phase_a"] = checks[
                "all_target_grids_match_phase_a"
            ] and target_grid == reference_grid
            observed = values[rows, columns].astype(np.int64)
            valid = (observed >= 0) & (observed < 9)
            checks["all_target_pixels_are_valid_classes_at_fixed_nodes"] = checks[
                "all_target_pixels_are_valid_classes_at_fixed_nodes"
            ] and bool(valid.all())
            if not valid.all():
                raise ValueError(f"invalid_target_class_at_fixed_node:{region_id}:{year}")
            for input_row, target_class in zip(
                region_inputs.itertuples(index=False), observed
            ):
                label_rows.append(
                    {
                        "region_id": region_id,
                        "node_id": input_row.node_id,
                        "target_year": year,
                        "target_class": int(target_class),
                    }
                )
                class_counts[str(int(target_class))] += 1
            artifact_rows.append(
                {
                    "region_id": region_id,
                    "year": year,
                    "path": str(path.relative_to(REPO_ROOT)),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                    "shape": list(target_grid[0]),
                    "crs": str(target_grid[2]),
                }
            )

    labels = pd.DataFrame(
        label_rows, columns=KEY_COLUMNS + ["target_class"]
    ).sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
    checks["label_keys_match_submission_keys"] = (
        len(labels) == len(expected_keys)
        and not labels.duplicated(KEY_COLUMNS).any()
        and labels[KEY_COLUMNS].equals(expected_keys[KEY_COLUMNS])
    )
    if not all(checks.values()):
        raise RuntimeError(f"phase_c_target_registration_failed:{checks}")

    PHASE_C_ROOT.mkdir(parents=True, exist_ok=True)
    write_parquet_atomic(labels, LABELS_PATH)

    origins = inputs[["region_id", "node_id", "land_class_2022"]].rename(
        columns={"land_class_2022": "origin_class"}
    )
    trajectory = labels.merge(origins, on=["region_id", "node_id"], validate="many_to_one")
    step_change_counts = {}
    regions_with_change = set()
    for (region_id, node_id), group in trajectory.groupby(
        ["region_id", "node_id"], sort=False
    ):
        group = group.sort_values("target_year", kind="mergesort")
        previous = int(group.iloc[0]["origin_class"])
        for row in group.itertuples(index=False):
            changed = int(row.target_class) != previous
            step_change_counts[str(int(row.target_year))] = step_change_counts.get(
                str(int(row.target_year)), 0
            ) + int(changed)
            if changed:
                regions_with_change.add(region_id)
            previous = int(row.target_class)

    registry_identity = {
        "suite_id": protocol["suite_id"],
        "prediction_commitment_fingerprint": commitment[
            "commitment_fingerprint"
        ],
        "prediction_commitment_sha256": sha256_file(COMMITMENT_PATH),
        "target_manifest_sha256": sha256_file(TARGET_MANIFEST_PATH),
        "download_status_sha256": sha256_file(TARGET_STATUS_PATH),
        "target_artifacts": artifact_rows,
        "labels_sha256": sha256_file(LABELS_PATH),
    }
    registry = {
        "schema": "gwm_bench.v3_phase_c_target_registry.v1",
        "suite_id": protocol["suite_id"],
        "status": "PHASE_C_TARGETS_REGISTERED_AFTER_PREDICTION_COMMITMENT",
        "registered_at": utc_now(),
        "registry_identity": registry_identity,
        "target_dataset_fingerprint": fingerprint(registry_identity),
        "counts": {
            "region_count": len(expected_region_ids),
            "target_raster_count": len(artifact_rows),
            "label_row_count": len(labels),
            "class_counts": class_counts,
            "step_change_counts": step_change_counts,
            "total_step_change_count": sum(step_change_counts.values()),
            "regions_with_at_least_one_change": len(regions_with_change),
        },
        "artifacts": {
            "labels": artifact(LABELS_PATH, role="registered_v3_observed_targets"),
            "target_manifest": artifact(
                TARGET_MANIFEST_PATH, role="phase_c_source_manifest"
            ),
            "download_status": artifact(
                TARGET_STATUS_PATH, role="phase_c_download_status"
            ),
        },
        "target_artifacts": artifact_rows,
        "prediction_commitment_preceded_target_access": True,
    }
    write_json_atomic(registry, REGISTRY_PATH)

    report = {
        "schema": "gwm_bench.v3_phase_c_target_registration_report.v1",
        "suite_id": protocol["suite_id"],
        "status": "PASS_PHASE_C_TARGETS_REGISTERED_SCORING_ALLOWED",
        "created_at": utc_now(),
        "checks": checks,
        "prediction_commitment_fingerprint": commitment[
            "commitment_fingerprint"
        ],
        "target_dataset_fingerprint": registry["target_dataset_fingerprint"],
        "counts": registry["counts"],
        "registry": artifact(REGISTRY_PATH, role="phase_c_target_registry"),
        "labels": registry["artifacts"]["labels"],
        "scoring_allowed": True,
    }
    write_json_atomic(report, output_path)
    print(report["status"])
    print(f"target_dataset_fingerprint: {registry['target_dataset_fingerprint']}")
    print(f"labels: {LABELS_PATH}")
    print(f"report: {output_path}")
    return report


if __name__ == "__main__":
    register()
