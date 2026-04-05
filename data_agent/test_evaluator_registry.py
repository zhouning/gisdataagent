"""
Tests for Evaluator Registry — 15 built-in evaluators + registry operations + REST endpoints.
"""
import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from data_agent.evaluator_registry import (
    BaseEvaluator,
    EvaluatorRegistry,
    ExactMatchEvaluator,
    RegexMatchEvaluator,
    JsonSchemaEvaluator,
    CompletenessEvaluator,
    CoherenceEvaluator,
    SafetyEvaluator,
    PiiDetectionEvaluator,
    SqlInjectionEvaluator,
    LatencyEvaluator,
    TokenCostEvaluator,
    OutputLengthEvaluator,
    ToolCallAccuracyEvaluator,
    NumericAccuracyEvaluator,
    GeoSpatialAccuracyEvaluator,
    InstructionFollowingEvaluator,
)


# ===========================================================================
# Registry CRUD tests
# ===========================================================================

class TestRegistryCRUD:
    def test_list_all_evaluators(self):
        all_evals = EvaluatorRegistry.list_evaluators()
        assert len(all_evals) >= 15
        names = [e["name"] for e in all_evals]
        assert "exact_match" in names
        assert "safety" in names
        assert "geospatial_accuracy" in names

    def test_list_by_category(self):
        quality = EvaluatorRegistry.list_evaluators(category="quality")
        assert len(quality) == 5
        assert all(e["category"] == "quality" for e in quality)

        safety = EvaluatorRegistry.list_evaluators(category="safety")
        assert len(safety) == 3

        perf = EvaluatorRegistry.list_evaluators(category="performance")
        assert len(perf) == 3

        accuracy = EvaluatorRegistry.list_evaluators(category="accuracy")
        assert len(accuracy) == 4

    def test_get_existing(self):
        ev = EvaluatorRegistry.get("exact_match")
        assert isinstance(ev, ExactMatchEvaluator)
        assert ev.name == "exact_match"

    def test_get_not_found(self):
        with pytest.raises(KeyError, match="not_a_real_evaluator"):
            EvaluatorRegistry.get("not_a_real_evaluator")

    def test_register_custom(self):
        class CustomEval(BaseEvaluator):
            name = "_test_custom_eval"
            category = "quality"
            description = "Test only"
            def evaluate(self, input_text, output_text, expected_output=None, **ctx):
                return {"score": 1.0, "passed": True, "details": {}}

        EvaluatorRegistry.register(CustomEval())
        ev = EvaluatorRegistry.get("_test_custom_eval")
        assert ev.name == "_test_custom_eval"
        # Clean up
        del EvaluatorRegistry._evaluators["_test_custom_eval"]


# ===========================================================================
# Individual evaluator tests (15)
# ===========================================================================

class TestExactMatch:
    def test_exact_match_pass(self):
        ev = ExactMatchEvaluator()
        r = ev.evaluate("q", "hello world", expected_output="hello world")
        assert r["score"] == 1.0
        assert r["passed"] is True

    def test_exact_match_fail(self):
        ev = ExactMatchEvaluator()
        r = ev.evaluate("q", "hello world", expected_output="Hello World")
        assert r["score"] == 0.0
        assert r["passed"] is False

    def test_exact_match_no_expected(self):
        r = ExactMatchEvaluator().evaluate("q", "hello")
        assert r["passed"] is False


class TestRegexMatch:
    def test_pattern_match(self):
        ev = RegexMatchEvaluator()
        r = ev.evaluate("q", "result: 42", pattern=r"\d+")
        assert r["passed"] is True

    def test_pattern_no_match(self):
        r = RegexMatchEvaluator().evaluate("q", "no numbers here", pattern=r"^\d+$")
        assert r["passed"] is False

    def test_invalid_regex(self):
        r = RegexMatchEvaluator().evaluate("q", "text", pattern=r"[invalid")
        assert r["passed"] is False
        assert "Invalid regex" in r["details"]["reason"]


class TestJsonSchema:
    def test_valid_json(self):
        r = JsonSchemaEvaluator().evaluate("q", '{"key": "value"}')
        assert r["passed"] is True
        assert r["score"] == 1.0

    def test_invalid_json(self):
        r = JsonSchemaEvaluator().evaluate("q", "not json at all")
        assert r["passed"] is False

    def test_schema_check_pass(self):
        schema = {"required_keys": ["name", "value"]}
        r = JsonSchemaEvaluator().evaluate("q", '{"name": "a", "value": 1}', schema=schema)
        assert r["passed"] is True

    def test_schema_check_missing_keys(self):
        schema = {"required_keys": ["name", "value", "extra"]}
        r = JsonSchemaEvaluator().evaluate("q", '{"name": "a"}', schema=schema)
        assert r["passed"] is False
        assert "value" in r["details"]["missing_keys"]


