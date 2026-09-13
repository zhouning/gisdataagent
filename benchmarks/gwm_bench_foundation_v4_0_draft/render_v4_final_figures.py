#!/usr/bin/env python3
"""Render data-accurate figures and previews for the V4 final report."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
RESULT_PATH = DRAFT_ROOT / "final_results/action_a4_results.json"
BUNDLE_ROOT = DRAFT_ROOT / "rc1_bundle"
PREDICTION_ROOT = DRAFT_ROOT / "predictions"
OUTPUT_ROOT = (
    REPO_ROOT
    / "docs/research/assets/gwm_benchmark_v4_final_2026-07-23"
)
TARGETS = ["pickup_count", "dropoff_count", "cbd_inflow", "cbd_outflow"]
HORIZONS = [1, 2, 4, 8, 12]


def save(fig: plt.Figure, name: str) -> None:
    fig.savefig(OUTPUT_ROOT / name, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def primary_score_chart(result: dict) -> None:
    ids = [
        "nonspatial_historical_ar",
        "fixed_adjacency_spatial_ar",
        "uwm_dam_gk_action",
        "dam_gk_no_action",
        "seasonal_persistence_52w",
    ]
    labels = [
        "Nonspatial historical AR",
        "Fixed-adjacency spatial AR",
        "UWM / DAM-GK action",
        "Matched DAM-GK no-action",
        "52-week persistence",
    ]
    scores = [
        result["metrics"][model_id]["primary_macro_pre_event_normalized_mae"]
        for model_id in ids
    ]
    colors = ["#2563eb", "#60a5fa", "#dc2626", "#f59e0b", "#94a3b8"]
    fig, ax = plt.subplots(figsize=(10, 5.2))
    bars = ax.barh(labels[::-1], scores[::-1], color=colors[::-1])
    for bar, value in zip(bars, scores[::-1]):
        ax.text(value + 0.004, bar.get_y() + bar.get_height() / 2, f"{value:.4f}", va="center")
    ax.set_xlim(0, max(scores) * 1.16)
    ax.set_xlabel("Macro pre-event normalized MAE (lower is better)")
    ax.set_title("GWM Benchmark V4 — Final model comparison")
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    save(fig, "01_primary_model_scores.png")


def horizon_chart(result: dict) -> None:
    action = result["metrics"]["uwm_dam_gk_action"]["by_horizon"]
    no_action = result["metrics"]["dam_gk_no_action"]["by_horizon"]
    action_values = [action[str(horizon)] for horizon in HORIZONS]
    no_action_values = [no_action[str(horizon)] for horizon in HORIZONS]
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    ax.plot(HORIZONS, action_values, marker="o", linewidth=2.4, color="#dc2626", label="Action-conditioned")
    ax.plot(HORIZONS, no_action_values, marker="o", linewidth=2.4, color="#f59e0b", label="Matched no-action")
    for horizon, left, right in zip(HORIZONS, action_values, no_action_values):
        delta = left - right
        ax.annotate(
            f"Δ {delta:+.4f}",
            (horizon, max(left, right)),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
            fontsize=8,
        )
    ax.set_xticks(HORIZONS)
    ax.set_xlabel("Forecast horizon (weeks)")
    ax.set_ylabel("Normalized MAE")
    ax.set_title("Action value emerges after week 1 but error grows with horizon")
    ax.legend()
    ax.grid(alpha=0.2)
    fig.tight_layout()
    save(fig, "02_action_vs_no_action_by_horizon.png")


def mechanism_control_chart(result: dict) -> None:
    action_score = result["metrics"]["uwm_dam_gk_action"][
        "primary_macro_pre_event_normalized_mae"
    ]
    controls = [
        ("Action deleted", "action_deleted"),
        ("Date −4 weeks", "effective_date_minus_4w"),
        ("Date +4 weeks", "effective_date_plus_4w"),
        ("Components permuted", "action_component_permutation"),
        ("CBD scope rewired", "cbd_scope_rewire"),
        ("Exposure shuffled", "zone_exposure_shuffle_seed_20260723"),
    ]
    labels = [label for label, _ in controls]
    values = [
        result["metrics"][model_id]["primary_macro_pre_event_normalized_mae"]
        - action_score
        for _, model_id in controls
    ]
    colors = ["#16a34a" if value > 0 else "#dc2626" for value in values]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    bars = ax.barh(labels[::-1], values[::-1], color=colors[::-1])
    ax.axvline(0, color="#111827", linewidth=1)
    for bar, value in zip(bars, values[::-1]):
        x = value + (0.00035 if value >= 0 else -0.00035)
        ax.text(
            x,
            bar.get_y() + bar.get_height() / 2,
            f"{value:+.4f}",
            va="center",
            ha="left" if value >= 0 else "right",
            fontsize=9,
        )
    ax.set_xlabel("Control score − correct-action score (positive means correct action wins)")
    ax.set_title("Mechanism checks — four perturbations beat the correct-action rollout")
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    save(fig, "03_action_mechanism_controls.png")


def system_total_chart() -> None:
    targets = pd.read_parquet(BUNDLE_ROOT / "test_targets/weekly_targets.parquet")
    action = pd.read_parquet(PREDICTION_ROOT / "uwm_dam_gk_action/prediction.parquet")
    baseline = pd.read_parquet(PREDICTION_ROOT / "nonspatial_historical_ar/prediction.parquet")
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), sharex=True)
    for ax, target in zip(axes.flat, TARGETS):
        actual = targets.groupby("horizon_week", observed=True)[target].sum()
        action_total = action.groupby("horizon_week", observed=True)[f"{target}_prediction"].sum()
        baseline_total = baseline.groupby("horizon_week", observed=True)[f"{target}_prediction"].sum()
        scale = 1_000_000.0
        ax.plot(actual.index, actual / scale, marker="o", color="#111827", label="Observed")
        ax.plot(action_total.index, action_total / scale, marker="o", color="#dc2626", label="DAM-GK action")
        ax.plot(baseline_total.index, baseline_total / scale, marker="o", color="#2563eb", label="Nonspatial AR")
        ax.set_title(target.replace("_", " ").title())
        ax.set_ylabel("System total (millions)")
        ax.grid(alpha=0.2)
    axes[1, 0].set_xlabel("Horizon week")
    axes[1, 1].set_xlabel("Horizon week")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, frameon=False)
    fig.suptitle("Observed and predicted NYC-wide weekly totals", y=0.98, fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    save(fig, "04_system_total_prediction_preview.png")


def preview_tables() -> None:
    zone_id = 161
    history = pd.read_parquet(BUNDLE_ROOT / "test_input/weekly_state_history.parquet")
    action_spec = pd.read_parquet(BUNDLE_ROOT / "test_input/future_action_spec.parquet")
    targets = pd.read_parquet(BUNDLE_ROOT / "test_targets/weekly_targets.parquet")
    prediction = pd.read_parquet(PREDICTION_ROOT / "uwm_dam_gk_action/prediction.parquet")
    history_preview = history.loc[
        history["zone_id"].eq(zone_id) & history["relative_week"].isin([-3, -2, -1]),
        ["relative_week", "week_start", *TARGETS],
    ].copy()
    action_preview = action_spec.loc[
        action_spec["zone_id"].eq(zone_id) & action_spec["horizon_week"].isin([1, 2, 3]),
        [
            "horizon_week",
            "week_start",
            "fixed_spatial_surcharge_contribution_usd",
            "expected_total_delta_usd",
            "expected_fractional_fare_delta",
            "spatial_applicability_share",
            "implementation_share",
        ],
    ].copy()
    result_preview = targets.loc[
        targets["zone_id"].eq(zone_id) & targets["horizon_week"].isin(HORIZONS),
        ["zone_id", "horizon_week", *TARGETS],
    ].merge(prediction, on=["zone_id", "horizon_week"], validate="one_to_one")
    result_preview = result_preview[
        [
            "horizon_week",
            "pickup_count",
            "pickup_count_prediction",
            "dropoff_count",
            "dropoff_count_prediction",
            "cbd_inflow",
            "cbd_inflow_prediction",
            "cbd_outflow",
            "cbd_outflow_prediction",
        ]
    ]
    history_preview.to_csv(OUTPUT_ROOT / "zone161_history_preview.csv", index=False)
    action_preview.to_csv(OUTPUT_ROOT / "zone161_action_preview.csv", index=False)
    result_preview.to_csv(OUTPUT_ROOT / "zone161_result_preview.csv", index=False)

    fig, axes = plt.subplots(3, 1, figsize=(15, 9.5))
    tables = [
        (history_preview, "Raw test input preview — Zone 161 Midtown Center, last 3 pre-action weeks"),
        (action_preview, "Future numeric action preview — Zone 161, first 3 rollout weeks"),
        (result_preview.round(1), "Observed vs DAM-GK action prediction — Zone 161, reported horizons"),
    ]
    for ax, (frame, title) in zip(axes, tables):
        ax.axis("off")
        display = frame.copy()
        for column in display.columns:
            if np.issubdtype(display[column].dtype, np.datetime64):
                display[column] = display[column].dt.strftime("%Y-%m-%d")
        table = ax.table(
            cellText=display.values,
            colLabels=display.columns,
            cellLoc="center",
            loc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(7.4)
        table.scale(1, 1.38)
        ax.set_title(title, fontsize=11, pad=10)
    fig.tight_layout()
    save(fig, "05_raw_and_result_data_preview.png")


def main() -> int:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    primary_score_chart(result)
    horizon_chart(result)
    mechanism_control_chart(result)
    system_total_chart()
    preview_tables()
    print(f"V4 final figures: {OUTPUT_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
