#!/usr/bin/env python3
"""Apply the versioned NL2SQL model profile thresholds to an analysis report.

This is a release gate, not an accuracy generator.  It keeps deterministic
reviewed-contract results visible while making the promotion decision from
model-evaluable Gold, refusal, and execution metrics only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_agent.nl2sql_model_profile import profile_for_model  # noqa: E402


def _ratio(passed: int | float | None, total: int | float | None) -> float | None:
    if total in (None, 0):
        return None
    return float(passed or 0) / float(total)


def _refusal_gate(
    metrics: dict,
    refusal: dict,
    thresholds: dict,
) -> tuple[dict[str, bool], dict[str, bool]]:
    """Evaluate refusal metrics without treating an empty class as failure.

    Precision is applicable when the model emitted at least one refusal;
    recall is applicable when the cohort contains at least one expected
    refusal.  A route with neither is neutral for both checks.  Unexpected
    refusals still make precision applicable and fail it, while a missed
    expected refusal still makes recall applicable and fail it.
    """

    expected = metrics.get("expected_refusals")
    observed = metrics.get("observed_refusals")
    if observed is None:
        observed = (metrics.get("actual_status_counts") or {}).get("rejected")
    precision = refusal.get("precision")
    recall = refusal.get("recall")
    precision_applicable = (
        int(observed or 0) > 0 if observed is not None else precision is not None
    )
    recall_applicable = (
        int(expected or 0) > 0 if expected is not None else recall is not None
    )
    checks = {
        "refusal_precision": (
            not precision_applicable
            or (
                precision is not None
                and float(precision) >= thresholds["refusal_precision"]
            )
        ),
        "refusal_recall": (
            not recall_applicable
            or (
                recall is not None
                and float(recall) >= thresholds["refusal_recall"]
            )
        ),
    }
    return checks, {
        "refusal_precision": precision_applicable,
        "refusal_recall": recall_applicable,
    }


def evaluate(analysis: dict, model_name: str | None = None) -> dict:
    model = analysis.get("model") or {}
    requested = model_name or model.get("id") or model.get("name") or model.get("model")
    profile = profile_for_model(requested)
    thresholds = profile["minimum_benchmark_thresholds"]
    routes = []

    # Full analyses expose ``by_actual_route``.  Only the route named ``llm``
    # represents model-generated proposals; deterministic reviewed contracts,
    # answerability policies, and binding gates are intentionally not mixed
    # into the model denominator.  Smoke analyses use the same route name in
    # their ``summary`` list.
    route_entries = [
        item
        for item in (analysis.get("by_actual_route") or [])
        if isinstance(item, dict)
        and str(item.get("route") or item.get("planner_route") or "").casefold()
        in {"llm", "governed_free_form_llm", "semantic_ir_experimental_llm"}
    ]
    route_source = "actual_model_route"
    if not route_entries:
        route_entries = [
            item
            for item in (analysis.get("summary") or [])
            if isinstance(item, dict)
            and str(item.get("planner_route") or item.get("route") or "").casefold()
            in {"llm", "governed_free_form_llm", "semantic_ir_experimental_llm"}
        ]
    if route_entries:
        for index, metrics in enumerate(route_entries):
            source = str(metrics.get("source") or "unknown")
            key = "{}_{}_{}".format(
                source,
                metrics.get("profile") or metrics.get("execution_profile") or "unknown",
                metrics.get("route") or metrics.get("planner_route") or "llm",
            )
            gold_total = metrics.get("current_gold_case_count")
            if gold_total is None:
                gold_total = metrics.get("gold_case_count")
            gold_passed = metrics.get("gold_equivalent")
            if gold_passed is None:
                gold_passed = metrics.get("gold_contract_passed")
            refusal = metrics.get("refusal") or {}
            if not refusal:
                expected_refusals = int(metrics.get("expected_refusals") or 0)
                correct_refusals = int(metrics.get("correct_refusals") or 0)
                observed_refusals = int(
                    metrics.get("observed_refusals")
                    or (metrics.get("actual_status_counts") or {}).get("rejected")
                    or 0
                )
                false_positives = max(0, observed_refusals - correct_refusals)
                refusal = {
                    "precision": _ratio(correct_refusals, correct_refusals + false_positives),
                    "recall": _ratio(correct_refusals, expected_refusals),
                }
            execution_rate = metrics.get("query_execution_success_rate")
            source_kind = source if source in {"makani", "liveability"} else "liveability"
            gold_threshold = thresholds[
                "makani_gold_equivalence"
                if source_kind == "makani"
                else "liveability_gold_equivalence"
            ]
            gold_rate = _ratio(gold_passed, gold_total)
            refusal_checks, refusal_applicability = _refusal_gate(
                metrics, refusal, thresholds
            )
            checks = {
                "gold_equivalence": gold_rate is not None and gold_rate >= gold_threshold,
                **refusal_checks,
                "query_execution_success": execution_rate is not None and float(execution_rate) >= thresholds["query_execution_success"],
            }
            routes.append(
                {
                    "run_key": key,
                    "source": source,
                    "profile": metrics.get("profile") or metrics.get("execution_profile"),
                    "actual_route": metrics.get("route") or metrics.get("planner_route"),
                    "gold_rate": gold_rate,
                    "gold_denominator": gold_total,
                    "gold_passed": gold_passed,
                    "gold_threshold": gold_threshold,
                    "refusal_precision": refusal.get("precision"),
                    "refusal_recall": refusal.get("recall"),
                    "metric_applicability": refusal_applicability,
                    "query_execution_success_rate": execution_rate,
                    "mean_generation_latency_ms": metrics.get("mean_generation_latency_ms"),
                    "p95_generation_latency_ms": metrics.get("p95_generation_latency_ms"),
                    "checks": checks,
                    "promotable": all(checks.values()),
                }
            )
    else:
        # Backward compatibility for pre-route analyses.  Such reports cannot
        # prove deterministic exclusion because their metrics are mixed; keep
        # the result usable but label the source explicitly for operators.
        route_source = "legacy_mixed_raw_run_metrics"
        for key, metrics in sorted((analysis.get("raw_run_metrics") or {}).items()):
            source = "makani" if key.startswith("makani") else "liveability"
            gold_total = metrics.get("model_evaluable_gold_case_count")
            gold_passed = metrics.get("model_gold_equivalence_passed_case_count")
            gold_rate = _ratio(gold_passed, gold_total)
            refusal = metrics.get("refusal") or {}
            execution_rate = metrics.get("query_execution_success_rate")
            gold_threshold = thresholds[
                "makani_gold_equivalence" if source == "makani" else "liveability_gold_equivalence"
            ]
            refusal_checks, refusal_applicability = _refusal_gate(
                metrics, refusal, thresholds
            )
            checks = {
                "gold_equivalence": gold_rate is not None and gold_rate >= gold_threshold,
                **refusal_checks,
                "query_execution_success": execution_rate is not None and float(execution_rate) >= thresholds["query_execution_success"],
            }
            routes.append(
                {
                    "run_key": key,
                    "source": source,
                    "profile": key.split("_", 1)[1] if "_" in key else key,
                    "actual_route": None,
                    "gold_rate": gold_rate,
                    "gold_denominator": gold_total,
                    "gold_passed": gold_passed,
                    "gold_threshold": gold_threshold,
                    "refusal_precision": refusal.get("precision"),
                    "refusal_recall": refusal.get("recall"),
                    "metric_applicability": refusal_applicability,
                    "query_execution_success_rate": execution_rate,
                    "mean_generation_latency_ms": metrics.get("mean_generation_latency_ms"),
                    "p95_generation_latency_ms": metrics.get("p95_generation_latency_ms"),
                    "checks": checks,
                    "promotable": all(checks.values()),
                }
            )
    return {
        "schema": "gda.nl2sql-model-compatibility-gate.v1",
        "model": {
            "requested": requested,
            "actual_route": model.get("effective_route") or model.get("adk_route"),
            "profile": profile,
        },
        "source_of_truth": route_source,
        "deterministic_contracts_excluded_from_model_gate": True,
        "routes": routes,
        "promote": bool(routes) and all(item["promotable"] for item in routes),
        "decision": "promote" if routes and all(item["promotable"] for item in routes) else "canary_or_rollback",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.analysis.read_text(encoding="utf-8")), args.model)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if result["promote"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
