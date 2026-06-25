#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Sequence


DEFAULT_CANDIDATES = (
    "twm_independent_transition_forecast_demand",
    "twm_hierarchical_transition_forecast_demand",
    "markov_transition_projection",
    "persistence",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize fixed-seed TWM vs FLUS Dynamic World comparison reports.")
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, default=None)
    args = parser.parse_args()

    summary = summarize_seed_reports(args.reports)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "output": str(args.output)}, ensure_ascii=False))


def summarize_seed_reports(paths: Sequence[Path]) -> dict[str, Any]:
    reports = [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]
    seed_rows = [_seed_row(path, report) for path, report in zip(paths, reports)]
    candidates = sorted(
        {
            candidate_id
            for report in reports
            for candidate_id in report["formal_forecast_comparison"].get("paired_deltas_vs_flus", {})
        }
    )
    return {
        "schema": "territory_world_model.dynamic_world_flus_seed_stability.v1",
        "status": "pass" if reports else "blocked",
        "seed_count": len(reports),
        "seeds": [row["flus_seed"] for row in seed_rows],
        "case_count_per_seed": seed_rows[0]["case_count"] if seed_rows else 0,
        "evaluated_case_count_per_seed": seed_rows[0]["evaluated_case_count"] if seed_rows else 0,
        "seed_reports": seed_rows,
        "candidate_stability": {
            candidate_id: _candidate_stability(reports, candidate_id)
            for candidate_id in candidates
        },
        "claim_boundary": (
            "Fixed-seed direct FLUS CA stability summary. FLUS suitability remains adapter-supplied "
            "transition-prior probability, not full FLUS ANN training."
        ),
    }


def _seed_row(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    profile = report.get("data_profile") or {}
    return {
        "path": str(path),
        "flus_seed": report.get("run_policy", {}).get("flus_seed"),
        "case_count": int(profile.get("case_count", 0)),
        "evaluated_case_count": int(profile.get("evaluated_case_count", 0)),
        "max_iterations": report.get("run_policy", {}).get("max_iterations"),
    }


def _candidate_stability(reports: list[dict[str, Any]], candidate_id: str) -> dict[str, Any]:
    paired_rows = [
        report["formal_forecast_comparison"]["paired_deltas_vs_flus"][candidate_id]
        for report in reports
        if candidate_id in report["formal_forecast_comparison"].get("paired_deltas_vs_flus", {})
    ]
    ranking_rows = [_ranking_by_candidate(report).get(candidate_id, {}) for report in reports]
    flus_rows = [_ranking_by_candidate(report).get("flus_console_direct", {}) for report in reports]
    return {
        "seed_count": len(paired_rows),
        "change_fom_delta": _numeric_stability(paired_rows, "mean_change_fom_delta"),
        "median_change_fom_delta": _numeric_stability(paired_rows, "median_change_fom_delta"),
        "overall_accuracy_delta": _numeric_stability(paired_rows, "mean_overall_accuracy_delta"),
        "macro_f1_delta": _numeric_stability(paired_rows, "mean_macro_f1_delta"),
        "target_demand_abs_error_delta": _numeric_stability(paired_rows, "total_target_demand_abs_error_delta"),
        "change_fom_win_count": _numeric_stability(paired_rows, "wins_by_change_fom"),
        "change_fom_loss_count": _numeric_stability(paired_rows, "losses_by_change_fom"),
        "candidate_mean_change_fom": _numeric_stability(ranking_rows, "mean_change_fom"),
        "flus_mean_change_fom": _numeric_stability(flus_rows, "mean_change_fom"),
        "candidate_mean_overall_accuracy": _numeric_stability(ranking_rows, "mean_overall_accuracy"),
        "flus_mean_overall_accuracy": _numeric_stability(flus_rows, "mean_overall_accuracy"),
    }


def _ranking_by_candidate(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row["candidate_id"]: row
        for row in report["formal_forecast_comparison"].get("ranking_by_mean_change_fom", [])
    }


def _numeric_stability(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = [float(row[key]) for row in rows if key in row]
    if not values:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
            "positive_seed_count": 0,
            "negative_seed_count": 0,
            "zero_seed_count": 0,
        }
    return {
        "count": len(values),
        "mean": round(float(statistics.mean(values)), 6),
        "median": round(float(statistics.median(values)), 6),
        "min": round(float(min(values)), 6),
        "max": round(float(max(values)), 6),
        "positive_seed_count": sum(1 for value in values if value > 0),
        "negative_seed_count": sum(1 for value in values if value < 0),
        "zero_seed_count": sum(1 for value in values if value == 0),
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# TWM vs FLUS Fixed-Seed Stability Summary",
        "",
        f"Seeds: {', '.join(str(seed) for seed in summary['seeds'])}",
        f"Cases per seed: {summary['case_count_per_seed']}",
        "",
        "| candidate | change FoM delta mean | change FoM delta range | OA delta mean | macro F1 delta mean |",
        "|---|---:|---:|---:|---:|",
    ]
    for candidate_id in DEFAULT_CANDIDATES:
        payload = summary["candidate_stability"].get(candidate_id)
        if not payload:
            continue
        change = payload["change_fom_delta"]
        oa = payload["overall_accuracy_delta"]
        macro = payload["macro_f1_delta"]
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{candidate_id}`",
                    f"{change['mean']:.6f}",
                    f"{change['min']:.6f} to {change['max']:.6f}",
                    f"{oa['mean']:.6f}",
                    f"{macro['mean']:.6f}",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "Claim boundary: fixed-seed direct FLUS CA with adapter-supplied transition-prior suitability; not yet full FLUS ANN suitability training.",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
