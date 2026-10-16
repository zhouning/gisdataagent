"""Candidate selection must preserve source authorization and full-result equality."""
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from data_agent import nl2sql_candidates as candidates
from data_agent.user_context import (
    current_managed_agent_authorization, current_tenant_id, current_tool_categories,
    current_user_id, current_user_role, current_nl2sql_llm_calls,
    current_nl2sql_llm_evidence,
    current_nl2sql_schemas,
)


@pytest.fixture(autouse=True)
def isolated_context(monkeypatch):
    variables = [(current_user_id, "tester"), (current_user_role, "analyst"),
                 (current_tenant_id, "tenant"), (current_tool_categories, {"query"}),
                 (current_managed_agent_authorization, {"source_ids": [1]}),
                 (current_nl2sql_llm_calls, []), (current_nl2sql_llm_evidence, {}),
                 (current_nl2sql_schemas, {})]
    tokens = [(var, var.set(value)) for var, value in variables]
    for name in ("GDA_NL2SQL_EXECUTION_CONSENSUS", "GDA_NL2SQL_REGISTERED_IR",
                 "GDA_NL2SQL_ANSWER_PLAN", "GDA_NL2SQL_OUTPUT_CONTRACT",
                 "GDA_NL2SQL_RELATIONAL_REVIEW", "GDA_NL2SQL_VALUE_LINKING",
                 "GDA_NL2SQL_REFERENCE_RANGE_REPAIR"):
        monkeypatch.setenv(name, "0")
    yield
    for var, token in reversed(tokens):
        var.reset(token)


def fingerprint(rows, columns=None, truncated=False):
    return candidates.result_fingerprint(columns or ["value"], rows, truncated)


def product(index, status="ok"):
    return {"status": status, "sql": f"SELECT {index}", "execution": {"status": status},
            "llm_calls": [{"model": "local", "total_tokens": index + 1}]}


def test_exact_bag_keeps_duplicates_and_column_order_but_ignores_aliases():
    rows = [(1, "x"), (2, "y"), (1, "x")]
    digest = fingerprint(rows, ["a", "b"])
    assert digest == fingerprint(list(reversed(rows)), ["first", "second"])
    assert digest != fingerprint(rows[:-1], ["a", "b"])
    assert digest != fingerprint([(b, a) for a, b in rows], ["b", "a"])


def test_exact_numeric_equality_does_not_round_to_benchmark_precision():
    assert fingerprint([(1,)]) == fingerprint([(Decimal("1.000"),)]) == fingerprint([(1.0,)])
    assert fingerprint([(-0.0,)]) == fingerprint([(Decimal("0"),)])
    assert fingerprint([(Decimal("1.000001"),)]) != fingerprint([(Decimal("1.000002"),)])
    assert fingerprint([(True,)]) != fingerprint([(1,)])
    assert fingerprint([(None,)]) != fingerprint([("null",)])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), Decimal("NaN"), object()])
def test_unsupported_values_cannot_vote(value):
    with pytest.raises(ValueError):
        fingerprint([(value,)])


def test_empty_truncated_and_invalid_width_do_not_establish_agreement():
    assert fingerprint([]) is None
    assert fingerprint([(1,)], truncated=True) is None
    with pytest.raises(ValueError, match="width"):
        fingerprint([(1, 2)])


def test_majority_selects_earliest_supporter_and_collects_all_calls():
    run = MagicMock(side_effect=[product(i) for i in range(3)])
    read = MagicMock(side_effect=[(["v"], [(0,)], False), (["v"], [(1,)], False), (["other"], [(1,)], False)])
    result = candidates.run_product_candidates(run, read, MagicMock())
    assert result["sql"] == "SELECT 1"
    assert result["candidate_selection"]["decision"] == "execution_agreement"
    assert result["candidate_selection"]["selected_candidate_id"] == 1
    assert [c["candidate_id"] for c in result["llm_calls"]] == [0, 1, 2]
    assert not candidates.in_candidate_run()
    assert candidates.candidate_generation_hint() == ""


def test_no_majority_keeps_first_success_and_never_reads_rejected_candidate():
    run = MagicMock(side_effect=[product(0, "rejected"), product(1), product(2)])
    read = MagicMock(side_effect=[(["v"], [(1,)], False), (["v"], [(2,)], False)])
    result = candidates.run_product_candidates(run, read, MagicMock())
    assert result["sql"] == "SELECT 1"
    assert read.call_count == 2
    assert result["candidate_selection"]["decision"] == "first_successful_or_original"


