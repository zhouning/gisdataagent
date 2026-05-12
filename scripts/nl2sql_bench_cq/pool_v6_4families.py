"""Pool 4-family Phase 3 results into a single v6 summary.

Inputs (per-family baseline/full × N=1 or N=3):
  Gemini:
    baseline N=1: cq_2026-05-08_090919/baseline_results.json (Spatial-85 subset)
    full N=3:     ablation_agentloop_2026-05-07_233516/Full_results.json
                  cq_2026-05-08_090919/full_results.json (Spatial-85 subset)
                  full_resample_2026-05-08_1040/Full_results.json
  DeepSeek:
    baseline N=3: cross_family_85q_phase1_2026-05-10_171030/deepseek_baseline_s{1,2,3}_results.json
    full N=3:     cross_family_85q_phase1_2026-05-10_171030/deepseek_full_s{1,2,3}_results.json
  Qwen:
    baseline N=3: cross_family_85q_phase3_qwen_2026-05-10_225710/qwen_baseline_s{1,2,3}_results.json
    full N=3:     cross_family_85q_phase3_qwen_2026-05-10_225710/qwen_full_s{1,2,3}_results.json
  Gemma:
    baseline N=3: cross_family_85q_phase3_gemma_ollama_2026-05-11_124343/gemma_ollama_baseline_s{1,2,3}_results.json
    full N=3:     cross_family_85q_phase3_gemma_ollama_2026-05-11_124343/gemma_ollama_full_s{1,2,3}_results.json (when available)

Output:
  data_agent/nl2sql_eval_results/v6_final_4family_summary.json
  Standard out: human-readable table for paper Section "Results".

Stats:
  - Per cell: mean EX + SD across N samples
  - Majority-vote (MV) EX per family: per-qid, ex=1 if >= ceil(N/2) of N samples ex=1
  - Paired McNemar per family (baseline MV vs full MV)
  - Cross-family baseline parity: all-pairs McNemar between family-baseline MVs

Pass-through: cells with no full data (e.g. Gemma still running) are recorded
with `incomplete: true` so the script can be re-run incrementally.
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2] / "data_agent" / "nl2sql_eval_results"

# Family source manifest
SOURCES = {
    "gemini": {
        "baseline": [ROOT / "cq_2026-05-08_090919" / "baseline_results.json"],
        "full": [
            ROOT / "ablation_agentloop_2026-05-07_233516" / "Full_results.json",
            ROOT / "cq_2026-05-08_090919" / "full_results.json",
            ROOT / "full_resample_2026-05-08_1040" / "Full_results.json",
        ],
    },
    "deepseek": {
        "baseline": [
            ROOT / "cross_family_85q_phase1_2026-05-10_171030"
            / f"deepseek_baseline_s{i}_results.json" for i in (1, 2, 3)
        ],
        "full": [
            ROOT / "cross_family_85q_phase1_2026-05-10_171030"
            / f"deepseek_full_s{i}_results.json" for i in (1, 2, 3)
        ],
    },
    "qwen": {
        "baseline": [
            ROOT / "cross_family_85q_phase3_qwen_2026-05-10_225710"
            / f"qwen_baseline_s{i}_results.json" for i in (1, 2, 3)
        ],
        "full": [
            ROOT / "cross_family_85q_phase3_qwen_2026-05-10_225710"
            / f"qwen_full_s{i}_results.json" for i in (1, 2, 3)
        ],
    },
    "gemma": {
        "baseline": [
            ROOT / "cross_family_85q_phase3_gemma_ollama_2026-05-11_124343"
            / f"gemma_ollama_baseline_s{i}_results.json" for i in (1, 2, 3)
        ],
        "full": [
            ROOT / "cross_family_85q_phase3_gemma_ollama_2026-05-11_124343"
            / f"gemma_ollama_full_s{i}_results.json" for i in (1, 2, 3)
        ],
    },
}


def _load_records(path: Path) -> list[dict] | None:
    if not path.exists():
        return None
    j = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(j, dict) and "records" in j:
        rs = j["records"]
    elif isinstance(j, list):
        rs = j
    else:
        rs = []
    # Always project to Spatial 85q subset
    return [r for r in rs
            if str(r.get("difficulty", "")).lower() in ("easy", "medium", "hard")]


def _per_qid_ex(records: list[dict]) -> dict[str, int]:
    """Map qid -> ex (0 or 1)."""
    out = {}
    for r in records:
        qid = r.get("qid") or r.get("id")
        if qid is None: continue
        out[qid] = 1 if r.get("ex") else 0
    return out


def _majority_vote(samples_qids: list[dict[str, int]]) -> dict[str, int]:
    """Per-qid, ex=1 if >= ceil(N/2) of N samples have ex=1."""
    if not samples_qids:
        return {}
    all_qids = set()
    for s in samples_qids:
        all_qids |= set(s.keys())
    n = len(samples_qids)
    threshold = math.ceil(n / 2)
    mv = {}
    for q in all_qids:
        votes = sum(1 for s in samples_qids if s.get(q, 0) == 1)
        mv[q] = 1 if votes >= threshold else 0
    return mv


def _ex_rate(qid_map: dict[str, int]) -> float:
    if not qid_map: return float("nan")
    return sum(qid_map.values()) / len(qid_map)


def _paired_mcnemar(base: dict[str, int], full: dict[str, int]) -> dict:
    """Paired McNemar b/c counts + two-sided exact binomial p-value."""
    qids = sorted(set(base.keys()) & set(full.keys()))
    b = sum(1 for q in qids if base[q] == 1 and full[q] == 0)
    c = sum(1 for q in qids if base[q] == 0 and full[q] == 1)
    delta = (sum(full[q] for q in qids) - sum(base[q] for q in qids)) / len(qids) if qids else 0
    # Exact binomial p-value (two-sided)
    try:
        from scipy.stats import binomtest
        if b + c == 0:
            p = 1.0
        else:
            res = binomtest(min(b, c), n=b + c, p=0.5, alternative="two-sided")
            p = res.pvalue
    except ImportError:
        p = None
    return {"n_pairs": len(qids), "b": b, "c": c,
            "delta_ex": round(delta, 4), "p_value": round(p, 4) if p else None}


def main() -> int:
    summary = {"families": {}, "cross_family_baseline_parity": {}}

    # 1. Per-family pooling
    family_mv = {}
    for fam, srcs in SOURCES.items():
        block = {}
        for mode in ("baseline", "full"):
            samples = []
            for p in srcs[mode]:
                recs = _load_records(Path(p))
                if recs is None or not recs:
                    continue
                samples.append({"path": str(p),
                                "n": len(recs),
                                "ex": _ex_rate(_per_qid_ex(recs)),
                                "qids": _per_qid_ex(recs)})
            if not samples:
                block[mode] = {"incomplete": True, "n_samples_loaded": 0}
                continue
            per_sample_ex = [s["ex"] for s in samples]
            mv = _majority_vote([s["qids"] for s in samples])
            block[mode] = {
                "n_samples": len(samples),
                "per_sample_ex": [round(e, 4) for e in per_sample_ex],
                "mean_ex": round(statistics.mean(per_sample_ex), 4),
                "sd_ex": round(statistics.stdev(per_sample_ex), 4) if len(per_sample_ex) > 1 else None,
                "majority_vote_ex": round(_ex_rate(mv), 4),
                "n_qids_mv": len(mv),
                "sources": [str(p) for p in srcs[mode] if Path(p).exists()],
            }
            family_mv.setdefault(fam, {})[mode] = mv
        # Paired McNemar baseline-vs-full
        if "baseline" in family_mv.get(fam, {}) and "full" in family_mv.get(fam, {}):
            block["mcnemar_baseline_vs_full"] = _paired_mcnemar(
                family_mv[fam]["baseline"], family_mv[fam]["full"]
            )
        summary["families"][fam] = block

    # 2. Cross-family baseline parity
    fams_with_baseline = [f for f, m in family_mv.items() if "baseline" in m]
    parity = {}
    for i, fa in enumerate(fams_with_baseline):
        for fb in fams_with_baseline[i + 1:]:
            key = f"{fa}_vs_{fb}"
            parity[key] = _paired_mcnemar(family_mv[fa]["baseline"], family_mv[fb]["baseline"])
    summary["cross_family_baseline_parity"] = parity

    # 3. Write JSON
    out = ROOT / "v6_final_4family_summary.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"[pool] wrote {out}")
    print()

    # 4. Human-readable
    print("=" * 78)
    print("v6 cross-family within-family Δ on 85q GIS Spatial")
    print("=" * 78)
    print(f'{"family":<10} {"base mean (sd, N)":<22} {"full mean (sd, N)":<22} '
          f'{"Δ_mv":>6} {"b":>3} {"c":>3} {"p":>7}')
    print("-" * 78)
    for fam, block in summary["families"].items():
        b = block.get("baseline", {})
        f = block.get("full", {})
        if b.get("incomplete") or f.get("incomplete"):
            note = " (incomplete)" if f.get("incomplete") else ""
            base_str = f'{b.get("mean_ex","?")}'
            full_str = f'{f.get("mean_ex","INCOMPLETE")}{note}'
            print(f"{fam:<10} {base_str:<22} {full_str:<22}")
            continue
        mc = block.get("mcnemar_baseline_vs_full", {})
        base_str = f'{b.get("mean_ex","?")} (sd={b.get("sd_ex","?")}, N={b.get("n_samples","?")})'
        full_str = f'{f.get("mean_ex","?")} (sd={f.get("sd_ex","?")}, N={f.get("n_samples","?")})'
        print(f'{fam:<10} {base_str:<22} {full_str:<22} '
              f'{mc.get("delta_ex","?"):>6} {mc.get("b","?"):>3} '
              f'{mc.get("c","?"):>3} {str(mc.get("p_value","?")):>7}')
    print()
    print("=" * 78)
    print("Cross-family baseline parity (paired McNemar on baseline MV)")
    print("=" * 78)
    print(f'{"pair":<30} {"n":>4} {"b":>3} {"c":>3} {"Δ":>7} {"p":>7}')
    print("-" * 78)
    for key, mc in summary["cross_family_baseline_parity"].items():
        print(f'{key:<30} {mc["n_pairs"]:>4} {mc["b"]:>3} {mc["c"]:>3} '
              f'{mc["delta_ex"]:>7} {str(mc["p_value"]):>7}')
    print()
    print(f'[pool] summary written to: {out}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
