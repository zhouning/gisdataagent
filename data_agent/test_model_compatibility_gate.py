from __future__ import annotations

import json

import pytest

from scripts.check_abu_dhabi_model_compatibility_gate import evaluate
from scripts.check_abu_dhabi_model_compatibility_stability_gate import (
    CompatibilityStabilityConfigurationError,
    evaluate_repeated,
)


def _stable_analysis(*, gold_rate: float = 0.9, cohort: str = "cohort-a", digest: str = "digest-a"):
    return {
        "schema": "gda.abu-dhabi-local-smoke-analysis.v1",
        "cohort_sha256": cohort,
        "code_sha256": {"data_agent/semantic_query_ir.py": "a" * 64},
        "model": {
            "id": "gemma4:26b",
            "effective_route": "ollama_chat/gemma4:26b",
            "timeout_seconds": 180,
            "generation_budget_seconds": 180,
            "installed": {"digest": digest},
            "compatibility_profile": {
                "profile_id": "gemma-compact-local",
                "profile_version": "nl2sql-model-profile-v1",
                "fingerprint": "profile-a",
                "minimum_benchmark_thresholds": {
                    "liveability_gold_equivalence": 0.8,
                    "makani_gold_equivalence": 0.2,
                    "refusal_precision": 0.9,
                    "refusal_recall": 0.95,
                    "query_execution_success": 0.9,
                },
            },
        },
        "summary": [
            {
                "source": "liveability",
                "execution_profile": "baseline_sql",
                "planner_route": "llm",
                "current_gold_case_count": 10,
                "gold_equivalent": round(gold_rate * 10),
                "query_execution_success_rate": 0.95,
                "refusal": {"precision": 1.0, "recall": 1.0},
                "mean_generation_latency_ms": 1000,
                "p95_generation_latency_ms": 1500,
            }
        ],
    }


def test_gate_excludes_deterministic_contracts_and_requires_all_routes():
    report = evaluate(
        {
            "model": {"id": "gemma4:26b", "effective_route": "ollama_chat/gemma4:26b"},
            "raw_run_metrics": {
                "liveability_baseline_sql": {
                    "model_evaluable_gold_case_count": 10,
                    "model_gold_equivalence_passed_case_count": 9,
                    "refusal": {"precision": 1.0, "recall": 1.0},
                    "query_execution_success_rate": 0.95,
                },
                "makani_baseline_sql": {
                    "model_evaluable_gold_case_count": 10,
                    "model_gold_equivalence_passed_case_count": 2,
                    "refusal": {"precision": 1.0, "recall": 1.0},
                    "query_execution_success_rate": 0.95,
                },
            },
        }
    )
    assert report["deterministic_contracts_excluded_from_model_gate"] is True
    assert report["promote"] is True


def test_gate_returns_canary_when_gold_or_refusal_threshold_fails():
    report = evaluate(
        {
            "model": {"id": "qwen3.8:latest"},
            "raw_run_metrics": {
                "liveability_baseline_sql": {
                    "model_evaluable_gold_case_count": 10,
                    "model_gold_equivalence_passed_case_count": 7,
                    "refusal": {"precision": 1.0, "recall": 0.8},
                    "query_execution_success_rate": 0.95,
                }
            },
        }
    )
    assert report["promote"] is False
    assert report["decision"] == "canary_or_rollback"


def test_gate_uses_only_actual_llm_route_when_mixed_metrics_look_better():
    report = evaluate(
        {
            "model": {"name": "gpt-5.6-terra", "effective_route": "openai/gpt-5.6-terra"},
            "by_actual_route": [
                {
                    "source": "liveability",
                    "profile": "baseline_sql",
                    "route": "deterministic_reviewed_metric_contract",
                    "current_gold_case_count": 8,
                    "gold_equivalent": 8,
                    "expected_query_case_count": 8,
                    "query_execution_success_rate": 1.0,
                    "refusal": {"precision": None, "recall": None},
                },
                {
                    "source": "liveability",
                    "profile": "baseline_sql",
                    "route": "llm",
                    "current_gold_case_count": 20,
                    "gold_equivalent": 13,
                    "expected_query_case_count": 20,
                    "query_execution_success_rate": 0.95,
                    "refusal": {"precision": 0.95, "recall": 0.95},
                    "mean_generation_latency_ms": 4200,
                    "p95_generation_latency_ms": 7300,
                },
            ],
            "raw_run_metrics": {
                "liveability_baseline_sql": {
                    "model_evaluable_gold_case_count": 28,
                    "model_gold_equivalence_passed_case_count": 21,
                    "query_execution_success_rate": 0.95,
                    "refusal": {"precision": 1.0, "recall": 1.0},
                }
            },
        }
    )

    assert report["source_of_truth"] == "actual_model_route"
    assert len(report["routes"]) == 1
    assert report["routes"][0]["actual_route"] == "llm"
    assert report["routes"][0]["gold_denominator"] == 20
    assert report["routes"][0]["gold_rate"] == 0.65
    assert report["promote"] is False


