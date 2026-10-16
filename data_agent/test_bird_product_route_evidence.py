"""Offline evaluation records must retain the actual route and every question."""
import importlib
from unittest.mock import MagicMock

import pytest

from data_agent.nl2sql_route_policy import resolve_bird_query_policy


@pytest.fixture
def evaluator(monkeypatch):
    # Importing legacy benchmark helpers normally loads project credentials.
    # These tests need only mocked product/source boundaries.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_a, **_kw: None)
    return importlib.import_module("scripts.nl2sql_bench_bird.eval_product_source")


@pytest.mark.parametrize("unsupported", [False, True])
def test_record_preserves_product_policy_and_scores_unsupported_in_denominator(evaluator, monkeypatch, unsupported):
    policy = resolve_bird_query_policy({"GDA_NL2SQL_QUERY_PROFILE": "registered_ir_strict"}).evidence()
    query = {"status": "query", "semantic_entity": "sample"}
    ir = {"status": "unsupported" if unsupported else "compiled", "strict_contract": True,
          "query": query, "compiled_plan": {"compiled_statement": "SELECT :p"}}
    product = {"status": "unsupported" if unsupported else "ok", "sql": "" if unsupported else "SELECT :p",
               "sql_parameters": {"p": 7}, "query_policy": policy, "registered_ir": ir,
               "llm_calls": []}
    monkeypatch.setattr(evaluator, "registered_database", lambda *_: None)
    monkeypatch.setattr(evaluator, "run_nl2semantic2sql", lambda *_a, **_kw: evaluator.json.dumps(product))
    read = MagicMock(return_value=(["v"], [(7,)], False))
    monkeypatch.setattr(evaluator, "query_rows", read)
    runtime = MagicMock()
    runtime.execute.return_value = {"status": "ok", "rows": [(7,)], "sql": "SELECT 7"}
    record = evaluator.evaluate_one({"question_id": 1, "db_id": "sample", "question": "A measure", "SQL": "SELECT 7"}, runtime)
    assert record["query_policy"] == policy and record["registered_ir"] == ir
    assert record["correct"] == int(not unsupported)
    if unsupported:
        read.assert_not_called()
    else:
        read.assert_called_once_with("sample", "SELECT :p", parameters={"p": 7})
    report = evaluator.summarize([record])
    assert report["n"] == 1
    assert report["unsupported_count"] == int(unsupported)
    assert report["query_profiles"] == {"registered_ir_strict": 1}


def test_summary_distinguishes_compilation_fallback_and_refusal(evaluator):
    policy = resolve_bird_query_policy({"GDA_NL2SQL_QUERY_PROFILE": "registered_ir_strict"}).evidence()
    base = {"db_id": "sample", "difficulty": "simple", "prediction_status": "ok", "gold_status": "ok",
            "correct": 1, "failure_category": "correct", "product_status": "ok", "query_policy": policy}
    records = [dict(base, registered_ir={"status": "compiled"}),
               dict(base, query_policy={"profile": "configured"}, registered_ir={"status": "unsupported", "fallback": "existing_sql_generator"}),
               dict(base, correct=0, product_status="unsupported", prediction_status="unsupported", registered_ir={"status": "unsupported", "fallback": "blocked_by_policy"}),
               dict(base, correct=0, product_status="rejected", prediction_status="rejected", registered_ir={"status": "rejected"})]
    report = evaluator.summarize(records)
    assert report["n"] == 4 and report["correct"] == 2 and report["execution_accuracy"] == 0.5
    assert report["sql_fallback_count"] == report["unsupported_count"] == report["rejected_count"] == 1
    assert report["registered_ir_statuses"] == {"compiled": 1, "unsupported": 2, "rejected": 1}


def test_strict_compilation_evidence_failure_stops_but_wrong_answer_does_not(evaluator):
    settings = {"GDA_NL2SQL_QUERY_PROFILE": "registered_ir_strict"}
    policy = resolve_bird_query_policy(settings).evidence()
    manifest = {"settings": settings, "query_policy": policy}
    record = {"question_id": 1, "product_status": "ok", "query_policy": policy, "sql": "SELECT :p", "sql_parameters": {"p": 1},
              "failure_category": "wrong_result", "registered_ir": {
                  "status": "compiled", "strict_contract": True, "query": {"status": "query"},
                  "compiled_plan": {"compiled_statement": "SELECT :p", "parameter_bindings": {"p": 1}}}}
    assert evaluator.integration_fault(record, manifest) is None
    record["registered_ir"]["fallback"] = "existing_sql_generator"
    assert evaluator.integration_fault(record, manifest) == "query_route_contract"
