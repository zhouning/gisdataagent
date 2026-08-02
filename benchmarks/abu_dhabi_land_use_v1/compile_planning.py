#!/usr/bin/env python3
"""Compile shared planning metrics and a transparent Pareto frontier."""

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
from planning import OBJECTIVES, pareto_frontier, planning_metrics

HERE = Path(__file__).resolve().parent
BUNDLE_ROOT = HERE / "artifacts/bundle"
INPUT_ROOT = HERE / "artifacts/gee"
OSM_ROOT = HERE / "artifacts/osm"
DEFAULT_INPUT = HERE / "planning_scenario_report.json"
DEFAULT_OUTPUT = HERE / "planning_comparison_report.json"
DEFAULT_MARKDOWN = HERE / "planning_comparison_report.md"
MODEL_IDS = ("geosos_flus", "geospatial_kernel", "paper58")
SCENARIO_IDS = ("compact", "ecological_priority", "outward_growth")
YEARS = tuple(range(2025, 2031))


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
    temporary = path.with_suffix(f".partial.{os.getpid()}.tif")
    with rasterio.open(temporary, "w", **profile) as dataset:
        dataset.write(state.astype(np.uint8), 1)
        dataset.set_band_description(1, "three_seed_majority_scenario")
    os.replace(temporary, path)


def majority_vote(states: list[np.ndarray]) -> np.ndarray:
    stack = np.stack(states)
    counts = np.stack(
        [np.count_nonzero(stack == value, axis=0) for value in range(1, 7)]
    )
    result = np.argmax(counts, axis=0).astype(np.uint8) + 1
    result[np.all(stack == 0, axis=0)] = 0
    return result


def _normalize_counts(values: dict[str | int, Any]) -> dict[int, int]:
    return {int(key): int(value) for key, value in values.items()}


def _scenario_targets() -> dict[tuple[str, int], dict[int, int]]:
    scenarios = json.loads(
        (BUNDLE_ROOT / "planning_scenarios.json").read_text(encoding="utf-8")
    )["scenarios"]
    return {
        (str(row["scenario_id"]), year): _normalize_counts(
            row["target_counts_by_year"][str(year)]
        )
        for row in scenarios
        for year in YEARS
    }


