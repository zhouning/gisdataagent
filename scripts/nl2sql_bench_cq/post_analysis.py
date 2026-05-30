"""Post-analysis report for a v7 minimod / grounding evaluation run.

Reads the N-sample JSONL records under
``data_agent/nl2sql_eval_results/<run-dir>/<family>/sample_*/`` and produces:

  1. Per-sample EX (strict + col_count-relaxed)
  2. Aggregate Δ with paired t-test (df = N − 1)
  3. Failure-bin transition (baseline → full per sub-bin)
  4. Unknown bin sub-classification (empty / col_count / pred_err / non_select / dangerous)
  5. Cross-family Δ comparison if other run dirs are passed via --compare

This is the canonical reproduction tool for the IJGIS minimod section. The
ad-hoc scripts under ``_review_unknown_bin.py``, ``_unknown_subbin_summary.py``,
and ``_rescore_relaxed_colcount.py`` are subsumed.

Usage:

    # Single run (gemini-3.5-flash N=3 so far, will pick up N=5 automatically)
    python scripts/nl2sql_bench_cq/post_analysis.py \
        --run-dir data_agent/nl2sql_eval_results/v7_gemini35_minimod_n3_20260524 \
        --family gemini-3.5-flash

    # Cross-family comparison
    python scripts/nl2sql_bench_cq/post_analysis.py \
        --run-dir data_agent/nl2sql_eval_results/v7_gemini35_minimod_n3_20260524 \
        --family gemini-3.5-flash \
        --compare data_agent/nl2sql_eval_results/v7_qwen37max_n3_2026-05-22_095715:qwen3.7-max \
                  data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934:deepseek-v4-flash

    # JSON output for downstream tooling (e.g. autogenerate paper tables)
    python scripts/nl2sql_bench_cq/post_analysis.py --run-dir ... --family ... --json
"""
from __future__ import annotations
import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "nl2sql_bench_cq"))
from run_v7_iteration import classify_failure  # type: ignore

COLCOUNT_RE = re.compile(r"col count: gold=(\d+)\s+pred=(\d+)")
# t critical at α=0.05 two-tailed for small df. Hardcoded to avoid scipy dep.
T_CRIT_95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
             6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228}


# ---------- core: load + score one sample ----------

def relaxed_ex(rec: dict) -> int:
    """Return 1 if rec passes under col_count-relaxed policy.

    Relaxed: if reason is purely 'col count: gold=A pred=B' with A <= B,
    treat as pass (gold is a strict subset of pred output → spec ambiguity,
    not semantic error).
    """
    if rec["ex"] == 1:
        return 1
    m = COLCOUNT_RE.search(rec.get("reason") or "")
    if not m:
        return 0
    g, p = int(m.group(1)), int(m.group(2))
    return 1 if g <= p else 0


def subclass_unknown(rec: dict) -> str:
    """Sub-classify an `unknown`-bin record by signature."""
    pred = (rec.get("pred_sql") or "").strip()
    reason = (rec.get("reason") or "").lower()
    perr = (rec.get("pred_error") or "").lower()
    if not pred:
        return "empty"
    if "dangerous" in reason:
        return "dangerous"
    if "non-select" in reason:
        return "non_select"
    if "col count" in reason:
        return "col_count"
    if "limit-unstable" in reason:
        return "limit_unstable"
    if perr:
        return "pred_error"
    return "other"


def score_sample(records: list[dict]) -> dict:
    n = len(records)
    strict_ex = sum(r["ex"] for r in records)
    relaxed = sum(relaxed_ex(r) for r in records)
    bins = Counter(classify_failure(r) for r in records)
    sub_unknown = Counter(subclass_unknown(r) for r in records
                          if classify_failure(r) == "unknown")
    # Per-record by-qid map for cross-mode (McNemar) and by-category breakdown
    per_qid = {}
    for r in records:
        per_qid[r["qid"]] = {
            "ex": r["ex"],
            "relaxed_ex": relaxed_ex(r),
            "category": r.get("category", "?"),
            "difficulty": r.get("difficulty", "?"),
        }
    return dict(
        n=n,
        strict_ex=strict_ex,
        relaxed_ex=relaxed,
        bins=dict(bins),
        sub_unknown=dict(sub_unknown),
        per_qid=per_qid,
    )


