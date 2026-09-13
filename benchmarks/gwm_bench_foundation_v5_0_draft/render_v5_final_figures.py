#!/usr/bin/env python3
"""Render publication figures for the completed GWM-Bench V5 result."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
RESULT_PATH = DRAFT_ROOT / "final_results/action_transfer_results.json"
ASSET_ROOT = REPO_ROOT / "docs/research/assets/gwm_benchmark_v5_final_2026-07-23"
TARGETS = ["pickup_count", "dropoff_count", "cbd_inflow", "cbd_outflow"]
FOLD_LABELS = {
    "holdout_2015": "2015",
    "holdout_2019": "2019",
    "holdout_2022": "2022",
    "holdout_2025": "2025",
}
EVENT_LABELS = {
    "event_2015_improvement_surcharge": "2015 improvement surcharge",
    "event_2019_nys_congestion_surcharge": "2019 congestion surcharge",
    "event_2022_tlc_taximeter_adjustment": "2022 taximeter adjustment",
    "event_2025_mta_crz": "2025 MTA CRZ",
}
MODEL_LABELS = {
    "history_ar_backbone": "History AR",
    "fixed_adjacency_spatial_ar": "Spatial AR",
    "dam_gk_residual_no_action": "DAM-GK no action",
    "uwm_dam_gk_action_residual": "DAM-GK correct action",
    "action_deleted": "Action deleted",
    "effective_date_minus_4w": "Date -4w",
    "effective_date_plus_4w": "Date +4w",
    "action_component_permutation": "Component permutation",
    "wrong_spatial_scope": "Wrong spatial scope",
    "cross_event_action_swap": "Cross-event swap",
    "zone_exposure_shuffle_seed_20260723": "Exposure shuffle",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 180,
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "axes.grid": True,
            "grid.alpha": 0.22,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def save(
    fig: plt.Figure,
    name: str,
    *,
    tight_layout_rect: tuple[float, float, float, float] | None = None,
) -> None:
    ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=tight_layout_rect)
    fig.savefig(ASSET_ROOT / name, bbox_inches="tight")
    plt.close(fig)


def primary_scores(result: dict[str, Any]) -> None:
    scores = {
        model_id: values["primary_equal_event_macro_pre_action_normalized_mae"]
        for model_id, values in result["metrics"].items()
    }
    order = sorted(scores, key=scores.get)
    colors = []
    for model_id in order:
        if model_id == "uwm_dam_gk_action_residual":
            colors.append("#d95f02")
        elif model_id == "history_ar_backbone":
            colors.append("#1b9e77")
        elif model_id == "fixed_adjacency_spatial_ar":
            colors.append("#386cb0")
        else:
            colors.append("#a9a9a9")
    fig, ax = plt.subplots(figsize=(10.5, 5.8))
    values = [scores[model_id] for model_id in order]
    bars = ax.barh([MODEL_LABELS[model_id] for model_id in order], values, color=colors)
    ax.invert_yaxis()
    ax.set_xlabel("Lower is better: equal-event normalized MAE")
    ax.set_title("V5 formal scores: models and frozen negative controls")
    ax.set_xlim(0, max(values) * 1.18)
    for bar, value in zip(bars, values):
        ax.text(value + 0.002, bar.get_y() + bar.get_height() / 2, f"{value:.4f}", va="center")
    save(fig, "01_primary_scores.png")


def fold_skill(result: dict[str, Any]) -> None:
    skills = result["action_transfer_gate"]["fold_skill"]
    labels = [FOLD_LABELS[key] for key in skills]
    values = [skills[key] * 100.0 for key in skills]
    colors = ["#1b9e77" if value > 0 else "#d95f02" for value in values]
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    bars = ax.bar(labels, values, color=colors)
    ax.axhline(0, color="#333333", linewidth=1)
    ax.axhline(1, color="#386cb0", linestyle="--", linewidth=1.2, label="+1% practical gate")
    ax.axhline(-2, color="#8c2d04", linestyle=":", linewidth=1.2, label="-2% degradation limit")
    ax.set_ylabel("Skill vs history AR (%)")
    ax.set_title("Correct-action residual helps two events and harms two events")
    ax.legend(frameon=False)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + (0.5 if value >= 0 else -1.2), f"{value:.1f}%", ha="center")
    save(fig, "02_fold_skill.png")


def target_horizon(result: dict[str, Any]) -> None:
    candidate = result["metrics"]["uwm_dam_gk_action_residual"]
    history = result["metrics"]["history_ar_backbone"]
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.5))
    target_labels = ["Pickup", "Dropoff", "CBD inflow", "CBD outflow"]
    target_keys = ["pickup_count", "dropoff_count", "cbd_inflow", "cbd_outflow"]
    x = np.arange(len(target_keys))
    width = 0.36
    axes[0].bar(
        x - width / 2,
        [history["by_target_equal_event"][key] for key in target_keys],
        width,
        label="History AR",
        color="#1b9e77",
    )
    axes[0].bar(
        x + width / 2,
        [candidate["by_target_equal_event"][key] for key in target_keys],
        width,
        label="Correct action residual",
        color="#d95f02",
    )
    axes[0].set_xticks(x, target_labels, rotation=18)
    axes[0].set_ylabel("Normalized MAE")
    axes[0].set_title("By target")
    axes[0].legend(frameon=False)

    horizons = [1, 2, 4, 8, 12]
    axes[1].plot(
        horizons,
        [history["by_horizon_equal_event"][str(value)] for value in horizons],
        marker="o",
        linewidth=2,
        color="#1b9e77",
        label="History AR",
    )
    axes[1].plot(
        horizons,
        [candidate["by_horizon_equal_event"][str(value)] for value in horizons],
        marker="o",
        linewidth=2,
        color="#d95f02",
        label="Correct action residual",
    )
    axes[1].set_xticks(horizons)
    axes[1].set_xlabel("Forecast horizon (weeks)")
    axes[1].set_ylabel("Normalized MAE")
    axes[1].set_title("By reported horizon")
    axes[1].legend(frameon=False)
    save(fig, "03_target_horizon_comparison.png")


def raw_data_preview() -> None:
    fig, axes = plt.subplots(2, 2, figsize=(12, 7.2), sharex=True)
    for ax, event_dir in zip(
        axes.ravel(),
        sorted((DRAFT_ROOT / "rc1_bundle/events").iterdir()),
    ):
        frame = pd.read_parquet(event_dir / "weekly_state_action.parquet")
        totals = frame.groupby("relative_week", observed=True)["pickup_count"].sum()
        ax.plot(totals.index, totals.values / 1_000_000.0, color="#386cb0", linewidth=1.8)
        ax.axvline(0, color="#d95f02", linestyle="--", linewidth=1.2)
        ax.axvspan(1, 12, color="#d95f02", alpha=0.08)
        ax.set_title(EVENT_LABELS[event_dir.name])
        ax.set_ylabel("Weekly pickups (million)")
        ax.set_xlabel("Action-aligned week")
    fig.suptitle("Original data preview: systemwide pickup trajectories around four actions", y=1.01)
    save(fig, "04_original_data_preview.png")


def result_preview() -> None:
    result = load_json(RESULT_PATH)
    candidate_path = Path(
        result["prediction_artifacts"]["uwm_dam_gk_action_residual"]["path"]
    )
    history_path = Path(result["prediction_artifacts"]["history_ar_backbone"]["path"])
    candidate = pd.read_parquet(REPO_ROOT / candidate_path)
    history = pd.read_parquet(REPO_ROOT / history_path)
    fig, axes = plt.subplots(2, 2, figsize=(12, 7.2), sharex=True)
    for ax, (fold_id, label) in zip(axes.ravel(), FOLD_LABELS.items()):
        targets = pd.read_parquet(
            DRAFT_ROOT / f"rc1_bundle/folds/{fold_id}/test_targets/weekly_targets.parquet"
        )
        observed = targets.groupby("horizon_week", observed=True)["pickup_count"].sum()
        candidate_total = (
            candidate.loc[candidate["fold_id"].eq(fold_id)]
            .groupby("horizon_week", observed=True)["pickup_count_prediction"]
            .sum()
        )
        history_total = (
            history.loc[history["fold_id"].eq(fold_id)]
            .groupby("horizon_week", observed=True)["pickup_count_prediction"]
            .sum()
        )
        ax.plot(observed.index, observed.values / 1_000_000.0, color="#222222", marker="o", label="Observed")
        ax.plot(history_total.index, history_total.values / 1_000_000.0, color="#1b9e77", marker="o", label="History AR")
        ax.plot(candidate_total.index, candidate_total.values / 1_000_000.0, color="#d95f02", marker="o", label="Correct action residual")
        ax.set_title(f"Held-out {label}")
        ax.set_xlabel("Post-action horizon week")
        ax.set_ylabel("Systemwide pickups (million)")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.955),
        ncol=3,
        frameon=False,
    )
    fig.suptitle("Result preview: observed and predicted pickup totals", y=0.995)
    save(
        fig,
        "05_prediction_result_preview.png",
        tight_layout_rect=(0.0, 0.0, 1.0, 0.88),
    )


def gate_summary(result: dict[str, Any]) -> None:
    conditions = result["action_transfer_gate"]["conditions"]
    short_labels = [
        "Mean skill ≥1%",
        "Bootstrap <0",
        "≥3/4 folds improve",
        "No fold worse >2%",
        "≥12/16 event-target",
        "≥4/5 horizons",
        "Beat every control",
        "Beat each control ≥3/4",
    ]
    values = list(conditions.values())
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    y = np.arange(len(values))
    colors = ["#1b9e77" if value else "#d95f02" for value in values]
    ax.barh(y, [1] * len(values), color=colors)
    ax.set_yticks(y, short_labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.05)
    ax.set_xticks([])
    ax.set_title("Frozen action-transfer gate: 0 of 8 conditions passed")
    for index, value in enumerate(values):
        ax.text(0.5, index, "PASS" if value else "FAIL", ha="center", va="center", color="white", fontweight="bold")
    save(fig, "06_gate_summary.png")


def main() -> int:
    style()
    result = load_json(RESULT_PATH)
    primary_scores(result)
    fold_skill(result)
    target_horizon(result)
    raw_data_preview()
    result_preview()
    gate_summary(result)
    print(f"GWM-Bench Foundation V5.0 figures: {ASSET_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
