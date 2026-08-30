import json

import pytest

from data_agent.free_form_nl2sql_benchmark import BenchmarkConfigurationError
from data_agent.nl2sql_benchmark_cohort_analysis import (
    analyze_benchmark_report_with_cohort,
)


def _write_inputs(tmp_path):
    source = {
        "source_id": 12,
        "database_name": "liveability",
        "authorized_schemas": ["public"],
        "discovery_fingerprint": "d" * 64,
        "profile_fingerprint": "p" * 64,
    }
    cases = []
    observations = []
    for index, status in enumerate(("current", "gold_stale_source_result"), 1):
        contract_id = f"GOLD_{index}"
        cases.append(
            {
                "case_id": f"CASE_{index}",
                "language": "en",
                "checks": {"gold_result_equivalence_match": False},
                "failure_class": "gold_result_mismatch",
                "observed": {
                    "gold_result_contract": {
                        "contract_id": contract_id,
                        "sha256": str(index) * 64,
                    }
                },
            }
        )
        observations.append(
            {
                "contract_id": contract_id,
                "status": status,
                "gold_contract_sha256": str(index) * 64,
            }
        )
    report = {
        "schema": "gda.free-form-nl2sql-benchmark-report.v1",
        "source": source,
        "benchmark": {"source_file_sha256": "b" * 64},
        "cases": cases,
    }
    cohort = {
        "schema": "gda.nl2sql-gold-source-cohort.v1",
        "status": "complete",
        "cohort_id": "c" * 64,
        "source": source,
        "inputs": {"benchmark_sha256": "b" * 64},
        "observations": observations,
    }
    report_path = tmp_path / "report.json"
    cohort_path = tmp_path / "cohort.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    cohort_path.write_text(json.dumps(cohort), encoding="utf-8")
    return report_path, cohort_path, report, cohort


def test_analysis_preserves_strict_failure_and_excludes_stale_gold(tmp_path):
    report_path, cohort_path, _report, _cohort = _write_inputs(tmp_path)

    analysis = analyze_benchmark_report_with_cohort(
        report_path=report_path,
        cohort_path=cohort_path,
    )

    assert analysis["metrics"] == {
        "strict_gold_case_count": 2,
        "strict_gold_equivalence_passed_case_count": 0,
        "strict_gold_equivalence_pass_rate": 0.0,
        "gold_stale_source_result_case_count": 1,
        "gold_stale_source_result_contract_count": 1,
        "model_evaluable_gold_case_count": 1,
        "model_gold_equivalence_passed_case_count": 0,
        "model_gold_equivalence_pass_rate": 0.0,
        "model_failure_class_counts": {"gold_result_mismatch": 1},
    }
    stale = analysis["case_assessments"][1]
    assert stale["model_evaluable"] is False
    assert stale["adjusted_failure_class"] == "gold_stale_source_result"
    assert stale["evaluation_exclusion_reason"] == "gold_stale_source_result"


def test_analysis_rejects_report_from_another_benchmark(tmp_path):
    report_path, cohort_path, _report, cohort = _write_inputs(tmp_path)
    cohort["inputs"]["benchmark_sha256"] = "x" * 64
    cohort_path.write_text(json.dumps(cohort), encoding="utf-8")

    with pytest.raises(BenchmarkConfigurationError, match="benchmark checksum differ"):
        analyze_benchmark_report_with_cohort(
            report_path=report_path,
            cohort_path=cohort_path,
        )
