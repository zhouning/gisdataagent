"""Compare matched NL2Semantic2SQL baseline and candidate benchmark reports.

The evaluator deliberately separates reviewed metric-contract cases from
free-form cases.  A contract is an existing semantic-product capability shared
by both execution profiles, so it must never be presented as a candidate
compiler win.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from .free_form_nl2sql_benchmark import REPORT_SCHEMA

COMPARISON_SCHEMA = "gda.nl2semantic2sql-pairwise-comparison.v1"
STABILITY_COMPARISON_SCHEMA = "gda.nl2semantic2sql-pairwise-stability-comparison.v1"


class PairwiseComparisonError(ValueError):
    """Reports cannot support a fair paired comparison."""


def _load_report(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PairwiseComparisonError(f"report_unreadable:{path}") from exc
    if payload.get("schema") != REPORT_SCHEMA:
        raise PairwiseComparisonError(f"report_schema_unsupported:{path}")
    return payload


def _same(value: Any, other: Any, *, label: str) -> None:
    if value != other:
        raise PairwiseComparisonError(f"paired_configuration_mismatch:{label}")


def _case_map(report: dict[str, Any], *, label: str) -> dict[str, dict[str, Any]]:
    cases = report.get("cases") or []
    mapped = {str(case.get("case_id") or ""): case for case in cases}
    if not mapped or "" in mapped or len(mapped) != len(cases):
        raise PairwiseComparisonError(f"report_case_ids_invalid:{label}")
    return mapped


def _contract_id(case: dict[str, Any]) -> str | None:
    contract = (case.get("observed") or {}).get("semantic_metric_contract") or {}
    contract_id = str(contract.get("contract_id") or "").strip()
    return contract_id or None


def _case_category(baseline: dict[str, Any], candidate: dict[str, Any]) -> str:
    baseline_contract = _contract_id(baseline)
    candidate_contract = _contract_id(candidate)
    if baseline_contract or candidate_contract:
        if baseline_contract == candidate_contract and baseline_contract:
            return "reviewed_metric_contract_control"
        return "routing_mismatch"
    if str(baseline.get("track") or "") == "safety":
        return "free_form_safety"
    return "free_form_query"


def _evaluation_bucket(baseline: dict[str, Any], candidate: dict[str, Any]) -> str:
    """Return the benchmark-defined evaluation bucket for a paired case."""

    baseline_bucket = str(baseline.get("evaluation_bucket") or "")
    candidate_bucket = str(candidate.get("evaluation_bucket") or "")
    if baseline_bucket and candidate_bucket and baseline_bucket != candidate_bucket:
        return "routing_mismatch"
    bucket = baseline_bucket or candidate_bucket
    if bucket in {"business_language", "technical_catalog_control", "safety"}:
        return bucket
    # Reports written before explicit bucket fields remain comparable. Their
    # safety track is still separable; all remaining non-control cases are
    # treated as business-language evidence rather than silently dropped.
    if str(baseline.get("track") or "") == "safety":
        return "safety"
    return "business_language"


def _outcome(baseline: dict[str, Any], candidate: dict[str, Any]) -> str:
    baseline_passed = baseline.get("status") == "passed"
    candidate_passed = candidate.get("status") == "passed"
    if baseline_passed and candidate_passed:
        return "both_passed"
    if baseline_passed:
        return "baseline_only_passed"
    if candidate_passed:
        return "candidate_only_passed"
    return "both_failed"


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3)


def _paired_generation_evidence(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize only pairs where both routes called a model.

    Contract controls and deterministic safety refusals intentionally have no
    generation latency. Including them would make the compiler look faster by
    counting work that neither route performed.
    """

    pairs = [
        case
        for case in cases
        if isinstance(case["baseline"].get("generation_latency_ms"), (int, float))
        and isinstance(case["candidate"].get("generation_latency_ms"), (int, float))
    ]
    baseline_latencies = [
        float(case["baseline"]["generation_latency_ms"])
        for case in pairs
    ]
    candidate_latencies = [
        float(case["candidate"]["generation_latency_ms"])
        for case in pairs
    ]
    latency_deltas = [
        candidate - baseline
        for baseline, candidate in zip(baseline_latencies, candidate_latencies, strict=True)
    ]
    usage_keys = ("input_tokens", "output_tokens", "reasoning_tokens")
    usage: dict[str, dict[str, float | int | None]] = {}
    for key in usage_keys:
        baseline_values = [
            int((case["baseline"].get("usage") or {}).get(key) or 0)
            for case in pairs
        ]
        candidate_values = [
            int((case["candidate"].get("usage") or {}).get(key) or 0)
            for case in pairs
        ]
        usage[key] = {
            "baseline_total": sum(baseline_values),
            "candidate_total": sum(candidate_values),
            "candidate_minus_baseline_total": sum(candidate_values) - sum(baseline_values),
            "baseline_mean": _mean([float(value) for value in baseline_values]),
            "candidate_mean": _mean([float(value) for value in candidate_values]),
            "candidate_minus_baseline_mean": _mean(
                [
                    float(candidate - baseline)
                    for baseline, candidate in zip(
                        baseline_values,
                        candidate_values,
                        strict=True,
                    )
                ]
            ),
        }
    return {
        "paired_model_generation_case_count": len(pairs),
        "baseline_mean_generation_latency_ms": _mean(baseline_latencies),
        "candidate_mean_generation_latency_ms": _mean(candidate_latencies),
        "candidate_minus_baseline_mean_generation_latency_ms": _mean(latency_deltas),
        "baseline_p95_generation_latency_ms": _p95(baseline_latencies),
        "candidate_p95_generation_latency_ms": _p95(candidate_latencies),
        "usage": usage,
    }


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = Counter(str(case["outcome"]) for case in cases)
    baseline_passed = sum(case["baseline"]["passed"] for case in cases)
    candidate_passed = sum(case["candidate"]["passed"] for case in cases)
    baseline_gold = [case for case in cases if case["baseline"]["gold_equivalent"] is not None]
    candidate_gold = [case for case in cases if case["candidate"]["gold_equivalent"] is not None]
    return {
        "case_count": len(cases),
        "outcome_counts": dict(sorted(outcomes.items())),
        "baseline_passed_case_count": baseline_passed,
        "candidate_passed_case_count": candidate_passed,
        "baseline_pass_rate": baseline_passed / len(cases) if cases else None,
        "candidate_pass_rate": candidate_passed / len(cases) if cases else None,
        "candidate_minus_baseline_pass_rate": (
            (candidate_passed - baseline_passed) / len(cases) if cases else None
        ),
        "baseline_gold_equivalence_passed_case_count": sum(
            case["baseline"]["gold_equivalent"] is True for case in baseline_gold
        ),
        "candidate_gold_equivalence_passed_case_count": sum(
            case["candidate"]["gold_equivalent"] is True for case in candidate_gold
        ),
        "baseline_gold_equivalence_pass_rate": (
            sum(case["baseline"]["gold_equivalent"] is True for case in baseline_gold)
            / len(baseline_gold)
            if baseline_gold
            else None
        ),
        "candidate_gold_equivalence_pass_rate": (
            sum(case["candidate"]["gold_equivalent"] is True for case in candidate_gold)
            / len(candidate_gold)
            if candidate_gold
            else None
        ),
        "paired_generation": _paired_generation_evidence(cases),
    }


