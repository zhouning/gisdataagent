#!/usr/bin/env python3
"""Freeze shared masks, actions and scenarios consumed by all candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from shared import CLASSES, class_counts, feasible_target_counts

HERE = Path(__file__).resolve().parent
DEFAULT_INPUT_ROOT = HERE / "artifacts/gee"
DEFAULT_OSM_ROOT = HERE / "artifacts/osm"
DEFAULT_CITY_MASK = HERE / "artifacts/abu_dhabi_city_100m_mask.tif"
DEFAULT_OUTPUT_ROOT = HERE / "artifacts/bundle"
DEFAULT_MANIFEST = HERE / "bundle_manifest.json"
YEARS = tuple(range(2017, 2025))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    with rasterio.open(path) as dataset:
        return dataset.read(), dataset.profile.copy()


def _write_like(
    path: Path,
    data: np.ndarray,
    *,
    reference_profile: dict[str, Any],
    descriptions: tuple[str, ...],
    nodata: int = 0,
) -> None:
    values = data if data.ndim == 3 else data[None, ...]
    profile = reference_profile.copy()
    profile.update(
        count=len(values),
        dtype=str(values.dtype),
        nodata=nodata,
        compress="deflate",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f".partial.{os.getpid()}.tif")
    with rasterio.open(temp_path, "w", **profile) as dataset:
        dataset.write(values)
        for index, description in enumerate(descriptions, start=1):
            dataset.set_band_description(index, description)
    os.replace(temp_path, path)


def _scenario_counts(
    origin_counts: dict[int, int],
    *,
    annual_built_gain: int,
    annual_green_gain: int,
    years: tuple[int, ...],
) -> dict[int, dict[int, int]]:
    current = dict(origin_counts)
    result = {}
    for year in years:
        built_gain = min(annual_built_gain, max(0, current[6]))
        current[6] -= built_gain
        current[5] += built_gain
        green_gain = min(annual_green_gain, max(0, current[6]))
        current[6] -= green_gain
        current[3] += green_gain
        result[year] = dict(current)
    return result


def build_bundle(
    *,
    input_root: Path,
    osm_root: Path,
    city_mask_path: Path,
    output_root: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    city_data, reference_profile = _read(city_mask_path)
    city = city_data[0].astype(bool)
    states = {
        year: _read(input_root / "land_cover" / f"land_cover_{year}_100m.tif")[0][0]
        for year in YEARS
    }
    qualities = {
        year: _read(
            input_root / "land_cover" / f"land_cover_quality_{year}_100m.tif"
        )[0]
        for year in YEARS
    }
    esa_constraints, _ = _read(
        input_root / "constraints" / "esa_worldcover_2021_water_ecological_100m.tif"
    )
    osm_constraints, _ = _read(osm_root / "osm_public_proxy_constraints_100m.tif")
    common_valid = city.copy()
    for state in states.values():
        common_valid &= np.isin(state, CLASSES)
    static_exclusion = city & (
        esa_constraints[0].astype(bool)
        | esa_constraints[1].astype(bool)
        | osm_constraints[0].astype(bool)
        | osm_constraints[1].astype(bool)
    )
    hard_masks = {}
    for origin_year in (2022, 2024):
        hard = common_valid & (
            static_exclusion | np.isin(states[origin_year], (1, 4))
        )
        hard_masks[origin_year] = hard
        _write_like(
            output_root / f"hard_exclusion_{origin_year}_100m.tif",
            hard.astype(np.uint8),
            reference_profile=reference_profile,
            descriptions=("hard_exclusion",),
        )
    _write_like(
        output_root / "common_valid_mask_100m.tif",
        common_valid.astype(np.uint8),
        reference_profile=reference_profile,
        descriptions=("common_valid_2017_2024",),
    )

    actions = []
    for start_year, target_year in ((2022, 2023), (2023, 2024)):
        desired = class_counts(states[target_year], common_valid)
        feasible = feasible_target_counts(
            desired,
            origin_state=states[2022],
            valid_mask=common_valid,
            hard_exclusion_mask=hard_masks[2022],
        )
        reliability = (
            common_valid
            & (qualities[start_year][0] >= 0.5)
            & (qualities[target_year][0] >= 0.5)
        )
        reliability_path = output_root / f"reliability_{start_year}_{target_year}_100m.tif"
        _write_like(
            reliability_path,
            reliability.astype(np.uint8),
            reference_profile=reference_profile,
            descriptions=("dynamic_world_confidence_ge_0_5_both_years",),
        )
        actions.append(
            {
                "schema": "gwm.land_use_demand_action.v1",
                "action_id": f"oracle_allocation_{start_year}_{target_year}",
                "source": "observed_allocation",
                "start_year": start_year,
                "target_year": target_year,
                "desired_observed_counts": {str(key): value for key, value in desired.items()},
                "feasible_target_counts": {str(key): value for key, value in feasible.items()},
                "hard_exclusion_origin_year": 2022,
                "reliability_mask": str(reliability_path.relative_to(HERE)),
                "model_may_read_reliability_mask": False,
            }
        )

    scenario_years = tuple(range(2025, 2031))
    origin_counts = class_counts(states[2024], common_valid)
    scenario_specs = {
        "compact": (500, 50),
        "ecological_priority": (350, 150),
        "outward_growth": (1000, 25),
    }
    scenarios = []
    for scenario_id, (built_gain, green_gain) in scenario_specs.items():
        counts_by_year = _scenario_counts(
            origin_counts,
            annual_built_gain=built_gain,
            annual_green_gain=green_gain,
            years=scenario_years,
        )
        scenarios.append(
            {
                "schema": "gwm.land_use_scenario.v1",
                "scenario_id": scenario_id,
                "source": "scenario_target",
                "origin_year": 2024,
                "annual_built_gain_pixels": built_gain,
                "annual_green_gain_pixels": green_gain,
                "target_counts_by_year": {
                    str(year): {str(key): value for key, value in counts.items()}
                    for year, counts in counts_by_year.items()
                },
                "interpretation": "Planner-supplied stress-test action, not a forecast.",
            }
        )

    actions_path = output_root / "allocation_actions.json"
    actions_path.write_text(
        json.dumps({"actions": actions}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    scenarios_path = output_root / "planning_scenarios.json"
    scenarios_path.write_text(
        json.dumps({"scenarios": scenarios}, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    artifact_paths = [
        output_root / "common_valid_mask_100m.tif",
        output_root / "hard_exclusion_2022_100m.tif",
        output_root / "hard_exclusion_2024_100m.tif",
        output_root / "reliability_2022_2023_100m.tif",
        output_root / "reliability_2023_2024_100m.tif",
        actions_path,
        scenarios_path,
    ]
    report = {
        "schema": "gwm.abu_dhabi_benchmark_bundle.v1",
        "benchmark_id": "abu-dhabi-land-use-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "complete",
        "common_valid_pixel_count": int(common_valid.sum()),
        "static_exclusion_pixel_count": int(static_exclusion.sum()),
        "hard_exclusion_pixel_counts": {
            str(year): int(mask.sum()) for year, mask in hard_masks.items()
        },
        "actions": actions,
        "scenarios": scenarios,
        "artifacts": [
            {
                "path": str(path.relative_to(HERE)),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in artifact_paths
        ],
    }
    manifest_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--osm-root", type=Path, default=DEFAULT_OSM_ROOT)
    parser.add_argument("--city-mask", type=Path, default=DEFAULT_CITY_MASK)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    report = build_bundle(
        input_root=args.input_root,
        osm_root=args.osm_root,
        city_mask_path=args.city_mask,
        output_root=args.output_root,
        manifest_path=args.manifest,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "common_valid_pixel_count": report["common_valid_pixel_count"],
                "hard_exclusion_pixel_counts": report["hard_exclusion_pixel_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