def test_gate_treats_absent_refusal_class_as_not_applicable():
    report = evaluate(
        {
            "model": {"id": "gemma4:26b"},
            "summary": [
                {
                    "source": "liveability",
                    "execution_profile": "baseline_sql",
                    "planner_route": "llm",
                    "current_gold_case_count": 10,
                    "gold_equivalent": 9,
                    "expected_refusals": 0,
                    "observed_refusals": 0,
                    "refusal": {"precision": None, "recall": None},
                    "query_execution_success_rate": 0.95,
                }
            ],
        }
    )

    route = report["routes"][0]
    assert route["metric_applicability"] == {
        "refusal_precision": False,
        "refusal_recall": False,
    }
    assert route["checks"]["refusal_precision"] is True
    assert route["checks"]["refusal_recall"] is True
    assert report["promote"] is True


def test_gate_fails_precision_for_unexpected_refusal_without_expected_class():
    report = evaluate(
        {
            "model": {"id": "gemma4:26b"},
            "summary": [
                {
                    "source": "liveability",
                    "execution_profile": "baseline_sql",
                    "planner_route": "llm",
                    "current_gold_case_count": 10,
                    "gold_equivalent": 9,
                    "expected_refusals": 0,
                    "observed_refusals": 1,
                    "refusal": {"precision": 0.0, "recall": None},
                    "query_execution_success_rate": 0.95,
                }
            ],
        }
    )

    route = report["routes"][0]
    assert route["metric_applicability"]["refusal_precision"] is True
    assert route["checks"]["refusal_precision"] is False
    assert route["checks"]["refusal_recall"] is True
    assert report["promote"] is False


def test_repeated_gate_uses_lower_bound_and_requires_minimum_runs():
    analyses = [
        {**_stable_analysis(), "report_sha256": f"report-{index}"}
        for index in range(3)
    ]
    report = evaluate_repeated(analyses)

    assert report["configuration_audit"]["evidence_sufficient"] is True
    assert report["routes"][0]["metrics"]["gold_rate"]["minimum"] == 0.9
    assert report["routes"][0]["stable_promotable"] is True
    assert report["decision"] == "promote"

    insufficient = evaluate_repeated(analyses[:2])
    assert insufficient["configuration_audit"]["evidence_sufficient"] is False
    assert insufficient["decision"] == "canary_or_rollback"


def test_repeated_gate_rejects_one_intermittent_run_and_configuration_drift():
    analyses = [
        {**_stable_analysis(), "report_sha256": f"report-{index}"}
        for index in range(2)
    ]
    analyses.append(
        {**_stable_analysis(gold_rate=0.7), "report_sha256": "report-2"}
    )
    report = evaluate_repeated(analyses)

    assert report["routes"][0]["metrics"]["gold_rate"]["minimum"] == 0.7
    assert report["routes"][0]["lower_bound_checks"]["gold_equivalence"] is False
    assert report["decision"] == "canary_or_rollback"

    drifted = {**_stable_analysis(digest="digest-b"), "report_sha256": "report-drift"}
    with pytest.raises(CompatibilityStabilityConfigurationError, match="model_digest"):
        evaluate_repeated([analyses[0], drifted])

    changed_runtime = {
        **_stable_analysis(),
        "report_sha256": "report-runtime-drift",
        "code_sha256": {"data_agent/semantic_query_ir.py": "b" * 64},
    }
    with pytest.raises(CompatibilityStabilityConfigurationError, match="runtime_code_fingerprint"):
        evaluate_repeated([analyses[0], changed_runtime])


def test_repeated_gate_requires_explicit_model_identity():
    incomplete = _stable_analysis()
    incomplete["model"]["installed"].pop("digest")

    with pytest.raises(
        CompatibilityStabilityConfigurationError,
        match="configuration_identity_missing:model_digest",
    ):
        evaluate_repeated([incomplete, _stable_analysis()])


def test_repeated_gate_accepts_full_run_model_digest_shape():
    analysis = _stable_analysis()
    analysis["model"] = {
        "name": "gemma4:26b",
        "digest": "digest-a",
        "effective_route": "ollama_chat/gemma4:26b",
        "request_timeout_seconds": 180,
        "generation_budget_seconds": 180,
        "compatibility_profile": analysis["model"]["compatibility_profile"],
    }

    report = evaluate_repeated(
        [{**analysis, "report_sha256": f"full-{index}"} for index in range(3)]
    )

    assert report["configuration_audit"]["evidence_sufficient"] is True
    assert report["model"]["model_digest"] == "digest-a"


def test_repeated_gate_cli_reports_incomplete_identity_without_traceback(tmp_path, capsys):
    from scripts.check_abu_dhabi_model_compatibility_stability_gate import main

    analysis = _stable_analysis()
    analysis["model"]["installed"].pop("digest")
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(analysis), encoding="utf-8")

    assert main([str(path)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "configuration_invalid"
    assert result["decision"] == "canary_or_rollback"
    assert result["reason"] == "configuration_identity_missing:model_digest"
