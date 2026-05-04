"""Translate 50 more BIRD questions to Chinese, expanding from 50 to 100.

Existing 50 cover only debit_card_specializing (30) + student_club (20).
We pick 50 more from the remaining 9 BIRD databases, balanced by difficulty.

Usage:
  $env:PYTHONPATH="D:\\adk"
  .venv\\Scripts\\python.exe scripts/translate_bird_chinese_100.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(str(PROJECT_ROOT / "data_agent" / ".env"))

EXISTING = PROJECT_ROOT / "data" / "bird_mini_dev" / "chinese_questions_50.json"
FULL = PROJECT_ROOT / "data" / "bird_mini_dev" / "llm" / "mini_dev_data" / "minidev" / "MINIDEV" / "mini_dev_postgresql.json"
OUT = PROJECT_ROOT / "data" / "bird_mini_dev" / "chinese_questions_100.json"

MODEL = "gemini-2.0-flash"
BATCH_SIZE = 10  # translate 10 questions per LLM call


def select_50_more(existing_qids: set[int], full: list[dict]) -> list[dict]:
    """Pick 50 questions balanced by difficulty + DB coverage."""
    # Target: 15 simple, 20 moderate, 15 challenging
    # Spread across at least 5 different DBs (excluding the 2 already covered)
    excluded_dbs = {"debit_card_specializing", "student_club"}
    candidates = [q for q in full
                  if q["question_id"] not in existing_qids
                  and q["db_id"] not in excluded_dbs]

    by_diff = {"simple": [], "moderate": [], "challenging": []}
    for q in candidates:
        d = q.get("difficulty", "?")
        if d in by_diff:
            by_diff[d].append(q)

    # Round-robin by db_id within each difficulty for balanced coverage
    def pick_balanced(pool: list[dict], n: int) -> list[dict]:
        from collections import defaultdict
        by_db = defaultdict(list)
        for q in pool:
            by_db[q["db_id"]].append(q)
        # Round-robin
        out = []
        dbs = sorted(by_db.keys())
        i = 0
        while len(out) < n and any(by_db[d] for d in dbs):
            db = dbs[i % len(dbs)]
            if by_db[db]:
                out.append(by_db[db].pop(0))
            i += 1
        return out

    selected = (pick_balanced(by_diff["simple"], 15)
                + pick_balanced(by_diff["moderate"], 20)
                + pick_balanced(by_diff["challenging"], 15))
    return selected


def translate_batch(client, batch: list[dict]) -> list[str]:
    """Translate a batch of question texts to Chinese in a single LLM call."""
    from google.genai import types
    numbered = "\n".join(f"{i+1}. {q['question']}" for i, q in enumerate(batch))
    prompt = (
        "Translate the following BIRD NL2SQL questions from English to fluent Chinese.\n\n"
        "Translation rules:\n"
        "- Keep table names, column names, and SQL keywords in English\n"
        "  (they are stored in the PostgreSQL database as English).\n"
        "- Keep domain abbreviations like LAM, SME, KAM, EUR, CZK, SQL in English.\n"
        "- Translate the natural language phrasing to natural Chinese.\n"
        "- Output ONLY the translations, one per line, numbered 1-N matching the input.\n"
        "- Do NOT add explanations or commentary.\n\n"
        f"English questions:\n{numbered}\n\n"
        "Chinese translations (numbered 1-N):\n"
    )
    resp = client.models.generate_content(
        model=MODEL,
        contents=[prompt],
        config=types.GenerateContentConfig(
            temperature=0.0,
            http_options=types.HttpOptions(timeout=60_000),
        ),
    )
    text = (resp.text or "").strip()
    # Parse numbered output
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Strip leading "1. " "2. " etc
        import re
        m = re.match(r"^(\d+)[\.\)、]\s*(.+)$", line)
        if m:
            lines.append(m.group(2).strip())
        else:
            lines.append(line)
    if len(lines) != len(batch):
        # Try fallback: keep all non-empty lines
        print(f"  WARN: got {len(lines)} translations for {len(batch)} questions", file=sys.stderr)
    return lines[:len(batch)]


def main() -> int:
    existing = json.loads(EXISTING.read_text(encoding="utf-8"))
    full = json.loads(FULL.read_text(encoding="utf-8"))
    existing_qids = {q["question_id"] for q in existing}

    print(f"[bird-cn] Existing: {len(existing)} Chinese questions")
    print(f"[bird-cn] Full BIRD: {len(full)} English questions")

    new_questions = select_50_more(existing_qids, full)
    print(f"[bird-cn] Selected: {len(new_questions)} new questions to translate")

    from collections import Counter
    print(f"  by difficulty: {dict(Counter(q['difficulty'] for q in new_questions))}")
    print(f"  by db_id: {dict(Counter(q['db_id'] for q in new_questions))}")

    # Init Gemini client
    from google import genai
    client = genai.Client()

    translated = []
    for i in range(0, len(new_questions), BATCH_SIZE):
        batch = new_questions[i:i + BATCH_SIZE]
        print(f"\n[bird-cn] Translating batch {i // BATCH_SIZE + 1}/{(len(new_questions) + BATCH_SIZE - 1) // BATCH_SIZE} "
              f"({len(batch)} questions)")
        try:
            cn_texts = translate_batch(client, batch)
        except Exception as e:
            print(f"  ERROR batch {i}: {e}", file=sys.stderr)
            cn_texts = ["[TRANSLATION FAILED]"] * len(batch)

        for orig, cn in zip(batch, cn_texts):
            translated.append({
                "question_id": orig["question_id"],
                "db_id": orig["db_id"],
                "question": cn,
                "evidence": orig.get("evidence", ""),
                "SQL": orig.get("SQL", ""),
                "difficulty": orig.get("difficulty", ""),
                "question_en": orig["question"],
            })
        time.sleep(1)  # rate-limit safety

    # Combine: existing + new (keep existing format, add question_en if missing)
    combined = []
    for q in existing:
        if "question_en" not in q:
            # Backfill from full
            full_q = next((fq for fq in full if fq["question_id"] == q["question_id"]), None)
            if full_q:
                q = {**q, "question_en": full_q["question"]}
        combined.append(q)
    combined.extend(translated)
    combined.sort(key=lambda q: q["question_id"])

    OUT.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[bird-cn] Written {len(combined)} questions to {OUT}")

    # Summary
    print(f"\n=== Summary ===")
    print(f"  Total: {len(combined)}")
    print(f"  by difficulty: {dict(Counter(q['difficulty'] for q in combined))}")
    print(f"  by db_id: {dict(Counter(q['db_id'] for q in combined))}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