def _case_evidence(case: dict[str, Any]) -> dict[str, Any]:
    observed = case.get("observed") or {}
    generation = observed.get("generation") or {}
    usage = generation.get("usage") or {}
    checks = case.get("checks") or {}
    plan = observed.get("semantic_plan") or {}
    return {
        "passed": case.get("status") == "passed",
        "business_language_eligible": case.get("business_language_eligible"),
        "evaluation_bucket": case.get("evaluation_bucket"),
        "provenance_kind": case.get("provenance_kind"),
        "observed_status": observed.get("status"),
        "gold_equivalent": checks.get("gold_result_equivalence_match"),
        "planner_route": (observed.get("planner") or {}).get("route"),
        "semantic_plan_authority": plan.get("authority"),
        "semantic_plan_schema": plan.get("schema_id"),
        "generation_latency_ms": generation.get("latency_ms"),
        "usage": {
            key: int(usage.get(key) or 0)
            for key in ("input_tokens", "output_tokens", "reasoning_tokens")
        },
    }


def _validate_pair(baseline: dict[str, Any], candidate: dict[str, Any]) -> None:
    baseline_benchmark = baseline.get("benchmark") or {}
    candidate_benchmark = candidate.get("benchmark") or {}
    if baseline_benchmark.get("execution_profile") != "baseline_sql":
        raise PairwiseComparisonError("baseline_execution_profile_invalid")
    if candidate_benchmark.get("execution_profile") != "semantic_ir_experimental":
        raise PairwiseComparisonError("candidate_execution_profile_invalid")
    for key in (
        "benchmark_id",
        "version",
        "source_file_sha256",
        "semantic_layer_version",
        "metric_contract_version",
        "request_interval_seconds",
        "max_concurrency",
        "selected_case_ids",
    ):
        _same(baseline_benchmark.get(key), candidate_benchmark.get(key), label=key)
    for key in (
        "source_id",
        "owner",
        "database_name",
        "authorized_schemas",
        "discovery_fingerprint",
        "profile_fingerprint",
        "execution_mode",
    ):
        _same(
            (baseline.get("source") or {}).get(key),
            (candidate.get("source") or {}).get(key),
            label=f"source.{key}",
        )
    for key in ("requested", "reasoning_effort"):
        _same(
            (baseline.get("model") or {}).get(key),
            (candidate.get("model") or {}).get(key),
            label=f"model.{key}",
        )
    _same(
        set(_case_map(baseline, label="baseline")),
        set(_case_map(candidate, label="candidate")),
        label="case_ids",
    )


