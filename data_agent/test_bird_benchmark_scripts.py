"""Tests for scripts/nl2sql_bench_bird/bird_paths.py."""

import importlib.util
import json
from pathlib import Path

import pytest


def _load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BIRD_PATHS = _load_module(
    str(Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_bird" / "bird_paths.py"),
    "bird_paths_mod",
)


def test_bird_paths_resolve_bird_layout_returns_expected_paths(tmp_path: Path):
    root = tmp_path / "bird_mini_dev"

    sqlite_questions = root / "finetuning" / "inference" / "mini_dev_prompt.jsonl"
    sqlite_questions.parent.mkdir(parents=True, exist_ok=True)
    sqlite_questions.write_text("{}\n", encoding="utf-8")

    pg_questions = root / "llm" / "mini_dev_data" / "minidev" / "MINIDEV" / "mini_dev_postgresql.json"
    pg_questions.parent.mkdir(parents=True, exist_ok=True)
    pg_questions.write_text("[]", encoding="utf-8")

    dev_databases = root / "llm" / "mini_dev_data" / "minidev" / "MINIDEV" / "dev_databases"
    dev_databases.mkdir(parents=True, exist_ok=True)

    layout = BIRD_PATHS.resolve_bird_layout(root)

    assert layout["bird_root"] == root.resolve()
    assert layout["sqlite_questions"] == sqlite_questions
    assert layout["pg_questions"] == pg_questions
    assert layout["dev_databases"] == dev_databases
    assert "results_root" in layout


def test_bird_paths_resolve_bird_layout_raises_when_layout_incomplete(tmp_path: Path):
    root = tmp_path / "bird_mini_dev"
    root.mkdir(parents=True, exist_ok=True)

    sqlite_questions = root / "finetuning" / "inference" / "mini_dev_prompt.jsonl"
    sqlite_questions.parent.mkdir(parents=True, exist_ok=True)
    sqlite_questions.write_text("{}\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="BIRD layout incomplete: missing"):
        BIRD_PATHS.resolve_bird_layout(root)


def test_report_pg_eval_writes_comparison_report(tmp_path):
    run_dir = tmp_path / "bird_pg_2026-04-30_120000"
    run_dir.mkdir()

    baseline = {
        "summary": {"mode": "baseline", "execution_accuracy": 0.25, "execution_valid_rate": 0.5, "by_difficulty": {"simple": 0.5}},
        "records": [{"qid": 1, "difficulty": "simple", "db_id": "db1", "ex": 0, "valid": 1, "gen_status": "ok"}],
    }
    full = {
        "summary": {"mode": "full", "execution_accuracy": 0.5, "execution_valid_rate": 0.75, "by_difficulty": {"simple": 1.0}},
        "records": [{"qid": 1, "difficulty": "simple", "db_id": "db1", "ex": 1, "valid": 1, "gen_status": "ok"}],
    }

    (run_dir / "baseline_results.json").write_text(json.dumps(baseline), encoding="utf-8")
    (run_dir / "full_results.json").write_text(json.dumps(full), encoding="utf-8")

    mod = _load_module(
        str(Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_bird" / "report_pg_eval.py"),
        "bird_report_mod",
    )

    mod.write_report(run_dir, baseline, full)
    report = (run_dir / "comparison_report.md").read_text(encoding="utf-8")
    assert "# BIRD PostgreSQL Evaluation Report" in report
    assert "delta=+0.2500" in report
    assert "| simple | 0.5000 | 1.0000 | +0.5000 |" in report


def test_run_bird_eval_parser_accepts_bird_root():
    mod = _load_module(
        str(Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_bird" / "run_bird_eval.py"),
        "run_bird_eval_mod",
    )
    parser = mod.build_arg_parser()
    args = parser.parse_args(["--bird-root", "D:/tmp/bird", "--limit", "3"])
    assert args.bird_root == "D:/tmp/bird"
    assert args.limit == 3


def test_run_pg_eval_parser_accepts_bird_root():
    mod = _load_module(
        str(Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_bird" / "run_pg_eval.py"),
        "run_pg_eval_mod",
    )
    parser = mod.build_arg_parser()
    args = parser.parse_args(["--bird-root", "D:/tmp/bird", "--mode", "both"])
    assert args.bird_root == "D:/tmp/bird"
    assert args.mode == "both"
