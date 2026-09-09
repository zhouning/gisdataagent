#!/usr/bin/env python3
"""Prepare a small customer-DTM grid for a SWMM--ANUGA pilot run.

The generated NPZ and metadata are runtime artifacts and should be written
outside the repository.  The SWMM input is read-only; no customer file is
modified.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import from_bounds


def parse_coordinates(path: Path) -> dict[str, tuple[float, float]]:
    result: dict[str, tuple[float, float]] = {}
    section = ""
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line.upper()
            continue
        if section != "[COORDINATES]" or not line or line.startswith(";"):
            continue
        values = line.split()
        if len(values) >= 3:
            try:
                result[values[0]] = (float(values[1]), float(values[2]))
            except ValueError:
                pass
    if not result:
        raise ValueError("pilot_grid_swmm_coordinates_missing")
    return result


def prepare(
    swmm_inp: Path,
    dtm: Path,
    output: Path,
    *,
    max_interfaces: int = 16,
    cell_size_m: float = 25.0,
    margin_m: float = 150.0,
) -> dict[str, object]:
    if max_interfaces <= 0 or cell_size_m <= 0.0 or margin_m < 0.0:
        raise ValueError("pilot_grid_parameters_invalid")
    coordinates = parse_coordinates(swmm_inp)
    node_ids = sorted(coordinates)[:max_interfaces]
    points = [coordinates[node_id] for node_id in node_ids]
    xmin = min(point[0] for point in points) - margin_m
    xmax = max(point[0] for point in points) + margin_m
    ymin = min(point[1] for point in points) - margin_m
    ymax = max(point[1] for point in points) + margin_m
    xmin = np.floor(xmin / cell_size_m) * cell_size_m
    ymin = np.floor(ymin / cell_size_m) * cell_size_m
    xmax = np.ceil(xmax / cell_size_m) * cell_size_m
    ymax = np.ceil(ymax / cell_size_m) * cell_size_m
    nx = int(round((xmax - xmin) / cell_size_m))
    ny = int(round((ymax - ymin) / cell_size_m))
    if nx < 2 or ny < 2:
        raise ValueError("pilot_grid_dimensions_invalid")
    with rasterio.open(dtm) as source:
        if source.crs is None or source.crs.to_epsg() != 32640:
            raise ValueError("pilot_grid_dtm_must_be_epsg32640")
        window = from_bounds(xmin, ymin, xmax, ymax, transform=source.transform).round_offsets().round_lengths()
        values = source.read(
            1,
            window=window,
            out_shape=(ny + 1, nx + 1),
            resampling=Resampling.bilinear,
            masked=True,
        )
        if np.ma.getmaskarray(values).any():
            raise ValueError("pilot_grid_dtm_contains_nodata")
        values = np.asarray(values, dtype=np.float32)
    x = np.linspace(xmin, xmax, nx + 1, dtype=np.float64)
    y = np.linspace(ymax, ymin, ny + 1, dtype=np.float64)
    land_mask = np.ones((ny, nx), dtype=bool)
    output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output / "terrain_grid.npz", values=values, x=x, y=y, land_mask=land_mask)
    payload = {
        "schema": "gwm.abu_dhabi_flood.bidirectional_pilot_grid.v1",
        "swmm_input": str(swmm_inp),
        "dtm": str(dtm),
        "selected_node_ids": node_ids,
        "bounds_epsg32640": [float(xmin), float(ymin), float(xmax), float(ymax)],
        "grid_shape": [int(ny + 1), int(nx + 1)],
        "cell_size_m": float(cell_size_m),
        "terrain_min_m": float(values.min()),
        "terrain_max_m": float(values.max()),
    }
    (output / "grid_metadata.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--swmm-inp", type=Path, required=True)
    parser.add_argument("--dtm", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-interfaces", type=int, default=16)
    parser.add_argument("--cell-size-m", type=float, default=25.0)
    parser.add_argument("--margin-m", type=float, default=150.0)
    args = parser.parse_args()
    print(json.dumps(prepare(args.swmm_inp, args.dtm, args.output, max_interfaces=args.max_interfaces, cell_size_m=args.cell_size_m, margin_m=args.margin_m), indent=2))


if __name__ == "__main__":
    main()

