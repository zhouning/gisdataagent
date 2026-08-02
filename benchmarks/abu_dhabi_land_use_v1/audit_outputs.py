#!/usr/bin/env python3
"""Hash and validate every published historical and planning prediction."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio

HERE = Path(__file__).resolve().parent
BUNDLE_ROOT = HERE / "artifacts/bundle"
INPUT_ROOT = HERE / "artifacts/gee"
DEFAULT_OUTPUT = HERE / "output_audit.json"
CLASSES = tuple(range(1, 7))


def _read(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    with rasterio.open(path) as dataset:
        return dataset.read(1), dataset.profile.copy()


def _resolve(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else HERE / path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _historical_records() -> list[dict[str, Any]]:
    records = []
    for model_id in ("geosos_flus", "geospatial_kernel", "paper58"):
        report = json.loads(
            (HERE / f"artifacts/predictions/{model_id}/report.json").read_text(
                encoding="utf-8"
            )
        )
        for seed in report["seeds"]:
            for year in seed["years"]:
                records.append(
                    {
                        "track": "historical_seed",
                        "model_id": model_id,
                        "seed": int(seed["seed"]),
                        "target_year": int(year["target_year"]),
                        "path": year["prediction_path"],
                        "origin_year": 2022,
                    }
                )
    comparison = json.loads((HERE / "comparison_report.json").read_text(encoding="utf-8"))
    for model_id, years in comparison["ensembles"].items():
        for year, row in years.items():
            records.append(
                {
                    "track": "historical_ensemble",
                    "model_id": model_id,
                    "seed": None,
                    "target_year": int(year),
                    "path": row["prediction_path"],
                    "origin_year": 2022,
                }
            )
    return records


def _planning_records() -> list[dict[str, Any]]:
    records = []
    source = json.loads(
        (HERE / "planning_scenario_report.json").read_text(encoding="utf-8")
    )
    for model_id, model in source["models"].items():
        for seed in model["seeds"]:
            for scenario in seed["scenarios"]:
                for year in scenario["years"]:
                    records.append(
                        {
                            "track": "planning_seed",
                            "model_id": model_id,
                            "scenario_id": scenario["scenario_id"],
                            "seed": int(seed["seed"]),
                            "target_year": int(year["target_year"]),
                            "path": year["prediction_path"],
                            "origin_year": 2024,
                        }
                    )
    comparison = json.loads(
        (HERE / "planning_comparison_report.json").read_text(encoding="utf-8")
    )
    for model_id, scenarios in comparison["ensembles"].items():
        for scenario_id, years in scenarios.items():
            for year, row in years.items():
                records.append(
                    {
                        "track": "planning_ensemble",
                        "model_id": model_id,
                        "scenario_id": scenario_id,
                        "seed": None,
                        "target_year": int(year),
                        "path": row["prediction_path"],
                        "origin_year": 2024,
                    }
                )
    return records


def audit(*, output_path: Path) -> dict[str, Any]:
    valid, reference = _read(BUNDLE_ROOT / "common_valid_mask_100m.tif")
    valid_mask = valid.astype(bool)
    origins = {
        year: _read(INPUT_ROOT / f"land_cover/land_cover_{year}_100m.tif")[0]
        for year in (2022, 2024)
    }
    hard_masks = {
        year: _read(BUNDLE_ROOT / f"hard_exclusion_{year}_100m.tif")[0].astype(bool)
        for year in (2022, 2024)
    }
    records = _historical_records() + _planning_records()
    if len(records) != 240:
        raise ValueError(f"unexpected_prediction_record_count:{len(records)}")
    if len({_resolve(row["path"]).resolve() for row in records}) != len(records):
        raise ValueError("duplicate_prediction_paths")

    artifacts = []
    failure_count = 0
    for record in records:
        path = _resolve(record["path"])
        values, profile = _read(path)
        origin_year = int(record["origin_year"])
        aligned = (
            profile["width"] == reference["width"]
            and profile["height"] == reference["height"]
            and profile["crs"] == reference["crs"]
            and profile["transform"] == reference["transform"]
        )
        invalid_class_pixels = int(
            np.count_nonzero(valid_mask & ~np.isin(values, CLASSES))
        )
        nonzero_outside = int(np.count_nonzero(values[~valid_mask]))
        constraint_violations = int(
            np.count_nonzero(
                valid_mask
                & hard_masks[origin_year]
                & (values != origins[origin_year])
            )
        )
        valid_output = (
            aligned
            and invalid_class_pixels == 0
            and nonzero_outside == 0
            and constraint_violations == 0
        )
        failure_count += int(not valid_output)
        artifacts.append(
            {
                **record,
                "path": str(path.relative_to(HERE)),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "grid_aligned": aligned,
                "invalid_class_pixels": invalid_class_pixels,
                "nonzero_outside_valid_pixels": nonzero_outside,
                "constraint_violation_pixels": constraint_violations,
                "valid": valid_output,
            }
        )
    report = {
        "schema": "gwm.abu_dhabi_output_audit.v1",
        "benchmark_id": "abu-dhabi-land-use-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if failure_count == 0 else "FAIL",
        "prediction_count": len(artifacts),
        "failure_count": failure_count,
        "track_counts": {
            track: sum(row["track"] == track for row in artifacts)
            for track in (
                "historical_seed",
                "historical_ensemble",
                "planning_seed",
                "planning_ensemble",
            )
        },
        "artifacts": artifacts,
    }
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = audit(output_path=args.output)
    print(
        json.dumps(
            {
                "status": report["status"],
                "prediction_count": report["prediction_count"],
                "failure_count": report["failure_count"],
            }
        )
    )


if __name__ == "__main__":
    main()
