"""Retrofill hint_injection_stats onto existing Smoke-B / P1 records.

For runs that ran BEFORE the hint_injection_stats field was added to the
per-record schema (Smoke-B on 2026-05-13 partial), this script reads every
records_{mode}.jsonl under an output dir and enriches each record with the
stats via a fresh call to build_nl2sql_context — write-back in place.

Why this works: _hint_injection_stats is derived from (question, family),
and family is known from the parent directory name + the per-family family
constant in run_v7_smoke_b.FAMILIES. No LLM / DB writes.

Usage:
  $env:PYTHONPATH = "D:\\adk"
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_cq/retrofill_hint_stats.py \\
      --run-dir data_agent/nl2sql_eval_results/v7_smoke_b_2026-05-13_145807
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=True)
sys.stdout.reconfigure(encoding="utf-8")

from run_v7_smoke_b import FAMILIES  # (model_name, family) pairs


def _family_for(model_dir_name: str) -> str | None:
    """Map a directory name back to its family constant."""
    for m, f in FAMILIES:
        if m.replace("/", "_") == model_dir_name:
            return f
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, type=Path,
                    help="Root of a v7_smoke_b_<ts>/ directory")
    args = ap.parse_args()

    from data_agent.nl2sql_grounding import build_nl2sql_context

    stats_cache: dict[tuple[str, str], dict | None] = {}
    enriched = 0
    skipped = 0

    for fam_dir in sorted(args.run_dir.iterdir()):
        if not fam_dir.is_dir():
            continue
        family = _family_for(fam_dir.name)
        if family is None:
            print(f"[skip] {fam_dir.name}: unknown family", flush=True)
            skipped += 1
            continue
        for jsonl_path in fam_dir.glob("records_*.jsonl"):
            lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            out_lines: list[str] = []
            for line in lines:
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("hint_injection_stats") is not None:
                    out_lines.append(line)
                    continue
                q = r.get("question", "")
                key = (q, family)
                if key not in stats_cache:
                    try:
                        ctx = build_nl2sql_context(q, family=family)
                        stats_cache[key] = ctx.get("_hint_injection_stats")
                    except Exception as e:
                        print(f"[warn] {fam_dir.name}/{jsonl_path.name} "
                              f"qid={r.get('qid')}: {e}", flush=True)
                        stats_cache[key] = None
                r["hint_injection_stats"] = stats_cache[key]
                out_lines.append(json.dumps(r, ensure_ascii=False))
                enriched += 1
            jsonl_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        print(f"[done] {fam_dir.name}  family={family}", flush=True)

    print(f"\n[summary] enriched={enriched}  skipped_dirs={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
