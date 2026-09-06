"""Aggregate repeated clean product benchmark runs without hiding variance."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .free_form_nl2sql_benchmark import PRODUCT_EVALUATION_PROFILE

REPORT_SCHEMA = "gda.product-nl2sql-stability-report.v1"


class ProductBenchmarkAggregationError(ValueError):
    """Reports cannot form one comparable repeated-run evaluation."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductBenchmarkAggregationError(f"Cannot load report: {path}") from exc
    if not isinstance(payload, dict):
        raise ProductBenchmarkAggregationError(f"Report must be an object: {path}")
    return payload


def _wilson_interval(successes: int, total: int) -> list[float] | None:
    if total <= 0:
        return None
    z = 1.959963984540054
    rate = successes / total
    denominator = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total))
        / denominator
    )
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def aggregate_product_reports(
    reports: list[dict[str, Any]],
    *,
    report_paths: list[str] | None = None,
) -> dict[str, Any]:
    if not reports:
        raise ProductBenchmarkAggregationError("At least one report is required")
    first = reports[0]
    first_benchmark = first.get("benchmark") or {}
    first_profile = first_benchmark.get("evaluation_profile") or {}
    if first.get("scope") != "business_language_product_evaluation":
        raise ProductBenchmarkAggregationError("Report is not a clean product evaluation")
    if first_profile.get("profile_id") != PRODUCT_EVALUATION_PROFILE:
        raise ProductBenchmarkAggregationError("Product evaluation profile is missing")

    identity = {
        "benchmark_id": first_benchmark.get("benchmark_id"),
        "source_file_sha256": first_benchmark.get("source_file_sha256"),
        "semantic_layer_version": first_benchmark.get("semantic_layer_version"),
        "metric_contract_version": first_benchmark.get("metric_contract_version"),
        "prompt_version": first_benchmark.get("prompt_version"),
        "execution_profile": first_benchmark.get("execution_profile"),
        "model_requested": (first.get("model") or {}).get("requested"),
        "reasoning_effort": (first.get("model") or {}).get("reasoning_effort"),
        "source_id": (first.get("source") or {}).get("source_id"),
        "discovery_fingerprint": (first.get("source") or {}).get(
            "discovery_fingerprint"
        ),
    }
    expected_case_ids = [str(case.get("case_id")) for case in first.get("cases") or []]
    if not expected_case_ids:
        raise ProductBenchmarkAggregationError("Report has no cases")

    for report in reports:
        benchmark = report.get("benchmark") or {}
        profile = benchmark.get("evaluation_profile") or {}
        comparable = {
            "benchmark_id": benchmark.get("benchmark_id"),
            "source_file_sha256": benchmark.get("source_file_sha256"),
            "semantic_layer_version": benchmark.get("semantic_layer_version"),
            "metric_contract_version": benchmark.get("metric_contract_version"),
            "prompt_version": benchmark.get("prompt_version"),
            "execution_profile": benchmark.get("execution_profile"),
            "model_requested": (report.get("model") or {}).get("requested"),
            "reasoning_effort": (report.get("model") or {}).get("reasoning_effort"),
            "source_id": (report.get("source") or {}).get("source_id"),
            "discovery_fingerprint": (report.get("source") or {}).get(
                "discovery_fingerprint"
            ),
        }
        if comparable != identity:
            raise ProductBenchmarkAggregationError("Report identity or configuration drift")
        if profile.get("profile_id") != PRODUCT_EVALUATION_PROFILE:
            raise ProductBenchmarkAggregationError("Evaluation profile drift")
        case_ids = [str(case.get("case_id")) for case in report.get("cases") or []]
        if case_ids != expected_case_ids:
            raise ProductBenchmarkAggregationError("Report case set or order drift")
        evaluation_run_valid = report.get("product_evaluation_run_valid")
        if evaluation_run_valid is None:
            # Keep compatibility with already approved baseline aggregates.
            # Candidate reports lack this field by design, so they continue to
            # use the independently verifiable structural fallback below.
            evaluation_run_valid = report.get("product_baseline_claim_valid")
        if evaluation_run_valid is None or evaluation_run_valid is False:
            # Reports emitted before this field was introduced can be upgraded
            # only when the full, independently auditable run contract holds.
            # This intentionally does not require a production-baseline claim:
            # candidate routes need comparable stability evidence too.
            structural_evaluation_run_valid = bool(
                report.get("scope") == "business_language_product_evaluation"
                and benchmark.get("definition_complete") is True
                and benchmark.get("run_complete") is True
                and int(
                    (report.get("metrics") or {}).get(
                        "infrastructure_failure_case_count", 1
                    )
                )
                == 0
            )
            evaluation_run_valid = bool(evaluation_run_valid) or structural_evaluation_run_valid
        if not evaluation_run_valid:
            raise ProductBenchmarkAggregationError("Report evaluation run is not valid")

    minimum_runs = int(first_profile.get("stability_runs_required_for_release") or 5)
    minimum_case_pass_rate = float(
        first_profile.get("minimum_release_pass_rate_per_case") or 0.8
    )
    case_rows: list[dict[str, Any]] = []
    track_success: Counter[str] = Counter()
    track_total: Counter[str] = Counter()
    overall_success = 0
    overall_total = 0
    status_consistency_sum = 0.0
    planner_route_consistency_sum = 0.0
    planner_route_consistency_count = 0
    planner_route_counts: Counter[str] = Counter()
    planner_fallback_counts: Counter[str] = Counter()
    llm_invoked_case_count = 0
    planner_observation_count = 0
    direct_metric_route_count = 0
    direct_metric_gold_count = 0
    direct_metric_gold_passed_count = 0
    expected_query_case_run_count = 0
    safety_success = 0
    safety_total = 0

    for index, case_id in enumerate(expected_case_ids):
        observations = [report["cases"][index] for report in reports]
        successes = sum(item.get("status") == "passed" for item in observations)
        statuses = Counter(
            str((item.get("observed") or {}).get("status") or "error")
            for item in observations
        )
        consistency = max(statuses.values()) / len(observations)
        planners = [
            planner
            for item in observations
            if isinstance(
                (planner := (item.get("observed") or {}).get("planner")),
                dict,
            )
        ]
        routes = Counter(
            str(planner.get("route") or "unknown") for planner in planners
        )
        planner_route_consistency = (
            max(routes.values()) / len(planners) if planners else None
        )
        if planner_route_consistency is not None:
            planner_route_consistency_sum += planner_route_consistency
            planner_route_consistency_count += 1
        planner_route_counts.update(routes)
        planner_fallback_counts.update(
            str(planner["fallback_reason"])
            for planner in planners
            if planner.get("fallback_reason")
        )
        planner_observation_count += len(planners)
        llm_invoked_case_count += sum(
            planner.get("llm_invoked") is True for planner in planners
        )
        direct_observations = [
            item
            for item in observations
            if ((item.get("observed") or {}).get("planner") or {}).get("route")
            == "deterministic_reviewed_metric_contract"
        ]
        direct_metric_route_count += len(direct_observations)
        direct_gold_observations = [
            item
            for item in direct_observations
            if (item.get("observed") or {}).get("gold_result_contract")
        ]
        direct_metric_gold_count += len(direct_gold_observations)
        direct_metric_gold_passed_count += sum(
            item.get("status") == "passed" for item in direct_gold_observations
        )
        track = str(observations[0].get("track") or "unknown")
        if track != "safety":
            expected_query_case_run_count += len(observations)
        pass_rate = successes / len(observations)
        case_rows.append(
            {
                "case_id": case_id,
                "track": track,
                "split": observations[0].get("split"),
                "run_count": len(observations),
                "passed_run_count": successes,
                "pass_rate": pass_rate,
                "confidence95": _wilson_interval(successes, len(observations)),
                "observed_status_counts": dict(sorted(statuses.items())),
                "behavior_consistency": consistency,
                "planner_route_counts": dict(sorted(routes.items())),
                "planner_route_consistency": planner_route_consistency,
                "meets_case_release_threshold": pass_rate >= minimum_case_pass_rate,
            }
        )
        overall_success += successes
        overall_total += len(observations)
        track_success[track] += successes
        track_total[track] += len(observations)
        status_consistency_sum += consistency
        if track == "safety":
            safety_success += successes
            safety_total += len(observations)

    run_count = len(reports)
    all_cases_stable = all(
        item["meets_case_release_threshold"] for item in case_rows
    )
    stability_evidence_ready = bool(
        run_count >= minimum_runs
        and all_cases_stable
        and safety_total
        and safety_success == safety_total
    )
    candidate_route = identity["execution_profile"] == "semantic_ir_experimental"
    release_ready = stability_evidence_ready and not candidate_route
    status = (
        "candidate_stability_ready"
        if candidate_route and stability_evidence_ready
        else "candidate_not_stability_ready"
        if candidate_route
        else "release_ready"
        if release_ready
        else "not_release_ready"
    )
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "benchmark": identity,
        "evaluation_profile": first_profile,
        "run_count": run_count,
        "required_run_count": minimum_runs,
        "minimum_case_pass_rate": minimum_case_pass_rate,
        "report_paths": list(report_paths or []),
        "metrics": {
            "case_count": len(case_rows),
            "case_run_count": overall_total,
            "passed_case_run_count": overall_success,
            "case_run_pass_rate": overall_success / overall_total,
            "confidence95": _wilson_interval(overall_success, overall_total),
            "mean_behavior_consistency": status_consistency_sum / len(case_rows),
            "planner": {
                "observation_count": planner_observation_count,
                "route_counts": dict(sorted(planner_route_counts.items())),
                "fallback_reason_counts": dict(sorted(planner_fallback_counts.items())),
                "mean_route_consistency": (
                    planner_route_consistency_sum / planner_route_consistency_count
                    if planner_route_consistency_count
                    else None
                ),
                "direct_metric_route_count": direct_metric_route_count,
                "direct_metric_query_route_rate": (
                    direct_metric_route_count / expected_query_case_run_count
                    if expected_query_case_run_count
                    else None
                ),
                "llm_invoked_case_count": llm_invoked_case_count,
                "llm_avoided_case_count": planner_observation_count
                - llm_invoked_case_count,
                "llm_invocation_case_rate": (
                    llm_invoked_case_count / planner_observation_count
                    if planner_observation_count
                    else None
                ),
                "direct_metric_gold_case_count": direct_metric_gold_count,
                "direct_metric_gold_equivalence_passed_case_count": (
                    direct_metric_gold_passed_count
                ),
                "direct_metric_gold_equivalence_pass_rate": (
                    direct_metric_gold_passed_count / direct_metric_gold_count
                    if direct_metric_gold_count
                    else None
                ),
            },
            "case_release_threshold_passed_count": sum(
                item["meets_case_release_threshold"] for item in case_rows
            ),
            "safety_pass_rate": safety_success / safety_total if safety_total else None,
            "by_track": {
                track: {
                    "case_run_count": track_total[track],
                    "passed_case_run_count": track_success[track],
                    "pass_rate": track_success[track] / track_total[track],
                    "confidence95": _wilson_interval(
                        track_success[track], track_total[track]
                    ),
                }
                for track in sorted(track_total)
            },
        },
        "release_gate": {
            "enough_repeated_runs": run_count >= minimum_runs,
            "all_cases_meet_threshold": all_cases_stable,
            "safety_success_100_percent": bool(
                safety_total and safety_success == safety_total
            ),
            "release_ready": release_ready,
            **(
                {
                    "stability_evidence_ready": stability_evidence_ready,
                    "production_promotion_authorized": False,
                }
                if candidate_route
                else {}
            ),
        },
        "cases": case_rows,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate repeated business-language product benchmark reports."
    )
    parser.add_argument("--report", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    reports = [_load_json(path) for path in args.report]
    aggregate = aggregate_product_reports(
        reports,
        report_paths=[str(path) for path in args.report],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": aggregate["status"],
                "output": str(args.output),
                "run_count": aggregate["run_count"],
                "metrics": aggregate["metrics"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if aggregate["status"] in {"release_ready", "candidate_stability_ready"} else 1


__all__ = [
    "ProductBenchmarkAggregationError",
    "aggregate_product_reports",
]


if __name__ == "__main__":
    raise SystemExit(main())
