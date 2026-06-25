"""Tests for CQ full-mode Gemma/Ollama high-level NL2Semantic2SQL path."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
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


def test_cq_full_agent_uses_single_tool_for_qwen_ollama(monkeypatch):
    mod = _load_script_module(
        "scripts/nl2sql_bench_cq/nl2sql_agent.py",
        "cq_nl2sql_agent_qwen_test",
    )
    from data_agent.nl2semantic2sql_direct_agent import DirectNL2SemanticSQLAgent

    class FakeQwenModel:
        model = "ollama_chat/Qwen3.6:35b"

    monkeypatch.setenv("NL2SQL_AGENT_MODEL", "qwen3.6-35b-host228")
    monkeypatch.setenv("NL2SQL_AGENT_FAMILY", "")
    monkeypatch.setenv("NL2SQL_QWEN_DIRECT_FULL", "1")
    monkeypatch.setattr("data_agent.model_gateway.create_model", lambda model_name: FakeQwenModel())
    monkeypatch.setattr("data_agent.model_gateway.family_of", lambda model_obj: "qwen")
    monkeypatch.setattr(
        "data_agent.prompts_nl2sql.load_system_instruction",
        lambda family, model_name=None: "qwen instruction",
    )

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


def test_cq_direct_fallback_preserves_sql_from_error_payload(monkeypatch):
    mod = _load_script_module(
        "scripts/nl2sql_bench_cq/run_cq_eval.py",
        "cq_run_eval_direct_error_sql_test",
    )

    tool_payload = {
        "status": "error",
        "sql": "WITH x AS (SELECT 1) SELECT * FROM x; AND invalid_tail",
        "execution": {"status": "error", "error": "syntax error at or near AND"},
    }
    monkeypatch.setattr(
        "data_agent.nl2sql_executor.run_nl2semantic2sql",
        lambda question: json.dumps(tool_payload, ensure_ascii=False),
    )

    result = mod._direct_full_fallback("cte with trailing clause")

    assert result["sql"] == "WITH x AS (SELECT 1) SELECT * FROM x; AND invalid_tail"


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


def test_cq_full_generate_rejects_schema_external_table(monkeypatch):
    mod = _load_script_module(
        "scripts/nl2sql_bench_cq/run_cq_eval.py",
        "cq_run_eval_schema_guard_test",
    )

    monkeypatch.setenv("NL2SQL_AGENT_MODEL", "gemma4-31b-host228")
    monkeypatch.setenv("NL2SQL_AGENT_FAMILY", "gemma")
    monkeypatch.setattr(
        mod,
        "_direct_full_fallback",
        lambda question: {"sql": "SELECT * FROM public.cq_weather_stations", "error": None},
    )
    monkeypatch.setattr(mod, "_apply_full_semantic_rewrites", lambda question, sql: sql)
    monkeypatch.setattr(
        mod,
        "get_schema",
        lambda: 'CREATE TABLE public.cq_land_use_dltb (\n  "BSM" text,\n);',
    )
    mod._SCHEMA_ALLOWED_TABLES_CACHE = None

    result = asyncio.run(mod.full_generate("weather station rainfall"))

    assert result["status"] == "guard_rejected"
    assert result["sql"] == ""
    assert "runtime_guard:hallucinated_table:public.cq_weather_stations" in result["error"]


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


def test_cq_full_generate_uses_direct_tool_first_for_gemma_model(monkeypatch):
    mod = _load_script_module(
        "scripts/nl2sql_bench_cq/run_cq_eval.py",
        "cq_run_eval_gemma_direct_first_test",
    )

    tool_payload = {
        "status": "ok",
        "sql": "SELECT COUNT(*) FROM cq_osm_roads_2021",
        "execution": {"status": "ok", "rows": 1},
    }

    monkeypatch.setenv("NL2SQL_AGENT_MODEL", "gemma4-31b-host228")
    monkeypatch.setenv("NL2SQL_AGENT_FAMILY", "")
    monkeypatch.setattr(
        "data_agent.nl2sql_executor.run_nl2semantic2sql",
        lambda question: json.dumps(tool_payload, ensure_ascii=False),
    )
    monkeypatch.setattr(
        "data_agent.pipeline_runner.run_pipeline_headless",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("pipeline should not run")),
    )

    gen = asyncio.run(mod.full_generate("count roads"))

    assert gen["status"] == "ok"
    assert gen["sql"] == "SELECT COUNT(*) FROM cq_osm_roads_2021 LIMIT 100000"
    assert gen["tokens"] == 0


def test_cq_full_generate_uses_direct_tool_first_for_qwen_model(monkeypatch):
    mod = _load_script_module(
        "scripts/nl2sql_bench_cq/run_cq_eval.py",
        "cq_run_eval_qwen_direct_first_test",
    )

    tool_payload = {
        "status": "ok",
        "sql": "SELECT COUNT(*) FROM cq_osm_roads_2021",
        "execution": {"status": "ok", "rows": 1},
    }

    monkeypatch.setenv("NL2SQL_AGENT_MODEL", "qwen3.6-35b-host228")
    monkeypatch.setenv("NL2SQL_AGENT_FAMILY", "qwen")
    monkeypatch.setenv("NL2SQL_QWEN_DIRECT_FULL", "1")
    monkeypatch.setattr(
        "data_agent.nl2sql_executor.run_nl2semantic2sql",
        lambda question: json.dumps(tool_payload, ensure_ascii=False),
    )
    monkeypatch.setattr(
        "data_agent.pipeline_runner.run_pipeline_headless",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("pipeline should not run")),
    )

    gen = asyncio.run(mod.full_generate("count roads"))

    assert gen["status"] == "ok"
    assert gen["sql"] == "SELECT COUNT(*) FROM cq_osm_roads_2021 LIMIT 100000"
    assert gen["tokens"] == 0


def test_cq_full_generate_qwen_direct_is_opt_in(monkeypatch):
    mod = _load_script_module(
        "scripts/nl2sql_bench_cq/run_cq_eval.py",
        "cq_run_eval_qwen_direct_opt_in_test",
    )

    monkeypatch.setenv("NL2SQL_AGENT_MODEL", "qwen3.6-35b-host228")
    monkeypatch.setenv("NL2SQL_AGENT_FAMILY", "qwen")
    monkeypatch.delenv("NL2SQL_QWEN_DIRECT_FULL", raising=False)

    assert mod._should_use_direct_full_path() is False

    monkeypatch.setenv("NL2SQL_QWEN_DIRECT_FULL", "1")

    assert mod._should_use_direct_full_path() is True


def test_cq_full_generate_uses_baseline_when_gemma_direct_returns_empty(monkeypatch):
    mod = _load_script_module(
        "scripts/nl2sql_bench_cq/run_cq_eval.py",
        "cq_run_eval_gemma_empty_baseline_test",
    )

    monkeypatch.setenv("NL2SQL_AGENT_MODEL", "gemma4-31b-host228")
    monkeypatch.setenv("NL2SQL_AGENT_FAMILY", "")
    monkeypatch.setattr(mod, "_direct_full_fallback", lambda question: {"sql": "", "error": ""})
    monkeypatch.setattr(
        mod,
        "baseline_generate_family_aware",
        lambda question, model_name=None: {
            "status": "ok",
            "sql": "SELECT name FROM cq_osm_roads_2021 LIMIT 5",
            "error": None,
            "tokens": 9,
        },
    )
    monkeypatch.setattr(
        "data_agent.pipeline_runner.run_pipeline_headless",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("pipeline should not run")),
    )

    gen = asyncio.run(mod.full_generate("list road names"))

    assert gen["status"] == "ok"
    assert gen["sql"] == "SELECT name FROM cq_osm_roads_2021 LIMIT 5"
    assert gen["tokens"] == 9


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


def test_run_one_full_reapplies_semantic_rewrite_before_scoring(monkeypatch):
    mod = _load_script_module(
        "scripts/nl2sql_bench_cq/run_cq_eval.py",
        "cq_run_eval_full_scoring_rewrite_test",
    )

    q = {
        "id": "TEST_FULL_REWRITE",
        "difficulty": "Easy",
        "category": "Aggregation",
        "question": "count rows",
        "golden_sql": "SELECT 1",
    }

    async def fake_full_generate(question):
        return {"status": "ok", "sql": "SELECT 1; AND invalid_tail", "error": None, "tokens": 0}

    calls = []

    def fake_execute_pg(sql, timeout_ms=60_000):
        calls.append(sql)
        if sql == "SELECT 1":
            return {"status": "ok", "rows": [(1,)]}
        return {"status": "error", "rows": None, "error": "raw sql reached scorer"}

    monkeypatch.setattr(mod, "full_generate", fake_full_generate)
    monkeypatch.setattr(mod, "_apply_full_semantic_rewrites", lambda question, sql: "SELECT 1")
    monkeypatch.setattr(mod, "execute_pg", fake_execute_pg)

    rec = asyncio.run(mod.run_one(q, "full"))

    assert rec["pred_sql"] == "SELECT 1"
    assert rec["ex"] == 1
    assert calls == ["SELECT 1", "SELECT 1"]


def test_baseline_family_aware_uses_configurable_litellm_timeout(monkeypatch):
    mod = _load_script_module(
        "scripts/nl2sql_bench_cq/run_cq_eval.py",
        "cq_run_eval_baseline_timeout_test",
    )

    class FakeLiteLlmModel:
        model = "ollama_chat/Gemma4:31b"
        _additional_args = {"extra_body": {"think": False}}

    calls = {}

    def fake_completion(**kwargs):
        calls["timeout"] = kwargs.get("timeout")
        calls["extra_body"] = kwargs.get("extra_body")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="SELECT 1"),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3),
        )

    monkeypatch.setenv("BASELINE_LITELLM_TIMEOUT", "240")
    monkeypatch.setattr(mod, "_init_runtime", lambda: None)
    monkeypatch.setattr(mod, "get_schema", lambda: "CREATE TABLE public.t (id integer);")
    monkeypatch.setattr(
        "data_agent.model_gateway.create_model",
        lambda name: FakeLiteLlmModel(),
    )
    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=fake_completion))

    result = mod.baseline_generate_family_aware("count rows", "gemma4-31b-host164")

    assert result["status"] == "ok"
    assert result["sql"] == "SELECT 1"
    assert result["tokens"] == 5
    assert calls == {"timeout": 240, "extra_body": {"think": False}}
