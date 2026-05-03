"""Smoke tests for DIN-SQL runner."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_predict_returns_sql_with_mocked_llm():
    from scripts.nl2sql_bench_baselines.din_sql.din_sql_runner import predict

    call_count = [0]
    def fake_call_llm(prompt, temperature=0.0):
        call_count[0] += 1
        if call_count[0] == 1:
            return "Tables: orders\nColumns: orders.id, orders.amount"
        elif call_count[0] == 2:
            return "EASY"
        elif call_count[0] == 3:
            return "SELECT SUM(amount) FROM orders"
        return ""

    with patch("scripts.nl2sql_bench_baselines.din_sql.din_sql_runner._call_llm", side_effect=fake_call_llm):
        result = predict(
            schema="CREATE TABLE orders (id INT, amount NUMERIC);",
            question="What is the total order amount?",
        )

    assert result["sql"] == "SELECT SUM(amount) FROM orders"
    assert result["difficulty"] == "EASY"
    assert result["stages_run"] == 3
    assert call_count[0] == 3


def test_predict_with_self_correction():
    from scripts.nl2sql_bench_baselines.din_sql.din_sql_runner import predict

    call_count = [0]
    def fake_call_llm(prompt, temperature=0.0):
        call_count[0] += 1
        if call_count[0] == 1:
            return "Tables: t\nColumns: t.id"
        elif call_count[0] == 2:
            return "EASY"
        elif call_count[0] == 3:
            return "SELECT * FROM t WHERE col = 1"
        elif call_count[0] == 4:
            return "SELECT * FROM t WHERE id = 1"
        return ""

    exec_calls = [0]
    def fake_execute(sql):
        exec_calls[0] += 1
        if exec_calls[0] == 1:
            return {"status": "error", "error": 'column "col" does not exist'}
        return {"status": "ok"}

    with patch("scripts.nl2sql_bench_baselines.din_sql.din_sql_runner._call_llm", side_effect=fake_call_llm):
        result = predict(
            schema="CREATE TABLE t (id INT);",
            question="Get row 1",
            execute_fn=fake_execute,
        )

    assert result["sql"] == "SELECT * FROM t WHERE id = 1"
    assert result["stages_run"] == 4


def test_classify_difficulty_extracts_label():
    from scripts.nl2sql_bench_baselines.din_sql.din_sql_runner import classify_difficulty

    with patch("scripts.nl2sql_bench_baselines.din_sql.din_sql_runner._call_llm", return_value="The difficulty is HARD because it requires subqueries."):
        result = classify_difficulty("complex question", "", "tables: a, b, c")
    assert result == "HARD"
