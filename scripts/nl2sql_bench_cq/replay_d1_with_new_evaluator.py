"""Replay evaluator on v7 P1 universal-fail qids using new compare_results.

Reads existing pred_sql from records_full.jsonl, re-executes gold + pred,
applies the new evaluator (with limit-unstable fallback), and reports
rescue rate per qid.

Doesn't write back to records — pure dry-run for impact estimation.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import sys
sys.path.insert(0, ".")

from scripts.nl2sql_bench_cq.run_cq_eval import compare_results, execute_pg


D1_QIDS = [
    "CQ_GEO_EASY_02", "CQ_GEO_EASY_10", "CQ_GEO_EASY_20", "CQ_GEO_EASY_24",
    "CQ_GEO_MEDIUM_05", "CQ_GEO_MEDIUM_08", "CQ_GEO_MEDIUM_10", "CQ_GEO_MEDIUM_20",
    "CQ_GEO_MEDIUM_26",
    "CQ_GEO_HARD_10", "CQ_GEO_HARD_12", "CQ_GEO_HARD_15", "CQ_GEO_HARD_22",
    "CQ_GEO_HARD_23",
]


def _iter_records(main_dir: Path, gemma_dir: Path):
    for fam_dir in sorted(p for p in main_dir.iterdir() if p.is_dir()):
        for sd in sorted(p for p in fam_dir.iterdir() if p.is_dir() and p.name.startswith("sample_")):
            fp = sd / "records_full.jsonl"
            if not fp.exists():
                continue
            for line in fp.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    r["_family"] = fam_dir.name
                    r["_sample"] = sd.name
                    yield r
    if gemma_dir and gemma_dir.exists():
        for fam_dir in sorted(p for p in gemma_dir.iterdir() if p.is_dir()):
            fp = fam_dir / "records_full.jsonl"
            if not fp.exists():
                continue
            for line in fp.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    r["_family"] = fam_dir.name
                    r["_sample"] = "sample_1"
                    yield r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--main-dir", required=True, type=Path)
    ap.add_argument("--gemma-dir", required=True, type=Path)
    ap.add_argument("--bench-json", required=False, type=Path, default=None,
                    help="If set, override gold_sql per qid by reading current benchmark JSON")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    overridden_gold: dict[str, str] = {}
    if args.bench_json:
        bench = json.loads(args.bench_json.read_text(encoding="utf-8"))
        for q in bench:
            if q.get("id") and q.get("golden_sql"):
                overridden_gold[q["id"]] = q["golden_sql"]
        print(f"loaded {len(overridden_gold)} gold_sql overrides from {args.bench_json}")

    targets = []
    for r in _iter_records(args.main_dir, args.gemma_dir):
        if r["qid"] in D1_QIDS and r.get("pred_sql"):
            if r["qid"] in overridden_gold:
                r["gold_sql"] = overridden_gold[r["qid"]]
            targets.append(r)
    print(f"loaded {len(targets)} D1 candidate records")

    by_qid_old: dict[str, Counter] = defaultdict(Counter)
    by_qid_new: dict[str, Counter] = defaultdict(Counter)
    rescued: list[dict] = []
    new_failed: list[dict] = []
    cache: dict[str, dict] = {}

    for i, r in enumerate(targets, 1):
        qid = r["qid"]
        gold_sql = r["gold_sql"]
        pred_sql = r["pred_sql"]
        old_ex = r.get("ex", 0)
        old_reason = r.get("reason", "")
        by_qid_old[qid]["pass" if old_ex else "fail"] += 1

        if gold_sql not in cache:
            cache[gold_sql] = execute_pg(gold_sql)
        gold_res = cache[gold_sql]
        pred_res = execute_pg(pred_sql)
        is_valid = pred_res["status"] == "ok"
        if is_valid:
            passed, reason = compare_results(gold_res, pred_res, gold_sql=gold_sql)
        else:
            passed, reason = False, pred_res.get("error", "")[:80]
        new_ex = 1 if passed else 0
        by_qid_new[qid]["pass" if new_ex else "fail"] += 1

        if i % 30 == 0:
            print(f"  {i}/{len(targets)} processed")

        if old_ex == 0 and new_ex == 1:
            rescued.append({"qid": qid, "family": r["_family"], "sample": r["_sample"],
                            "old_reason": old_reason, "new_reason": reason})
        elif old_ex == 1 and new_ex == 0:
            new_failed.append({"qid": qid, "family": r["_family"], "sample": r["_sample"],
                               "old_reason": old_reason, "new_reason": reason})

    lines: list[str] = []
    lines.append("# D1 Replay — Evaluator with limit-unstable fallback")
    lines.append("")
    lines.append(f"Records replayed: **{len(targets)}**")
    lines.append(f"Rescued (old=fail, new=pass): **{len(rescued)}**")
    lines.append(f"Newly failed (old=pass, new=fail): **{len(new_failed)}**")
    lines.append(f"Net rescue: **{len(rescued) - len(new_failed)}**")
    lines.append("")
    lines.append("## Per-qid pass count (old → new)")
    lines.append("")
    lines.append("| qid | old pass | new pass | total | Δ |")
    lines.append("|---|---|---|---|---|")
    for qid in D1_QIDS:
        old_p = by_qid_old[qid]["pass"]
        new_p = by_qid_new[qid]["pass"]
        total = sum(by_qid_old[qid].values())
        lines.append(f"| `{qid}` | {old_p} | {new_p} | {total} | {new_p - old_p:+d} |")
    lines.append("")

    if rescued:
        lines.append("## Sample rescues (first 30)")
        lines.append("")
        lines.append("| qid | family | sample | old_reason | new_reason |")
        lines.append("|---|---|---|---|---|")
        for r in rescued[:30]:
            lines.append(f"| `{r['qid']}` | {r['family']} | {r['sample']} | `{r['old_reason'][:50]}` | `{r['new_reason'][:80]}` |")
        lines.append("")

    if new_failed:
        lines.append("## ⚠️ Newly failed (regressions to investigate)")
        lines.append("")
        lines.append("| qid | family | sample | old_reason | new_reason |")
        lines.append("|---|---|---|---|---|")
        for r in new_failed:
            lines.append(f"| `{r['qid']}` | {r['family']} | {r['sample']} | `{r['old_reason'][:50]}` | `{r['new_reason'][:80]}` |")

    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwrote {args.out}")
    print(f"rescued={len(rescued)} newly_failed={len(new_failed)} net={len(rescued) - len(new_failed)}")


if __name__ == "__main__":
    main()