def compare_reports(
    *,
    baseline_reports: list[Path],
    candidate_reports: list[Path],
) -> dict[str, Any]:
    """Return an auditable comparison for one or more non-overlapping pairs."""

    if len(baseline_reports) != len(candidate_reports) or not baseline_reports:
        raise PairwiseComparisonError("paired_report_count_invalid")

    cases: list[dict[str, Any]] = []
    seen_case_keys: set[tuple[int, str]] = set()
    pair_metadata: list[dict[str, Any]] = []
    for baseline_path, candidate_path in zip(baseline_reports, candidate_reports, strict=True):
        baseline = _load_report(baseline_path)
        candidate = _load_report(candidate_path)
        _validate_pair(baseline, candidate)
        baseline_cases = _case_map(baseline, label="baseline")
        candidate_cases = _case_map(candidate, label="candidate")
        source_id = int((baseline.get("source") or {}).get("source_id") or 0)
        selected_case_ids = list((baseline.get("benchmark") or {}).get("selected_case_ids") or [])
        pair_metadata.append(
            {
                "baseline_report": str(baseline_path),
                "candidate_report": str(candidate_path),
                "benchmark_id": (baseline.get("benchmark") or {}).get("benchmark_id"),
                "source_id": source_id,
                "database_name": (baseline.get("source") or {}).get("database_name"),
                "baseline_prompt_version": (baseline.get("benchmark") or {}).get("prompt_version"),
                "candidate_prompt_version": (candidate.get("benchmark") or {}).get(
                    "prompt_version"
                ),
                "selected_case_ids": selected_case_ids,
            }
        )
        for case_id in selected_case_ids:
            key = (source_id, case_id)
            if key in seen_case_keys:
                raise PairwiseComparisonError(f"duplicate_case_across_pairs:{source_id}:{case_id}")
            seen_case_keys.add(key)
            baseline_case = baseline_cases[case_id]
            candidate_case = candidate_cases[case_id]
            baseline_bucket = baseline_case.get("evaluation_bucket")
            candidate_bucket = candidate_case.get("evaluation_bucket")
            if baseline_bucket and candidate_bucket and baseline_bucket != candidate_bucket:
                raise PairwiseComparisonError(
                    f"evaluation_bucket_mismatch:{source_id}:{case_id}"
                )
            category = _case_category(baseline_case, candidate_case)
            cases.append(
                {
                    "source_id": source_id,
                    "database_name": (baseline.get("source") or {}).get("database_name"),
                    "case_id": case_id,
                    "language": baseline_case.get("language"),
                    "track": baseline_case.get("track"),
                    "split": baseline_case.get("split"),
                    "category": category,
                    "evaluation_bucket": _evaluation_bucket(baseline_case, candidate_case),
                    "metric_contract_id": _contract_id(baseline_case)
                    or _contract_id(candidate_case),
                    "outcome": _outcome(baseline_case, candidate_case),
                    "baseline": _case_evidence(baseline_case),
                    "candidate": _case_evidence(candidate_case),
                }
            )

    by_category = {
        category: _summary([case for case in cases if case["category"] == category])
        for category in sorted({case["category"] for case in cases})
    }
    by_evaluation_bucket = {
        bucket: _summary(
            [case for case in cases if case["evaluation_bucket"] == bucket]
        )
        for bucket in sorted({case["evaluation_bucket"] for case in cases})
    }
    return {
        "schema": COMPARISON_SCHEMA,
        "status": "passed",
        "release_gate": False,
        "comparison_role": "candidate_canary_vs_current_production_baseline",
        "paired_configuration_verified": True,
        "pair_count": len(pair_metadata),
        "pairs": pair_metadata,
        "metrics": {
            "all_matched_cases": _summary(cases),
            "by_category": by_category,
            "by_evaluation_bucket": by_evaluation_bucket,
            "business_language_product_comparison": _summary(
                [case for case in cases if case["evaluation_bucket"] == "business_language"]
            ),
            "technical_catalog_control_comparison": _summary(
                [
                    case
                    for case in cases
                    if case["evaluation_bucket"] == "technical_catalog_control"
                ]
            ),
            "safety_comparison": _summary(
                [case for case in cases if case["evaluation_bucket"] == "safety"]
            ),
            "free_form_route_comparison": _summary(
                [
                    case
                    for case in cases
                    if case["category"] in {"free_form_query", "free_form_safety"}
                ]
            ),
        },
        "cases": cases,
        "limitations": [
            "Reviewed metric-contract controls are reported separately and do not "
            "evidence a candidate compiler advantage.",
            "A paired single run is not a release decision; use the frozen full "
            "benchmark and repeated stability runs before promotion.",
            "The comparison contains status, fingerprints, plan authority, timing, "
            "and token evidence only; it does not contain source result rows, Gold "
            "results, or SQL text.",
        ],
    }


