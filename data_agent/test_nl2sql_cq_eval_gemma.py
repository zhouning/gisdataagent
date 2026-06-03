"""Tests for CQ full-mode Gemma/Ollama high-level NL2Semantic2SQL path."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


def _load_script_module(rel_path: str, name: str):
    root = Path(__file__).resolve().parents[1]
    path = root / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_cq_full_agent_uses_single_tool_for_gemma_ollama(monkeypatch):
    mod = _load_script_module(
        "scripts/nl2sql_bench_cq/nl2sql_agent.py",
        "cq_nl2sql_agent_gemma_test",
    )
    from data_agent.nl2semantic2sql_direct_agent import DirectNL2SemanticSQLAgent
    monkeypatch.setenv("NL2SQL_AGENT_MODEL", "gemma4-26b-host9")
    monkeypatch.setenv("NL2SQL_AGENT_FAMILY", "")

    agent = mod.build_nl2sql_agent()

    assert isinstance(agent, DirectNL2SemanticSQLAgent)


def test_cq_full_generate_extracts_sql_from_high_level_tool(monkeypatch):
    mod = _load_script_module(
        "scripts/nl2sql_bench_cq/run_cq_eval.py",
        "cq_run_eval_high_level_test",
    )

    tool_payload = {
        "status": "ok",
        "sql": "SELECT COUNT(*) FROM cq_osm_roads_2021",
        "execution": {"status": "ok", "rows": 1},
    }
    result = SimpleNamespace(
        tool_execution_log=[{
            "tool_name": "run_nl2semantic2sql",
            "args": {"user_question": "count roads"},
            "result_summary": json.dumps(tool_payload, ensure_ascii=False),
        }],
        total_input_tokens=3,
        total_output_tokens=5,
        error=None,
        report_text="",
    )

    assert mod._extract_full_pred_sql(result) == "SELECT COUNT(*) FROM cq_osm_roads_2021"


def test_cq_full_generate_extracts_error_from_high_level_tool():
    mod = _load_script_module(
        "scripts/nl2sql_bench_cq/run_cq_eval.py",
        "cq_run_eval_high_level_error_test",
    )

    tool_payload = {
        "status": "error",
        "sql": "",
        "error": "gemma_sql_generation_failed:timeout",
    }
    result = SimpleNamespace(
        tool_execution_log=[{
            "tool_name": "run_nl2semantic2sql",
            "result_summary": json.dumps(tool_payload, ensure_ascii=False),
        }],
        total_input_tokens=3,
        total_output_tokens=5,
        error=None,
        report_text="",
    )

    assert mod._extract_full_pred_sql(result) == ""
    assert mod._extract_high_level_tool_error(result) == "gemma_sql_generation_failed:timeout"


def test_cq_full_generate_does_not_extract_sql_from_rejected_high_level_tool():
    mod = _load_script_module(
        "scripts/nl2sql_bench_cq/run_cq_eval.py",
        "cq_run_eval_high_level_rejected_test",
    )

    tool_payload = {
        "status": "rejected",
        "sql": "SELECT name FROM hallucinated_table",
        "error": "runtime_guard:hallucinated_table:hallucinated_table",
    }
    result = SimpleNamespace(
        tool_execution_log=[{
            "tool_name": "run_nl2semantic2sql",
            "result_summary": json.dumps(tool_payload, ensure_ascii=False),
        }],
        total_input_tokens=3,
        total_output_tokens=5,
        error=None,
        report_text="",
    )

    assert mod._extract_full_pred_sql(result) == ""
    assert mod._extract_high_level_tool_error(result) == "runtime_guard:hallucinated_table:hallucinated_table"


def test_cq_full_semantic_rewrite_runs_after_sql_extraction(monkeypatch):
    mod = _load_script_module(
        "scripts/nl2sql_bench_cq/run_cq_eval.py",
        "cq_run_eval_post_extract_rewrite_test",
    )

    context = {
        "candidate_tables": [
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {"column_name": "kind", "quoted_ref": "kind", "needs_quoting": False},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True},
                ],
            },
            {
                "table_name": "buildings",
                "columns": [
                    {
                        "column_name": "id",
                        "quoted_ref": "id",
                        "needs_quoting": False,
                        "value_semantics": {"identifier": True},
                    },
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True},
                ],
            },
        ],
    }
    monkeypatch.setattr(
        "data_agent.nl2sql_grounding.build_nl2sql_context",
        lambda question, family=None: context,
    )

    rewritten = mod._apply_full_semantic_rewrites(
        "count buildings that intersect each school POI using ST_Intersects",
        "SELECT p.name, COUNT(b.id) AS building_count "
        "FROM pois AS p LEFT JOIN buildings AS b "
        "ON ST_INTERSECTS(p.geometry, b.geometry) "
        "WHERE p.kind LIKE '%school%' GROUP BY p.name LIMIT 10",
    )

    assert "LEFT JOIN" not in rewritten
    assert "JOIN buildings AS b" in rewritten
    assert "COUNT(DISTINCT b.id)" in rewritten


def test_cq_full_generate_falls_back_to_direct_tool_when_agent_log_has_no_sql(monkeypatch):
    mod = _load_script_module(
        "scripts/nl2sql_bench_cq/run_cq_eval.py",
        "cq_run_eval_direct_fallback_test",
    )

    async def fake_run_pipeline_headless(**kwargs):
        return SimpleNamespace(
            tool_execution_log=[],
            total_input_tokens=11,
            total_output_tokens=3,
            error=None,
            report_text="no extracted sql",
        )

    fallback_payload = {
        "status": "ok",
        "sql": "SELECT COUNT(*) FROM cq_osm_roads_2021",
        "execution": {"status": "ok", "rows": 1},
    }

    monkeypatch.setattr(mod, "_lazy_init_full", lambda: (object(), object()))
    monkeypatch.setattr(mod, "get_schema", lambda: "schema")
    monkeypatch.setattr(
        "data_agent.pipeline_runner.run_pipeline_headless",
        fake_run_pipeline_headless,
    )
    monkeypatch.setattr(
        "data_agent.nl2sql_executor.run_nl2semantic2sql",
        lambda question: json.dumps(fallback_payload, ensure_ascii=False),
    )

    gen = asyncio.run(mod.full_generate("count roads"))

    assert gen["status"] == "ok"
    assert gen["sql"] == "SELECT COUNT(*) FROM cq_osm_roads_2021 LIMIT 100000"
    assert gen["error"] is None


def test_compare_results_allows_multirow_numeric_rounding_tolerance():
    mod = _load_script_module(
        "scripts/nl2sql_bench_cq/run_cq_eval.py",
        "cq_run_eval_numeric_tolerance_test",
    )

    gold = {"status": "ok", "rows": [("A", 100.0), ("B", 200.0)]}
    pred = {"status": "ok", "rows": [("B", 200.04), ("A", 100.03)]}

    ok, reason = mod.compare_results(gold, pred, rel_tol=1e-3)

    assert ok is True
    assert "numeric tolerance" in reason


def test_run_one_baseline_uses_configured_family_model(monkeypatch):
    mod = _load_script_module(
        "scripts/nl2sql_bench_cq/run_cq_eval.py",
        "cq_run_eval_baseline_family_model_test",
    )

    q = {
        "id": "TEST_BASELINE_MODEL",
        "difficulty": "Easy",
        "category": "Aggregation",
        "question": "count rows",
        "golden_sql": "SELECT 1",
    }
    calls = {}

    def legacy_baseline(question):
        calls["legacy"] = question
        return {"status": "ok", "sql": "SELECT 0", "error": None, "tokens": 0}

    def family_baseline(question, model_name=None):
        calls["family"] = (question, model_name)
        return {"status": "ok", "sql": "SELECT 1", "error": None, "tokens": 0}

    monkeypatch.setenv("NL2SQL_BASELINE_MODEL", "gemma4-26b-host228")
    monkeypatch.setattr(mod, "baseline_generate", legacy_baseline)
    monkeypatch.setattr(mod, "baseline_generate_family_aware", family_baseline)
    monkeypatch.setattr(
        mod,
        "execute_pg",
        lambda sql, timeout_ms=60_000: {"status": "ok", "rows": [(1,)]},
    )

    rec = asyncio.run(mod.run_one(q, "baseline"))

    assert calls == {"family": ("count rows", "gemma4-26b-host228")}
    assert rec["ex"] == 1