def _numeric_means(rows: list[dict[str, Any]]) -> dict[str, float]:
    keys = [
        key
        for key, value in rows[0].items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    return {key: statistics.mean(float(row[key]) for row in rows) for key in keys}


def _objective_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for key in OBJECTIVES:
        values = [float(row[key]) for row in rows]
        result[key] = {
            "mean": statistics.mean(values),
            "population_std": statistics.pstdev(values),
            "values": values,
        }
    return result


def _find_year(
    model_report: dict[str, Any], *, seed: int, scenario_id: str, year: int
) -> dict[str, Any]:
    seed_row = next(row for row in model_report["seeds"] if int(row["seed"]) == seed)
    scenario = next(
        row for row in seed_row["scenarios"] if row["scenario_id"] == scenario_id
    )
    return next(row for row in scenario["years"] if int(row["target_year"]) == year)


def compile_report(
    *, input_path: Path, output_path: Path, markdown_path: Path
) -> dict[str, Any]:
    source = json.loads(input_path.read_text(encoding="utf-8"))
    if source["status"] != "complete":
        raise ValueError(f"planning_scenarios_not_complete:{source['status']}")
    if set(source["models"]) != set(MODEL_IDS):
        raise ValueError("planning_three_models_required")

    origin_data, reference = _read(
        INPUT_ROOT / "land_cover/land_cover_2024_100m.tif"
    )
    valid_data, _ = _read(BUNDLE_ROOT / "common_valid_mask_100m.tif")
    hard_data, _ = _read(BUNDLE_ROOT / "hard_exclusion_2024_100m.tif")
    roads, _ = _read(OSM_ROOT / "road_accessibility_100m.tif")
    origin = origin_data[0]
    valid = valid_data[0].astype(bool)
    hard = hard_data[0].astype(bool)
    targets = _scenario_targets()
    seeds = tuple(int(value) for value in source["seeds"])
    if seeds != (31, 47, 73):
        raise ValueError(f"three_frozen_seeds_required:{seeds}")

    seed_metrics = []
    aggregate: dict[str, dict[str, dict[str, Any]]] = {}
    ensembles: dict[str, dict[str, dict[str, Any]]] = {}
    final_candidates = []
    for model_id in MODEL_IDS:
        aggregate[model_id] = {}
        ensembles[model_id] = {}
        model_report = source["models"][model_id]
        for scenario_id in SCENARIO_IDS:
            aggregate[model_id][scenario_id] = {}
            ensembles[model_id][scenario_id] = {}
            final_seed_rows = []
            for year in YEARS:
                rows = []
                states = []
                for seed in seeds:
                    year_record = _find_year(
                        model_report,
                        seed=seed,
                        scenario_id=scenario_id,
                        year=year,
                    )
                    state_data, _ = _read(HERE / year_record["prediction_path"])
                    state = state_data[0]
                    metrics = planning_metrics(
                        state,
                        origin_state=origin,
                        valid_mask=valid,
                        hard_exclusion_mask=hard,
                        target_counts=targets[(scenario_id, year)],
                        road_distance_m=roads[0],
                        major_road_distance_m=roads[1],
                    )
                    row = {
                        "model_id": model_id,
                        "scenario_id": scenario_id,
                        "seed": seed,
                        "target_year": year,
                        "prediction_path": year_record["prediction_path"],
                        **metrics,
                    }
                    seed_metrics.append(row)
                    rows.append(metrics)
                    states.append(state)
                aggregate[model_id][scenario_id][str(year)] = {
                    "means": _numeric_means(rows),
                    "objectives": _objective_summary(rows),
                }
                if year == 2030:
                    final_seed_rows = rows

                ensemble = majority_vote(states)
                ensemble_path = (
                    HERE
                    / "artifacts/planning"
                    / model_id
                    / scenario_id
                    / "ensemble"
                    / f"prediction_{year}.tif"
                )
                _write(ensemble_path, ensemble, reference)
                ensembles[model_id][scenario_id][str(year)] = {
                    "prediction_path": str(ensemble_path.relative_to(HERE)),
                    "metrics": planning_metrics(
                        ensemble,
                        origin_state=origin,
                        valid_mask=valid,
                        hard_exclusion_mask=hard,
                        target_counts=targets[(scenario_id, year)],
                        road_distance_m=roads[0],
                        major_road_distance_m=roads[1],
                    ),
                }
            candidate = {
                "candidate_id": f"{model_id}:{scenario_id}",
                "model_id": model_id,
                "scenario_id": scenario_id,
                **_numeric_means(final_seed_rows),
                "objective_uncertainty": _objective_summary(final_seed_rows),
            }
            final_candidates.append(candidate)

    frontier = pareto_frontier(final_candidates)
    report = {
        "schema": "gwm.abu_dhabi_planning_comparison.v1",
        "benchmark_id": "abu-dhabi-land-use-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "complete",
        "origin_year": 2024,
        "final_year": 2030,
        "models": list(MODEL_IDS),
        "scenarios": list(SCENARIO_IDS),
        "seeds": list(seeds),
        "objective_directions": OBJECTIVES,
        "final_candidates": final_candidates,
        "pareto_frontier": frontier,
        "aggregate": aggregate,
        "ensembles": ensembles,
        "seed_metrics": seed_metrics,
        "claim_boundary": [
            "Scenario demands are planner-supplied stress tests, not forecasts.",
            (
                "Ecology and infrastructure quantities are public-data proxies, not "
                "monetary or statutory impacts."
            ),
            (
                "Pareto membership is conditional on this frozen objective set and cannot "
                "establish policy causality."
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
    labels = {
        "geosos_flus": "GeoSOS-FLUS",
        "geospatial_kernel": "Geospatial Kernel",
        "paper58": "Paper58",
    }
    frontier = set(report["pareto_frontier"])
    lines = [
        "# Abu Dhabi 2025-2030 土地利用情景模拟与优化",
        "",
        "以下为 2030 年三随机种子均值。Pareto 表示在冻结目标集合下未被其他方案全面支配。",
        "",
        (
            "| 模型 | 情景 | demand TV | 生态转建成率 | 新建成邻域紧凑度 | "
            "距主干路(m) | 距原建成区(m) | 建成净增 | 建成退出 | 绿地净增 | Pareto |"
        ),
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for row in report["final_candidates"]:
        lines.append(
            f"| {labels[row['model_id']]} | {row['scenario_id']} | "
            f"{row['demand_total_variation']:.5f} | "
            f"{row['ecological_conversion_rate']:.4f} | "
            f"{row['new_built_neighbor_fraction']:.4f} | "
            f"{row['new_built_mean_major_road_distance_m']:.1f} | "
            f"{row['new_built_mean_prior_built_distance_m']:.1f} | "
            f"{row['built_gain_pixels']:.0f} | {row['removed_built_pixels']:.0f} | "
            f"{row['green_gain_pixels']:.0f} | "
            f"{'是' if row['candidate_id'] in frontier else '否'} |"
        )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "- 三组需求是规划压力测试，不是对阿布扎比未来的预测。",
            "- 生态和基础设施指标来自公开数据代理，不等于法定或货币化影响。",
            "- Pareto 结果只在当前冻结目标、100 m 网格和公共约束下成立。",
            "- FLUS 的既有建成退出是冻结转换规则下的模型行为，未做事后修正。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args()
    report = compile_report(
        input_path=args.input,
        output_path=args.output,
        markdown_path=args.markdown,
    )
    print(
        json.dumps(
            {"status": report["status"], "pareto_frontier": report["pareto_frontier"]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
