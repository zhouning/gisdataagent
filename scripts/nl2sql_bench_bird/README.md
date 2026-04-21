# BIRD mini_dev NL2SQL Baseline Evaluation

Evaluates Gemini's raw NL2SQL capability on the [BIRD mini_dev](https://github.com/bird-bench/mini_dev)
benchmark (500 questions, 11 SQLite databases, 3 difficulty levels).

This is a **pure LLM baseline** — no semantic layer, no RAG, no few-shot injection.
Results directly comparable to the [BIRD leaderboard](https://bird-bench.github.io/).

## Setup

```bash
cd D:\adk

# 1. Clone repo (already done if you see data/bird_mini_dev/)
git clone --depth 1 https://github.com/bird-bench/mini_dev.git data/bird_mini_dev

# 2. Download + extract SQLite databases
# (download from https://bird-bench.oss-cn-beijing.aliyuncs.com/minidev.zip)
cd data/bird_mini_dev/llm/mini_dev_data
# unzip minidev.zip (or use Python: zipfile.ZipFile('minidev.zip').extractall('.'))
```

## Run

```bash
cd D:\adk
$env:PYTHONPATH="D:\adk"

# Smoke test (10 questions)
.venv\Scripts\python.exe scripts/nl2sql_bench_bird/run_bird_eval.py --limit 10

# By difficulty
.venv\Scripts\python.exe scripts/nl2sql_bench_bird/run_bird_eval.py --difficulty simple --limit 20

# Full run (500 questions, ~30-60 min depending on Gemini quota)
.venv\Scripts\python.exe scripts/nl2sql_bench_bird/run_bird_eval.py
```

## Output

`data_agent/nl2sql_eval_results/bird_<timestamp>/bird_baseline_results.json`

Contains per-question records + aggregate summary:
- `execution_accuracy` (EX): result set matches gold
- `execution_valid_rate`: SQL executes without error
- `by_difficulty`: {simple, moderate, challenging} breakdown

## Reference Scores (BIRD leaderboard, 2025)

| Model | EX (mini_dev) |
|-------|---:|
| GPT-4o | ~67% |
| Claude 3.5 Sonnet | ~65% |
| Gemini 1.5 Pro | ~62% |
| GPT-3.5 Turbo | ~45% |

Your result gives a direct comparison point for Gemini 2.5 Flash.
