"""Pool 3 Full-mode samples on GIS Spatial 85q and emit paper-ready stats.

Inputs:
  - ablation_agentloop_2026-05-07_233516/Full_results.json        (sample 1)
  - cq_2026-05-08_090919/full_results.json                        (sample 2, full 125q run — spatial subset)
  - full_resample_2026-05-08_1040/Full_results.json               (sample 3, this script's prerequisite)
  - cq_2026-05-08_090919/baseline_results.json                    (paired baseline, 125q)

Emits:
  - Per-sample EX on Spatial 85q + Robustness 40q
  - Pooled Spatial 85q EX, mean, std, per-question majority-vote EX
  - Paired McNemar: (baseline_85q) vs (majority-vote Full_85q)
  - Same for Robustness 40q (baseline vs full)
  - Per-configuration Ablation EX vs pooled Full
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from scipy.stats import binomtest

ROOT = Path("D:/adk/data_agent/nl2sql_eval_results")
SAMPLE_FILES = [
    ROOT / "ablation_agentloop_2026-05-07_233516/Full_results.json",
    ROOT / "cq_2026-05-08_090919/full_results.json",
    ROOT / "full_resample_2026-05-08_1040/Full_results.json",
]
BASELINE_FILE = ROOT / "cq_2026-05-08_090919/baseline_results.json"


def load_ex_map(path: Path, spatial_only: bool = False) -> dict[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, int] = {}
    for r in data["records"]:
        if spatial_only and r.get("difficulty") == "Robustness":
            continue
        out[r["qid"]] = r.get("ex", 0)
    return out


def mcnemar(a: dict[str, int], b: dict[str, int], qids: list[str]) -> tuple[int, int, float]:
    b_cnt = c_cnt = 0
    for q in qids:
        fa, fb = a.get(q, 0), b.get(q, 0)
        if fa == 1 and fb == 0:
            b_cnt += 1
        elif fa == 0 and fb == 1:
            c_cnt += 1
    n = b_cnt + c_cnt
    p = binomtest(min(b_cnt, c_cnt), n, p=0.5, alternative="two-sided").pvalue if n else 1.0
    return b_cnt, c_cnt, p


def main() -> None:
    print(f"{'Sample':50s} {'n':>3s} {'ex':>3s} {'ex_rate':>7s}")
    print("-" * 68)
    samples = []
    for path in SAMPLE_FILES:
        if not path.exists():
            print(f"  MISSING: {path}")
            return
        ex_map = load_ex_map(path, spatial_only=True)
        ex = sum(ex_map.values())
        print(f"  {path.parent.name + '/' + path.name:50s} {len(ex_map):>3d} {ex:>3d} {ex/len(ex_map):>7.4f}")
        samples.append(ex_map)

    # Union of qids (should be the same 85 in each sample)
    all_qids = sorted(set().union(*samples))
    if len(all_qids) != 85:
        print(f"WARN: expected 85 qids, got {len(all_qids)}")

    # Per-question majority vote
    majority: dict[str, int] = {}
    for q in all_qids:
        votes = [s.get(q, 0) for s in samples]
        majority[q] = 1 if sum(votes) >= 2 else 0

    # Sample mean / std of ex_rate
    rates = [sum(s.values()) / len(all_qids) for s in samples]
    print()
    print(f"Sample rates: {[round(r,4) for r in rates]}")
    print(f"  mean = {statistics.mean(rates):.4f}")
    print(f"  stdev = {statistics.stdev(rates):.4f}")
    print(f"  range = [{min(rates):.4f}, {max(rates):.4f}]")
    print(f"  majority-vote EX = {sum(majority.values())}/{len(all_qids)} = "
          f"{sum(majority.values())/len(all_qids):.4f}")

    # Paired McNemar: baseline vs each sample (Spatial 85q)
    baseline = load_ex_map(BASELINE_FILE, spatial_only=True)
    print()
    print("Paired McNemar: baseline vs each Full sample (Spatial 85q)")
    print(f"  baseline EX = {sum(baseline.values())}/85 = {sum(baseline.values())/85:.4f}")
    for i, s in enumerate(samples, 1):
        b, c, p = mcnemar(baseline, s, all_qids)
        print(f"  Sample {i}: b={b:>2d} c={c:>2d} p={p:.4f}")
    # baseline vs majority-vote
    b, c, p = mcnemar(baseline, majority, all_qids)
    print(f"  Majority-vote Full: b={b:>2d} c={c:>2d} p={p:.4f}")

    # Robustness 40q paired (single sample from cq_2026-05-08_090919)
    print()
    print("Robustness 40q paired (from cq_2026-05-08_090919):")
    b_rob = load_ex_map(BASELINE_FILE, spatial_only=False)
    f_rob = load_ex_map(ROOT / "cq_2026-05-08_090919/full_results.json", spatial_only=False)
    rob_qids = [q for q in b_rob if q not in all_qids]
    b, c, p = mcnemar(b_rob, f_rob, rob_qids)
    bex = sum(b_rob[q] for q in rob_qids)
    fex = sum(f_rob[q] for q in rob_qids)
    print(f"  Robustness 40q: baseline={bex}/40={bex/40:.4f} full={fex}/40={fex/40:.4f} "
          f"b={b} c={c} p={p:.4f}")


if __name__ == "__main__":
    main()
