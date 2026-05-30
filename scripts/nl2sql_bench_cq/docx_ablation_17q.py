"""Minimal ablation: docx_off vs docx_on on 17 natural_res questions.

Hypothesis: injecting the DLTB 国标字段字典 (Chinese name ↔ field code mapping)
into the prompt helps the LLM map clean-benchmark question terms like
"地类名称" / "图斑面积" / "图斑标识码" to physical PG columns `dlmc` / `tbmj` / `bsm`.

Setup:
  - benchmark:  benchmarks/chongqing_geo_nl2sql_125q_clean.json (paren-stripped)
  - filter:     golden_sql primary table ∈ {cq_dltb, cq_land_use_dltb}  → 17 q
  - model:      gemini-2.5-flash (NL2SQL_AGENT_MODEL default)
  - prompt:     run_cq_eval.BASELINE_PROMPT + SCHEMA + [docx hint?] + question
  - eval:       run_cq_eval.execute_pg + compare_results (same as v6)
  - N=1 (signal check, not significance — significance run is next phase)

Output: data_agent/nl2sql_eval_results/docx_ablation_<ts>/
  - results.json  (per-question detailed)
  - summary.md    (human-readable)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "nl2sql_bench_cq"))

# Reuse run_cq_eval primitives
import run_cq_eval as rce
from data_agent.standards.docx_standard_provider import get_field_dict_for_tables

BENCH = ROOT / "benchmarks" / "chongqing_geo_nl2sql_125q_clean_v3.json"
OUT_ROOT = ROOT / "data_agent" / "nl2sql_eval_results"


def load_clean_natural_res_questions() -> list[dict]:
    rows = json.loads(BENCH.read_text(encoding="utf-8"))
    picked = []
    for r in rows:
        sql = (r.get("golden_sql") or "").lower()
        tables = re.findall(r"\bcq_[a-z0-9_]+", sql)
        if not tables:
            continue
        primary = tables[0]
        if primary in ("cq_dltb", "cq_land_use_dltb"):
            picked.append(r)
    return picked


def build_prompt(question: str, schema: str, with_docx: bool) -> str:
    p = rce.BASELINE_PROMPT
    p += f"\n\nSCHEMA:\n{schema}\n"
    if with_docx:
        hint = get_field_dict_for_tables(["DLTB"])
        if hint:
            p += "\n" + hint + "\n"
    p += f"\nQUESTION: {question}\n\nSQL:"
    return p


def call_llm(prompt: str, model: str = "gemini-2.5-flash") -> str:
    """Single LLM call returning SQL string."""
    rce._init_runtime()
    from google.genai import types  # imported via _init_runtime
    resp = rce._client.models.generate_content(
        model=model,
        contents=[prompt],
        config=types.GenerateContentConfig(
            http_options=types.HttpOptions(timeout=60_000),
            temperature=0.0,
        ),
    )
    text_out = (resp.text or "").strip()
    return rce._strip_fences(text_out)


def eval_one(q: dict, schema: str, with_docx: bool) -> dict:
    prompt = build_prompt(q["question"], schema, with_docx)
    t0 = time.time()
    try:
        sql = call_llm(prompt)
    except Exception as e:
        return {"id": q["id"], "ok": False, "error": f"llm_fail: {e}",
                "sql": None, "elapsed": time.time() - t0}
    pred = rce.execute_pg(sql)
    gold = rce.execute_pg(q["golden_sql"])
    ok, reason = rce.compare_results(gold, pred)
    return {
        "id": q["id"],
        "ok": bool(ok),
        "reason": reason,
        "sql": sql,
        "pred_status": pred.get("status"),
        "pred_error": (pred.get("error") or "")[:200],
        "elapsed": round(time.time() - t0, 2),
    }


def main():
    qs = load_clean_natural_res_questions()
    print(f"[ablation] picked {len(qs)} natural_res questions from clean benchmark")
    print(f"[ablation] model = gemini-2.5-flash, N=1, modes = [off, on]")

    rce._init_runtime()
    schema = rce.get_schema()

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = OUT_ROOT / f"docx_ablation_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {"off": [], "on": []}

    for q in qs:
        print(f"\n--- {q['id']} ---")
        print(f"  Q: {q['question'][:100]}")
        r_off = eval_one(q, schema, with_docx=False)
        print(f"  off: ok={r_off['ok']:1}  reason={r_off['reason'][:60]}")
        r_on = eval_one(q, schema, with_docx=True)
        print(f"  on:  ok={r_on['ok']:1}  reason={r_on['reason'][:60]}")
        r_off["question"] = q["question"]
        r_off["golden_sql"] = q["golden_sql"]
        r_on["question"] = q["question"]
        r_on["golden_sql"] = q["golden_sql"]
        results["off"].append(r_off)
        results["on"].append(r_on)

    # Save raw
    (out_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Summary
    n = len(qs)
    n_off = sum(1 for r in results["off"] if r["ok"])
    n_on  = sum(1 for r in results["on"]  if r["ok"])
    pairs = list(zip(results["off"], results["on"]))
    gained = [(o, n_) for o, n_ in pairs if not o["ok"] and n_["ok"]]
    lost   = [(o, n_) for o, n_ in pairs if o["ok"] and not n_["ok"]]
    both_ok = [(o, n_) for o, n_ in pairs if o["ok"] and n_["ok"]]
    both_bad = [(o, n_) for o, n_ in pairs if not o["ok"] and not n_["ok"]]

    md = []
    md.append(f"# Docx-injection ablation — natural_res 17q (v7 clean benchmark)\n")
    md.append(f"Generated: {ts}  Model: gemini-2.5-flash  N=1\n")
    md.append(f"## Headline")
    md.append(f"- off (no docx hint):  **{n_off}/{n} = {100*n_off/n:.1f}%**")
    md.append(f"- on  (+DLTB dict):    **{n_on}/{n} = {100*n_on/n:.1f}%**")
    md.append(f"- delta: **{n_on - n_off:+d}**  (gained {len(gained)}, lost {len(lost)})\n")

    md.append(f"## Per-question table\n")
    md.append("| id | off | on | direction | off-reason | on-reason |")
    md.append("|---|---|---|---|---|---|")
    for o, n_ in pairs:
        d = "→" if o["ok"] == n_["ok"] else ("📈" if not o["ok"] and n_["ok"] else "📉")
        md.append(f"| {o['id']} | {'✓' if o['ok'] else '✗'} | {'✓' if n_['ok'] else '✗'} | {d} | {o['reason'][:50]} | {n_['reason'][:50]} |")

    if gained:
        md.append(f"\n## ✅ Gained ({len(gained)} questions)\n")
        for o, n_ in gained:
            md.append(f"### {o['id']}")
            md.append(f"**Q:** {o['question']}")
            md.append(f"**Off SQL:**\n```sql\n{(o['sql'] or '')[:600]}\n```")
            md.append(f"**Off reason:** {o['reason']}")
            md.append(f"**On SQL:**\n```sql\n{(n_['sql'] or '')[:600]}\n```\n")

    if lost:
        md.append(f"\n## ❌ Lost ({len(lost)} questions)\n")
        for o, n_ in lost:
            md.append(f"### {o['id']}")
            md.append(f"**Q:** {o['question']}")
            md.append(f"**Off SQL:**\n```sql\n{(o['sql'] or '')[:600]}\n```")
            md.append(f"**On SQL:**\n```sql\n{(n_['sql'] or '')[:600]}\n```")
            md.append(f"**On reason:** {n_['reason']}\n")

    md.append(f"\n## Other stats\n")
    md.append(f"- both ✓: {len(both_ok)}, both ✗: {len(both_bad)}")
    md.append(f"- avg latency  off: {sum(r['elapsed'] for r in results['off'])/n:.2f}s,  on: {sum(r['elapsed'] for r in results['on'])/n:.2f}s")

    (out_dir / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\nOutput: {out_dir}")
    print(f"  off: {n_off}/{n} = {100*n_off/n:.1f}%")
    print(f"  on : {n_on}/{n} = {100*n_on/n:.1f}%")
    print(f"  Δ = {n_on - n_off:+d} (gained {len(gained)}, lost {len(lost)})")


if __name__ == "__main__":
    main()