class TestCompleteness:
    def test_complete_output(self):
        r = CompletenessEvaluator().evaluate(
            "Explain the temperature and precipitation in Shanghai",
            "The temperature in Shanghai averages 16C. Precipitation is about 1200mm annually."
        )
        assert r["score"] > 0.5
        assert r["passed"] is True

    def test_incomplete_output(self):
        r = CompletenessEvaluator().evaluate(
            "Discuss temperature and precipitation patterns",
            "Hello, how are you?",
            required_terms=["temperature", "precipitation"]
        )
        assert r["passed"] is False


class TestCoherence:
    def test_coherent_output(self):
        r = CoherenceEvaluator().evaluate("q", "The sky is blue and the grass is green.")
        assert r["passed"] is True
        assert r["score"] == 1.0

    def test_contradiction_detected(self):
        r = CoherenceEvaluator().evaluate("q", "The value increased significantly but also decreased.")
        assert r["passed"] is False
        assert len(r["details"]["issues"]) > 0

    def test_empty_output(self):
        r = CoherenceEvaluator().evaluate("q", "")
        assert r["passed"] is False
        assert "empty output" in r["details"]["issues"]


class TestSafety:
    def test_safe_output(self):
        r = SafetyEvaluator().evaluate("q", "Here is a summary of the geospatial analysis.")
        assert r["passed"] is True

    def test_unsafe_output(self):
        r = SafetyEvaluator().evaluate("q", "DROP TABLE users; --")
        assert r["passed"] is False

    def test_leaked_secrets(self):
        r = SafetyEvaluator().evaluate("q", "api_key = sk-12345abc")
        assert r["passed"] is False


class TestPiiDetection:
    def test_no_pii(self):
        r = PiiDetectionEvaluator().evaluate("q", "The parcel area is 500 sqm.")
        assert r["passed"] is True

    def test_email_detected(self):
        r = PiiDetectionEvaluator().evaluate("q", "Contact john@example.com for details.")
        assert r["passed"] is False
        assert "email" in r["details"]["pii_found"]

    def test_phone_detected(self):
        r = PiiDetectionEvaluator().evaluate("q", "Call 13812345678 for info.")
        assert r["passed"] is False
        assert "phone" in r["details"]["pii_found"]

    def test_id_card_detected(self):
        r = PiiDetectionEvaluator().evaluate("q", "ID: 310101199001011234")
        assert r["passed"] is False
        assert "id_card" in r["details"]["pii_found"]


class TestSqlInjection:
    def test_clean_output(self):
        r = SqlInjectionEvaluator().evaluate("q", "SELECT name FROM parcels WHERE id = 1")
        assert r["passed"] is True

    def test_union_injection(self):
        r = SqlInjectionEvaluator().evaluate("q", "UNION SELECT password FROM users")
        assert r["passed"] is False

    def test_stacked_query(self):
        r = SqlInjectionEvaluator().evaluate("q", "1; DROP TABLE users;")
        assert r["passed"] is False


class TestLatency:
    def test_within_threshold(self):
        r = LatencyEvaluator().evaluate("q", "output", latency_ms=1000, threshold_ms=5000)
        assert r["passed"] is True
        assert r["score"] == 1.0

    def test_exceeds_threshold(self):
        r = LatencyEvaluator().evaluate("q", "output", latency_ms=10000, threshold_ms=5000)
        assert r["passed"] is False
        assert r["score"] < 1.0

    def test_no_latency_provided(self):
        r = LatencyEvaluator().evaluate("q", "output")
        assert r["passed"] is False


class TestTokenCost:
    def test_within_budget(self):
        r = TokenCostEvaluator().evaluate("q", "short output", tokens_used=100, token_budget=4096)
        assert r["passed"] is True

    def test_exceeds_budget(self):
        r = TokenCostEvaluator().evaluate("q", "output", tokens_used=5000, token_budget=4096)
        assert r["passed"] is False

    def test_auto_estimate(self):
        r = TokenCostEvaluator().evaluate("q", "x" * 200, token_budget=100)
        # 200 chars ~ 50 tokens, within budget of 100
        assert r["passed"] is True


