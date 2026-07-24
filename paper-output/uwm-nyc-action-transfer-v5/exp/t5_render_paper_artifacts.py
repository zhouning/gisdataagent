#!/usr/bin/env python3
"""Render figures and tables from frozen-result paper CSV files.

Reads only paper-output/uwm-nyc-action-transfer-v5/results/*.csv created by
T0-T4. It does not open model training code, synthetic data or Chongqing data.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


OUTPUT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = OUTPUT_ROOT / "results"
FIGURES_ROOT = OUTPUT_ROOT / "figures"
TABLES_ROOT = OUTPUT_ROOT / "tables"
sys.path.insert(0, str(FIGURES_ROOT))

from paper_plot_style import OKABE_ITO, apply_paper_style  # noqa: E402


MODEL_SHORT = {
    "history_ar_backbone": "History AR",
    "fixed_adjacency_spatial_ar": "Spatial AR",
    "dam_gk_residual_no_action": "Matched no-action",
    "uwm_dam_gk_action_residual": "Correct action",
}

EVENT_SHORT = {
    "holdout_2015": "2015 improvement",
    "holdout_2019": "2019 congestion",
    "holdout_2022": "2022 taximeter",
    "holdout_2025": "2025 CRZ",
}


def _panel_label(ax: plt.Axes, label: str) -> None:
    ax.text(
        -0.12,
        1.04,
        label,
        transform=ax.transAxes,
        fontsize=10,
        fontweight="bold",
        va="bottom",
    )


def _save(fig: plt.Figure, figure_id: str, source: pd.DataFrame) -> None:
    FIGURES_ROOT.mkdir(parents=True, exist_ok=True)
    base = FIGURES_ROOT / figure_id
    fig.savefig(base.with_suffix(".pdf"))
    fig.savefig(base.with_suffix(".svg"))
    fig.savefig(base.with_suffix(".png"), dpi=600)
    source.to_csv(FIGURES_ROOT / f"{figure_id}_source_data.csv", index=False)
    plt.close(fig)


def _figure_1() -> None:
    support = pd.read_csv(RESULTS_ROOT / "support_units.csv")
    events = pd.DataFrame(
        [
            (2015, "Improvement\nsurcharge", "citywide"),
            (2019, "Congestion\nsurcharge", "Manhattan trips"),
            (2022, "Taximeter\nadjustment", "citywide bundle"),
            (2025, "CRZ\ncharge", "CBD-related"),
        ],
        columns=["year", "action", "scope"],
    )
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.8), gridspec_kw={"width_ratios": [1.35, 1]})
    ax = axes[0]
    ax.hlines(0, 2014.4, 2025.6, color=OKABE_ITO["light_gray"], linewidth=2)
    for index, row in events.iterrows():
        color = [
            OKABE_ITO["blue"],
            OKABE_ITO["orange"],
            OKABE_ITO["green"],
            OKABE_ITO["vermillion"],
        ][index]
        ax.scatter(row["year"], 0, s=70, color=color, edgecolor="white", linewidth=0.8, zorder=3)
        direction = 1 if index % 2 == 0 else -1
        ax.text(row["year"], 0.16 * direction, f'{row["year"]}\n{row["action"]}', ha="center", va="center")
    ax.set_xlim(2014.2, 2025.8)
    ax.set_ylim(-0.42, 0.42)
    ax.set_yticks([])
    ax.set_xlabel("Four model-held-out action environments")
    for spine in ("left", "right", "top"):
        ax.spines[spine].set_visible(False)
    _panel_label(ax, "a")

    ax = axes[1]
    wanted = [
        "independent_action_events",
        "training_actions_per_fold",
        "zones_per_event",
        "weeks_per_event",
        "total_zone_week_rows",
    ]
    labels = ["Action\nevents", "Training actions\nper fold", "Zones", "Weeks/event", "Zone-week\nrows"]
    values = [int(support.set_index("quantity").loc[key, "value"]) for key in wanted]
    ypos = np.arange(len(values))
    bars = ax.barh(ypos, values, color=OKABE_ITO["gray"], height=0.68)
    bars[0].set_color(OKABE_ITO["vermillion"])
    bars[1].set_color(OKABE_ITO["orange"])
    ax.set_xscale("log")
    ax.set_yticks(ypos, [label.replace("\n", " ") for label in labels])
    ax.invert_yaxis()
    ax.set_xlabel("Count (log scale)")
    ax.grid(axis="x", color=OKABE_ITO["light_gray"], linewidth=0.5)
    ax.spines[["top", "right"]].set_visible(False)
    for bar, value in zip(bars, values):
        ax.text(value * 1.12, bar.get_y() + bar.get_height() / 2, f"{value:,}", ha="left", va="center")
    ax.set_xlim(2.5, 180000)
    _panel_label(ax, "b")
    fig.tight_layout(w_pad=2.0)
    source = pd.concat(
        [
            events.assign(panel="a", quantity="event", value=events["year"]),
            pd.DataFrame({"panel": "b", "quantity": wanted, "value": values}),
        ],
        ignore_index=True,
        sort=False,
    )
    _save(fig, "F1_benchmark_design", source)


def _figure_2() -> None:
    scores = pd.read_csv(RESULTS_ROOT / "primary_scores.csv").sort_values("primary_error", ascending=False)
    gates = pd.read_csv(RESULTS_ROOT / "gate_summary.csv")
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 4.3), gridspec_kw={"width_ratios": [1.55, 1]})
    ax = axes[0]
    y = np.arange(len(scores))
    color_map = {
        "candidate": OKABE_ITO["blue"],
        "baseline": OKABE_ITO["black"],
        "matched_no_action": OKABE_ITO["orange"],
        "negative_control": OKABE_ITO["gray"],
    }
    markers = {"candidate": "D", "baseline": "s", "matched_no_action": "^", "negative_control": "o"}
    for model_type, group in scores.groupby("model_type", observed=True):
        indices = [scores.index.get_loc(index) for index in group.index]
        ax.scatter(group["primary_error"], indices, color=color_map[model_type], marker=markers[model_type], s=35, label=model_type.replace("_", " "))
    ax.set_yticks(y, scores["model_label"])
    ax.set_xlabel("Equal-event normalized MAE (lower is better)")
    ax.grid(axis="x", color=OKABE_ITO["light_gray"], linewidth=0.5)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(
        frameon=False,
        loc="lower left",
        bbox_to_anchor=(0.0, 1.005),
        ncol=2,
        columnspacing=1.2,
        handletextpad=0.5,
    )
    _panel_label(ax, "a")

    ax = axes[1]
    gate_labels = [
        "Mean skill >= 1%",
        "Bootstrap CI < 0",
        "At least 3/4 events",
        "No severe fold loss",
        "At least 12/16 targets",
        "At least 4/5 horizons",
        "Beat every control",
        "Control fold wins",
    ]
    ypos = np.arange(len(gates))[::-1]
    ax.scatter(np.zeros(len(gates)), ypos, marker="x", s=75, linewidth=2, color=OKABE_ITO["vermillion"])
    ax.set_yticks(ypos, gate_labels)
    ax.set_xticks([])
    ax.set_xlim(-0.5, 0.8)
    ax.text(0.48, 0.94, "0 / 8 passed", transform=ax.transAxes, color=OKABE_ITO["vermillion"], fontweight="bold")
    ax.spines[:].set_visible(False)
    _panel_label(ax, "b")
    fig.tight_layout(w_pad=2.5)
    source = pd.concat([scores.assign(panel="a"), gates.assign(panel="b")], ignore_index=True, sort=False)
    _save(fig, "F2_primary_tournament", source)


def _figure_3() -> None:
    folds = pd.read_csv(RESULTS_ROOT / "fold_skill.csv")
    decomposition = pd.read_csv(RESULTS_ROOT / "error_decomposition.csv")
    event_target = decomposition.loc[decomposition["dimension"].eq("event_target")].copy()
    split = event_target["key"].str.split("|", expand=True)
    event_target["fold_id"] = split[0]
    event_target["target"] = split[1]
    pivot = event_target.pivot(index="fold_id", columns="target", values="candidate_minus_history")
    pivot = pivot.loc[list(EVENT_SHORT), ["pickup_count", "dropoff_count", "cbd_inflow", "cbd_outflow"]]

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.1), gridspec_kw={"width_ratios": [1, 1.35]})
    ax = axes[0]
    ordered = folds.set_index("fold_id").loc[list(EVENT_SHORT)].reset_index()
    colors = [OKABE_ITO["green"] if value > 0 else OKABE_ITO["vermillion"] for value in ordered["skill"]]
    bars = ax.bar(range(len(ordered)), ordered["skill"] * 100, color=colors)
    ax.axhline(0, color=OKABE_ITO["black"], linewidth=0.8)
    ax.set_xticks(range(len(ordered)), [label.split()[0] for label in EVENT_SHORT.values()])
    ax.set_ylabel("Skill versus History AR (%)")
    ax.spines[["top", "right"]].set_visible(False)
    for bar, value in zip(bars, ordered["skill"] * 100):
        ax.text(bar.get_x() + bar.get_width() / 2, value + (0.8 if value >= 0 else -0.8), f"{value:.1f}", ha="center", va="bottom" if value >= 0 else "top")
    lower = float((ordered["skill"] * 100).min())
    upper = float((ordered["skill"] * 100).max())
    ax.set_ylim(lower - 3.0, upper + 2.5)
    _panel_label(ax, "a")

    ax = axes[1]
    limit = float(np.abs(pivot.to_numpy()).max())
    image = ax.imshow(pivot.to_numpy(), cmap="BrBG_r", norm=mcolors.TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit), aspect="auto")
    ax.set_xticks(range(4), ["Pickup", "Dropoff", "CBD in", "CBD out"])
    ax.set_yticks(range(4), [EVENT_SHORT[key] for key in pivot.index])
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            value = pivot.iloc[i, j]
            ax.text(j, i, f"{value:+.3f}", ha="center", va="center", fontsize=7)
    colorbar = fig.colorbar(image, ax=ax, fraction=0.045, pad=0.03)
    colorbar.set_label("Candidate - History AR error")
    _panel_label(ax, "b")
    fig.tight_layout(w_pad=2.0)
    source = pd.concat([folds.assign(panel="a"), event_target.assign(panel="b")], ignore_index=True, sort=False)
    _save(fig, "F3_event_heterogeneity", source)


def _figure_4() -> None:
    controls = pd.read_csv(RESULTS_ROOT / "action_controls.csv").sort_values("candidate_minus_control")
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.5), gridspec_kw={"width_ratios": [1.6, 1]})
    ax = axes[0]
    y = np.arange(len(controls))
    delta = controls["candidate_minus_control"].to_numpy()
    xerr = np.vstack(
        [
            delta - controls["bootstrap_ci_low"].to_numpy(),
            controls["bootstrap_ci_high"].to_numpy() - delta,
        ]
    )
    colors = [OKABE_ITO["green"] if value < 0 else OKABE_ITO["vermillion"] for value in delta]
    for index in range(len(controls)):
        ax.errorbar(delta[index], index, xerr=xerr[:, index:index+1], fmt="o", color=colors[index], ecolor=colors[index], capsize=2)
    ax.axvline(0, color=OKABE_ITO["black"], linewidth=0.8)
    ax.set_yticks(y, controls["control_label"])
    ax.set_xlabel("Correct action - corrupted action error")
    ax.text(0.02, 1.02, "Correct action better", transform=ax.transAxes, color=OKABE_ITO["green"], va="bottom")
    ax.text(0.98, 1.02, "Corruption better", transform=ax.transAxes, color=OKABE_ITO["vermillion"], ha="right", va="bottom")
    ax.grid(axis="x", color=OKABE_ITO["light_gray"], linewidth=0.5)
    ax.spines[["top", "right"]].set_visible(False)
    _panel_label(ax, "a")

    ax = axes[1]
    bars = ax.barh(y, controls["candidate_fold_wins"], color=OKABE_ITO["gray"])
    ax.axvline(3, color=OKABE_ITO["vermillion"], linestyle="--", linewidth=1, label="required: 3/4")
    ax.set_yticks(y, [label.replace("Action ", "") for label in controls["control_label"]])
    ax.set_xlim(0, 4.2)
    ax.set_xticks(range(5))
    ax.set_xlabel("Folds won by correct action")
    ax.text(
        3.02,
        1.01,
        "3/4 threshold",
        transform=ax.get_xaxis_transform(),
        color=OKABE_ITO["vermillion"],
        ha="center",
        va="bottom",
        fontsize=7,
    )
    ax.spines[["top", "right"]].set_visible(False)
    for bar, value in zip(bars, controls["candidate_fold_wins"]):
        ax.text(value + 0.08, bar.get_y() + bar.get_height() / 2, str(int(value)), va="center")
    _panel_label(ax, "b")
    fig.tight_layout(w_pad=2.0)
    _save(fig, "F4_semantic_controls", controls.assign(panel="a_b"))


def _figure_5() -> None:
    horizons = pd.read_csv(RESULTS_ROOT / "horizon_profile.csv")
    contrasts = pd.read_csv(RESULTS_ROOT / "metric_sensitivity_contrasts.csv")
    horizon_pivot = horizons.pivot(index="horizon_week", columns="model_id", values="equal_event_normalized_mae")
    reported = set([1, 2, 4, 8, 12])

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.4), gridspec_kw={"width_ratios": [1.15, 1.35]})
    ax = axes[0]
    x = horizon_pivot.index.to_numpy()
    for baseline_id, color, marker, label in [
        ("history_ar_backbone", OKABE_ITO["black"], "o", "History AR"),
        ("fixed_adjacency_spatial_ar", OKABE_ITO["orange"], "s", "Spatial AR"),
    ]:
        delta = horizon_pivot["uwm_dam_gk_action_residual"] - horizon_pivot[baseline_id]
        ax.plot(x, delta, color=color, linewidth=1.2, label=label)
        for week, value in zip(x, delta):
            face = color if int(week) in reported else "white"
            ax.scatter(week, value, marker=marker, facecolor=face, edgecolor=color, s=28, zorder=3)
    ax.axhline(0, color=OKABE_ITO["gray"], linewidth=0.8)
    ax.set_xticks(range(1, 13))
    ax.set_xlabel("Forecast horizon (weeks); filled = preregistered")
    ax.set_ylabel("Candidate - baseline error")
    ax.legend(frameon=False)
    ax.grid(axis="y", color=OKABE_ITO["light_gray"], linewidth=0.5)
    ax.spines[["top", "right"]].set_visible(False)
    _panel_label(ax, "a")

    ax = axes[1]
    order = {
        ("reported_horizons_all_zones", "equal_event_normalized_mae"): 0,
        ("all_12_horizons_all_zones", "equal_event_normalized_mae"): 1,
        ("reported_horizons_all_zones", "equal_event_log1p_mae"): 2,
        ("reported_horizons_all_zones", "equal_event_median_normalized_ae"): 3,
        ("reported_horizons_all_zones", "equal_event_wape"): 4,
        ("reported_horizons_scale_at_least_10", "equal_event_normalized_mae"): 5,
        ("reported_horizons_scale_at_least_100", "equal_event_normalized_mae"): 6,
    }
    contrasts = contrasts.assign(
        display_order=[order[(row.specification, row.metric_id)] for row in contrasts.itertuples()]
    ).sort_values("display_order")
    labels = [
        "Primary: weeks 1/2/4/8/12",
        "All weeks 1-12",
        "Reported weeks, log1p MAE",
        "Reported weeks, median norm. AE",
        "Reported weeks, WAPE",
        "Reported weeks, scale >= 10",
        "Reported weeks, scale >= 100",
    ]
    y = np.arange(len(contrasts))
    ax.axhspan(-0.45, 0.45, color=OKABE_ITO["vermillion"], alpha=0.08, linewidth=0)
    ax.axhspan(0.55, 1.45, color=OKABE_ITO["green"], alpha=0.08, linewidth=0)
    ax.scatter(contrasts["candidate_minus_history"], y - 0.12, color=OKABE_ITO["black"], marker="o", label="History AR")
    ax.scatter(contrasts["candidate_minus_spatial_ar"], y + 0.12, color=OKABE_ITO["orange"], marker="s", label="Spatial AR")
    ax.axvline(0, color=OKABE_ITO["gray"], linewidth=0.8)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.get_yticklabels()[0].set_fontweight("bold")
    ax.set_xlabel("Candidate - baseline score")
    ax.grid(axis="x", color=OKABE_ITO["light_gray"], linewidth=0.5)
    ax.spines[["top", "right"]].set_visible(False)
    ax.text(0.012, 0, "loses both", color=OKABE_ITO["vermillion"], va="center", fontsize=7)
    ax.text(0.002, 1, "wins both", color=OKABE_ITO["green"], va="center", fontsize=7)
    ax.legend(frameon=False, loc="lower right")
    _panel_label(ax, "b")
    fig.tight_layout(w_pad=2.0)
    source = pd.concat([horizons.assign(panel="a"), contrasts.assign(panel="b")], ignore_index=True, sort=False)
    _save(fig, "F5_horizon_metric_sensitivity", source)


def _write_tables() -> None:
    TABLES_ROOT.mkdir(parents=True, exist_ok=True)
    primary = pd.read_csv(RESULTS_ROOT / "primary_scores.csv")[
        ["rank", "model_label", "model_type", "primary_error"]
    ].copy()
    primary["model_type"] = primary["model_type"].str.replace("_", " ")
    primary = primary.rename(
        columns={
            "rank": "Rank",
            "model_label": "Submission",
            "model_type": "Type",
            "primary_error": "Error",
        }
    )

    folds = pd.read_csv(RESULTS_ROOT / "fold_skill.csv").copy()
    folds["fold_id"] = folds["fold_id"].map(
        {
            "holdout_2015": "2015 improvement",
            "holdout_2019": "2019 congestion",
            "holdout_2022": "2022 taximeter",
            "holdout_2025": "2025 CRZ",
        }
    )
    folds["skill"] *= 100
    folds["candidate_improves"] = folds["candidate_improves"].map(
        {True: "Yes", False: "No"}
    )
    folds = folds.rename(
        columns={
            "fold_id": "Held-out action",
            "history_error": "History AR",
            "candidate_error": "Correct action",
            "candidate_minus_history": "Difference",
            "skill": "Skill (\\%)",
            "candidate_improves": "Improves",
        }
    )

    controls = pd.read_csv(RESULTS_ROOT / "action_controls.csv")[
        [
            "control_label",
            "control_error",
            "candidate_minus_control",
            "bootstrap_ci_low",
            "bootstrap_ci_high",
            "candidate_fold_wins",
        ]
    ].rename(
        columns={
            "control_label": "Corrupted action",
            "control_error": "Error",
            "candidate_minus_control": "Correct $-$ control",
            "bootstrap_ci_low": "CI low",
            "bootstrap_ci_high": "CI high",
            "candidate_fold_wins": "Fold wins",
        }
    )

    sensitivity = pd.read_csv(
        RESULTS_ROOT / "metric_sensitivity_contrasts.csv"
    ).copy()
    sensitivity["Specification"] = sensitivity.apply(
        lambda row: (
            "All weeks 1--12"
            if row["specification"] == "all_12_horizons_all_zones"
            else "Reported weeks, all zones"
            if row["specification"] == "reported_horizons_all_zones"
            else "Reported weeks, scale $\\geq$ 10"
            if row["specification"] == "reported_horizons_scale_at_least_10"
            else "Reported weeks, scale $\\geq$ 100"
        ),
        axis=1,
    )
    sensitivity["Metric"] = sensitivity["metric_id"].map(
        {
            "equal_event_normalized_mae": "Normalized MAE",
            "equal_event_median_normalized_ae": "Median normalized AE",
            "equal_event_log1p_mae": "Log1p MAE",
            "equal_event_wape": "WAPE",
        }
    )
    sensitivity["Outcome"] = np.where(
        sensitivity["candidate_beats_history"]
        & sensitivity["candidate_beats_spatial_ar"],
        "Wins both",
        "Loses both",
    )
    table_order = {
        ("reported_horizons_all_zones", "equal_event_normalized_mae"): 0,
        ("all_12_horizons_all_zones", "equal_event_normalized_mae"): 1,
        ("reported_horizons_all_zones", "equal_event_log1p_mae"): 2,
        ("reported_horizons_all_zones", "equal_event_median_normalized_ae"): 3,
        ("reported_horizons_all_zones", "equal_event_wape"): 4,
        ("reported_horizons_scale_at_least_10", "equal_event_normalized_mae"): 5,
        ("reported_horizons_scale_at_least_100", "equal_event_normalized_mae"): 6,
    }
    sensitivity["display_order"] = [
        table_order[(row.specification, row.metric_id)]
        for row in sensitivity.itertuples()
    ]
    sensitivity = sensitivity.sort_values("display_order")
    sensitivity = sensitivity[
        [
            "Specification",
            "Metric",
            "candidate_score",
            "history_score",
            "spatial_ar_score",
            "candidate_minus_history",
            "candidate_minus_spatial_ar",
            "Outcome",
        ]
    ].rename(
        columns={
            "candidate_score": "Correct",
            "history_score": "History",
            "spatial_ar_score": "Spatial",
            "candidate_minus_history": "$\\Delta$Hist.",
            "candidate_minus_spatial_ar": "$\\Delta$Spatial",
        }
    )

    tables = {
        "tab1_primary_scores": primary,
        "tab2_fold_skill": folds,
        "tab3_action_controls": controls,
        "tab4_metric_sensitivity": sensitivity,
    }
    captions = {
        "tab1_primary_scores": "Primary equal-event model and control ranking.",
        "tab2_fold_skill": "Leave-one-action-out skill relative to the History AR baseline.",
        "tab3_action_controls": "Semantic action-control comparisons.",
        "tab4_metric_sensitivity": "Non-retuned metric and horizon sensitivity.",
    }
    for name, frame in tables.items():
        latex = frame.to_latex(
            index=False,
            float_format="%.4f",
            caption=captions[name],
            label=f"tab:{name}",
            escape=False,
        )
        latex = latex.replace("\\begin{table}", "\\begin{table}[H]", 1)
        if name == "tab3_action_controls":
            size = "\\scriptsize\n\\setlength{\\tabcolsep}{4pt}"
        else:
            size = "\\scriptsize" if name == "tab4_metric_sensitivity" else "\\small"
        latex = latex.replace("\\begin{tabular}", f"{size}\n\\begin{{tabular}}", 1)
        (TABLES_ROOT / f"{name}.tex").write_text(latex, encoding="utf-8")


def main() -> int:
    apply_paper_style()
    _figure_1()
    _figure_2()
    _figure_3()
    _figure_4()
    _figure_5()
    _write_tables()
    print("Rendered 5 figures in PDF/SVG/PNG and 4 LaTeX tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
