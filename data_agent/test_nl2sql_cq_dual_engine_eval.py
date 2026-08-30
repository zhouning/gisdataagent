"""Tests for the dual-engine benchmark contract."""
from pathlib import Path


def test_technical_question_field_uses_technical_engine_goldens():
    from scripts.nl2sql_bench_cq.run_cq_dual_engine_eval import (
        DEFAULT_ENGINE_GOLDENS,
        _default_engine_goldens_for_benchmark,
    )

    selected = _default_engine_goldens_for_benchmark(
        Path("chongqing_geo_nl2sql_125q_business_lang.json"),
        "question",
    )

    assert selected == DEFAULT_ENGINE_GOLDENS


def test_business_question_field_uses_business_engine_goldens():
    from scripts.nl2sql_bench_cq.run_cq_dual_engine_eval import (
        DEFAULT_BUSINESS_ENGINE_GOLDENS,
        _default_engine_goldens_for_benchmark,
    )

    selected = _default_engine_goldens_for_benchmark(
        Path("arbitrary_filename.json"),
        "question_business",
    )

    assert selected == DEFAULT_BUSINESS_ENGINE_GOLDENS


def test_retryable_generation_failure_only_matches_transport_failures():
    from scripts.nl2sql_bench_cq.run_cq_dual_engine_eval import (
        _is_retryable_generation_failure,
    )

    assert _is_retryable_generation_failure(
        {
            "generator_status": "error",
            "generator_error": (
                "deepseek_sql_generation_failed:deepseek LLM request failed: "
                "SSL UNEXPECTED_EOF"
            ),
        }
    ) is True
    assert _is_retryable_generation_failure(
        {
            "generator_status": "error",
            "generator_error": (
                "deepseek_sql_generation_failed:deepseek LLM returned an empty response "
                "(status=incomplete)"
            ),
        }
    ) is True
    assert _is_retryable_generation_failure(
        {
            "generator_status": "error",
            "generator_error": "Execution failed: column does not exist",
        }
    ) is False
