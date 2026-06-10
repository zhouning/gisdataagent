"""Tests for NL2SQL tool execution helpers."""
from __future__ import annotations

import json
import subprocess
import sys

import pandas as pd


def test_execute_safe_sql_allows_read_only_with_query(monkeypatch):
    from data_agent.toolsets.nl2sql_tools import execute_safe_sql

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *_args, **_kwargs):
            return None

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr("data_agent.db_engine.get_engine", lambda: FakeEngine())
    monkeypatch.setattr("data_agent.database_tools._inject_user_context", lambda conn: None)
    monkeypatch.setattr(
        "data_agent.toolsets.nl2sql_tools.pd.read_sql",
        lambda *_args, **_kwargs: pd.DataFrame([{"n": 1}]),
    )

    result = json.loads(execute_safe_sql("WITH t AS (SELECT 1 AS n) SELECT n FROM t"))

    assert result["status"] == "ok"
    assert result["data"] == [{"n": 1}]


def test_package_level_nl2sql_toolset_import_does_not_load_analysis_toolset():
    code = (
        "import sys; "
        "from data_agent.toolsets import NL2SQLToolset; "
        "print(NL2SQLToolset.__name__); "
        "print('data_agent.toolsets.analysis_tools' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines() == ["NL2SQLToolset", "False"]
