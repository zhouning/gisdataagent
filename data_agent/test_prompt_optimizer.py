"""Tests for prompt_optimizer module — BadCaseCollector, FailureAnalyzer, PromptOptimizer."""
import json
from unittest.mock import patch, MagicMock
from datetime import datetime

from data_agent.conftest import run_async


# ---------------------------------------------------------------------------
# BadCaseCollector tests
# ---------------------------------------------------------------------------

def test_collect_from_eval_history_returns_low_scores():
    """BadCaseCollector should return eval runs below min_score."""
    from data_agent.prompt_optimizer import BadCaseCollector

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_rows = [
        (1, "run_abc", "optimization", "gemini-2.0-flash", 0.3, 0.2, "FAIL",
         json.dumps({"error": "bad output"}), datetime(2026, 4, 1)),
        (2, "run_def", "general", "gemini-2.5-flash", 0.1, 0.0, "FAIL",
         json.dumps({}), datetime(2026, 4, 2)),
    ]
    mock_conn.execute.return_value.fetchall.return_value = mock_rows
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("data_agent.prompt_optimizer.get_engine", return_value=mock_engine):
        collector = BadCaseCollector()
        cases = run_async(collector.collect_from_eval_history(min_score=0.5, limit=10))

    assert len(cases) == 2
    assert cases[0]["source"] == "eval_history"
    assert cases[0]["score"] == 0.3
    assert cases[0]["run_id"] == "run_abc"
    assert cases[1]["score"] == 0.1


def test_collect_from_eval_history_db_unavailable():
    """Should return empty list when DB is unavailable."""
    from data_agent.prompt_optimizer import BadCaseCollector

    with patch("data_agent.prompt_optimizer.get_engine", return_value=None):
        collector = BadCaseCollector()
        cases = run_async(collector.collect_from_eval_history())

    assert cases == []


def test_collect_from_pipeline_failures():
    """BadCaseCollector should return pipeline failure audit entries."""
    from data_agent.prompt_optimizer import BadCaseCollector

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_rows = [
        (10, "user1", {"pipeline_type": "optimization", "error": "timeout"},
         datetime(2026, 4, 3)),
    ]
    mock_conn.execute.return_value.fetchall.return_value = mock_rows
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("data_agent.prompt_optimizer.get_engine", return_value=mock_engine):
        collector = BadCaseCollector()
        cases = run_async(collector.collect_from_pipeline_failures(days=7, limit=10))

    assert len(cases) == 1
    assert cases[0]["source"] == "pipeline_failure"
    assert cases[0]["username"] == "user1"
    assert cases[0]["details"]["error"] == "timeout"


def test_collect_from_pipeline_failures_db_unavailable():
    """Should return empty list when DB is unavailable."""
    from data_agent.prompt_optimizer import BadCaseCollector

    with patch("data_agent.prompt_optimizer.get_engine", return_value=None):
        collector = BadCaseCollector()
        cases = run_async(collector.collect_from_pipeline_failures())

    assert cases == []


def test_collect_from_user_feedback():
    """BadCaseCollector should return low-rated feedback."""
    from data_agent.prompt_optimizer import BadCaseCollector

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_rows = [
        (20, "user2", {"rating": 1, "comment": "bad result"}, datetime(2026, 4, 2)),
    ]
    mock_conn.execute.return_value.fetchall.return_value = mock_rows
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("data_agent.prompt_optimizer.get_engine", return_value=mock_engine):
        collector = BadCaseCollector()
        cases = run_async(collector.collect_from_user_feedback(min_rating=2, limit=10))

    assert len(cases) == 1
    assert cases[0]["source"] == "user_feedback"
    assert cases[0]["details"]["rating"] == 1


def test_collect_from_user_feedback_db_unavailable():
    """Should return empty list when DB is unavailable."""
    from data_agent.prompt_optimizer import BadCaseCollector

    with patch("data_agent.prompt_optimizer.get_engine", return_value=None):
        collector = BadCaseCollector()
        cases = run_async(collector.collect_from_user_feedback())

    assert cases == []


def test_collect_all_aggregates_sources():
    """collect_all should aggregate from all three sources."""
    from data_agent.prompt_optimizer import BadCaseCollector

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    call_count = 0

    def fake_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.fetchall.return_value = [
                (1, "r1", "opt", "m1", 0.2, 0.1, "FAIL", "{}", datetime(2026, 4, 1)),
            ]
        elif call_count == 2:
            result.fetchall.return_value = [
                (10, "u1", {"err": "x"}, datetime(2026, 4, 2)),
            ]
        else:
            result.fetchall.return_value = [
                (20, "u2", {"rating": 1}, datetime(2026, 4, 3)),
            ]
        return result

    mock_conn.execute.side_effect = fake_execute
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("data_agent.prompt_optimizer.get_engine", return_value=mock_engine):
        collector = BadCaseCollector()
        all_cases = run_async(collector.collect_all())

    assert len(all_cases) == 3
    sources = {c["source"] for c in all_cases}
    assert sources == {"eval_history", "pipeline_failure", "user_feedback"}