def load_sample(sample_dir: Path, mode: str) -> list[dict] | None:
    p = sample_dir / f"records_{mode}.jsonl"
    if not p.exists():
        return None
    return [json.loads(l) for l in p.open(encoding="utf-8")]


def discover_samples(run_dir: Path, family: str) -> list[Path]:
    fam_dir = run_dir / family
    return sorted([p for p in fam_dir.glob("sample_*") if p.is_dir()],
                  key=lambda p: int(p.name.split("_")[1]))


# ---------- t-test ----------

def t_test(deltas: list[float]) -> dict:
    n = len(deltas)
    if n < 2:
        return {"n": n, "mean": deltas[0] if deltas else 0.0,
                "sd": 0.0, "se": 0.0, "t": 0.0, "ci95_lo": 0.0, "ci95_hi": 0.0}
    m = sum(deltas) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in deltas) / (n - 1))
    se = sd / math.sqrt(n)
    t = m / se if se else float("inf")
    tc = T_CRIT_95.get(n - 1, T_CRIT_95[10])
    ci = tc * se
    return {"n": n, "mean": m, "sd": sd, "se": se, "t": t,
            "ci95_lo": m - ci, "ci95_hi": m + ci}


# ---------- McNemar exact binomial paired test ----------

def _binom_logpmf(k: int, n: int, p: float = 0.5) -> float:
    """Log binomial pmf without scipy."""
    if k < 0 or k > n:
        return float("-inf")
    # log C(n,k)
    log_c = sum(math.log(n - i) - math.log(i + 1) for i in range(k))
    return log_c + k * math.log(p) + (n - k) * math.log(1 - p)


def mcnemar_exact(b: int, c: int) -> dict:
    """Exact two-sided McNemar test on discordant pairs.

    b = baseline-pass / full-fail
    c = baseline-fail / full-pass
    Discordant n = b + c. Under H0 each discordant tilts either way w.p. 0.5.
    Two-sided p = 2 * P(K <= min(b, c) | n, 0.5), clipped at 1.0.
    """
    n_disc = b + c
    if n_disc == 0:
        return {"b": 0, "c": 0, "n_discordant": 0, "p": 1.0, "favor": "tie"}
    k = min(b, c)
    log_p_one = math.log(sum(math.exp(_binom_logpmf(i, n_disc)) for i in range(k + 1)))
    p_two = min(1.0, 2 * math.exp(log_p_one))
    favor = "full" if c > b else ("baseline" if b > c else "tie")
    return {"b": b, "c": c, "n_discordant": n_disc, "p": p_two, "favor": favor}


def per_sample_mcnemar(base_per_qid: dict, full_per_qid: dict, key: str = "ex") -> dict:
    """Compute McNemar b/c by aligning qids across modes."""
    common = set(base_per_qid) & set(full_per_qid)
    b = sum(1 for q in common
            if base_per_qid[q][key] == 1 and full_per_qid[q][key] == 0)
    c = sum(1 for q in common
            if base_per_qid[q][key] == 0 and full_per_qid[q][key] == 1)
    return mcnemar_exact(b, c)


def aggregate_mcnemar(rows: list[dict]) -> dict:
    """Pool discordant pairs across all complete samples, then test once."""
    bb, cc = 0, 0
    for r in rows:
        b, f = r.get("baseline"), r.get("full")
        if not (b and f):
            continue
        common = set(b["per_qid"]) & set(f["per_qid"])
        bb += sum(1 for q in common
                  if b["per_qid"][q]["ex"] == 1 and f["per_qid"][q]["ex"] == 0)
        cc += sum(1 for q in common
                  if b["per_qid"][q]["ex"] == 0 and f["per_qid"][q]["ex"] == 1)
    return mcnemar_exact(bb, cc)


# ---------- Subset Δ (robustness / spatial / by category) ----------

