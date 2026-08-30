from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_agent.nl2semantic2sql_pairwise_comparison import (
    PairwiseComparisonError,
    aggregate_pairwise_comparisons,
    compare_reports,
)


def _report(*, profile: str, cases: list[dict], source_id: int = 13) -> dict:
    return {
        "schema": "gda.free-form-nl2sql-benchmark-report.v1",
        "benchmark": {
            "benchmark_id": "test-product-v1",
            "version": "1",
            "source_file_sha256": "a" * 64,
            "semantic_layer_version": "semantic-v1",
            "metric_contract_version": "metric-v1",
            "execution_profile": profile,
            "request_interval_seconds": 2.0,
            "max_concurrency": 1,
            "selected_case_ids": [case["case_id"] for case in cases],
            "prompt_version": "baseline" if profile == "baseline_sql" else "candidate",
        },
        "source": {
            "source_id": source_id,
            "owner": "operator",
            "database_name": "customer_db",
            "authorized_schemas": ["public"],
            "discovery_fingerprint": "b" * 64,
            "profile_fingerprint": "c" * 64,
            "execution_mode": "registered_governed_virtual_read_only",
        },
        "model": {"requested": "gpt-5.1", "reasoning_effort": "medium"},
        "cases": cases,
    }


def _case(
    case_id: str,
    *,
    passed: bool,
    contract_id: str | None = None,
    track: str = "warehouse",
) -> dict:
    return {
        "case_id": case_id,
        "status": "passed" if passed else "failed",
        "language": "en",
        "track": track,
        "split": "holdout",
        "checks": {"gold_result_equivalence_match": passed},
        "observed": {
            "status": "ok" if track != "safety" else "rejected",
            "planner": {"route": "test"},
            "generation": {"latency_ms": 10.0, "usage": {"input_tokens": 2}},
            "semantic_metric_contract": ({"contract_id": contract_id} if contract_id else None),
            "semantic_plan": {"authority": "test-authority"},
        },
    }


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_comparison_separates_shared_metric_contract_from_free_form(tmp_path: Path) -> None:
    baseline_cases = [
        _case("CONTROL", passed=True, contract_id="REVIEWED_METRIC"),
        _case("FREE_FORM", passed=True),
        _case("SAFETY", passed=True, track="safety"),
    ]
    candidate_cases = [
        _case("CONTROL", passed=True, contract_id="REVIEWED_METRIC"),
        _case("FREE_FORM", passed=False),
        _case("SAFETY", passed=True, track="safety"),
    ]
    result = compare_reports(
        baseline_reports=[
            _write(
                tmp_path / "baseline.json", _report(profile="baseline_sql", cases=baseline_cases)
            )
        ],
        candidate_reports=[
            _write(
                tmp_path / "candidate.json",
                _report(profile="semantic_ir_experimental", cases=candidate_cases),
            )
        ],
    )

    assert result["paired_configuration_verified"] is True
    assert result["metrics"]["by_category"]["reviewed_metric_contract_control"]["case_count"] == 1
    assert result["metrics"]["free_form_route_comparison"]["case_count"] == 2
    assert (
        result["metrics"]["free_form_route_comparison"]["candidate_minus_baseline_pass_rate"]
        == -0.5
    )
    generation = result["metrics"]["free_form_route_comparison"]["paired_generation"]
    assert generation["paired_model_generation_case_count"] == 2
    assert generation["candidate_minus_baseline_mean_generation_latency_ms"] == 0.0
    assert generation["usage"]["input_tokens"]["candidate_minus_baseline_total"] == 0
    assert result["cases"][0]["category"] == "reviewed_metric_contract_control"
    assert "question" not in result["cases"][0]


def test_comparison_rejects_different_case_sets(tmp_path: Path) -> None:
    baseline = _write(
        tmp_path / "baseline.json",
        _report(profile="baseline_sql", cases=[_case("BASELINE", passed=True)]),
    )
    candidate = _write(
        tmp_path / "candidate.json",
        _report(profile="semantic_ir_experimental", cases=[_case("CANDIDATE", passed=True)]),
    )

    with pytest.raises(PairwiseComparisonError, match="selected_case_ids"):
        compare_reports(baseline_reports=[baseline], candidate_reports=[candidate])


def test_repeated_pairwise_comparisons_preserve_tie_without_promotion() -> None:
    comparison = {
        "schema": "gda.nl2semantic2sql-pairwise-comparison.v1",
        "status": "passed",
        "comparison_role": "candidate_canary_vs_current_production_baseline",
        "pairs": [
            {
                "baseline_report": "baseline-run-1.json",
                "candidate_report": "candidate-run-1.json",
                "source_id": 12,
            }
        ],
        "cases": [
            {
                "source_id": 12,
                "database_name": "customer_db",
                "case_id": "Q1",
                "language": "en",
                "track": "warehouse",
                "split": "holdout",
                "category": "free_form_query",
                "outcome": "both_passed",
                "baseline": {"passed": True, "gold_equivalent": True},
                "candidate": {"passed": True, "gold_equivalent": True},
            }
        ],
    }
    second = json.loads(json.dumps(comparison))
    second["pairs"][0]["baseline_report"] = "baseline-run-2.json"
    second["pairs"][0]["candidate_report"] = "candidate-run-2.json"

    result = aggregate_pairwise_comparisons([comparison, second])

    assert result["runs_by_source"] == {"12": 2}
    assert result["metrics"]["all_matched_observations"]["case_count"] == 2
    assert result["metrics"]["case_stability"]["all_cases_both_passed_on_every_observation"]
    assert result["candidate_promotion_assessment"] == {
        "promotion_supported": False,
        "candidate_only_passed_observation_count": 0,
        "baseline_only_passed_observation_count": 0,
        "reason": "no_measured_candidate_accuracy_advantage",
        "all_observations_both_passed": True,
    }