# ---------------------------------------------------------------------------
# FailureAnalyzer tests
# ---------------------------------------------------------------------------

def test_failure_analyzer_empty_cases():
    """FailureAnalyzer should return empty structure for no cases."""
    from data_agent.prompt_optimizer import FailureAnalyzer

    analyzer = FailureAnalyzer()
    result = run_async(analyzer.analyze([]))

    assert result["patterns"] == []
    assert result["root_causes"] == []
    assert result["affected_prompts"] == []


def test_failure_analyzer_with_llm():
    """FailureAnalyzer should call LLM and parse response."""
    from data_agent.prompt_optimizer import FailureAnalyzer

    llm_response = json.dumps({
        "patterns": [
            {
                "category": "timeout",
                "description": "Multiple timeout errors on large datasets",
                "frequency": 3,
                "examples": ["dataset > 1GB caused timeout"],
            }
        ],
        "root_causes": ["No timeout handling in data processing prompt"],
        "affected_prompts": ["optimization/data_processing"],
    })

    mock_genai_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = llm_response
    mock_genai_client.models.generate_content.return_value = mock_resp

    bad_cases = [
        {"source": "eval_history", "pipeline": "optimization", "score": 0.2,
         "details": {"error": "timeout"}},
        {"source": "pipeline_failure", "details": {"error": "timeout"}},
    ]

    with patch("data_agent.prompt_optimizer._get_genai_client", return_value=mock_genai_client):
        analyzer = FailureAnalyzer()
        result = run_async(analyzer.analyze(bad_cases))

    assert len(result["patterns"]) == 1
    assert result["patterns"][0]["category"] == "timeout"
    assert result["root_causes"] == ["No timeout handling in data processing prompt"]
    assert result["affected_prompts"] == ["optimization/data_processing"]


def test_failure_analyzer_llm_failure_fallback():
    """FailureAnalyzer should fall back to statistical analysis when LLM fails."""
    from data_agent.prompt_optimizer import FailureAnalyzer

    bad_cases = [
        {"source": "eval_history", "pipeline": "optimization", "score": 0.2},
        {"source": "eval_history", "pipeline": "general", "score": 0.3},
        {"source": "pipeline_failure", "details": {}},
    ]

    with patch("data_agent.prompt_optimizer._get_genai_client", side_effect=Exception("API unavailable")):
        analyzer = FailureAnalyzer()
        result = run_async(analyzer.analyze(bad_cases))

    assert len(result["patterns"]) == 2
    categories = {p["category"] for p in result["patterns"]}
    assert "eval_history" in categories
    assert "pipeline_failure" in categories
    assert any("LLM analysis unavailable" in rc for rc in result["root_causes"])


# ---------------------------------------------------------------------------
# PromptOptimizer tests
# ---------------------------------------------------------------------------

def test_suggest_improvements_with_llm():
    """PromptOptimizer should generate improvement suggestion via LLM."""
    from data_agent.prompt_optimizer import PromptOptimizer

    llm_response = json.dumps({
        "suggested_prompt": "Improved prompt text with guardrails",
        "changes": ["Added timeout handling instruction", "Clarified output format"],
        "expected_improvement": "Should reduce timeout failures by 50%",
    })

    mock_genai_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = llm_response
    mock_genai_client.models.generate_content.return_value = mock_resp

    failure_analysis = {
        "patterns": [{"category": "timeout", "description": "timeout errors", "frequency": 3}],
        "root_causes": ["Missing timeout guidance"],
    }

    # Mock the prompt registry to return an original prompt
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = ("Original prompt text",)
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("data_agent.prompt_registry.get_engine", return_value=mock_engine), \
         patch("data_agent.prompt_optimizer._get_genai_client", return_value=mock_genai_client):
        optimizer = PromptOptimizer()
        result = run_async(optimizer.suggest_improvements(
            "optimization", "data_processing", failure_analysis,
        ))

    assert result["original_prompt"] == "Original prompt text"
    assert result["suggested_prompt"] == "Improved prompt text with guardrails"
    assert len(result["changes"]) == 2
    assert "timeout" in result["expected_improvement"].lower()


def test_suggest_improvements_no_original_prompt():
    """PromptOptimizer should handle missing original prompt gracefully."""
    from data_agent.prompt_optimizer import PromptOptimizer

    with patch("data_agent.prompt_registry.get_engine", return_value=None), \
         patch("data_agent.prompts.load_prompts", side_effect=Exception("not found")):
        optimizer = PromptOptimizer()
        result = run_async(optimizer.suggest_improvements("missing", "key", {}))

    assert result["original_prompt"] == ""
    assert result["suggested_prompt"] == ""
    assert "Cannot optimize" in result["expected_improvement"]


def test_apply_suggestion_success():
    """PromptOptimizer.apply_suggestion should create a new prompt version."""
    from data_agent.prompt_optimizer import PromptOptimizer

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    call_count = 0

    def fake_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar.return_value = 2
        else:
            result.scalar.return_value = 42
        return result

    mock_conn.execute.side_effect = fake_execute
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("data_agent.prompt_registry.get_engine", return_value=mock_engine):
        optimizer = PromptOptimizer()
        result = run_async(optimizer.apply_suggestion(
            "optimization", "data_processing",
            "Improved prompt text", environment="dev",
        ))

    assert result["status"] == "created"
    assert result["version_id"] == 42
    assert result["environment"] == "dev"