def _load_comparison(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PairwiseComparisonError(f"comparison_unreadable:{path}") from exc
    if payload.get("schema") != COMPARISON_SCHEMA:
        raise PairwiseComparisonError(f"comparison_schema_unsupported:{path}")
    if payload.get("status") != "passed":
        raise PairwiseComparisonError(f"comparison_status_invalid:{path}")
    return payload


def aggregate_pairwise_comparisons(
    comparisons: list[dict[str, Any]],
    *,
    comparison_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate repeated, already validated pairwise comparisons.

    Single-run pair comparisons deliberately reject duplicate source/case keys.
    This separate aggregation consumes those immutable pair outputs and treats
    duplicate keys as repeated observations, preserving every run's evidence.
    """

    if not comparisons:
        raise PairwiseComparisonError("pairwise_comparison_reports_required")

    observations: list[dict[str, Any]] = []
    pair_observation_keys: set[tuple[str, str]] = set()
    runs_by_source: Counter[str] = Counter()
    for comparison in comparisons:
        if comparison.get("schema") != COMPARISON_SCHEMA:
            raise PairwiseComparisonError("comparison_schema_unsupported")
        if comparison.get("status") != "passed":
            raise PairwiseComparisonError("comparison_status_invalid")
        if comparison.get("comparison_role") != "candidate_canary_vs_current_production_baseline":
            raise PairwiseComparisonError("comparison_role_invalid")
        pairs = comparison.get("pairs") or []
        cases = comparison.get("cases") or []
        if not pairs or not cases:
            raise PairwiseComparisonError("comparison_evidence_missing")
        for pair in pairs:
            key = (
                str(pair.get("baseline_report") or ""),
                str(pair.get("candidate_report") or ""),
            )
            if not all(key) or key in pair_observation_keys:
                raise PairwiseComparisonError("duplicate_or_invalid_pair_observation")
            pair_observation_keys.add(key)
            runs_by_source[str(pair.get("source_id") or "unknown")] += 1
        observations.extend(cases)

    grouped: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for observation in observations:
        source_id = int(observation.get("source_id") or 0)
        case_id = str(observation.get("case_id") or "")
        if source_id <= 0 or not case_id:
            raise PairwiseComparisonError("comparison_case_identity_invalid")
        grouped.setdefault((source_id, case_id), []).append(observation)

    case_rows: list[dict[str, Any]] = []
    for (source_id, case_id), case_observations in sorted(grouped.items()):
        first = case_observations[0]
        for observation in case_observations[1:]:
            for key in ("database_name", "language", "track", "split", "category"):
                _same(observation.get(key), first.get(key), label=f"case.{source_id}.{case_id}.{key}")
        outcomes = Counter(str(item.get("outcome") or "unknown") for item in case_observations)
        case_rows.append(
            {
                "source_id": source_id,
                "database_name": first.get("database_name"),
                "case_id": case_id,
                "language": first.get("language"),
                "track": first.get("track"),
                "split": first.get("split"),
                "category": first.get("category"),
                "observation_count": len(case_observations),
                "outcome_counts": dict(sorted(outcomes.items())),
                "all_observations_both_passed": outcomes.get("both_passed", 0)
                == len(case_observations),
            }
        )

    all_matched = _summary(observations)
    outcomes = Counter(str(item.get("outcome") or "unknown") for item in observations)
    candidate_wins = outcomes.get("candidate_only_passed", 0)
    baseline_wins = outcomes.get("baseline_only_passed", 0)
    all_both_passed = outcomes.get("both_passed", 0) == len(observations)
    return {
        "schema": STABILITY_COMPARISON_SCHEMA,
        "status": "passed",
        "comparison_role": "candidate_canary_vs_current_production_baseline",
        "pairwise_comparison_count": len(comparisons),
        "comparison_paths": list(comparison_paths or []),
        "runs_by_source": dict(sorted(runs_by_source.items())),
        "metrics": {
            "all_matched_observations": all_matched,
            "by_category": {
                category: _summary(
                    [item for item in observations if item.get("category") == category]
                )
                for category in sorted({str(item.get("category") or "unknown") for item in observations})
            },
            "outcome_counts": dict(sorted(outcomes.items())),
            "case_stability": {
                "distinct_source_case_count": len(case_rows),
                "all_cases_both_passed_on_every_observation": all(
                    item["all_observations_both_passed"] for item in case_rows
                ),
            },
        },
        "candidate_promotion_assessment": {
            "promotion_supported": False,
            "candidate_only_passed_observation_count": candidate_wins,
            "baseline_only_passed_observation_count": baseline_wins,
            "reason": (
                "no_measured_candidate_accuracy_advantage"
                if candidate_wins == baseline_wins
                else "candidate_promotion_requires_broader_predeclared_evidence"
            ),
            "all_observations_both_passed": all_both_passed,
        },
        "cases": case_rows,
        "limitations": [
            "This summarizes only supplied, prevalidated pairwise reports; it does not establish full-database coverage.",
            "Reviewed metric-contract controls remain controls, not candidate compiler advantage evidence.",
            "Candidate stability or a tie does not authorize production promotion.",
        ],
    }
def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gda-nl2semantic2sql-pairwise-compare",
        description="Compare matched NL2Semantic2SQL baseline and candidate reports.",
    )
    parser.add_argument("--baseline-report", type=Path, action="append")
    parser.add_argument("--candidate-report", type=Path, action="append")
    parser.add_argument("--pairwise-report", type=Path, action="append")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.pairwise_report:
            if args.baseline_report or args.candidate_report:
                raise PairwiseComparisonError("pairwise_aggregation_arguments_mixed")
            comparison = aggregate_pairwise_comparisons(
                [_load_comparison(path) for path in args.pairwise_report],
                comparison_paths=[str(path) for path in args.pairwise_report],
            )
        elif args.baseline_report and args.candidate_report:
            comparison = compare_reports(
                baseline_reports=list(args.baseline_report),
                candidate_reports=list(args.candidate_report),
            )
        else:
            raise PairwiseComparisonError("baseline_and_candidate_reports_required")
    except PairwiseComparisonError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "passed", "output": str(args.output)}, ensure_ascii=False))
    return 0


__all__ = [
    "COMPARISON_SCHEMA",
    "STABILITY_COMPARISON_SCHEMA",
    "PairwiseComparisonError",
    "aggregate_pairwise_comparisons",
    "compare_reports",
]


if __name__ == "__main__":
    raise SystemExit(main())