class TestOutputLength:
    def test_within_range(self):
        r = OutputLengthEvaluator().evaluate("q", "Hello world", min_chars=1, max_chars=100)
        assert r["passed"] is True

    def test_too_short(self):
        r = OutputLengthEvaluator().evaluate("q", "", min_chars=10, max_chars=100)
        assert r["passed"] is False

    def test_too_long(self):
        r = OutputLengthEvaluator().evaluate("q", "x" * 200, min_chars=1, max_chars=50)
        assert r["passed"] is False


class TestToolCallAccuracy:
    def test_all_correct(self):
        r = ToolCallAccuracyEvaluator().evaluate(
            "q", "output",
            expected_tools=["explore_data", "plot_chart"],
            actual_tools=["explore_data", "plot_chart"]
        )
        assert r["passed"] is True
        assert r["score"] == 1.0

    def test_missing_tools(self):
        r = ToolCallAccuracyEvaluator().evaluate(
            "q", "output",
            expected_tools=["explore_data", "plot_chart"],
            actual_tools=["explore_data"]
        )
        assert r["passed"] is False
        assert "plot_chart" in r["details"]["missing"]

    def test_no_expected_tools(self):
        r = ToolCallAccuracyEvaluator().evaluate("q", "output")
        assert r["passed"] is True


class TestNumericAccuracy:
    def test_exact_match(self):
        r = NumericAccuracyEvaluator().evaluate(
            "q", "The area is 42.0 hectares",
            expected_value=42.0, actual_value=42.0
        )
        assert r["passed"] is True
        assert r["score"] == 1.0

    def test_within_tolerance(self):
        r = NumericAccuracyEvaluator().evaluate(
            "q", "Area: 42.3",
            expected_value=42.0, actual_value=42.3, tolerance=0.01
        )
        assert r["passed"] is True

    def test_outside_tolerance(self):
        r = NumericAccuracyEvaluator().evaluate(
            "q", "Area: 50",
            expected_value=42.0, actual_value=50.0, tolerance=0.01
        )
        assert r["passed"] is False

    def test_auto_extract_from_text(self):
        r = NumericAccuracyEvaluator().evaluate(
            "q", "The value is 3.14", expected_output="3.14", tolerance=0.01
        )
        assert r["passed"] is True


class TestGeoSpatialAccuracy:
    def test_valid_point(self):
        geojson = json.dumps({
            "type": "Point",
            "coordinates": [121.47, 31.23]
        })
        r = GeoSpatialAccuracyEvaluator().evaluate("q", geojson)
        assert r["passed"] is True
        assert r["score"] == 1.0

    def test_valid_feature_collection(self):
        geojson = json.dumps({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [121.47, 31.23]},
                "properties": {"name": "Shanghai"}
            }]
        })
        r = GeoSpatialAccuracyEvaluator().evaluate("q", geojson)
        assert r["passed"] is True

    def test_invalid_coordinates(self):
        geojson = json.dumps({
            "type": "Point",
            "coordinates": [999, 999]
        })
        r = GeoSpatialAccuracyEvaluator().evaluate("q", geojson)
        assert r["passed"] is False
        assert any("out of valid range" in i for i in r["details"]["issues"])

    def test_not_json(self):
        r = GeoSpatialAccuracyEvaluator().evaluate("q", "not json")
        assert r["passed"] is False


class TestInstructionFollowing:
    def test_json_format_match(self):
        r = InstructionFollowingEvaluator().evaluate(
            "Return result as json", '{"result": 42}',
            expected_format="json"
        )
        assert r["passed"] is True

    def test_json_format_mismatch(self):
        r = InstructionFollowingEvaluator().evaluate(
            "Return result as json", "not json at all",
            expected_format="json"
        )
        assert r["passed"] is False

    def test_markdown_format(self):
        r = InstructionFollowingEvaluator().evaluate(
            "Use markdown", "# Title\n\n- item 1\n- item 2",
            expected_format="markdown"
        )
        assert r["passed"] is True

    def test_no_format_required(self):
        r = InstructionFollowingEvaluator().evaluate("just a question", "answer")
        assert r["passed"] is True


# ===========================================================================
# Batch evaluation test
# ===========================================================================

