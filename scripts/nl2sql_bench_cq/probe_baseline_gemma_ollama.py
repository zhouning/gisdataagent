"""Quick probe — verify baseline path works for gemma-4-31b-it-ollama."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=True)
sys.stdout.reconfigure(encoding="utf-8")

from run_cq_eval import _init_runtime, baseline_generate_family_aware  # type: ignore

QUESTION = "重庆市一共有多少栋建筑物"

if __name__ == "__main__":
    _init_runtime()
    r = baseline_generate_family_aware(QUESTION, "gemma-4-31b-it-ollama")
    print(f"status={r['status']}  tokens={r['tokens']}")
    if r.get("error"):
        print(f"error: {r['error'][:500]}")
    print(f"sql: {r['sql'][:500]}")
    ok = r["status"] == "ok" and r["sql"].strip().upper().startswith(("SELECT", "WITH"))
    print("PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)
