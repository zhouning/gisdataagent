"""Analyze an existing NL2SQL report using independent Gold source evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .free_form_nl2sql_benchmark import (
    GOLD_SOURCE_COHORT_SCHEMA,
    REPORT_SCHEMA,
    BenchmarkConfigurationError,
    _atomic_write_json,
)

ANALYSIS_SCHEMA = "gda.nl2sql-benchmark-cohort-analysis.v1"


def _load(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchmarkConfigurationError(f"Cannot load analysis input: {exc}") from exc
    if not isinstance(payload, dict):
        raise BenchmarkConfigurationError("Analysis input must be a JSON object")
    return payload, hashlib.sha256(raw).hexdigest()


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def analyze_benchmark_report_with_cohort(
    *,
    report_path: Path,
    cohort_path: Path,
) -> dict[str, Any]:
    report_path = report_path.expanduser().resolve()
    cohort_path = cohort_path.expanduser().resolve()
    report, report_sha256 = _load(report_path)
    cohort, cohort_sha256 = _load(cohort_path)
    if report.get("schema") != REPORT_SCHEMA:
        raise BenchmarkConfigurationError("Unsupported NL2SQL benchmark report schema")
    if cohort.get("schema") != GOLD_SOURCE_COHORT_SCHEMA:
        raise BenchmarkConfigurationError("Unsupported Gold source cohort schema")
    if cohort.get("status") != "complete":
        raise BenchmarkConfigurationError("Gold source cohort must be complete")
    report_source = report.get("source") or {}
    cohort_source = cohort.get("source") or {}
    for key in (
        "source_id",
        "database_name",
        "authorized_schemas",
        "discovery_fingerprint",
        "profile_fingerprint",
    ):
        if report_source.get(key) != cohort_source.get(key):
            raise BenchmarkConfigurationError(
                f"Benchmark report and Gold source cohort {key} differ"
            )
    report_benchmark = report.get("benchmark") or {}
    cohort_inputs = cohort.get("inputs") or {}
    if (
        report_benchmark.get("source_file_sha256")
        != cohort_inputs.get("benchmark_sha256")
    ):
        raise BenchmarkConfigurationError(
            "Benchmark report and Gold source cohort benchmark checksum differ"
        )

    observations = {
        str(item.get("contract_id") or ""): item
        for item in cohort.get("observations") or []
        if isinstance(item, dict) and item.get("contract_id")
    }
    assessments: list[dict[str, Any]] = []
    for case in report.get("cases") or []:
        gold = (case.get("observed") or {}).get("gold_result_contract") or {}
        contract_id = str(gold.get("contract_id") or "")
        if not contract_id:
            continue
        observation = observations.get(contract_id)
        if observation is None:
            raise BenchmarkConfigurationError(
                f"Gold source cohort lacks report contract evidence: {contract_id}"
            )
        if gold.get("sha256") != observation.get("gold_contract_sha256"):
            raise BenchmarkConfigurationError(
                f"Report Gold checksum differs from cohort evidence: {contract_id}"
            )
        source_status = str(observation.get("status") or "")
        if source_status not in {"current", "gold_stale_source_result"}:
            raise BenchmarkConfigurationError(
                f"Cohort observation is not evaluable: {contract_id}"
            )
        strict_pass = (
            (case.get("checks") or {}).get("gold_result_equivalence_match") is True
        )
        model_evaluable = source_status == "current"
        original_failure_class = case.get("failure_class")
        adjusted_failure_class = original_failure_class
        if (
            source_status == "gold_stale_source_result"
            and original_failure_class == "gold_result_mismatch"
        ):
            adjusted_failure_class = "gold_stale_source_result"
        assessments.append(
            {
                "case_id": case.get("case_id"),
                "language": case.get("language"),
                "track": case.get("track"),
                "split": case.get("split"),
                "contract_id": contract_id,
                "strict_gold_equivalence_passed": strict_pass,
                "gold_source_status": source_status,
                "model_evaluable": model_evaluable,
                "model_gold_equivalence_passed": (
                    strict_pass if model_evaluable else None
                ),
                "evaluation_exclusion_reason": (
                    "gold_stale_source_result" if not model_evaluable else None
                ),
                "original_failure_class": original_failure_class,
                "adjusted_failure_class": adjusted_failure_class,
            }
        )
    if not assessments:
        raise BenchmarkConfigurationError("Benchmark report contains no Gold cases")

    strict_passed = sum(
        item["strict_gold_equivalence_passed"] is True for item in assessments
    )
    model_evaluable = [item for item in assessments if item["model_evaluable"]]
    model_passed = sum(
        item["model_gold_equivalence_passed"] is True for item in model_evaluable
    )
    stale = [
        item
        for item in assessments
        if item["gold_source_status"] == "gold_stale_source_result"
    ]
    adjusted_failure_counts = Counter(
        str(item["adjusted_failure_class"])
        for item in assessments
        if item.get("adjusted_failure_class")
        and item["gold_source_status"] == "current"
    )
    stale_contract_ids = sorted({str(item["contract_id"]) for item in stale})
    current_failures = [
        item
        for item in model_evaluable
        if item["model_gold_equivalence_passed"] is not True
    ]
    return {
        "schema": ANALYSIS_SCHEMA,
        "version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "complete",
        "inputs": {
            "benchmark_report": str(report_path),
            "benchmark_report_sha256": report_sha256,
            "gold_source_cohort": str(cohort_path),
            "gold_source_cohort_sha256": cohort_sha256,
            "cohort_id": cohort.get("cohort_id"),
        },
        "source": cohort_source,
        "metrics": {
            "strict_gold_case_count": len(assessments),
            "strict_gold_equivalence_passed_case_count": strict_passed,
            "strict_gold_equivalence_pass_rate": _ratio(
                strict_passed, len(assessments)
            ),
            "gold_stale_source_result_case_count": len(stale),
            "gold_stale_source_result_contract_count": len(stale_contract_ids),
            "model_evaluable_gold_case_count": len(model_evaluable),
            "model_gold_equivalence_passed_case_count": model_passed,
            "model_gold_equivalence_pass_rate": _ratio(
                model_passed, len(model_evaluable)
            ),
            "model_failure_class_counts": dict(
                sorted(adjusted_failure_counts.items())
            ),
        },
        "current_model_failures": current_failures,
        "stale_contract_ids": stale_contract_ids,
        "case_assessments": assessments,
        "claim_boundary": {
            "model_was_not_rerun": True,
            "gold_freshness_was_observed_independently": True,
            "model_output_used_for_source_classification": False,
            "source_rows_persisted": False,
            "full_post_fix_accuracy_requires_a_new_complete_benchmark_run": True,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    analysis = analyze_benchmark_report_with_cohort(
        report_path=args.report,
        cohort_path=args.cohort,
    )
    _atomic_write_json(args.output.expanduser().resolve(), analysis)
    print(
        json.dumps(
            {
                "status": analysis["status"],
                "output": str(args.output),
                "metrics": analysis["metrics"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
