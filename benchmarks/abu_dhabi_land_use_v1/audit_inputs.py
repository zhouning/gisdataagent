#!/usr/bin/env python3
"""Audit completeness, alignment and temporal signal of benchmark inputs."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio

HERE = Path(__file__).resolve().parent
DEFAULT_GRID_PROFILE = HERE / "grid_profile.json"
DEFAULT_CITY_MASK = HERE / "artifacts/abu_dhabi_city_100m_mask.tif"
DEFAULT_INPUT_ROOT = HERE / "artifacts/gee"
DEFAULT_OUTPUT = HERE / "data_audit.json"
YEARS = tuple(range(2017, 2025))
CLASSES = tuple(range(1, 7))
NODATA_FLOAT = -32768.0


def _grid(profile_path: Path) -> dict[str, Any]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    return {
        "crs": str(profile["crs"]),
        "width": int(profile["width"]),
        "height": int(profile["height"]),
        "transform": tuple(float(value) for value in profile["transform_gdal"]),
        "resolution_m": int(profile["resolution_m"]),
    }


def _read(
    path: Path,
    *,
    grid: dict[str, Any],
    expected_count: int,
) -> tuple[np.ndarray, float | int | None, tuple[str | None, ...]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with rasterio.open(path) as dataset:
        if dataset.crs is None or dataset.crs.to_string() != grid["crs"]:
            raise ValueError(f"crs_mismatch:{path}")
        if (dataset.width, dataset.height) != (grid["width"], grid["height"]):
            raise ValueError(f"shape_mismatch:{path}")
        if dataset.count != expected_count:
            raise ValueError(f"band_count_mismatch:{path}:{dataset.count}")
        if tuple(dataset.transform.to_gdal()) != grid["transform"]:
            raise ValueError(f"transform_mismatch:{path}")
        return dataset.read(), dataset.nodata, dataset.descriptions


def _summary(values: np.ndarray) -> dict[str, float]:
    return {
        "min": float(np.min(values)),
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "max": float(np.max(values)),
    }


def audit(
    *,
    grid_profile_path: Path = DEFAULT_GRID_PROFILE,
    city_mask_path: Path = DEFAULT_CITY_MASK,
    input_root: Path = DEFAULT_INPUT_ROOT,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    grid = _grid(grid_profile_path)
    city_data, _, _ = _read(city_mask_path, grid=grid, expected_count=1)
    city = city_data[0].astype(bool)
    city_count = int(city.sum())
    states: dict[int, np.ndarray] = {}
    state_rows = []
    quality_rows = []
    outside_clean = True
    for year in YEARS:
        state_data, _, _ = _read(
            input_root / "land_cover" / f"land_cover_{year}_100m.tif",
            grid=grid,
            expected_count=1,
        )
        state = state_data[0].astype(np.uint8)
        states[year] = state
        outside_clean &= not np.any(state[~city] != 0)
        class_counts = {
            str(value): int(np.count_nonzero(state[city] == value)) for value in CLASSES
        }
        valid_count = sum(class_counts.values())
        state_rows.append(
            {
                "year": year,
                "valid_pixel_count": valid_count,
                "nodata_pixel_count": city_count - valid_count,
                "nodata_fraction": float((city_count - valid_count) / city_count),
                "class_pixel_counts": class_counts,
                "class_area_km2": {
                    key: float(value * grid["resolution_m"] ** 2 / 1_000_000.0)
                    for key, value in class_counts.items()
                },
            }
        )
        quality, nodata, _ = _read(
            input_root / "land_cover" / f"land_cover_quality_{year}_100m.tif",
            grid=grid,
            expected_count=2,
        )
        quality_valid = city & np.all(quality != nodata, axis=0)
        outside_clean &= not np.any(quality[:, ~city] != nodata)
        quality_rows.append(
            {
                "year": year,
                "valid_pixel_count": int(quality_valid.sum()),
                "mean_top_probability": _summary(quality[0][quality_valid]),
                "observation_count": _summary(quality[1][quality_valid]),
                "fraction_below_confidence_0_5": float(
                    np.mean(quality[0][quality_valid] < 0.5)
                ),
            }
        )

    pair_rows = []
    for start_year, target_year in zip(YEARS[:-1], YEARS[1:], strict=True):
        start = states[start_year]
        target = states[target_year]
        valid = city & np.isin(start, CLASSES) & np.isin(target, CLASSES)
        changed = valid & (start != target)
        transition_counts = np.zeros((len(CLASSES), len(CLASSES)), dtype=np.int64)
        np.add.at(
            transition_counts,
            (start[valid].astype(np.int64) - 1, target[valid].astype(np.int64) - 1),
            1,
        )
        pair_rows.append(
            {
                "start_year": start_year,
                "target_year": target_year,
                "valid_pixel_count": int(valid.sum()),
                "changed_pixel_count": int(changed.sum()),
                "change_fraction": float(changed.sum() / valid.sum()),
                "built_gain_pixels": int(np.count_nonzero(valid & (start != 5) & (target == 5))),
                "built_loss_pixels": int(np.count_nonzero(valid & (start == 5) & (target != 5))),
                "transition_counts": transition_counts.tolist(),
            }
        )

    reversion_rows = []
    for previous_year, middle_year, next_year in zip(
        YEARS[:-2], YEARS[1:-1], YEARS[2:], strict=True
    ):
        previous = states[previous_year]
        middle = states[middle_year]
        following = states[next_year]
        valid = city & np.isin(previous, CLASSES) & np.isin(middle, CLASSES) & np.isin(
            following, CLASSES
        )
        changed = valid & (previous != middle)
        reverted = changed & (following == previous)
        reversion_rows.append(
            {
                "years": [previous_year, middle_year, next_year],
                "middle_year_change_pixels": int(changed.sum()),
                "one_year_reversion_pixels": int(reverted.sum()),
                "one_year_reversion_fraction": float(reverted.sum() / max(1, changed.sum())),
            }
        )

    alpha_rows = []
    alpha_arrays: dict[int, np.ndarray] = {}
    alpha_valid: dict[int, np.ndarray] = {}
    for year in YEARS:
        embedding, nodata, _ = _read(
            input_root / "alphaearth" / f"alphaearth_{year}_100m.tif",
            grid=grid,
            expected_count=64,
        )
        valid = city & np.all(embedding != nodata, axis=0)
        norm = np.linalg.norm(embedding[:, valid], axis=0)
        outside_clean &= not np.any(embedding[:, ~city] != nodata)
        alpha_arrays[year] = embedding
        alpha_valid[year] = valid
        alpha_rows.append(
            {
                "year": year,
                "valid_pixel_count": int(valid.sum()),
                "city_coverage_fraction": float(valid.sum() / city_count),
                "l2_norm": _summary(norm),
            }
        )

    alpha_pair_rows = []
    for start_year, target_year in zip(YEARS[:-1], YEARS[1:], strict=True):
        valid = alpha_valid[start_year] & alpha_valid[target_year]
        cosine = np.sum(
            alpha_arrays[start_year][:, valid] * alpha_arrays[target_year][:, valid],
            axis=0,
        )
        state_valid = valid & np.isin(states[start_year], CLASSES) & np.isin(
            states[target_year], CLASSES
        )
        changed = state_valid & (states[start_year] != states[target_year])
        stable = state_valid & ~changed
        changed_cosine = np.sum(
            alpha_arrays[start_year][:, changed] * alpha_arrays[target_year][:, changed],
            axis=0,
        )
        stable_cosine = np.sum(
            alpha_arrays[start_year][:, stable] * alpha_arrays[target_year][:, stable],
            axis=0,
        )
        alpha_pair_rows.append(
            {
                "start_year": start_year,
                "target_year": target_year,
                "cosine_all": _summary(cosine),
                "cosine_changed_mean": float(np.mean(changed_cosine)),
                "cosine_stable_mean": float(np.mean(stable_cosine)),
                "changed_minus_stable_cosine": float(
                    np.mean(changed_cosine) - np.mean(stable_cosine)
                ),
            }
        )

    viirs_rows = []
    for year in YEARS:
        values, nodata, _ = _read(
            input_root / "viirs" / f"viirs_{year}_100m.tif",
            grid=grid,
            expected_count=1,
        )
        valid = city & (values[0] != nodata) & np.isfinite(values[0])
        outside_clean &= not np.any(values[:, ~city] != nodata)
        viirs_rows.append(
            {
                "year": year,
                "valid_pixel_count": int(valid.sum()),
                "annual_mean_radiance": _summary(values[0][valid]),
            }
        )

    terrain, terrain_nodata, terrain_descriptions = _read(
        input_root / "terrain" / "copernicus_dem_2024_1_slope_100m.tif",
        grid=grid,
        expected_count=2,
    )
    terrain_valid = city & np.all(terrain != terrain_nodata, axis=0)
    outside_clean &= not np.any(terrain[:, ~city] != terrain_nodata)
    constraints, _, constraint_descriptions = _read(
        input_root / "constraints" / "esa_worldcover_2021_water_ecological_100m.tif",
        grid=grid,
        expected_count=2,
    )
    water_mask = city & constraints[0].astype(bool)
    ecological_mask = city & constraints[1].astype(bool)

    median_reversion = float(
        np.median([row["one_year_reversion_fraction"] for row in reversion_rows])
    )
    low_confidence_fraction = float(
        np.mean([row["fraction_below_confidence_0_5"] for row in quality_rows])
    )
    gates = {
        "all_required_files_aligned": True,
        "all_outputs_clean_outside_city_mask": bool(outside_clean),
        "maximum_land_cover_nodata_fraction_le_0_001": max(
            row["nodata_fraction"] for row in state_rows
        )
        <= 0.001,
        "alphaearth_city_coverage_at_least_0_99": min(
            row["city_coverage_fraction"] for row in alpha_rows
        )
        >= 0.99,
        "alphaearth_l2_norm_error_below_1e_5": max(
            abs(row["l2_norm"][key] - 1.0)
            for row in alpha_rows
            for key in ("min", "mean", "max")
        )
        < 1e-5,
        "every_transition_has_observed_change": all(
            row["changed_pixel_count"] > 0 for row in pair_rows
        ),
    }
    report = {
        "schema": "gwm.abu_dhabi_input_audit.v1",
        "benchmark_id": "abu-dhabi-land-use-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "PASS_WITH_LABEL_NOISE_WARNING" if all(gates.values()) else "FAIL",
        "gates": gates,
        "grid": {**grid, "city_pixel_count": city_count},
        "land_cover_by_year": state_rows,
        "land_cover_quality_by_year": quality_rows,
        "land_cover_transitions": pair_rows,
        "one_year_reversions": reversion_rows,
        "alphaearth_by_year": alpha_rows,
        "alphaearth_transitions": alpha_pair_rows,
        "viirs_by_year": viirs_rows,
        "terrain": {
            "valid_pixel_count": int(terrain_valid.sum()),
            "bands": {
                str(description): _summary(terrain[index][terrain_valid])
                for index, description in enumerate(terrain_descriptions)
            },
        },
        "constraints": {
            "bands": list(constraint_descriptions),
            "permanent_water_pixels": int(water_mask.sum()),
            "permanent_water_area_km2": float(
                water_mask.sum() * grid["resolution_m"] ** 2 / 1_000_000.0
            ),
            "wetland_or_mangrove_pixels": int(ecological_mask.sum()),
            "wetland_or_mangrove_area_km2": float(
                ecological_mask.sum() * grid["resolution_m"] ** 2 / 1_000_000.0
            ),
        },
        "warnings": {
            "mean_fraction_below_dynamic_world_confidence_0_5": low_confidence_fraction,
            "median_one_year_land_cover_reversion_fraction": median_reversion,
            "interpretation": (
                "Annual Dynamic World labels contain classification volatility. "
                "Models must be scored both on all valid pixels and on a confidence/stability "
                "sensitivity mask; observed changes are not treated as observed policy actions."
            ),
        },
    }
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--grid-profile", type=Path, default=DEFAULT_GRID_PROFILE)
    parser.add_argument("--city-mask", type=Path, default=DEFAULT_CITY_MASK)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = audit(
        grid_profile_path=args.grid_profile,
        city_mask_path=args.city_mask,
        input_root=args.input_root,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "gates": report["gates"],
                "warnings": report["warnings"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
