#!/usr/bin/env python3
"""Validate smoke evidence and attach independent Gold freshness to its metrics."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_abu_dhabi_local_smoke import (  # noqa: E402
    assert_artifacts_unchanged,
    sha256,
    summarize,
    write_json,
)


def failure_layer(case: dict, expected: dict) -> str | None:
    observed = case.get("observed") or {}
    inherited = case.get("failure_class")
    if inherited in {"model_provider_unavailable", "virtual_source_unavailable"}:
        return inherited
    if expected["status"] == "rejected" and observed.get("status") == "ok":
        return "unexpected_answer"
    if expected["status"] == "ok" and observed.get("status") == "rejected":
        return "unexpected_refusal"
    error = str(observed.get("error") or case.get("error") or "").lower()
    if "model_structured_output" in error:
        return "model_output_schema"
    if "sql_parse" in error:
        return "sql_parse_validation"
    if "semantic_ir" in error or "semantic_" in error:
        return "semantic_validation"
    if case.get("checks", {}).get("gold_result_equivalence_match") is False:
        return (
            "gold_stale_source_result"
            if case.get("gold_source_status") == "gold_stale_source_result"
            else "result_equivalence"
        )
    return inherited


def analyze(report_path: Path, gold_dir: Path) -> dict:
    from data_agent.free_form_nl2sql_benchmark import (
        _apply_gold_source_evaluation,
        _load_gold_source_cohort,
        _validate_benchmark,
    )

    report = json.loads(report_path.read_text())
    if report["status"] != "completed":
        raise ValueError("The two-route smoke run must complete before final analysis")
    assert_artifacts_unchanged(report)
    expectations = {}
    gold_by_source = {}
    for source in report["cohort"]["sources"]:
        key = source["source_key"]
        artifacts = report["artifacts"][key]
        benchmark_path = ROOT / artifacts["benchmark_path"]
        benchmark = json.loads(benchmark_path.read_text())
        semantic = json.loads((ROOT / artifacts["semantic_path"]).read_text())
        source_id = artifacts["source"]["source_id"]
        all_cases = _validate_benchmark(
            benchmark, semantic, source_id=source_id, benchmark_path=benchmark_path
        )
        selected = {item["case_id"] for item in source["cases"]}
        cases = [case for case in all_cases if case["case_id"] in selected]
        expectations.update({(key, case["case_id"]): case for case in cases})
        gold_by_source[key] = _load_gold_source_cohort(
            gold_dir / f"{key}_gold.json",
            benchmark=benchmark,
            semantic_layer=semantic,
            binding=semantic["source_binding"],
            source_id=source_id,
            cases=cases,
        )
    expected_population = {
        (key, case_id, profile)
        for key, case_id in expectations
        for profile in ("baseline_sql", "semantic_ir_experimental")
    }
    actual_population = [
        (case["source_key"], case["case_id"], case["execution_profile"]) for case in report["cases"]
    ]
    if (
        len(actual_population) != len(set(actual_population))
        or set(actual_population) != expected_population
    ):
        raise ValueError("Report contains duplicate, missing, or unexpected case/profile pairs")
    cases = []
    for original in report["cases"]:
        key = original["source_key"]
        expectation = expectations[(key, original["case_id"])]
        case = _apply_gold_source_evaluation(
            copy.deepcopy(original), expectation, gold_by_source[key]
        )
        # Carry the frozen expectation into the summary input so route-level
        # metrics can distinguish model refusals from expected refusals and
        # compute model-only accuracy without relying on a mixed total.
        case["expected_status"] = expectation["expected"]["status"]
        case["has_gold"] = bool(expectation["expected"].get("gold_result_contract"))
        case["failure_layer"] = failure_layer(case, expectation["expected"])
        plan = case.get("observed", {}).get("semantic_plan") or {}
        validation = plan.get("validation") or {}
        case["plan_validation_observed"] = validation.get("valid")
        case["error_code"] = case.get("observed", {}).get("error") or case.get("error")
        cases.append(case)
    return {
        "schema": "gda.abu-dhabi-local-smoke-analysis.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "report_path": str(report_path),
        "report_sha256": sha256(report_path),
        "cohort_sha256": report["cohort_sha256"],
        "code_sha256": report.get("code_sha256") or {},
        "gold_audits": {
            key: {"cohort_id": value["cohort_id"], "sha256": value["artifact_sha256"]}
            for key, value in gold_by_source.items()
        },
        "model": {
            **report["model"],
            "temperature": None,
            "temperature_source": "provider_default_not_overridden_by_query_runtime",
            "probe_temperature": 0,
        },
        "summary": summarize(cases),
        "failure_layers": dict(
            Counter(case["failure_layer"] for case in cases if case["failure_layer"])
        ),
        "case_diagnostics": [
            {
                key: case.get(key)
                for key in (
                    "source_key",
                    "case_id",
                    "execution_profile",
                    "status",
                    "failure_class",
                    "failure_layer",
                    "gold_source_status",
                    "plan_validation_observed",
                    "error_code",
                    "presentation",
                    "elapsed_seconds",
                )
            }
            for case in cases
        ],
        "map_controls": report.get("map_controls", []),
        "claim_boundary": {
            **report["claim_boundary"],
            "gold_freshness_revalidated": True,
            "refusal_reason_correctness_evaluated": False,
            "full_frozen_population_evaluated": False,
            "temperature_note": (
                "The original run metadata recorded 0; only the endpoint probe set 0. "
                "Query generation used provider defaults. This analysis corrects that "
                "metadata without changing outcomes."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--gold-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("--output must be a new path")
    result = analyze(args.report, args.gold_dir)
    write_json(args.output, result)
    print(json.dumps({"output": str(args.output), "summary": result["summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
