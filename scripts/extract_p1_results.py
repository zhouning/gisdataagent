"""Extract BIRD P2 results from resume cache."""
import json, sqlite3, sys
from pathlib import Path
from collections import Counter

RUN_DIR = Path("data_agent/nl2sql_eval_results/bird_pg_2026-05-04_093040")
DB = RUN_DIR / "run_state.db"

conn = sqlite3.connect(str(DB))

for mode in ["baseline", "full"]:
    rows = conn.execute(
        "SELECT payload FROM done WHERE mode=? ORDER BY rowid", (mode,)
    ).fetchall()
    records = [json.loads(r[0]) for r in rows]
    n = len(records)
    if n == 0:
        print(f"{mode}: no records")
        continue
    ex = sum(r.get("ex", 0) for r in records)
    valid = sum(r.get("valid", 0) for r in records)
    by_diff = {}
    for r in records:
        d = r.get("difficulty", "?")
        by_diff.setdefault(d, [0, 0])
        by_diff[d][0] += 1
        by_diff[d][1] += r.get("ex", 0)

    print(f"\n=== {mode.upper()} ({n} questions) ===")
    print(f"  EX = {ex/n:.3f} ({ex}/{n})")
    print(f"  Valid = {valid/n:.3f}")
    for d in sorted(by_diff):
        total, correct = by_diff[d]
        print(f"  {d:13s}: {correct}/{total} = {correct/total:.3f}")

    # Write results JSON
    summary = {
        "mode": mode, "model": "gemini-2.5-flash", "n": n,
        "execution_accuracy": round(ex / n, 4),
        "execution_valid_rate": round(valid / n, 4),
        "by_difficulty": {d: round(c[1] / c[0], 3) for d, c in sorted(by_diff.items())},
        "note": f"partial run ({n}/500)" if n < 500 else "complete",
    }
    out = {"summary": summary, "records": records}
    out_path = RUN_DIR / f"{mode}_results.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Written to {out_path}")

conn.close()

# Compare with Phase A run
print("\n\n=== COMPARISON: Phase A vs P2 (single-pass + English intent) ===")
pa_full = json.loads(Path("data_agent/nl2sql_eval_results/bird_pg_2026-05-01_182457/full_results.json").read_text(encoding="utf-8"))
p2_full = json.loads((RUN_DIR / "full_results.json").read_text(encoding="utf-8"))
print(f"  Phase A full: EX={pa_full['summary']['execution_accuracy']} (n={pa_full['summary']['n']})")
print(f"  P2 full:      EX={p2_full['summary']['execution_accuracy']} (n={p2_full['summary']['n']})")
delta = p2_full['summary']['execution_accuracy'] - pa_full['summary']['execution_accuracy']
print(f"  Delta:        {delta:+.3f}")

# Compare with DIN-SQL
din = json.loads(Path("data_agent/nl2sql_eval_results/bird_din_sql_2026-05-03_193412/results.json").read_text(encoding="utf-8"))
print(f"\n  DIN-SQL:      EX={din['summary']['execution_accuracy']} (n={din['summary']['n']})")
print(f"  P2 vs DIN:    {p2_full['summary']['execution_accuracy'] - din['summary']['execution_accuracy']:+.3f}")
