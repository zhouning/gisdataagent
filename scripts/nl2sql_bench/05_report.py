"""Step 5 — Generate comparison report from eval run output.

Reads `full_results.json` and/or `baseline_results.json` from a run dir,
emits `comparison_report.md` + `error_analysis.md` + `by_difficulty.png`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESULTS_ROOT = Path(__file__).resolve().parents[2] / "data_agent" / "nl2sql_eval_results"


def load_run(run_dir: Path) -> dict:
    out: dict = {"dir": run_dir, "full": None, "baseline": None}
    for mode in ("full", "baseline"):
        fp = run_dir / f"{mode}_results.json"
        if fp.exists():
            out[mode] = json.loads(fp.read_text(encoding="utf-8"))
    return out


def latest_run_dir() -> Path:
    if not RESULTS_ROOT.exists():
        raise FileNotFoundError(f"no results root: {RESULTS_ROOT}")
    candidates = sorted(
        [p for p in RESULTS_ROOT.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"no run dirs under {RESULTS_ROOT}")
    return candidates[0]


def render_chart(run: dict, out_png: Path) -> None:
    """Bar chart of EX by difficulty for full vs baseline."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  matplotlib not available, skipping chart")
        return

    diffs = sorted(
        set((run["full"] or {}).get("aggregate", {}).get("by_difficulty", {}).keys())
        | set((run["baseline"] or {}).get("aggregate", {}).get("by_difficulty", {}).keys())
    )
    if not diffs:
        return

    full_vals = [(run["full"] or {}).get("aggregate", {}).get("by_difficulty", {}).get(d, 0.0) for d in diffs]
    base_vals = [(run["baseline"] or {}).get("aggregate", {}).get("by_difficulty", {}).get(d, 0.0) for d in diffs]

    import numpy as np
    x = np.arange(len(diffs))
    w = 0.38
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(x - w / 2, full_vals, w, label="Full pipeline", color="#2563eb")
    ax.bar(x + w / 2, base_vals, w, label="Baseline (LLM only)", color="#9ca3af")
    ax.set_xticks(x)
    ax.set_xticklabels(diffs)
    ax.set_ylabel("Execution Accuracy (EX)")
    ax.set_ylim(0, 1.05)
    ax.set_title("FloodSQL-Bench EX by difficulty")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_png, dpi=120)
    plt.close(fig)
    print(f"  wrote {out_png}")


def render_report(run: dict, out_md: Path) -> None:
    full = run["full"]
    base = run["baseline"]

    lines: list[str] = []
    lines.append("# FloodSQL-Bench NL2SQL Comparison Report")
    lines.append("")
    lines.append(f"Run dir: `{run['dir']}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Full pipeline | Baseline (LLM only) | Δ |")
    lines.append("|---|---:|---:|---:|")

    def m(d: dict | None, k: str) -> float:
        return (d or {}).get("aggregate", {}).get(k, 0.0)

    for k in ("execution_accuracy", "execution_valid_rate", "exact_match_rate"):
        f, b = m(full, k), m(base, k)
        delta = f - b
        lines.append(f"| {k} | {f:.3f} | {b:.3f} | {delta:+.3f} |")
    n_full = (full or {}).get("aggregate", {}).get("n", 0)
    n_base = (base or {}).get("aggregate", {}).get("n", 0)
    lines.append(f"| n | {n_full} | {n_base} | — |")

    lines.append("")
    lines.append("## EX by difficulty")
    lines.append("")
    lines.append("![EX by difficulty](by_difficulty.png)")
    lines.append("")

    # Error type table
    for label, d in [("Full", full), ("Baseline", base)]:
        if not d:
            continue
        et = d.get("aggregate", {}).get("error_types", {})
        if not et:
            continue
        lines.append(f"### {label} error types")
        lines.append("")
        lines.append("| Type | Count |")
        lines.append("|---|---:|")
        for k, v in et.items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

    # Cross-mode diff samples (if both available)
    if full and base:
        full_by = {r["qid"]: r for r in full["records"]}
        base_by = {r["qid"]: r for r in base["records"]}
        full_only_correct = []
        base_only_correct = []
        for qid in full_by.keys() & base_by.keys():
            f = full_by[qid]["metrics"]["execution_accuracy"] == 1.0
            b = base_by[qid]["metrics"]["execution_accuracy"] == 1.0
            if f and not b:
                full_only_correct.append(qid)
            elif b and not f:
                base_only_correct.append(qid)

        lines.append(f"## Where they differ")
        lines.append("")
        lines.append(f"- Full correct, baseline wrong: **{len(full_only_correct)}** "
                     "(potential semantic-layer wins)")
        lines.append(f"- Baseline correct, full wrong: **{len(base_only_correct)}** "
                     "(potential pipeline regressions)")
        lines.append("")
        if full_only_correct:
            lines.append("### Top 10 — full-only correct (semantic-layer wins)")
            lines.append("")
            for qid in full_only_correct[:10]:
                q = full_by[qid]
                lines.append(f"- `{qid}` ({q['difficulty']}): {q['question']}")
        if base_only_correct:
            lines.append("")
            lines.append("### Top 10 — baseline-only correct (full pipeline regressions)")
            lines.append("")
            for qid in base_only_correct[:10]:
                q = base_by[qid]
                lines.append(f"- `{qid}` ({q['difficulty']}): {q['question']}")
        lines.append("")

    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"  wrote {out_md}")


def render_error_analysis(run: dict, out_md: Path) -> None:
    """Per-mode list of failures with predicted vs gold SQL for inspection."""
    lines: list[str] = ["# NL2SQL Error Analysis", ""]
    for label, key in [("Full pipeline", "full"), ("Baseline", "baseline")]:
        d = run[key]
        if not d:
            continue
        fails = [r for r in d["records"] if r["metrics"]["execution_accuracy"] != 1.0]
        lines.append(f"## {label}: {len(fails)} failures")
        lines.append("")
        for r in fails[:50]:
            lines.append(f"### `{r['qid']}` ({r['difficulty']})")
            lines.append(f"- **Question**: {r['question']}")
            lines.append(f"- **Gold SQL**: `{r['gold_sql'][:300]}`")
            lines.append(f"- **Pred SQL**: `{r.get('pred_sql', '')[:300]}`")
            lines.append(f"- **Reason**: {r['metrics'].get('compare_reason', '')} "
                         f"(pred_status={r['metrics'].get('pred_status')})")
            lines.append("")
        if len(fails) > 50:
            lines.append(f"_(... {len(fails) - 50} more failures truncated)_")
            lines.append("")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"  wrote {out_md}")


def main() -> int:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dir", help="Run directory to report on")
    g.add_argument("--latest", action="store_true", help="Use the latest run dir")
    args = p.parse_args()

    if args.latest or not args.dir:
        run_dir = latest_run_dir()
    else:
        run_dir = Path(args.dir)

    print(f"[report] {run_dir}")
    run = load_run(run_dir)
    if not run["full"] and not run["baseline"]:
        print("ERROR: neither full_results.json nor baseline_results.json found.", file=sys.stderr)
        return 1

    render_chart(run, run_dir / "by_difficulty.png")
    render_report(run, run_dir / "comparison_report.md")
    render_error_analysis(run, run_dir / "error_analysis.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