def subset_delta(rows: list[dict], filter_fn) -> dict:
    """Δ on subset of qids matching filter_fn(qid_meta).

    Returns dict with per-sample EX (baseline/full) and aggregate mean Δ.
    """
    per_sample = []
    for r in rows:
        b, f = r.get("baseline"), r.get("full")
        if not (b and f):
            continue
        # Filter qids using baseline's metadata (all qids share same metadata)
        sub_qids = [q for q, meta in b["per_qid"].items() if filter_fn(meta)]
        n_sub = len(sub_qids)
        if n_sub == 0:
            continue
        bex = sum(b["per_qid"][q]["ex"] for q in sub_qids)
        fex = sum(f["per_qid"][q]["ex"] for q in sub_qids)
        per_sample.append({
            "sample": r["sample"],
            "n": n_sub, "b_ex": bex, "f_ex": fex,
            "delta_pp": (fex - bex) / n_sub * 100,
        })
    # Aggregate Δ across samples
    if per_sample:
        deltas = [s["delta_pp"] for s in per_sample]
        stats = t_test(deltas)
    else:
        stats = t_test([])
    # Aggregate McNemar
    bb, cc = 0, 0
    for r in rows:
        b, f = r.get("baseline"), r.get("full")
        if not (b and f):
            continue
        sub_qids = [q for q, meta in b["per_qid"].items() if filter_fn(meta)]
        bb += sum(1 for q in sub_qids
                  if b["per_qid"][q]["ex"] == 1 and f["per_qid"][q]["ex"] == 0)
        cc += sum(1 for q in sub_qids
                  if b["per_qid"][q]["ex"] == 0 and f["per_qid"][q]["ex"] == 1)
    return {
        "per_sample": per_sample,
        "stats": stats,
        "mcnemar": mcnemar_exact(bb, cc),
    }


# ---------- aggregation ----------

def analyze_run(run_dir: Path, family: str, expected_n: int = 125) -> dict:
    samples = discover_samples(run_dir, family)
    if not samples:
        raise SystemExit(f"no sample_* dirs under {run_dir}/{family}")
    rows: list[dict] = []
    for sd in samples:
        row = {"sample": sd.name}
        for mode in ("baseline", "full"):
            recs = load_sample(sd, mode)
            if recs is None:
                row[mode] = None
                row[f"{mode}_status"] = "missing"
            elif len(recs) < expected_n:
                row[mode] = None
                row[f"{mode}_status"] = f"in-progress ({len(recs)}/{expected_n})"
            else:
                row[mode] = score_sample(recs)
                row[f"{mode}_status"] = "complete"
        rows.append(row)
    # Δ vectors only over samples where both modes are complete
    strict_d = []
    relaxed_d = []
    for r in rows:
        b, f = r.get("baseline"), r.get("full")
        if not (b and f):
            continue
        strict_d.append((f["strict_ex"] - b["strict_ex"]) / b["n"] * 100)
        relaxed_d.append((f["relaxed_ex"] - b["relaxed_ex"]) / b["n"] * 100)
    return {
        "run_dir": str(run_dir),
        "family": family,
        "expected_n": expected_n,
        "samples": rows,
        "strict": {"deltas": strict_d, "stats": t_test(strict_d)},
        "relaxed": {"deltas": relaxed_d, "stats": t_test(relaxed_d)},
    }


def aggregate_failure_bins(rows: list[dict]) -> dict:
    """Mean failure bin and unknown sub-bin counts per mode across complete samples."""
    out = {"baseline": {}, "full": {}}
    for mode in ("baseline", "full"):
        bins_acc = Counter()
        sub_acc = Counter()
        n_samples = 0
        for r in rows:
            m = r.get(mode)
            if not m:
                continue
            n_samples += 1
            bins_acc.update(m["bins"])
            sub_acc.update(m["sub_unknown"])
        out[mode] = {
            "n_samples": n_samples,
            "bins_mean": {k: v / n_samples for k, v in bins_acc.items()} if n_samples else {},
            "sub_unknown_mean": {k: v / n_samples for k, v in sub_acc.items()} if n_samples else {},
        }
    return out


# ---------- rendering ----------

