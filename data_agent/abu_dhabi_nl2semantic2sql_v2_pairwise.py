"""Fair paired comparison for Abu Dhabi NL2Semantic2SQL v2 reports."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from .abu_dhabi_nl2semantic2sql_v2_evaluator import REPORT_SCHEMA

COMPARISON_SCHEMA = "gda.abu-dhabi-nl2semantic2sql-v2-pairwise.v1"


class V2PairwiseComparisonError(ValueError):
    """Two reports do not form a controlled paired experiment."""


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise V2PairwiseComparisonError(f"report_unreadable:{path}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != REPORT_SCHEMA:
        raise V2PairwiseComparisonError(f"report_schema_invalid:{path}")
    return payload


def _same(left: Any, right: Any, label: str) -> None:
    if left != right:
        raise V2PairwiseComparisonError(f"paired_configuration_mismatch:{label}")


def _case_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cases = list(report.get("cases") or [])
    mapped = {str(item.get("case_id") or ""): item for item in cases}
    if not mapped or "" in mapped or len(mapped) != len(cases):
        raise V2PairwiseComparisonError("report_case_ids_invalid")
    return mapped


def _contract_id(case: dict[str, Any]) -> str | None:
    contract = (case.get("observed") or {}).get("semantic_metric_contract") or {}
    value = str(contract.get("contract_id") or "").strip()
    return value or None


def _category(baseline: dict[str, Any], candidate: dict[str, Any]) -> str:
    if str(baseline.get("scope") or "") == "federated":
        return "federated_shared_control"
    if str(baseline.get("expected_outcome") or "") != "execute":
        return "admission_policy_shared_control"
    baseline_contract = _contract_id(baseline)
    candidate_contract = _contract_id(candidate)
    if baseline_contract or candidate_contract:
        if baseline_contract and baseline_contract == candidate_contract:
            return "reviewed_metric_contract_shared_control"
        return "route_or_contract_mismatch"
    return "single_source_free_form_route"


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


def _route_evidence(case: dict[str, Any]) -> dict[str, Any]:
    observed = case.get("observed") or {}
    generation = observed.get("generation") or {}
    usage = generation.get("usage") or {}
    semantic_plan = observed.get("semantic_plan") or {}
    validation = semantic_plan.get("validation") or {}
    checks = case.get("checks") or {}
    return {
        "passed": case.get("status") == "passed",
        "observed_status": observed.get("status"),
        "observed_outcome": observed.get("outcome"),
        "planner_route": observed.get("planner_route"),
        "llm_invoked": observed.get("llm_invoked"),
        "result_equivalent": checks.get("result_equivalent"),
        "failure_reasons": list(case.get("failure_reasons") or []),
        "error": observed.get("error"),
        "metric_contract_id": _contract_id(case),
        "semantic_plan_status": semantic_plan.get("status"),
        "semantic_plan_valid": validation.get("valid"),
        "semantic_plan_execution_authority": semantic_plan.get("execution_authority"),
        "generation_latency_ms": generation.get("latency_ms"),
        "usage": {
            key: int(usage.get(key) or 0)
            for key in ("input_tokens", "output_tokens", "reasoning_tokens")
        },
        "observed_model_versions": list(generation.get("observed_model_versions") or []),
    }


def _generation_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    pairs = [
        item
        for item in cases
        if isinstance(item["baseline"].get("generation_latency_ms"), (int, float))
        and isinstance(item["candidate"].get("generation_latency_ms"), (int, float))
    ]
    baseline_latency = [float(item["baseline"]["generation_latency_ms"]) for item in pairs]
    candidate_latency = [float(item["candidate"]["generation_latency_ms"]) for item in pairs]
    usage: dict[str, Any] = {}
    for key in ("input_tokens", "output_tokens", "reasoning_tokens"):
        baseline_values = [int(item["baseline"]["usage"].get(key) or 0) for item in pairs]
        candidate_values = [int(item["candidate"]["usage"].get(key) or 0) for item in pairs]
        usage[key] = {
            "baseline_total": sum(baseline_values),
            "candidate_total": sum(candidate_values),
            "candidate_minus_baseline_total": sum(candidate_values) - sum(baseline_values),
        }
    return {
        "paired_model_generation_case_count": len(pairs),
        "baseline_mean_latency_ms": _mean(baseline_latency),
        "candidate_mean_latency_ms": _mean(candidate_latency),
        "candidate_minus_baseline_mean_latency_ms": _mean(
            [right - left for left, right in zip(baseline_latency, candidate_latency, strict=True)]
        ),
        "baseline_p95_latency_ms": _p95(baseline_latency),
        "candidate_p95_latency_ms": _p95(candidate_latency),
        "usage": usage,
    }


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_passed = sum(item["baseline"]["passed"] for item in cases)
    candidate_passed = sum(item["candidate"]["passed"] for item in cases)
    execute = [item for item in cases if item["expected_outcome"] == "execute"]
    return {
        "case_count": len(cases),
        "baseline_passed_case_count": baseline_passed,
        "candidate_passed_case_count": candidate_passed,
        "baseline_pass_rate": baseline_passed / len(cases) if cases else None,
        "candidate_pass_rate": candidate_passed / len(cases) if cases else None,
        "candidate_minus_baseline_pass_rate": (
            (candidate_passed - baseline_passed) / len(cases) if cases else None
        ),
        "baseline_execute_result_equivalent_count": sum(
            item["baseline"].get("result_equivalent") is True for item in execute
        ),
        "candidate_execute_result_equivalent_count": sum(
            item["candidate"].get("result_equivalent") is True for item in execute
        ),
        "outcome_counts": dict(sorted(Counter(item["outcome"] for item in cases).items())),
        "baseline_failure_class_counts": dict(
            sorted(
                Counter(
                    reason for item in cases for reason in item["baseline"]["failure_reasons"]
                ).items()
            )
        ),
        "candidate_failure_class_counts": dict(
            sorted(
                Counter(
                    reason for item in cases for reason in item["candidate"]["failure_reasons"]
                ).items()
            )
        ),
        "candidate_valid_ir_but_wrong_result_count": sum(
            item["candidate"].get("semantic_plan_valid") is True
            and item["candidate"].get("observed_status") == "ok"
            and item["candidate"].get("result_equivalent") is False
            for item in execute
        ),
        "paired_generation": _generation_summary(cases),
    }


def compare_v2_reports(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    baseline_path: str | None = None,
    candidate_path: str | None = None,
) -> dict[str, Any]:
    if baseline.get("execution_profile") != "baseline_sql":
        raise V2PairwiseComparisonError("baseline_execution_profile_invalid")
    if candidate.get("execution_profile") != "semantic_ir_experimental":
        raise V2PairwiseComparisonError("candidate_execution_profile_invalid")
    for key in (
        "evaluation_scope",
        "public_benchmark",
        "private_gold",
        "semantic_configuration",
    ):
        _same(baseline.get(key), candidate.get(key), key)
    semantic_configuration = baseline.get("semantic_configuration") or {}
    if set(semantic_configuration) != {"liveability", "makani"} or any(
        len(str((semantic_configuration.get(source) or {}).get("sha256") or "")) != 64
        for source in ("liveability", "makani")
    ):
        raise V2PairwiseComparisonError("semantic_configuration_invalid")
    _same(
        baseline.get("runtime_isolation"),
        candidate.get("runtime_isolation"),
        "runtime_isolation",
    )
    baseline_cases = _case_map(baseline)
    candidate_cases = _case_map(candidate)
    _same(set(baseline_cases), set(candidate_cases), "case_ids")

    cases: list[dict[str, Any]] = []
    selected = list((baseline.get("public_benchmark") or {}).get("selected_case_ids") or [])
    for case_id in selected:
        left = baseline_cases[str(case_id)]
        right = candidate_cases[str(case_id)]
        for key in ("scope", "language", "split", "family", "expected_outcome"):
            _same(left.get(key), right.get(key), f"case.{case_id}.{key}")
        cases.append(
            {
                "case_id": case_id,
                "scope": left.get("scope"),
                "language": left.get("language"),
                "split": left.get("split"),
                "family": left.get("family"),
                "expected_outcome": left.get("expected_outcome"),
                "category": _category(left, right),
                "outcome": _outcome(left, right),
                "baseline": _route_evidence(left),
                "candidate": _route_evidence(right),
            }
        )

    categories = sorted({item["category"] for item in cases})
    route_cases = [
        item
        for item in cases
        if item["category"]
        in {
            "single_source_free_form_route",
            "route_or_contract_mismatch",
        }
    ]
    candidate_wins = sum(item["outcome"] == "candidate_only_passed" for item in route_cases)
    baseline_wins = sum(item["outcome"] == "baseline_only_passed" for item in route_cases)
    return {
        "schema": COMPARISON_SCHEMA,
        "status": "passed",
        "paired_configuration_verified": True,
        "comparison_role": "semantic_ir_candidate_vs_baseline_sql",
        "baseline_report": baseline_path,
        "candidate_report": candidate_path,
        "metrics": {
            "all_cases": _summary(cases),
            "route_comparison": _summary(route_cases),
            "by_category": {
                category: _summary([item for item in cases if item["category"] == category])
                for category in categories
            },
        },
        "candidate_promotion_assessment": {
            "promotion_supported": False,
            "candidate_only_passed_case_count": candidate_wins,
            "baseline_only_passed_case_count": baseline_wins,
            "reason": (
                "candidate_does_not_outperform_baseline"
                if candidate_wins <= baseline_wins
                else "single_run_advantage_requires_repeated_stability_evidence"
            ),
        },
        "cases": cases,
        "limitations": [
            "Federated and admission-policy cases are shared controls, not compiler advantage evidence.",
            "A shared reviewed metric contract is a control even when both profiles execute it.",
            "No production promotion is authorized by one paired run.",
            "The comparison contains no questions, SQL, source rows, or private Gold fingerprints.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-report", type=Path, required=True)
    parser.add_argument("--candidate-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = compare_v2_reports(
            _load(args.baseline_report),
            _load(args.candidate_report),
            baseline_path=str(args.baseline_report),
            candidate_path=str(args.candidate_report),
        )
    except V2PairwiseComparisonError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps({"status": report["status"], "metrics": report["metrics"]}, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
