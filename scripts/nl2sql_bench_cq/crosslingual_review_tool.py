"""Export a CSV for bilingual hand-review of the 50 LLM-translated BIRD questions.

The 50 question_ids are read from the most recent v3 chinese-eval run
(bird_pg_chinese_2026-05-05_201113/chinese_eval_report.json -> chinese_records -> qid).
For each qid, the CSV shows the English original and the LLM-translated Chinese;
the reviewer fills 'status' (ok / fix / drop) and, for 'fix', the corrected Chinese.

Task 11 will ingest the filled CSV and re-run the cross-lingual eval.

Responds to 2026-05-07 reviewer B section 3 (Validity of Cross-lingual Evaluation).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

SRC_BENCHMARK = Path("D:/adk/benchmarks/bird_chinese_100_benchmark.json")
SRC_EVAL = Path("D:/adk/data_agent/nl2sql_eval_results/"
                "bird_pg_chinese_2026-05-05_201113/chinese_eval_report.json")
OUT_CSV = Path("D:/adk/benchmarks/bird_chinese_50q_review.csv")


def main() -> None:
    # 1. Read the 50 qids used in the v3 eval
    eval_data = json.loads(SRC_EVAL.read_text(encoding="utf-8"))
    chinese_qids = [r["qid"] for r in eval_data["chinese_records"]]
    assert len(chinese_qids) == 50, f"Expected 50 qids, got {len(chinese_qids)}"

    # 2. Read the benchmark and index by question_id
    bench = json.loads(SRC_BENCHMARK.read_text(encoding="utf-8"))
    bench_by_qid = {q["question_id"]: q for q in bench}

    missing = [q for q in chinese_qids if q not in bench_by_qid]
    if missing:
        raise SystemExit(f"qids missing from benchmark: {missing[:5]}... "
                         f"({len(missing)} total). Cannot build review CSV.")

    # 3. Write CSV with utf-8-sig so Excel opens it without mojibake
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "qid",
            "db_id",
            "difficulty",
            "english_original",
            "llm_chinese_translation",
            "status",              # reviewer fills: ok / fix / drop
            "corrected_chinese",   # reviewer fills if status=fix
            "reviewer_note",       # optional notes
        ])
        for qid in chinese_qids:
            q = bench_by_qid[qid]
            w.writerow([
                qid,
                q.get("db_id", ""),
                q.get("difficulty", ""),
                q.get("question_en", ""),
                q.get("question", ""),
                "pending",
                "",
                "",
            ])

    print(f"Wrote {OUT_CSV}")
    print(f"  50 rows (qid range {min(chinese_qids)}-{max(chinese_qids)})")
    print(f"\nNext steps:")
    print(f"  1. Open {OUT_CSV.name} in Excel/LibreOffice")
    print(f"  2. For each row, set status = ok (translation is fine) / fix / drop")
    print(f"  3. If status=fix, paste the corrected Chinese into corrected_chinese")
    print(f"  4. Save the CSV, then run Task 11 re-eval driver")


if __name__ == "__main__":
    main()
