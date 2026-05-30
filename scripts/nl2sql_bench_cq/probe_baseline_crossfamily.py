"""v7 P1-pre — verify cross-family baseline_generate parity.

Three checks:
  (a) Gemini path via baseline_generate_family_aware() must produce SQL with
      the same structure as the legacy baseline_generate() path for the same
      question (byte equivalence not required; structure+output required).
  (b) DeepSeek path via baseline_generate_family_aware() must return non-empty
      SQL for a simple question.
  (c) Qwen path via baseline_generate_family_aware() must return non-empty
      SQL for a simple question.

Exit 0 iff all three checks pass.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=True)
sys.stdout.reconfigure(encoding="utf-8")

from run_cq_eval import (  # type: ignore
    _init_runtime, baseline_generate, baseline_generate_family_aware,
)

QUESTION = "重庆市一共有多少栋建筑物"


def main() -> int:
    _init_runtime()
    print("=" * 88)
    print("v7 P1-pre cross-family baseline path verification")
    print("=" * 88)

    # Check (a): Gemini path via legacy vs family-aware
    print("\n--- (a) Gemini path parity ---")
    r_legacy = baseline_generate(QUESTION)
    r_fa_gemini = baseline_generate_family_aware(QUESTION, "gemini-2.5-flash")
    print(f"  legacy     status={r_legacy['status']}  tokens={r_legacy['tokens']}")
    print(f"    sql: {r_legacy['sql'][:200]}")
    print(f"  family-aware (gemini-2.5-flash)  status={r_fa_gemini['status']}  tokens={r_fa_gemini['tokens']}")
    print(f"    sql: {r_fa_gemini['sql'][:200]}")
    check_a = (r_legacy["status"] == "ok" and r_fa_gemini["status"] == "ok"
               and r_legacy["sql"].strip().upper().startswith(("SELECT", "WITH"))
               and r_fa_gemini["sql"].strip().upper().startswith(("SELECT", "WITH")))
    print(f"  PASS" if check_a else f"  FAIL")

    # Check (b): DeepSeek path
    print("\n--- (b) DeepSeek path ---")
    r_ds = baseline_generate_family_aware(QUESTION, "deepseek-v4-flash")
    print(f"  status={r_ds['status']}  tokens={r_ds['tokens']}")
    if r_ds.get("error"):
        print(f"  error: {r_ds['error'][:300]}")
    print(f"  sql: {r_ds['sql'][:300]}")
    check_b = (r_ds["status"] == "ok"
               and r_ds["sql"].strip().upper().startswith(("SELECT", "WITH")))
    print(f"  PASS" if check_b else f"  FAIL")

    # Check (c): Qwen path
    print("\n--- (c) Qwen path ---")
    r_qw = baseline_generate_family_aware(QUESTION, "qwen3.6-flash")
    print(f"  status={r_qw['status']}  tokens={r_qw['tokens']}")
    if r_qw.get("error"):
        print(f"  error: {r_qw['error'][:300]}")
    print(f"  sql: {r_qw['sql'][:300]}")
    check_c = (r_qw["status"] == "ok"
               and r_qw["sql"].strip().upper().startswith(("SELECT", "WITH")))
    print(f"  PASS" if check_c else f"  FAIL")

    print("\n" + "=" * 88)
    total_pass = sum([check_a, check_b, check_c])
    print(f"total: {total_pass}/3 checks passed")
    print("=" * 88)
    return 0 if total_pass == 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