def test_identical_previews_cannot_vote_when_complete_101st_rows_differ():
    products = [dict(product(i), execution={"status": "ok", "data": [{"v": n} for n in range(100)]}) for i in range(3)]
    rows = [[(n,) for n in range(100)] + [(100 + i,)] for i in range(3)]
    result = candidates.run_product_candidates(MagicMock(side_effect=products),
        MagicMock(side_effect=[(["v"], item, False) for item in rows]), MagicMock())
    assert result["candidate_selection"]["decision"] == "first_successful_or_original"
    assert all(entry["row_count"] == 101 for entry in result["candidate_selection"]["candidates"])
    assert len(result["candidate_selection"]["agreement_groups"]) == 3


def test_full_read_failure_cannot_supply_a_vote():
    read = MagicMock(side_effect=[RuntimeError("offline"), (["v"], [(1,)], False), (["v"], [(2,)], False)])
    result = candidates.run_product_candidates(MagicMock(side_effect=[product(i) for i in range(3)]), read, MagicMock())
    assert result["candidate_selection"]["selected_candidate_id"] == 0
    assert result["candidate_selection"]["candidates"][0]["verification_error_type"] == "RuntimeError"


def test_initial_authorization_denial_prevents_generation():
    run = MagicMock()
    with pytest.raises(PermissionError):
        candidates.run_product_candidates(run, MagicMock(), MagicMock(side_effect=PermissionError("denied")))
    run.assert_not_called()


@pytest.mark.parametrize("variable,value", [(current_user_id, "other"), (current_user_role, "admin"),
    (current_tenant_id, "other"), (current_tool_categories, {"admin"}),
    (current_managed_agent_authorization, {"source_ids": [2]})])
def test_principal_change_during_generation_rejects_all_buffered_results(variable, value):
    def generate():
        variable.set(value)
        return product(0)
    read = MagicMock()
    with pytest.raises(PermissionError, match="principal changed"):
        candidates.run_product_candidates(generate, read, MagicMock())
    read.assert_not_called()
    assert not candidates.in_candidate_run()


def test_mutating_managed_authorization_in_place_is_detected():
    def generate():
        current_managed_agent_authorization.get()["source_ids"].append(2)
        return product(0)
    with pytest.raises(PermissionError):
        candidates.run_product_candidates(generate, MagicMock(), MagicMock())


def test_permission_revocation_at_full_read_propagates():
    with pytest.raises(PermissionError):
        candidates.run_product_candidates(lambda: product(0), MagicMock(side_effect=PermissionError("revoked")), MagicMock())


def test_context_restores_on_generation_failure_and_nested_selection_is_rejected():
    def generate():
        assert candidates.in_candidate_run()
        with pytest.raises(ValueError, match="Nested"):
            candidates.run_product_candidates(MagicMock(), MagicMock(), MagicMock())
        raise RuntimeError("generation failed")
    with pytest.raises(RuntimeError):
        candidates.run_product_candidates(generate, MagicMock(), MagicMock())
    assert not candidates.in_candidate_run()


def test_policy_refusal_stops_generation_and_overrides_prior_success():
    refusal = {"status": "rejected", "error": "policy_refusal", "sql": ""}
    run = MagicMock(side_effect=[product(0), refusal, product(2)])
    result = candidates.run_product_candidates(run, lambda p: (["v"], [(0,)], False), MagicMock())
    assert result["status"] == "rejected"
    assert result["error"] == "policy_refusal"
    assert result["candidate_selection"]["decision"] == "policy_refusal"
    assert run.call_count == 2


def test_setting_defaults_off_and_invalid_setting_fails_closed(monkeypatch):
    monkeypatch.delenv("GDA_NL2SQL_EXECUTION_CONSENSUS")
    assert not candidates.candidates_enabled()
    monkeypatch.setenv("GDA_NL2SQL_EXECUTION_CONSENSUS", "yes")
    assert candidates.candidates_enabled()
    monkeypatch.setenv("GDA_NL2SQL_EXECUTION_CONSENSUS", "automatic")
    with pytest.raises(ValueError):
        candidates.candidates_enabled()
    from data_agent.nl2sql_executor import run_nl2semantic2sql
    with patch("data_agent.nl2sql_executor._generate_gemma_sql") as generate:
        assert json.loads(run_nl2semantic2sql("Names", bird_db_id="sample"))["status"] == "rejected"
    generate.assert_not_called()


