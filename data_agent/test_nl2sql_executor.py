"""Tests for nl2sql_executor tools."""
from unittest.mock import patch, MagicMock
import json


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
         patch("data_agent.nl2sql_executor.execute_safe_sql", return_value='{"status":"ok","rows":1,"data":[{"count":123}],"message":"ok"}') as mock_exec, \
         patch("data_agent.nl2sql_executor._auto_curate"):
        result = execute_nl2sql("SELECT count(*) FROM cq_buildings_2021 WHERE floor >= 40")
    mock_exec.assert_called_once_with('SELECT COUNT(*) FROM cq_buildings_2021 WHERE "Floor" >= 40')
    assert '"status":"ok"' in result


# --- Phase 2: self-correction tests ---


def test_execute_nl2sql_retries_on_failure():
    """First execution fails, LLM retry succeeds."""
    from data_agent.nl2sql_executor import execute_nl2sql, current_nl2sql_question

    current_nl2sql_question.set("test question")

    class FakeResult:
        rejected = False
        reject_reason = ""
        def __init__(self, sql):
            self.sql = sql

    call_count = [0]
    def fake_postprocess(sql, schemas, large_tables, **kwargs):
        return FakeResult(sql)

    def fake_execute(sql):
        call_count[0] += 1
        if call_count[0] == 1:
            return json.dumps({"status": "error", "error": 'column "dlmc" does not exist'})
        return json.dumps({"status": "ok", "rows": 1, "data": [{"count": 42}]})

    with patch("data_agent.nl2sql_executor.postprocess_sql", side_effect=fake_postprocess), \
         patch("data_agent.nl2sql_executor.execute_safe_sql", side_effect=fake_execute), \
         patch("data_agent.nl2sql_executor._retry_with_llm", return_value='SELECT COUNT(*) FROM t WHERE "DLMC" = \'x\''), \
         patch("data_agent.nl2sql_executor._auto_curate"):
        result = execute_nl2sql("SELECT COUNT(*) FROM t WHERE dlmc = 'x'")

    parsed = json.loads(result)
    assert parsed["status"] == "ok"
    assert call_count[0] == 2


def test_execute_nl2sql_max_retries_exceeded():
    """All retries fail, returns last error."""
    from data_agent.nl2sql_executor import execute_nl2sql, current_nl2sql_question

    current_nl2sql_question.set("test question")

    class FakeResult:
        rejected = False
        reject_reason = ""
        def __init__(self, sql):
            self.sql = sql

    error_json = json.dumps({"status": "error", "error": "persistent error"})

    with patch("data_agent.nl2sql_executor.postprocess_sql", side_effect=lambda s, *a, **kw: FakeResult(s)), \
         patch("data_agent.nl2sql_executor.execute_safe_sql", return_value=error_json), \
         patch("data_agent.nl2sql_executor._retry_with_llm", return_value="SELECT 1"):
        result = execute_nl2sql("SELECT bad_sql")

    parsed = json.loads(result)
    assert parsed["status"] == "error"


def test_execute_nl2sql_auto_curates_on_success():
    """Successful execution triggers auto-curate."""
    from data_agent.nl2sql_executor import execute_nl2sql, current_nl2sql_question

    current_nl2sql_question.set("count buildings")

    class FakeResult:
        rejected = False
        reject_reason = ""
        sql = "SELECT COUNT(*) FROM buildings"

    with patch("data_agent.nl2sql_executor.postprocess_sql", return_value=FakeResult()), \
         patch("data_agent.nl2sql_executor.execute_safe_sql", return_value='{"status":"ok","rows":1}'), \
         patch("data_agent.nl2sql_executor._auto_curate") as mock_curate:
        execute_nl2sql("SELECT COUNT(*) FROM buildings")

    mock_curate.assert_called_once_with("count buildings", "SELECT COUNT(*) FROM buildings")


def test_execute_nl2sql_skip_curate_on_reject():
    """Security rejection should not trigger auto-curate."""
    from data_agent.nl2sql_executor import execute_nl2sql

    class FakeResult:
        rejected = True
        reject_reason = "write operation"
        sql = "DELETE FROM t"

    with patch("data_agent.nl2sql_executor.postprocess_sql", return_value=FakeResult()), \
         patch("data_agent.nl2sql_executor._auto_curate") as mock_curate:
        execute_nl2sql("DELETE FROM t")

    mock_curate.assert_not_called()


def test_retry_with_llm_sets_timeout_and_retry_options():
    """Retry path should set explicit API timeout to avoid hanging the UI."""
    from data_agent.nl2sql_executor import _retry_with_llm

    mock_resp = MagicMock()
    mock_resp.text = 'SELECT 1'
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_resp

    with patch('google.genai.Client', return_value=mock_client):
        result = _retry_with_llm('q', 'bad sql', 'syntax error', {'t': []})

    assert result == 'SELECT 1'
    kwargs = mock_client.models.generate_content.call_args.kwargs
    config = kwargs['config']
    assert getattr(config, 'temperature', None) == 0.0
    assert getattr(config, 'http_options', None) is not None


def test_execute_nl2sql_no_retry_when_llm_returns_none():
    """If LLM retry returns None, return original error without further retries."""
    from data_agent.nl2sql_executor import execute_nl2sql, current_nl2sql_question

    current_nl2sql_question.set("test")

    class FakeResult:
        rejected = False
        reject_reason = ""
        def __init__(self, sql):
            self.sql = sql

    error_json = json.dumps({"status": "error", "error": "some error"})

    exec_calls = [0]
    def fake_exec(sql):
        exec_calls[0] += 1
        return error_json

    with patch("data_agent.nl2sql_executor.postprocess_sql", side_effect=lambda s, *a, **kw: FakeResult(s)), \
         patch("data_agent.nl2sql_executor.execute_safe_sql", side_effect=fake_exec), \
         patch("data_agent.nl2sql_executor._retry_with_llm", return_value=None):
        result = execute_nl2sql("SELECT bad")

    assert exec_calls[0] == 1


def test_prepare_nl2sql_context_caches_intent():
    from unittest.mock import patch
    from data_agent.nl2sql_intent import IntentLabel
    from data_agent import nl2sql_executor
    from data_agent.user_context import current_nl2sql_intent

    payload = {
        "candidate_tables": [],
        "intent": IntentLabel.KNN,
        "intent_source": "rule",
        "grounding_prompt": "...",
    }
    with patch("data_agent.nl2sql_executor.build_nl2sql_context", return_value=payload):
        nl2sql_executor.prepare_nl2sql_context("问题")
    assert current_nl2sql_intent.get() is IntentLabel.KNN