def render_text(report: dict, comparisons: list[dict] | None = None) -> str:
    lines: list[str] = []
    push = lines.append
    push(f"# Post-analysis: {report['family']}")
    push(f"  run_dir: {report['run_dir']}")
    push("")

    rows = report["samples"]
    push("## 1. Per-sample EX")
    push(f"  {'sample':10s}{'B EX':>10s}{'F EX':>10s}{'B EX (rel)':>14s}{'F EX (rel)':>14s}{'strict Δ':>11s}{'relaxed Δ':>12s}")
    for r in rows:
        b, f = r.get("baseline"), r.get("full")
        if b and f:
            sd = (f["strict_ex"] - b["strict_ex"]) / b["n"] * 100
            rd = (f["relaxed_ex"] - b["relaxed_ex"]) / b["n"] * 100
            push(f"  {r['sample']:10s}"
                 f"{b['strict_ex']:>5d}/{b['n']:<4d}"
                 f"{f['strict_ex']:>5d}/{f['n']:<4d}"
                 f"{b['relaxed_ex']:>9d}/{b['n']:<4d}"
                 f"{f['relaxed_ex']:>9d}/{f['n']:<4d}"
                 f"{sd:>+10.2f}pp"
                 f"{rd:>+11.2f}pp")
        else:
            stat = " | ".join(f"{m}: {r.get(f'{m}_status', 'missing')}"
                              for m in ("baseline", "full"))
            push(f"  {r['sample']:10s}  (incomplete — {stat})")

    push("")
    push("## 2. Aggregate Δ (paired t-test, df = n-1)")
    for label in ("strict", "relaxed"):
        s = report[label]["stats"]
        push(f"  {label:8s} N={s['n']}  mean={s['mean']:+.2f}pp  "
             f"sd={s['sd']:.2f}  SE={s['se']:.2f}  "
             f"t={s['t']:.2f}  95% CI=[{s['ci95_lo']:+.2f}, {s['ci95_hi']:+.2f}]")

    push("")
    push("## 3. Failure-bin mean (across complete samples)")
    fb = aggregate_failure_bins(rows)
    keys = ["pass", "catalog", "safety", "unknown", "dialect", "golden"]
    push(f"  {'mode':10s}{'n':>4s}" + "".join(f"{k:>10s}" for k in keys))
    for mode in ("baseline", "full"):
        b = fb[mode]
        push(f"  {mode:10s}{b['n_samples']:>4d}" +
             "".join(f"{b['bins_mean'].get(k, 0):>10.2f}" for k in keys))

    push("")
    push("## 4. Unknown sub-bin mean")
    sub_keys = ["empty", "col_count", "pred_error", "non_select", "dangerous", "limit_unstable", "other"]
    push(f"  {'mode':10s}" + "".join(f"{k:>11s}" for k in sub_keys))
    for mode in ("baseline", "full"):
        b = fb[mode]
        push(f"  {mode:10s}" +
             "".join(f"{b['sub_unknown_mean'].get(k, 0):>11.2f}" for k in sub_keys))

    # ---- 5. McNemar (pooled across samples) ----
    push("")
    push("## 5. McNemar paired exact-binomial test (pooled across complete samples)")
    mc = aggregate_mcnemar(rows)
    push(f"  b (baseline-pass / full-fail) = {mc['b']}")
    push(f"  c (baseline-fail / full-pass) = {mc['c']}")
    push(f"  discordant pairs              = {mc['n_discordant']}")
    push(f"  exact two-sided p-value       = {mc['p']:.6f}")
    push(f"  favoured mode                 = {mc['favor']}")

    # ---- 6. Subset analyses ----
    push("")
    push("## 6. Subset analyses (Δ on Robustness vs Spatial subsets)")
    subsets = [
        ("Robustness (40q)", lambda m: m["difficulty"] == "Robustness"),
        ("Spatial / non-robust (85q)", lambda m: m["difficulty"] != "Robustness"),
        ("Easy (24q)", lambda m: m["difficulty"] == "Easy"),
        ("Medium (36q)", lambda m: m["difficulty"] == "Medium"),
        ("Hard (25q)", lambda m: m["difficulty"] == "Hard"),
    ]
    push(f"  {'subset':30s}{'mean Δ':>10s}{'95% CI':>22s}{'McNemar p':>14s}{'b/c':>10s}")
    for label, fn in subsets:
        sub = subset_delta(rows, fn)
        s = sub["stats"]
        m = sub["mcnemar"]
        push(f"  {label:30s}"
             f"{s['mean']:>+9.2f}pp"
             f"  [{s['ci95_lo']:+.2f}, {s['ci95_hi']:+.2f}]"
             f"{m['p']:>13.4f}"
             f"  {m['b']}/{m['c']}")

    # ---- 7. Category breakdown (top 8 by total fail count) ----
    push("")
    push("## 7. Category breakdown — Δ pass count and pred error rate per category")
    # Aggregate per-category pass counts across all complete samples
    cat_acc = {}
    for r in rows:
        b, f = r.get("baseline"), r.get("full")
        if not (b and f):
            continue
        for q, meta in b["per_qid"].items():
            cat = meta["category"]
            slot = cat_acc.setdefault(cat, {"n_q": 0, "b_pass": 0, "f_pass": 0})
            slot["n_q"] += 1
            slot["b_pass"] += b["per_qid"][q]["ex"]
            slot["f_pass"] += f["per_qid"][q]["ex"]
    n_samples = sum(1 for r in rows if r.get("baseline") and r.get("full"))
    rows_sorted = sorted(cat_acc.items(),
                         key=lambda kv: -(kv[1]["n_q"] // max(n_samples, 1)))
    push(f"  {'category':32s}{'n/sample':>10s}{'B pass%':>10s}{'F pass%':>10s}{'Δ':>10s}")
    for cat, v in rows_sorted:
        nq = v["n_q"] // max(n_samples, 1)
        if nq == 0:
            continue
        bp = v["b_pass"] / v["n_q"] * 100
        fp = v["f_pass"] / v["n_q"] * 100
        push(f"  {cat[:32]:32s}{nq:>10d}{bp:>9.1f}%{fp:>9.1f}%{fp - bp:>+9.1f}pp")

    if comparisons:
        push("")
        push("## 8. Cross-family Δ comparison (strict)")
        push(f"  {'family':30s}{'baseline EX':>14s}{'full EX':>12s}{'Δ (mean)':>12s}{'95% CI':>22s}")
        # main row first
        s = report["strict"]["stats"]
        push(f"  {report['family']:30s}"
             f"{_mean_ex(rows, 'baseline'):>13.2f}%"
             f"{_mean_ex(rows, 'full'):>11.2f}%"
             f"{s['mean']:>+11.2f}pp"
             f"  [{s['ci95_lo']:+.2f}, {s['ci95_hi']:+.2f}]")
        for c in comparisons:
            cs = c["strict"]["stats"]
            push(f"  {c['family']:30s}"
                 f"{_mean_ex(c['samples'], 'baseline'):>13.2f}%"
                 f"{_mean_ex(c['samples'], 'full'):>11.2f}%"
                 f"{cs['mean']:>+11.2f}pp"
                 f"  [{cs['ci95_lo']:+.2f}, {cs['ci95_hi']:+.2f}]")

    return "\n".join(lines)


def _mean_ex(rows: list[dict], mode: str) -> float:
    vals = [r[mode]["strict_ex"] / r[mode]["n"] * 100 for r in rows
            if r.get(mode)]
    return sum(vals) / len(vals) if vals else 0.0


# ---------- main ----------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run-dir", required=True, type=Path,
                    help="run dir, e.g. data_agent/nl2sql_eval_results/v7_gemini35_minimod_n3_20260524")
    ap.add_argument("--family", required=True,
                    help="family subdir name, e.g. gemini-3.5-flash")
    ap.add_argument("--compare", nargs="*", default=[],
                    help="zero or more 'run_dir:family' pairs for cross-family table")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON instead of text")
    args = ap.parse_args()

    main_report = analyze_run(args.run_dir, args.family)
    comparisons = []
    for spec in args.compare:
        rd, fam = spec.split(":", 1)
        comparisons.append(analyze_run(Path(rd), fam))

    if args.json:
        payload = {"main": main_report, "comparisons": comparisons}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(main_report, comparisons))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
