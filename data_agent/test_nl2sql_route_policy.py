"""Route preflight must fail before paid work on contradictory settings."""
import pytest

from data_agent.nl2sql_route_policy import (
    QueryPolicyError, resolve_bird_query_policy, validate_evaluation_profile,
)


def test_default_preserves_configured_sql_and_strict_profile_owns_its_flags():
    assert resolve_bird_query_policy({}).route == "sql"
    policy = resolve_bird_query_policy({"GDA_NL2SQL_QUERY_PROFILE": "registered_ir_strict"})
    assert policy.route == "registered_ir"
    assert policy.strict_contract and not policy.allow_sql_fallback


@pytest.mark.parametrize("flag,value", [
    ("GDA_NL2SQL_REGISTERED_IR", "0"),
    ("GDA_NL2SQL_REGISTERED_IR_EXPLICIT_OPERATIONS", "0"),
    ("GDA_NL2SQL_REGISTERED_IR_CATALOG_SCHEMA", "0"),
    ("GDA_NL2SQL_REGISTERED_IR_COMPACT_CATALOG", "0"),
    ("GDA_NL2SQL_TYPED_BINDINGS", "1"),
    ("GDA_NL2SQL_EXECUTION_CONSENSUS", "1"),
    ("GDA_NL2SQL_REGISTERED_IR", "invalid"),
])
def test_strict_conflicts_rejected(flag, value):
    with pytest.raises(QueryPolicyError):
        resolve_bird_query_policy({"GDA_NL2SQL_QUERY_PROFILE": "registered_ir_strict", flag: value})


def test_frozen_evaluation_profile_must_match_requested_route():
    with pytest.raises(QueryPolicyError):
        validate_evaluation_profile({}, "registered_ir_strict")
    assert validate_evaluation_profile({}, "configured")["route"] == "sql"


def test_product_policy_rejection_clears_previous_model_calls(monkeypatch):
    from data_agent import nl2sql_executor as executor
    import json
    from unittest.mock import patch

    monkeypatch.setenv("GDA_NL2SQL_QUERY_PROFILE", "registered_ir_strict")
    monkeypatch.setenv("GDA_NL2SQL_EXECUTION_CONSENSUS", "1")
    token = executor.current_nl2sql_llm_calls.set([{"model": "previous"}])
    try:
        with patch.object(executor, "_run_nl2semantic2sql") as run:
            result = json.loads(executor.run_nl2semantic2sql("Show names", bird_db_id="sample"))
        run.assert_not_called()
        assert result["status"] == "rejected" and result["llm_calls"] == []
    finally:
        executor.current_nl2sql_llm_calls.reset(token)
