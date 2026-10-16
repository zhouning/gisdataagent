"""No model/network calls: timing correctness and product boundary regression."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest

from data_agent import nl2sql_observability as obs
from data_agent.user_context import current_trace_id


@pytest.fixture(autouse=True)
def isolated_sink(monkeypatch, tmp_path):
    monkeypatch.setenv("GDA_NL2SQL_TRACE_SUMMARY_PATH", str(tmp_path / "timing.jsonl"))
    monkeypatch.setattr("data_agent.otel_tracing._tracer", None)


def read_summaries(monkeypatch):
    import os
    from pathlib import Path
    return [json.loads(line) for line in Path(os.environ["GDA_NL2SQL_TRACE_SUMMARY_PATH"]).read_text().splitlines()]


def test_request_preserves_result_and_has_durable_content_free_trace(monkeypatch):
    secret = "private question and password must not be in telemetry"
    seen_ids = []

    @obs.observe_stage("catalog.load")
    def load(question):
        seen_ids.append(current_trace_id.get())
        obs.annotate_stage(candidate_count=3, question=question, password=secret)

    @obs.observe_request
    def product():
        load(secret)
        obs.record_route("sql")
        return json.dumps({"status": "ok", "data": [secret]})

    result = json.loads(product())
    summary = result["observability"]
    assert result["data"] == [secret]
    assert summary["trace_id"] == seen_ids[0]
    assert summary["route"] == "sql" and summary["status"] == "ok"
    assert summary["summary_persisted"] and not summary["otel_recording"]
    assert summary["steps"][1]["attributes"]["candidate_count"] == 3
    assert secret not in json.dumps(summary)
    assert secret not in json.dumps(read_summaries(monkeypatch))
    assert obs.current_run() is None


@pytest.mark.parametrize("status", ["rejected", "error"])
def test_early_terminal_status_is_not_success(status, monkeypatch):
    @obs.observe_request
    def product():
        return json.dumps({"status": status, "error": "sensitive details"})
    result = json.loads(product())
    assert result["status"] == result["observability"]["status"] == status
    assert "sensitive details" not in json.dumps(read_summaries(monkeypatch))


def test_exception_is_reraised_and_summary_retains_only_class(monkeypatch):
    @obs.observe_stage("llm.request")
    def failure():
        raise ValueError("credential and prompt")

    @obs.observe_request
    def product():
        failure()

    with pytest.raises(ValueError, match="credential"):
        product()
    summary = read_summaries(monkeypatch)[0]
    assert summary["status"] == "error"
    assert summary["first_failed_stage"] == "llm.request"
    assert "credential" not in json.dumps(summary)
    assert summary["steps"][1]["attributes"]["error_code"] == "ValueError"
    assert obs.current_run() is None


def test_cancellation_closes_all_spans_and_resets_context(monkeypatch):
    @obs.observe_stage("database.execute")
    async def cancel():
        raise asyncio.CancelledError()

    @obs.observe_request
    def product():
        asyncio.run(cancel())

    with pytest.raises(asyncio.CancelledError):
        product()
    summary = read_summaries(monkeypatch)[0]
    assert summary["status"] == "cancelled"
    assert all(step["status"] == "cancelled" for step in summary["steps"])
    assert all(step["duration_ms"] >= 0 for step in summary["steps"])
    assert obs.current_run() is None


def test_self_time_subtracts_union_of_overlapping_children():
    root = obs.Step("gda.nl2sql.request", None, 0, end_ns=100_000_000)
    first = obs.Step("retrieval.bm25", root.step_id, 10_000_000, end_ns=70_000_000)
    second = obs.Step("retrieval.dependencies", root.step_id, 40_000_000, end_ns=80_000_000)
    root.children = [first, second]
    run = obs.Run(steps=[root, first, second])
    records = obs.summarize(run)["steps"]
    assert records[0]["duration_ms"] == 100
    assert records[0]["self_ms"] == 30
    assert sum(s["duration_ms"] for s in records[1:]) == 100


def test_retries_and_recovered_failure_remain_visible():
    @obs.observe_stage("llm.request")
    def call(fail=False):
        if fail:
            raise TimeoutError("not exported")

    @obs.observe_request
    def product():
        with obs.stage("planning.generate", purpose="answer_plan_json"):
            try:
                call(True)
            except TimeoutError:
                pass
            call()
        obs.record_route("sql", fallback=True)
        return '{"status":"ok"}'

    summary = json.loads(product())["observability"]
    calls = [s for s in summary["steps"] if s["stage"] == "llm.request"]
    assert [s["attributes"]["attempt"] for s in calls] == [1, 2]
    assert [s["status"] for s in calls] == ["error", "ok"]
    assert all(s["attributes"]["purpose"] == "answer_plan_json" for s in calls)
    assert summary["status"] == "ok" and summary["fallback"]
    assert summary["first_failed_stage"] == "llm.request"


def test_parallel_requests_do_not_share_steps_or_trace_ids(monkeypatch):
    barrier = threading.Barrier(2)

    @obs.observe_request
    def product(index):
        with obs.stage("catalog.load", candidate_count=index):
            barrier.wait(timeout=5)
        return '{"status":"ok"}'

    with ThreadPoolExecutor(2) as pool:
        summaries = [json.loads(r)["observability"] for r in pool.map(product, [1, 2])]
    assert summaries[0]["trace_id"] != summaries[1]["trace_id"]
    assert [s["steps"][1]["attributes"]["candidate_count"] for s in summaries] == [1, 2]
    assert len(read_summaries(monkeypatch)) == 2


def test_parallel_async_children_have_the_correct_parent():
    @obs.observe_stage("retrieval.bm25")
    async def child():
        await asyncio.sleep(0)

    async def combined():
        with obs.stage("semantic.retrieve"):
            await asyncio.gather(child(), child())

    @obs.observe_request
    def product():
        asyncio.run(combined())
        return '{"status":"ok"}'

    steps = json.loads(product())["observability"]["steps"]
    parent = steps[1]
    assert steps[2]["parent_id"] == steps[3]["parent_id"] == parent["step_id"]
    assert parent["self_ms"] >= 0


def test_persistence_failure_does_not_change_product_status(monkeypatch):
    def fail(summary):
        raise OSError("sensitive path")
    monkeypatch.setattr(obs, "_persist_summary", fail)

    @obs.observe_request
    def product():
        return '{"status":"ok"}'

    result = json.loads(product())
    assert result["status"] == "ok"
    assert result["observability"]["observability_degraded"]
    assert result["observability"]["summary_persisted"] is False


@pytest.mark.parametrize("query_fails", [False, True])
def test_summary_and_logging_failures_preserve_business_result_or_exception(monkeypatch, query_fails):
    def telemetry_failure(*args, **kwargs):
        raise RuntimeError("telemetry subsystem unavailable")
    monkeypatch.setattr(obs, "summarize", telemetry_failure)
    monkeypatch.setattr(obs, "_persist_summary", telemetry_failure)
    monkeypatch.setattr(obs.logger, "warning", telemetry_failure)
    monkeypatch.setattr(obs.logger, "info", telemetry_failure)

    @obs.observe_request
    def product():
        if query_fails:
            raise ValueError("original query failure")
        return '{"status":"ok","data":[42]}'

    if query_fails:
        with pytest.raises(ValueError, match="original query failure"):
            product()
    else:
        result = json.loads(product())
        assert result["status"] == "ok" and result["data"] == [42]
        assert result["observability"]["observability_degraded"]
        assert result["observability"]["summary_persisted"] is False
    assert obs.current_run() is None


def test_step_cap_marks_incomplete_self_time(monkeypatch):
    monkeypatch.setattr(obs, "_MAX_STEPS", 3)

    @obs.observe_request
    def product():
        for _ in range(9):
            with obs.stage("query.final_audit"):
                pass
        return '{"status":"ok"}'

    summary = json.loads(product())["observability"]
    assert len(summary["steps"]) == 3 and summary["dropped_steps"] == 7
    assert summary["steps"][0]["self_ms"] is None


def test_nested_candidate_runs_share_one_trace_and_persist_once(monkeypatch):
    @obs.observe_request
    def product(n=0):
        if n == 0:
            product(1)
            product(2)
            obs.record_route("candidates")
        return '{"status":"ok"}'

    result = json.loads(product())
    assert result["observability"]["route"] == "candidates"
    assert [s["stage"] for s in result["observability"]["steps"]] == [
        "gda.nl2sql.request", "candidate.attempt", "candidate.attempt"]
    assert len(read_summaries(monkeypatch)) == 1


def test_actual_otel_context_matches_product_id_and_redacts_exception(monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr("data_agent.otel_tracing._tracer", provider.get_tracer("test"))
    outer = current_trace_id.set("previous-correlation")
    seen = []

    @obs.observe_request
    def product():
        seen.append(current_trace_id.get())
        try:
            with obs.stage("llm.request"):
                raise ValueError("secret prompt")
        except ValueError:
            pass
        return '{"status":"ok"}'

    try:
        summary = json.loads(product())["observability"]
        assert current_trace_id.get() == "previous-correlation"
    finally:
        current_trace_id.reset(outer)
        provider.shutdown()
    spans = exporter.get_finished_spans()
    root = next(span for span in spans if span.name == "gda.nl2sql.request")
    child = next(span for span in spans if span.name == "llm.request")
    assert summary["trace_id"] == seen[0] == format(root.context.trace_id, "032x")
    assert child.parent.span_id == root.context.span_id
    assert child.events == ()
    assert "secret prompt" not in str(child.attributes)
    assert summary["otel_recording"]


def test_real_product_invalid_engine_is_traced_without_llm(monkeypatch):
    from data_agent.nl2sql_executor import run_nl2semantic2sql
    monkeypatch.setenv("GDA_NL2SQL_EXECUTION_CONSENSUS", "0")
    result = json.loads(run_nl2semantic2sql("anything", execution_engine="invalid"))
    assert result["status"] == "error"
    assert result["observability"]["status"] == "error"
    assert not any(step["stage"] == "llm.request" for step in result["observability"]["steps"])


def test_source_fetch_execute_and_connection_checkout_are_separate(monkeypatch):
    from unittest.mock import MagicMock
    from data_agent import bird_source

    control = MagicMock()
    control.connect.return_value.__enter__.return_value.execute.return_value = [
        ("records", [{"column_name": "id"}])]
    remote = MagicMock()
    conn = remote.connect.return_value.__enter__.return_value
    conn.execute.return_value.keys.return_value = ["id"]
    conn.execute.return_value.fetchall.return_value = [(1,), (2,)]
    monkeypatch.setattr(bird_source, "registered_database", lambda _: "bird_sample")
    monkeypatch.setattr(bird_source, "get_engine", lambda: control)
    monkeypatch.setattr(bird_source, "_remote_engine", lambda _: remote)

    @obs.observe_request
    def product():
        columns, rows, truncated = bird_source.query_rows("sample", "SELECT id FROM records", max_rows=1)
        assert columns == ["id"] and rows == [(1,)] and truncated
        return '{"status":"ok"}'

    summary = json.loads(product())["observability"]
    stages = {s["stage"] for s in summary["steps"]}
    assert {"query.source_audit", "database.pool_checkout", "database.session_setup",
            "database.execute", "database.fetch"} <= stages
    remote.connect.return_value.__exit__.assert_called_once()


def test_unknown_usage_stays_unknown_and_remote_compatible_is_not_free():
    from data_agent.nl2sql_executor import _aggregate_llm_evidence
    from data_agent.user_context import current_nl2sql_llm_calls
    token = current_nl2sql_llm_calls.set([
        {"provider": "openai_compatible", "usage": {"prompt_tokens": 5, "completion_tokens": 0}},
        {"provider": "openai_compatible"},
    ])
    try:
        usage = _aggregate_llm_evidence()
    finally:
        current_nl2sql_llm_calls.reset(token)
    assert usage["input_tokens"] is None and usage["output_tokens"] is None
    assert usage["estimated_cost_usd"] is None


def test_completion_evidence_preserves_zero_token_counts():
    from data_agent.openai_compatible_llm import OpenAICompatibleLLMConfig, _completion_evidence
    cfg = OpenAICompatibleLLMConfig(provider="ollama", model="fake", base_url="http://127.0.0.1:11434/v1", api_key="unused", timeout_seconds=1)
    result = _completion_evidence(cfg, {}, {}, {"prompt_tokens": 0, "completion_tokens": 0},
                                 response_id="", response_model="", prompt="", response_text="",
                                 elapsed_ms=0, status="succeeded")
    assert result["usage"]["prompt_tokens"] == result["usage"]["completion_tokens"] == 0
