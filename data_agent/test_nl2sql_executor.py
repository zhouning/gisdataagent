"""Tests for nl2sql_executor tools."""
from unittest.mock import patch


def test_prepare_nl2sql_context_returns_prompt_and_caches_schema():
    from data_agent.nl2sql_executor import prepare_nl2sql_context, _cached_schemas

    payload = {
        "candidate_tables": [{
            "table_name": "cq_buildings_2021",
            "columns": [
                {"column_name": "Id", "needs_quoting": True},
                {"column_name": "Floor", "needs_quoting": True},
            ],
            "row_count_hint": 107035,
        }],
        "semantic_hints": {},
        "few_shots": [],
        "grounding_prompt": "PROMPT BLOCK",
    }
    with patch("data_agent.nl2sql_executor.build_nl2sql_context", return_value=payload):
        prompt = prepare_nl2sql_context("统计层高>=40")
    assert prompt == "PROMPT BLOCK"
    cached = _cached_schemas.get()
    assert "cq_buildings_2021" in cached
    assert cached["cq_buildings_2021"][0]["column_name"] == "Id"


def test_execute_nl2sql_rejected_returns_message():
    from data_agent.nl2sql_executor import execute_nl2sql
    class FakeResult:
        rejected = True
        reject_reason = "Only SELECT/WITH queries are allowed"
        sql = "DELETE FROM t"
    with patch("data_agent.nl2sql_executor.postprocess_sql", return_value=FakeResult()):
        result = execute_nl2sql("DELETE FROM t")
    assert "安全拒绝" in result


def test_execute_nl2sql_executes_corrected_sql():
    from data_agent.nl2sql_executor import execute_nl2sql
    class FakeResult:
        rejected = False
        reject_reason = ""
        sql = 'SELECT COUNT(*) FROM cq_buildings_2021 WHERE "Floor" >= 40'
    with patch("data_agent.nl2sql_executor.postprocess_sql", return_value=FakeResult()), \
         patch("data_agent.nl2sql_executor.execute_safe_sql", return_value='{"status":"ok","rows":1,"data":[{"count":123}],"message":"ok"}') as mock_exec:
        result = execute_nl2sql("SELECT count(*) FROM cq_buildings_2021 WHERE floor >= 40")
    mock_exec.assert_called_once_with('SELECT COUNT(*) FROM cq_buildings_2021 WHERE "Floor" >= 40')
    assert '"status":"ok"' in result
