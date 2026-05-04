#!/usr/bin/env python3
"""
generate_gis100_benchmark.py
----------------------------
Generates a 100-question GIS NL2SQL benchmark for Chongqing spatial data.
Combines 20 existing questions from chongqing_geo_nl2sql_full_benchmark.json
with 80 new hardcoded questions, validates each golden_sql against the live DB,
and writes the combined set to benchmarks/chongqing_geo_nl2sql_100_benchmark.json.

Usage:
    $env:PYTHONPATH="D:\adk"
    .venv/Scripts/python.exe scripts/generate_gis100_benchmark.py
"""

import json
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / "data_agent" / ".env")

DB_CONN = dict(
    host=os.getenv("POSTGRES_HOST", "119.3.175.198"),
    port=int(os.getenv("POSTGRES_PORT", 5432)),
    dbname=os.getenv("POSTGRES_DATABASE", "flights_dataset"),
    user=os.getenv("POSTGRES_USER", "agent_user"),
    password=os.getenv("POSTGRES_PASSWORD", "SuperMap@123"),
)

EXISTING_PATH   = BASE_DIR / "benchmarks" / "chongqing_geo_nl2sql_full_benchmark.json"
OUTPUT_PATH     = BASE_DIR / "benchmarks" / "chongqing_geo_nl2sql_100_benchmark.json"
# The 80 new questions are stored in a companion JSON file built by _build_questions.py
NEW_Q_PATH      = Path(__file__).parent / "new_questions_80.json"


# ── Validation ────────────────────────────────────────────────────────────────

def validate_questions(questions: list, conn) -> dict:
    """Execute each golden_sql and return pass/fail results."""
    results = {}
    cur = conn.cursor()
    for q in questions:
        qid = q["id"]
        sql = q.get("golden_sql")
        if sql is None:
            results[qid] = {"status": "SKIP", "note": "null golden_sql (refusal question)"}
            continue
        try:
            cur.execute(sql)
            cur.fetchall()
            conn.rollback()
            results[qid] = {"status": "PASS"}
        except Exception as e:
            conn.rollback()
            results[qid] = {"status": "FAIL", "error": str(e)}
    cur.close()
    return results


def main():
    print("=" * 60)
    print("GIS NL2SQL 100-Question Benchmark Generator")
    print("=" * 60)

    # 1. Load existing 20 questions
    print(f"\n[1] Loading existing questions from:\n    {EXISTING_PATH}")
    with open(EXISTING_PATH, encoding="utf-8") as f:
        existing = json.load(f)
    print(f"    Loaded {len(existing)} existing questions.")

    # 2. Load 80 new questions
    print(f"\n[2] Loading 80 new questions from:\n    {NEW_Q_PATH}")
    with open(NEW_Q_PATH, encoding="utf-8") as f:
        new_questions = json.load(f)
    assert len(new_questions) == 80, f"Expected 80 new questions, got {len(new_questions)}"
    print(f"    Loaded {len(new_questions)} new questions.")

    # 3. Combine
    all_questions = existing + new_questions
    print(f"\n[3] Total questions: {len(all_questions)} (20 existing + 80 new)")

    # 4. Connect to DB and validate new questions
    print(f"\n[4] Connecting to PostgreSQL at {DB_CONN['host']}:{DB_CONN['port']} ...")
    try:
        conn = psycopg2.connect(**DB_CONN)
        print("    Connection successful.")
    except Exception as e:
        print(f"    ERROR: Could not connect to DB: {e}")
        sys.exit(1)

    print(f"\n[5] Validating {len(new_questions)} new golden SQL statements ...")
    results = validate_questions(new_questions, conn)
    conn.close()

    # 5. Report
    passed  = [qid for qid, r in results.items() if r["status"] == "PASS"]
    skipped = [qid for qid, r in results.items() if r["status"] == "SKIP"]
    failed  = [qid for qid, r in results.items() if r["status"] == "FAIL"]

    print(f"\n{'='*60}")
    print("VALIDATION RESULTS")
    print(f"{'='*60}")
    print(f"  PASS  : {len(passed)}")
    print(f"  SKIP  : {len(skipped)}  (null golden_sql -- refusal questions)")
    print(f"  FAIL  : {len(failed)}")

    if failed:
        print("\nFailed questions:")
        for qid in failed:
            print(f"  [{qid}] {results[qid]['error']}")

    # 6. Write combined JSON
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_questions, f, ensure_ascii=False, indent=2)
    print(f"\n[6] Written {len(all_questions)} questions to:\n    {OUTPUT_PATH}")

    # Final summary
    executable = sum(1 for q in new_questions if q.get("golden_sql") is not None)
    print(f"\nSummary: {len(passed)}/{executable} executable new questions have valid gold SQL.")
    if failed:
        print("WARNING: Some SQL statements failed validation. Review errors above.")
        sys.exit(1)
    else:
        print("All executable gold SQL statements validated successfully.")


if __name__ == "__main__":
    main()