def test_apply_suggestion_db_unavailable():
    """apply_suggestion should report error when DB unavailable."""
    from data_agent.prompt_optimizer import PromptOptimizer

    with patch("data_agent.prompt_registry.get_engine", return_value=None):
        optimizer = PromptOptimizer()
        result = run_async(optimizer.apply_suggestion(
            "optimization", "key", "prompt text",
        ))

    assert result["status"] == "error"
    assert result["version_id"] is None


# ---------------------------------------------------------------------------
# REST endpoint tests
# ---------------------------------------------------------------------------

def test_api_collect_bad_cases_unauthorized():
    """Endpoint should return 401 for unauthenticated requests."""
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.routing import Route
    from data_agent.frontend_api import _api_prompts_collect_bad_cases

    app = Starlette(routes=[
        Route("/api/prompts/collect-bad-cases", endpoint=_api_prompts_collect_bad_cases, methods=["POST"]),
    ])
    client = TestClient(app)

    with patch("data_agent.frontend_api._get_user_from_request", return_value=None):
        resp = client.post("/api/prompts/collect-bad-cases", json={})

    assert resp.status_code == 401


def test_api_analyze_failures_missing_body():
    """Endpoint should return 400 when bad_cases not provided."""
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.routing import Route
    from data_agent.frontend_api import _api_prompts_analyze_failures

    app = Starlette(routes=[
        Route("/api/prompts/analyze-failures", endpoint=_api_prompts_analyze_failures, methods=["POST"]),
    ])
    client = TestClient(app)

    mock_user = MagicMock()
    mock_user.identifier = "test_user"
    mock_user.metadata = {"role": "admin"}

    with patch("data_agent.frontend_api._get_user_from_request", return_value=mock_user):
        resp = client.post("/api/prompts/analyze-failures", json={})

    assert resp.status_code == 400
    assert "bad_cases required" in resp.json()["error"]


def test_api_optimize_missing_params():
    """Endpoint should return 400 when domain/prompt_key missing."""
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.routing import Route
    from data_agent.frontend_api import _api_prompts_optimize

    app = Starlette(routes=[
        Route("/api/prompts/optimize", endpoint=_api_prompts_optimize, methods=["POST"]),
    ])
    client = TestClient(app)

    mock_user = MagicMock()
    mock_user.identifier = "test_user"
    mock_user.metadata = {"role": "admin"}

    with patch("data_agent.frontend_api._get_user_from_request", return_value=mock_user):
        resp = client.post("/api/prompts/optimize", json={"domain": "general"})

    assert resp.status_code == 400
    assert "prompt_key required" in resp.json()["error"]


def test_api_apply_suggestion_missing_params():
    """Endpoint should return 400 when required params missing."""
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.routing import Route
    from data_agent.frontend_api import _api_prompts_apply_suggestion

    app = Starlette(routes=[
        Route("/api/prompts/apply-suggestion", endpoint=_api_prompts_apply_suggestion, methods=["POST"]),
    ])
    client = TestClient(app)

    mock_user = MagicMock()
    mock_user.identifier = "test_user"
    mock_user.metadata = {"role": "admin"}

    with patch("data_agent.frontend_api._get_user_from_request", return_value=mock_user):
        resp = client.post("/api/prompts/apply-suggestion", json={
            "domain": "general", "prompt_key": "test",
        })

    assert resp.status_code == 400
    assert "suggested_prompt required" in resp.json()["error"]


def test_collect_from_eval_history_db_exception():
    """BadCaseCollector should gracefully handle DB query exceptions."""
    from data_agent.prompt_optimizer import BadCaseCollector

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = Exception("connection lost")
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("data_agent.prompt_optimizer.get_engine", return_value=mock_engine):
        collector = BadCaseCollector()
        cases = run_async(collector.collect_from_eval_history())

    assert cases == []


def test_failure_analyzer_llm_returns_markdown_fenced_json():
    """FailureAnalyzer should strip markdown code fences from LLM response."""
    from data_agent.prompt_optimizer import FailureAnalyzer

    llm_response = '```json\n' + json.dumps({
        "patterns": [{"category": "format", "description": "x", "frequency": 1, "examples": []}],
        "root_causes": ["bad format"],
        "affected_prompts": [],
    }) + '\n```'

    mock_genai_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = llm_response
    mock_genai_client.models.generate_content.return_value = mock_resp

    bad_cases = [{"source": "eval_history", "score": 0.1, "details": {}}]

    with patch("data_agent.prompt_optimizer._get_genai_client", return_value=mock_genai_client):
        analyzer = FailureAnalyzer()
        result = run_async(analyzer.analyze(bad_cases))

    assert result["patterns"][0]["category"] == "format"
    assert result["root_causes"] == ["bad format"]
