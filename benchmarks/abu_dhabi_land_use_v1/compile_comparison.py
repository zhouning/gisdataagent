#!/usr/bin/env python3
"""Compile the shared three-model historical comparison and ensembles."""

from __future__ import annotations

import argparse
import json
import os
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from shared import evaluate_prediction

HERE = Path(__file__).resolve().parent
PREDICTION_ROOT = HERE / "artifacts/predictions"
BUNDLE_ROOT = HERE / "artifacts/bundle"
INPUT_ROOT = HERE / "artifacts/gee"
DEFAULT_OUTPUT = HERE / "comparison_report.json"
DEFAULT_MARKDOWN = HERE / "comparison_report.md"
MODELS = ("geosos_flus", "geospatial_kernel", "paper58")
YEARS = (2023, 2024)


def _read(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    with rasterio.open(path) as dataset:
        return dataset.read(), dataset.profile.copy()


def _write(path: Path, state: np.ndarray, reference: dict[str, Any]) -> None:
    profile = reference.copy()
    profile.update(
        count=1,
        dtype="uint8",
        nodata=0,
        compress="deflate",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f".partial.{os.getpid()}.tif")
    with rasterio.open(temp, "w", **profile) as dataset:
        dataset.write(state.astype(np.uint8), 1)
        dataset.set_band_description(1, "three_seed_majority_prediction")
    os.replace(temp, path)


def majority_vote(states: list[np.ndarray]) -> np.ndarray:
    stack = np.stack(states)
    counts = np.stack([np.count_nonzero(stack == value, axis=0) for value in range(1, 7)])
    result = np.argmax(counts, axis=0).astype(np.uint8) + 1
    result[np.all(stack == 0, axis=0)] = 0
    return result


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys = (
        "change_figure_of_merit",
        "change_f1",
        "overall_accuracy",
        "macro_f1",
        "demand_total_variation",
        "constraint_violation_rate",
    )
    result = {}
    for key in keys:
        values = [float(row[key]) for row in rows]
        result[key] = {
            "mean": statistics.mean(values),
            "population_std": statistics.pstdev(values),
            "values": values,
        }
    reliability_values = [
        float(row["reliability_sensitivity"]["change_figure_of_merit"]) for row in rows
    ]
    result["reliability_change_figure_of_merit"] = {
        "mean": statistics.mean(reliability_values),
        "population_std": statistics.pstdev(reliability_values),
        "values": reliability_values,
    }
    return result


def compile_report(*, output_path: Path, markdown_path: Path) -> dict[str, Any]:
    common, reference = _read(BUNDLE_ROOT / "common_valid_mask_100m.tif")
    hard, _ = _read(BUNDLE_ROOT / "hard_exclusion_2022_100m.tif")
    valid = common[0].astype(bool)
    hard_mask = hard[0].astype(bool)
    origin, _ = _read(INPUT_ROOT / "land_cover/land_cover_2022_100m.tif")
    actions = json.loads((BUNDLE_ROOT / "allocation_actions.json").read_text())["actions"]
    action_by_year = {int(row["target_year"]): row for row in actions}
    observed = {
        year: _read(INPUT_ROOT / "land_cover" / f"land_cover_{year}_100m.tif")[0][0]
        for year in YEARS
    }
    reports = {
        model: json.loads((PREDICTION_ROOT / model / "report.json").read_text())
        for model in MODELS
    }
    summaries = {}
    ensembles = {}
    for model in MODELS:
        summaries[model] = {}
        ensembles[model] = {}
        seed_ids = [int(row["seed"]) for row in reports[model]["seeds"]]
        if seed_ids != [31, 47, 73]:
            raise ValueError(f"three_frozen_seeds_required:{model}:{seed_ids}")
        for year in YEARS:
            evaluation_rows = [
                next(row for row in seed["years"] if int(row["target_year"]) == year)[
                    "evaluation"
                ]
                for seed in reports[model]["seeds"]
            ]
            summaries[model][str(year)] = _aggregate(evaluation_rows)
            states = [
                _read(PREDICTION_ROOT / model / f"seed_{seed}/prediction_{year}.tif")[0][0]
                for seed in seed_ids
            ]
            ensemble = majority_vote(states)
            ensemble_path = PREDICTION_ROOT / model / "ensemble" / f"prediction_{year}.tif"
            _write(ensemble_path, ensemble, reference)
            action = action_by_year[year]
            reliability, _ = _read(HERE / action["reliability_mask"])
            target_counts = {
                int(key): int(value)
                for key, value in action["feasible_target_counts"].items()
            }
            ensembles[model][str(year)] = {
                "prediction_path": str(ensemble_path.relative_to(HERE)),
                "evaluation": evaluate_prediction(
                    ensemble,
                    origin_state=origin[0],
                    observed_target=observed[year],
                    valid_mask=valid,
                    hard_exclusion_mask=hard_mask,
                    requested_counts=target_counts,
                    reliability_mask=reliability[0].astype(bool),
                ),
            }

    persistence = {}
    for year in YEARS:
        action = action_by_year[year]
        reliability, _ = _read(HERE / action["reliability_mask"])
        persistence[str(year)] = evaluate_prediction(
            origin[0],
            origin_state=origin[0],
            observed_target=observed[year],
            valid_mask=valid,
            hard_exclusion_mask=hard_mask,
            requested_counts={
                int(key): int(value)
                for key, value in action["feasible_target_counts"].items()
            },
            reliability_mask=reliability[0].astype(bool),
        )

    deltas = {}
    for year in YEARS:
        key = str(year)
        deltas[key] = {}
        for left, right in (
            ("geospatial_kernel", "geosos_flus"),
            ("paper58", "geosos_flus"),
            ("paper58", "geospatial_kernel"),
        ):
            deltas[key][f"{left}_minus_{right}_change_fom"] = (
                summaries[left][key]["change_figure_of_merit"]["mean"]
                - summaries[right][key]["change_figure_of_merit"]["mean"]
            )
    report = {
        "schema": "gwm.abu_dhabi_three_model_comparison.v1",
        "benchmark_id": "abu-dhabi-land-use-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "HISTORICAL_ALLOCATION_COMPLETE",
        "models": list(MODELS),
        "seeds": [31, 47, 73],
        "summaries": summaries,
        "ensembles": ensembles,
        "persistence": persistence,
        "mean_change_fom_deltas": deltas,
        "interpretation": [
            "Geospatial Kernel has the strongest one-step 2023 mean change FoM.",
            "Paper58 has the strongest two-step open-loop 2024 mean change FoM.",
            "Both proposed candidates exceed external GeoSOS-FLUS mean change FoM in both years.",
            (
                "High-confidence sensitivity FoM is low for all candidates; full-grid gains "
                "may partly reflect Dynamic World label volatility."
            ),
            (
                "These results establish historical conditional allocation skill, not future "
                "policy prediction or causal planning effects."
            ),
        ],
    }
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Abu Dhabi 三模型土地覆盖历史模拟比较",
        "",
        f"生成时间：{report['created_at']}",
        "",
        "同一 100 m 网格、需求动作、硬约束和评价器下的三随机种子均值。",
        "",
        "| 年份 | 模型 | change FoM | change F1 | OA | macro-F1 | demand TV |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "geosos_flus": "GeoSOS-FLUS",
        "geospatial_kernel": "Geospatial Kernel",
        "paper58": "Paper58",
    }
    for year in YEARS:
        for model in MODELS:
            row = report["summaries"][model][str(year)]
            lines.append(
                f"| {year} | {labels[model]} | "
                f"{row['change_figure_of_merit']['mean']:.4f} | "
                f"{row['change_f1']['mean']:.4f} | "
                f"{row['overall_accuracy']['mean']:.4f} | "
                f"{row['macro_f1']['mean']:.4f} | "
                f"{row['demand_total_variation']['mean']:.5f} |"
            )
    lines.extend(
        [
            "",
            "## 当前结论",
            "",
            "- 2023 单步：Geospatial Kernel 的平均 change FoM 最高。",
            "- 2024 两步开环：Paper58 的平均 change FoM 最高。",
            "- 两个拟议模型在两个年份均高于外部 GeoSOS-FLUS 的平均 change FoM。",
            "- 三者在高置信度标签子集上的 FoM 都很低，必须保留标签噪声警告。",
            "- 这是历史条件分配结果，不是未来政策预测，也不是因果效应证据。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args()
    report = compile_report(output_path=args.output, markdown_path=args.markdown)
    print(
        json.dumps(
            {
                "status": report["status"],
                "mean_change_fom_deltas": report["mean_change_fom_deltas"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
