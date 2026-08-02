#!/usr/bin/env python3
"""Render 2030 ensemble allocation changes for the three-model comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

HERE = Path(__file__).resolve().parent
DEFAULT_REPORT = HERE / "planning_comparison_report.json"
DEFAULT_OUTPUT = HERE / "planning_2030_comparison.png"
MODEL_IDS = ("geosos_flus", "geospatial_kernel", "paper58")
SCENARIO_IDS = ("compact", "ecological_priority", "outward_growth")
MODEL_LABELS = {
    "geosos_flus": "GeoSOS-FLUS",
    "geospatial_kernel": "Geospatial Kernel",
    "paper58": "Paper58",
}
SCENARIO_LABELS = {
    "compact": "Compact",
    "ecological_priority": "Ecological priority",
    "outward_growth": "Outward growth",
}
COLORS = (
    "#ffffff",
    "#4d9bd6",
    "#5b9a58",
    "#2d3439",
    "#d1493f",
    "#d9dde0",
    "#79c267",
    "#e2a23b",
)


def _read(path: Path) -> np.ndarray:
    with rasterio.open(path) as dataset:
        return dataset.read(1)


def _resolve(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else HERE / path


def change_view(
    state: np.ndarray, *, origin: np.ndarray, valid: np.ndarray
) -> np.ndarray:
    view = np.full(state.shape, 5, dtype=np.uint8)
    view[~valid] = 0
    view[valid & np.isin(state, (1, 4))] = 1
    view[valid & np.isin(state, (2, 3))] = 2
    view[valid & (origin == 5) & (state == 5)] = 3
    view[valid & (origin != 5) & (state == 5)] = 4
    view[valid & ~np.isin(origin, (2, 3)) & np.isin(state, (2, 3))] = 6
    view[valid & (origin == 5) & (state != 5)] = 7
    return view


def _candidate_metrics(
    report: dict[str, Any], model_id: str, scenario_id: str
) -> dict[str, Any]:
    candidate_id = f"{model_id}:{scenario_id}"
    return next(
        row for row in report["final_candidates"] if row["candidate_id"] == candidate_id
    )


def render(*, report_path: Path, output_path: Path) -> None:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    origin = _read(HERE / "artifacts/gee/land_cover/land_cover_2024_100m.tif")
    valid = _read(HERE / "artifacts/bundle/common_valid_mask_100m.tif").astype(bool)
    figure, axes = plt.subplots(3, 3, figsize=(12.6, 13.2), constrained_layout=True)
    cmap = ListedColormap(COLORS)
    for row_index, scenario_id in enumerate(SCENARIO_IDS):
        for column_index, model_id in enumerate(MODEL_IDS):
            axis = axes[row_index, column_index]
            record = report["ensembles"][model_id][scenario_id]["2030"]
            state = _read(_resolve(record["prediction_path"]))
            axis.imshow(
                change_view(state, origin=origin, valid=valid),
                cmap=cmap,
                vmin=0,
                vmax=len(COLORS) - 1,
                interpolation="nearest",
            )
            metrics = _candidate_metrics(report, model_id, scenario_id)
            axis.set_title(
                f"{MODEL_LABELS[model_id]}\n"
                f"new {metrics['new_built_pixels']:.0f} | "
                f"retired {metrics['removed_built_pixels']:.0f}",
                fontsize=10.5,
                pad=7,
            )
            axis.set_xticks([])
            axis.set_yticks([])
            if column_index == 0:
                axis.set_ylabel(
                    SCENARIO_LABELS[scenario_id],
                    fontsize=12,
                    fontweight="bold",
                    labelpad=12,
                )
            for spine in axis.spines.values():
                spine.set_color("#aeb4b8")
                spine.set_linewidth(0.7)

    legend = [
        Patch(facecolor=COLORS[1], label="Water / wetland"),
        Patch(facecolor=COLORS[2], label="Vegetation retained"),
        Patch(facecolor=COLORS[3], label="Built retained"),
        Patch(facecolor=COLORS[4], label="New built since 2024"),
        Patch(facecolor=COLORS[6], label="New vegetation since 2024"),
        Patch(facecolor=COLORS[7], label="Built retired since 2024"),
        Patch(facecolor=COLORS[5], label="Bare / other"),
    ]
    figure.legend(
        handles=legend,
        loc="lower center",
        ncol=4,
        frameon=False,
        fontsize=9.5,
        bbox_to_anchor=(0.5, -0.012),
    )
    figure.suptitle(
        "Abu Dhabi conditional land-cover allocations, 2030",
        fontsize=17,
        fontweight="bold",
    )
    figure.text(
        0.5,
        0.965,
        "Three-seed majority ensembles | 100 m grid | scenario demands, not forecasts",
        ha="center",
        fontsize=10.5,
        color="#4a5054",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    render(report_path=args.report, output_path=args.output)
    print(args.output)


if __name__ == "__main__":
    main()