@pytest.mark.parametrize("enabled,reject_first", [(False, False), (True, False), (True, True)])
def test_product_reuses_generation_postprocessor_runtime_guard_and_source_execution(monkeypatch, enabled, reject_first):
    from data_agent import nl2sql_executor as executor
    from data_agent.test_nl2sql_executor import _cq_context
    monkeypatch.setenv("NL2SQL_AGENT_FAMILY", "gemma")
    monkeypatch.setenv("GDA_NL2SQL_EXECUTION_CONSENSUS", str(int(enabled)))
    payload = _cq_context("cq_osm_roads_2021")
    payload.update(grounding_prompt="GROUNDING", few_shots=[], _hint_injection_stats={})
    prompts = []

    def generate(prompt):
        index = len(prompts)
        prompts.append(prompt)
        current_nl2sql_llm_calls.set([{"model": "local", "provider": "ollama", "total_tokens": 10}])
        return f"SELECT {index} FROM cq_osm_roads_2021"

    def execution(db_id, sql, *args, **kwargs):
        current_nl2sql_schemas.set({"selected_context": int(sql.split()[1])})
        return '{"status":"ok","rows":1}'

    class Processed:
        rejected = False
        reject_reason = ""
        corrections = []
        def __init__(self, sql):
            self.sql = sql

    with patch("data_agent.bird_source.registered_database", return_value="bird_sample"), \
         patch.object(executor, "build_nl2sql_context", side_effect=lambda *a, **kw: __import__('copy').deepcopy(payload)), \
         patch.object(executor, "_should_refuse_nl2sql_question", return_value=False), \
         patch.object(executor, "_generate_gemma_sql", side_effect=generate), \
         patch.object(executor, "apply_gemma_semantic_rewrites", side_effect=lambda q, s, p: (s, [])), \
         patch.object(executor, "postprocess_sql", side_effect=lambda s, *a, **kw: Processed(s)) as postprocess, \
         patch("data_agent.runtime_guards.is_safe_sql", side_effect=[(not reject_first, "test_denial"), (True, ""), (True, "")]) as guard, \
         patch.object(executor, "_postprocess_safe_preview_fallback", return_value=(None, "no_preview_fallback")), \
         patch("data_agent.bird_source.execute_bird_sql", side_effect=execution) as execute, \
         patch("data_agent.bird_source.query_rows", side_effect=[(["v"], [(0,)], False), (["v"], [(1,)], False), (["v"], [(1,)], False)]) as read:
        result = json.loads(executor.run_nl2semantic2sql("Show values", bird_db_id="sample"))
    count = 3 if enabled else 1
    assert postprocess.call_count == guard.call_count == count
    assert execute.call_count == count - int(reject_first)
    assert read.call_count == (3 - int(reject_first) if enabled else 0)
    assert result["status"] == "ok"
    assert len(result["llm_calls"]) == count
    assert current_nl2sql_schemas.get() == {"selected_context": 1 if enabled else 0}
    if enabled:
        assert result["candidate_selection"]["selected_candidate_id"] == 1
        assert "Independent generation focus" not in prompts[0]
        assert "Independent generation focus" in prompts[1]
        assert result["llm_usage"]["calls"] == 3
    else:
        assert "candidate_selection" not in result


def test_ir_and_candidates_cannot_be_enabled_together(monkeypatch):
    from data_agent import nl2sql_executor as executor
    monkeypatch.setenv("GDA_NL2SQL_EXECUTION_CONSENSUS", "1")
    monkeypatch.setenv("GDA_NL2SQL_REGISTERED_IR", "1")
    with patch.object(executor, "_generate_gemma_sql") as generate:
        result = json.loads(executor.run_nl2semantic2sql("Names", bird_db_id="sample"))
    assert result["status"] == "rejected"
    generate.assert_not_called()


def test_product_permission_failure_clears_buffered_model_evidence(monkeypatch):
    from data_agent import nl2sql_executor as executor
    monkeypatch.setenv("GDA_NL2SQL_EXECUTION_CONSENSUS", "1")
    def revoked(*args):
        current_nl2sql_llm_calls.set([{"prompt": "buffered private schema"}])
        current_nl2sql_llm_evidence.set({"prompt": "buffered private schema"})
        current_nl2sql_schemas.set({"private_context": 1})
        raise PermissionError("revoked")
    with patch.object(candidates, "run_product_candidates", side_effect=revoked):
        result = json.loads(executor.run_nl2semantic2sql("Names", bird_db_id="sample"))
    assert result["status"] == "rejected"
    assert "buffered private schema" not in json.dumps(result)
    assert current_nl2sql_llm_calls.get() == []
    assert current_nl2sql_llm_evidence.get() == {}
    assert current_nl2sql_schemas.get() == {}
