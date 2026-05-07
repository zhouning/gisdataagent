"""Compute paired McNemar per ablation config vs Full on the 85q.

Usage:
    .venv\\Scripts\\python.exe scripts/nl2sql_bench_cq/ablation_stats.py \\
        <path-to-ablation_agentloop_YYYY-MM-DD_HHMMSS-dir>

For each noXxx config, b = Full-OK & noXxx-ERR, c = Full-ERR & noXxx-OK.
p-value via two-sided exact binomial on min(b, c).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from scipy.stats import binomtest


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit("Usage: ablation_stats.py <ablation_dir>")
    d = Path(argv[1])
    full_path = d / "Full_results.json"
    if not full_path.exists():
        raise SystemExit(f"Missing {full_path}")
    full = json.loads(full_path.read_text(encoding="utf-8"))
    full_by_qid = {r["qid"]: r.get("ex", 0) for r in full["records"]}
    full_n = len(full["records"])
    full_ex = sum(full_by_qid.values())
    print(f"Full baseline: EX = {full_ex}/{full_n} = {full_ex/full_n:.4f}")
    print()
    print(f"{'Config':25s} {'EX':>8s} {'n':>3s} {'b':>3s} {'c':>3s} {'p':>8s}")
    print("-" * 56)
    for cfg_file in sorted(d.glob("no*_results.json")):
        abl = json.loads(cfg_file.read_text(encoding="utf-8"))
        b = c = 0
        cfg_ex = 0
        for r in abl["records"]:
            f = full_by_qid.get(r["qid"], 0)
            a = r.get("ex", 0)
            cfg_ex += a
            if f == 1 and a == 0:
                b += 1
            elif f == 0 and a == 1:
                c += 1
        n = b + c
        if n == 0:
            p = 1.0
        else:
            p = binomtest(min(b, c), n, p=0.5, alternative="two-sided").pvalue
        name = cfg_file.stem.replace("_results", "")
        print(f"{name:25s} {cfg_ex/len(abl['records']):>8.4f} "
              f"{n:>3d} {b:>3d} {c:>3d} {p:>8.4f}")


if __name__ == "__main__":
    main(sys.argv)
