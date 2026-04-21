# FloodSQL-Bench NL2SQL Evaluation Harness

A/B benchmark of the GIS Data Agent's NL→Semantic→SQL pipeline against a
pure-LLM baseline on [FloodSQL-Bench](https://github.com/HanzhouLiu/FloodSQL-Bench)
(443 questions, 10 PostGIS tables, difficulty L0–L5).

## Prerequisites

1. `.env` with working PostgreSQL/PostGIS credentials (the existing project DB)
2. Hugging Face CLI logged in + dataset terms accepted:
   ```bash
   huggingface-cli login
   # then visit https://huggingface.co/datasets/HanzhouLiu/FloodSQL-Bench and click "Agree"
   ```
3. `GOOGLE_API_KEY` or Vertex AI configured (for LLM inference)

## Usage

```bash
cd D:\adk
$env:PYTHONPATH="D:\adk"

# One-time setup
.venv/Scripts/python.exe scripts/nl2sql_bench/01_download.py
.venv/Scripts/python.exe scripts/nl2sql_bench/02_import_to_pg.py
.venv/Scripts/python.exe scripts/nl2sql_bench/03_register_semantic.py

# Smoke test (5 L0 questions, both modes)
.venv/Scripts/python.exe scripts/nl2sql_bench/04_run_eval.py --mode both --limit 5

# Full run (443 × 2 modes, ~4–7h)
.venv/Scripts/python.exe scripts/nl2sql_bench/04_run_eval.py --mode both

# Report
.venv/Scripts/python.exe scripts/nl2sql_bench/05_report.py --latest
```

## Output

`data_agent/nl2sql_eval_results/<timestamp>/`:
- `full_results.json` / `baseline_results.json` — per-question records
- `comparison_report.md` — EX delta + by-difficulty + error types
- `by_difficulty.png` — L0–L5 bar chart
- `run_state.db` — SQLite resume cache
