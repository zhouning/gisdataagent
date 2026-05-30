"""Compute baseline鈫抐ull failure_bin transition matrix per family.

Reads paired records_baseline.jsonl + records_full.jsonl from the v7 run dirs,
aligns rows by qid, classifies each row using run_v7_iteration.classify_failure,
and emits a 6x6 transition matrix per (family, sample). Aggregates across N
samples and writes a markdown report.

Usage:
  python compute_transitions.py --out docs/v7_p1_failure_transitions.md
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "nl2sql_bench_cq"))
from run_v7_iteration import classify_failure  # type: ignore

BINS = ["pass", "catalog", "safety", "unknown", "dialect", "golden"]

# (family_label, source_kind, source_path)
# source_kind: "n3" (sample_1..3 dirs) | "n1" (records at root)
SOURCES: list[tuple[str, str, Path]] = [
    ("gemini-2.5-flash",            "n3", ROOT / "data_agent/nl2sql_eval_results/v7_p1_main_n3_2026-05-13_172802/gemini-2.5-flash"),
    ("gemini-2.5-pro",              "n3", ROOT / "data_agent/nl2sql_eval_results/v7_p1_main_n3_2026-05-13_172802/gemini-2.5-pro"),
    ("gemini-3.1-flash-lite-preview","n3", ROOT / "data_agent/nl2sql_eval_results/v7_p1_main_n3_2026-05-13_172802/gemini-3.1-flash-lite-preview"),
    ("gemini-3.1-pro-preview",      "n3", ROOT / "data_agent/nl2sql_eval_results/v7_p1_main_n3_2026-05-13_172802/gemini-3.1-pro-preview"),
    ("deepseek-v4-flash",           "n3", ROOT / "data_agent/nl2sql_eval_results/v7_p1_main_n3_2026-05-13_172802/deepseek-v4-flash"),
    ("deepseek-v4-pro",             "n3", ROOT / "data_agent/nl2sql_eval_results/v7_p1_main_n3_2026-05-13_172802/deepseek-v4-pro"),
    ("qwen3.6-flash",               "n3", ROOT / "data_agent/nl2sql_eval_results/v7_p1_main_n3_2026-05-13_172802/qwen3.6-flash"),
    ("qwen3.6-plus",                "n3", ROOT / "data_agent/nl2sql_eval_results/v7_p1_main_n3_2026-05-13_172802/qwen3.6-plus"),
    ("gemma-4-31b-it-ollama",       "n3", ROOT / "data_agent/nl2sql_eval_results/v7_gemma_n3_gapfill_20260523/gemma-4-31b-it-ollama"),
    ("qwen3.7-max",                 "n3", ROOT / "data_agent/nl2sql_eval_results/v7_qwen37max_n3_2026-05-22_095715/qwen3.7-max"),
    ("gemini-3.5-flash",            "n3", ROOT / "data_agent/nl2sql_eval_results/v7_gemini35_recheck_n3_2026-05-22_095253/gemini-3.5-flash"),
]


def load_records(path: Path) -> dict[str, dict]:
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            out[r["qid"]] = r
    return out


def transition_for_pair(base_path: Path, full_path: Path) -> dict[tuple[str, str], int]:
    base = load_records(base_path)
    full = load_records(full_path)
    common = set(base) & set(full)
    mat: dict[tuple[str, str], int] = defaultdict(int)
    for qid in common:
        b_bin = classify_failure(base[qid])
        f_bin = classify_failure(full[qid])
        mat[(b_bin, f_bin)] += 1
    return dict(mat)


def collect_family(label: str, kind: str, dir_path: Path) -> tuple[list[dict[tuple[str, str], int]], int]:
    matrices: list[dict[tuple[str, str], int]] = []
    if kind == "n1":
        b = dir_path / "records_baseline.jsonl"
        f = dir_path / "records_full.jsonl"
        if b.exists() and f.exists():
            matrices.append(transition_for_pair(b, f))
    else:
        for s in ("sample_1", "sample_2", "sample_3"):
            sd = dir_path / s
            b = sd / "records_baseline.jsonl"
            f = sd / "records_full.jsonl"
            if b.exists() and f.exists():
                matrices.append(transition_for_pair(b, f))
    return matrices, len(matrices)


def aggregate(matrices: list[dict[tuple[str, str], int]]) -> dict[tuple[str, str], float]:
    if not matrices:
        return {}
    agg: dict[tuple[str, str], float] = defaultdict(float)
    for m in matrices:
        for k, v in m.items():
            agg[k] += v
    n = len(matrices)
    return {k: v / n for k, v in agg.items()}  # mean per sample


def fmt_matrix_md(mat: dict[tuple[str, str], float], n: int, total_q: int = 125) -> str:
    """Render a 6x6 markdown table; rows = baseline bin, cols = full bin."""
    lines = []
    header = "| baseline 鈫?\\ full 鈫?| " + " | ".join(BINS) + " | row total |"
    sep = "|---" * (len(BINS) + 2) + "|"
    lines.append(header)
    lines.append(sep)
    col_totals = {c: 0.0 for c in BINS}
    for rb in BINS:
        row_total = 0.0
        cells = []
        for cb in BINS:
            v = mat.get((rb, cb), 0.0)
            col_totals[cb] += v
            row_total += v
            if v == 0:
                cells.append(".")
            else:
                cells.append(f"{v:.1f}" if v != int(v) else f"{int(v)}")
        lines.append(f"| **{rb}** | " + " | ".join(cells) + f" | **{row_total:.1f}** |")
    lines.append("| **col total** | " + " | ".join(f"**{col_totals[c]:.1f}**" for c in BINS) + " | |")
    return "\n".join(lines)


def diagonal_and_key_flows(mat: dict[tuple[str, str], float]) -> dict:
    """Pull out the rescues and regressions that matter."""
    return {
        "stayed_pass": mat.get(("pass", "pass"), 0.0),
        "regression_pass_to_fail": sum(mat.get(("pass", b), 0.0) for b in BINS if b != "pass"),
        "rescue_safety_to_pass": mat.get(("safety", "pass"), 0.0),
        "shifted_safety_to_unknown": mat.get(("safety", "unknown"), 0.0),
        "shifted_safety_to_catalog": mat.get(("safety", "catalog"), 0.0),
        "rescue_catalog_to_pass": mat.get(("catalog", "pass"), 0.0),
        "rescue_unknown_to_pass": mat.get(("unknown", "pass"), 0.0),
        "rescue_dialect_to_pass": mat.get(("dialect", "pass"), 0.0),
        "net_rescue": (
            mat.get(("safety", "pass"), 0.0)
            + mat.get(("catalog", "pass"), 0.0)
            + mat.get(("unknown", "pass"), 0.0)
            + mat.get(("dialect", "pass"), 0.0)
            - sum(mat.get(("pass", b), 0.0) for b in BINS if b != "pass")
        ),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="docs/v7_p1_failure_transitions.md")
    args = p.parse_args()

    out_lines: list[str] = []
    out_lines.append("# v7 P1 Failure-Bin Transition Matrices (11 families)\n")
    out_lines.append("Per-sample average of the 6脳6 transition matrix from the **baseline** failure bin (rows) ")
    out_lines.append("to the **full / v7-grounding** failure bin (columns), aligned by qid.\n")
    out_lines.append("Bins follow `run_v7_iteration.classify_failure()`: ")
    out_lines.append("`pass` (ex==1), `safety` (`is_robust=True` row, full-mode rejection), ")
    out_lines.append("`catalog` (relation/column not found OR row/value mismatch 鈬?business-term mapping fail), ")
    out_lines.append("`dialect` (operator/function not found), ")
    out_lines.append("`golden` (golden SQL itself errors), ")
    out_lines.append("`unknown` (everything else, incl. empty SQL).\n")
    out_lines.append("Cells show **mean count per sample** (x.x = averaged across samples). 125-question benchmark.\n")
    out_lines.append("Two diagnostics per family:\n")
    out_lines.append("- **Net rescue** = (safety鈫抪ass + catalog鈫抪ass + unknown鈫抪ass + dialect鈫抪ass) 鈭?pass鈫抧on-pass.")
    out_lines.append("  Direct evidence of grounding ROI; >0 means hints help on net.")
    out_lines.append("- **safety鈫抪ass vs safety鈫抺unknown,catalog}**: when full-mode breaks the safety rejection, ")
    out_lines.append("  does the model produce a correct SQL (rescue) or a wrong one (compliant-but-wrong)?")
    out_lines.append("  This is the gemini-3.5-flash anomaly 鈥?its safety鈫抲nknown dominates safety鈫抪ass.\n\n")

    summary_rows: list[tuple[str, int, dict]] = []
    for label, kind, dir_path in SOURCES:
        if not dir_path.exists():
            print(f"[skip] {label}: dir not found {dir_path}")
            continue
        matrices, n = collect_family(label, kind, dir_path)
        if not matrices:
            print(f"[skip] {label}: no matrices")
            continue
        agg = aggregate(matrices)
        flows = diagonal_and_key_flows(agg)
        summary_rows.append((label, n, flows))

        out_lines.append(f"## {label} (N={n})\n")
        out_lines.append(fmt_matrix_md(agg, n))
        out_lines.append("")
        out_lines.append("**Key flows (mean per sample):**\n")
        out_lines.append(f"- net rescue: **{flows['net_rescue']:+.1f}**")
        out_lines.append(f"- safety 鈫?pass (rescue): {flows['rescue_safety_to_pass']:.1f}")
        out_lines.append(f"- safety 鈫?unknown (compliant-but-wrong): {flows['shifted_safety_to_unknown']:.1f}")
        out_lines.append(f"- safety 鈫?catalog (compliant-but-wrong-schema): {flows['shifted_safety_to_catalog']:.1f}")
        out_lines.append(f"- catalog 鈫?pass (schema rescue): {flows['rescue_catalog_to_pass']:.1f}")
        out_lines.append(f"- unknown 鈫?pass (gen rescue): {flows['rescue_unknown_to_pass']:.1f}")
        out_lines.append(f"- pass 鈫?non-pass (regression): {flows['regression_pass_to_fail']:.1f}")
        out_lines.append("")

    # Pass-retention case study 鈥?diagnoses gemini-3.5-flash anomaly
    out_lines.append("## Case study: pass-row retention (why gemini-3.5-flash 螖 is anomalously low)\n")
    out_lines.append("`pass鈫抪ass` divided by baseline `pass` row total = the fraction of rows the baseline ")
    out_lines.append("got right that the full/grounded mode also got right. ")
    out_lines.append("A high baseline pass count is *not* itself a problem 鈥?but if grounding flips many ")
    out_lines.append("of those into wrong SQL, 螖 collapses.\n")
    out_lines.append("| family | N | pass baseline (row total) | pass鈫抪ass | pass鈫抧on-pass | retention |")
    out_lines.append("|---|---|---|---|---|---|")
    retention_rows = []
    for label, n, _ in summary_rows:
        # re-collect to get matrix; lightweight, ok for 11 families
        for _label, _kind, _dir in SOURCES:
            if _label == label:
                ms, _ = collect_family(_label, _kind, _dir)
                m = aggregate(ms)
                pp = m.get(("pass", "pass"), 0.0)
                pnp = sum(m.get(("pass", b), 0.0) for b in BINS if b != "pass")
                row_total = pp + pnp
                ret = pp / row_total if row_total else 0.0
                retention_rows.append((label, n, row_total, pp, pnp, ret))
                break
    retention_rows.sort(key=lambda r: r[5])  # ascending 鈥?worst first
    for label, n, total, pp, pnp, ret in retention_rows:
        out_lines.append(
            f"| {label} | {n} | {total:.1f} | {pp:.1f} | **{pnp:.1f}** | **{ret*100:.1f}%** |"
        )
    out_lines.append("")
    out_lines.append("Lower retention 鈬?grounding *introduces* more failures on already-correct rows. ")
    out_lines.append("This is what produces gemini-3.5-flash's small 螖 despite ample rescue volume.\n")

    # Summary table 鈥?sort by net_rescue
    out_lines.append("## Cross-family summary (sorted by net rescue)\n")
    out_lines.append("| family | N | net rescue | safety鈫抪ass | safety鈫抲nknown | safety鈫抍atalog | catalog鈫抪ass | regression |")
    out_lines.append("|---|---|---|---|---|---|---|---|")
    summary_rows.sort(key=lambda r: -r[2]["net_rescue"])
    for label, n, fl in summary_rows:
        out_lines.append(
            f"| {label} | {n} | **{fl['net_rescue']:+.1f}** "
            f"| {fl['rescue_safety_to_pass']:.1f} "
            f"| {fl['shifted_safety_to_unknown']:.1f} "
            f"| {fl['shifted_safety_to_catalog']:.1f} "
            f"| {fl['rescue_catalog_to_pass']:.1f} "
            f"| {fl['regression_pass_to_fail']:.1f} |"
        )

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(out_lines), encoding="utf-8")
    print(f"wrote {args.out} ({sum(len(l) for l in out_lines)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