class TestBatchEvaluation:
    def test_run_multiple_evaluators(self):
        test_cases = [
            {
                "input": "What is 2+2?",
                "output": "The answer is 4",
                "expected_output": "The answer is 4",
            },
            {
                "input": "What is 3+3?",
                "output": "The answer is 6",
                "expected_output": "The answer is 6",
            },
        ]
        result = EvaluatorRegistry.run_evaluation(
            ["exact_match", "output_length", "coherence"],
            test_cases
        )
        assert result["summary"]["total_cases"] == 2
        assert result["summary"]["evaluators_run"] == 3
        assert "exact_match" in result["summary"]["avg_scores"]
        assert len(result["results"]) == 2

    def test_run_with_nonexistent_evaluator(self):
        with pytest.raises(KeyError):
            EvaluatorRegistry.run_evaluation(["nonexistent"], [{"input": "", "output": ""}])


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_empty_input_output(self):
        ev = ExactMatchEvaluator()
        r = ev.evaluate("", "", expected_output="")
        assert r["passed"] is True

    def test_unicode_content(self):
        ev = ExactMatchEvaluator()
        r = ev.evaluate("q", "上海市浦东新区", expected_output="上海市浦东新区")
        assert r["passed"] is True

    def test_very_long_output(self):
        ev = OutputLengthEvaluator()
        r = ev.evaluate("q", "x" * 100000, max_chars=50000)
        assert r["passed"] is False

    def test_malformed_json_in_geospatial(self):
        ev = GeoSpatialAccuracyEvaluator()
        r = ev.evaluate("q", '{"type": "Invalid", "coordinates": [1,2]}')
        assert r["passed"] is False

    def test_evaluator_metadata(self):
        ev = SafetyEvaluator()
        meta = ev.metadata()
        assert meta["name"] == "safety"
        assert meta["category"] == "safety"
        assert len(meta["description"]) > 0


# ===========================================================================
# REST endpoint tests
# ===========================================================================

def _run_async(coro):
    """Run an async coroutine safely, creating a new event loop if needed."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _make_request(query_params=None, body=None):
    """Create a mock Starlette Request."""
    req = MagicMock()
    req.query_params = query_params or {}
    req.cookies = {"access_token": "test_token"}
    if body is not None:
        req.json = AsyncMock(return_value=body)
    return req


class TestEvalEndpoints:
    """Test REST API endpoints for evaluator registry."""

    @patch("data_agent.frontend_api._get_user_from_request", return_value="test_user")
    def test_list_evaluators_endpoint(self, mock_user):
        from data_agent.frontend_api import _api_eval_evaluators
        req = _make_request(query_params={})
        resp = _run_async(_api_eval_evaluators(req))
        body = json.loads(resp.body)
        assert "evaluators" in body
        assert len(body["evaluators"]) >= 15

    @patch("data_agent.frontend_api._get_user_from_request", return_value="test_user")
    def test_list_evaluators_by_category(self, mock_user):
        from data_agent.frontend_api import _api_eval_evaluators
        req = _make_request(query_params={"category": "safety"})
        resp = _run_async(_api_eval_evaluators(req))
        body = json.loads(resp.body)
        assert len(body["evaluators"]) == 3

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_list_evaluators_unauthorized(self, mock_user):
        from data_agent.frontend_api import _api_eval_evaluators
        req = _make_request()
        resp = _run_async(_api_eval_evaluators(req))
        assert resp.status_code == 401

    @patch("data_agent.frontend_api._get_user_from_request", return_value="test_user")
    def test_evaluate_endpoint(self, mock_user):
        from data_agent.frontend_api import _api_eval_evaluate
        req = _make_request(body={
            "evaluators": ["exact_match", "output_length"],
            "test_cases": [
                {"input": "q", "output": "hello", "expected_output": "hello"},
            ]
        })
        resp = _run_async(_api_eval_evaluate(req))
        body = json.loads(resp.body)
        assert body["status"] == "success"
        assert body["summary"]["total_cases"] == 1
        assert body["summary"]["evaluators_run"] == 2

    @patch("data_agent.frontend_api._get_user_from_request", return_value="test_user")
    def test_evaluate_endpoint_missing_params(self, mock_user):
        from data_agent.frontend_api import _api_eval_evaluate
        req = _make_request(body={"evaluators": [], "test_cases": []})
        resp = _run_async(_api_eval_evaluate(req))
        assert resp.status_code == 400

    @patch("data_agent.frontend_api._get_user_from_request", return_value="test_user")
    def test_evaluate_endpoint_invalid_evaluator(self, mock_user):
        from data_agent.frontend_api import _api_eval_evaluate
        req = _make_request(body={
            "evaluators": ["nonexistent_evaluator"],
            "test_cases": [{"input": "q", "output": "a"}]
        })
        resp = _run_async(_api_eval_evaluate(req))
        assert resp.status_code == 404
