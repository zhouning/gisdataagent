"""Aggregate repeated controlled pairwise NL2Semantic2SQL evaluations."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from .abu_dhabi_nl2semantic2sql_v2_evaluator import REPORT_SCHEMA
from .abu_dhabi_nl2semantic2sql_v2_pairwise import COMPARISON_SCHEMA

STABILITY_SCHEMA = "gda.abu-dhabi-nl2semantic2sql-v2-stability.v1"
_ROOT = Path(__file__).resolve().parents[1]
_RUNTIME_ISOLATION_INVARIANTS = (
    "runtime_module_scan_passed",
    "questions_loaded_only_by_evaluator",
    "gold_loaded_only_by_evaluator",
    "source_rows_persisted",
)


class V2StabilityConfigurationError(ValueError):
    """Repeated reports do not form a comparable stability experiment."""


def _load(path: Path, schema: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise V2StabilityConfigurationError(f"artifact_unreadable:{path}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != schema:
        raise V2StabilityConfigurationError(f"artifact_schema_invalid:{path}")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _same(left: Any, right: Any, label: str) -> None:
    if left != right:
        raise V2StabilityConfigurationError(f"stability_configuration_mismatch:{label}")


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 3) if values else None


def _run_input(pairwise_path: Path) -> dict[str, Any]:
    pairwise = _load(pairwise_path, COMPARISON_SCHEMA)
    baseline_path = _ROOT / str(pairwise.get("baseline_report") or "")
    candidate_path = _ROOT / str(pairwise.get("candidate_report") or "")
    baseline = _load(baseline_path, REPORT_SCHEMA)
    candidate = _load(candidate_path, REPORT_SCHEMA)
    if baseline.get("execution_profile") != "baseline_sql":
        raise V2StabilityConfigurationError("baseline_profile_invalid")
    if candidate.get("execution_profile") != "semantic_ir_experimental":
        raise V2StabilityConfigurationError("candidate_profile_invalid")
    for key in (
        "public_benchmark",
        "private_gold",
        "semantic_configuration",
        "runtime_isolation",
    ):
        _same(baseline.get(key), candidate.get(key), f"within_run.{key}")
    if pairwise.get("paired_configuration_verified") is not True:
        raise V2StabilityConfigurationError("paired_configuration_unverified")
    return {
        "run_id": pairwise_path.stem,
        "pairwise": pairwise,
        "baseline": baseline,
        "candidate": candidate,
        "artifact_sha256": {
            "pairwise": _sha256(pairwise_path),
            "baseline": _sha256(baseline_path),
            "candidate": _sha256(candidate_path),
        },
    }


def aggregate_stability_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    if len(runs) < 2:
        raise V2StabilityConfigurationError("at_least_two_runs_required")
    reference = runs[0]
    for index, run in enumerate(runs[1:], start=2):
        for key in ("public_benchmark", "private_gold", "semantic_configuration"):
            _same(
                reference["baseline"].get(key),
                run["baseline"].get(key),
                f"run_{index}.{key}",
            )
        left_isolation = reference["baseline"].get("runtime_isolation") or {}
        right_isolation = run["baseline"].get("runtime_isolation") or {}
        for key in _RUNTIME_ISOLATION_INVARIANTS:
            _same(left_isolation.get(key), right_isolation.get(key), f"run_{index}.{key}")
        left_cases = {
            str(item.get("case_id")): (
                item.get("scope"),
                item.get("family"),
                item.get("category"),
                item.get("expected_outcome"),
            )
            for item in reference["pairwise"].get("cases") or []
        }
        right_cases = {
            str(item.get("case_id")): (
                item.get("scope"),
                item.get("family"),
                item.get("category"),
                item.get("expected_outcome"),
            )
            for item in run["pairwise"].get("cases") or []
        }
        _same(left_cases, right_cases, f"run_{index}.case_contracts")

    run_summaries: list[dict[str, Any]] = []
    route_cases: dict[str, dict[str, Any]] = {}
    latency_deltas: list[float] = []
    token_deltas = Counter()
    outcomes = Counter()
    for run in runs:
        pairwise = run["pairwise"]
        metrics = pairwise.get("metrics") or {}
        all_cases = metrics.get("all_cases") or {}
        route = metrics.get("route_comparison") or {}
        generation = route.get("paired_generation") or {}
        latency_delta = generation.get("candidate_minus_baseline_mean_latency_ms")
        if isinstance(latency_delta, (int, float)):
            latency_deltas.append(float(latency_delta))
        for token_type, values in (generation.get("usage") or {}).items():
            token_deltas[token_type] += int(
                (values or {}).get("candidate_minus_baseline_total") or 0
            )
        outcomes.update(route.get("outcome_counts") or {})
        run_summaries.append(
            {
                "run_id": run["run_id"],
                "artifact_sha256": run.get("artifact_sha256") or {},
                "baseline_status": run["baseline"].get("status"),
                "candidate_status": run["candidate"].get("status"),
                "baseline_all_passed": all_cases.get("baseline_passed_case_count"),
                "candidate_all_passed": all_cases.get("candidate_passed_case_count"),
                "baseline_route_passed": route.get("baseline_passed_case_count"),
                "candidate_route_passed": route.get("candidate_passed_case_count"),
                "route_case_count": route.get("case_count"),
                "candidate_minus_baseline_mean_latency_ms": latency_delta,
            }
        )
        for case in pairwise.get("cases") or []:
            if case.get("category") not in {
                "single_source_free_form_route",
                "route_or_contract_mismatch",
            }:
                continue
            case_id = str(case.get("case_id") or "")
            summary = route_cases.setdefault(
                case_id,
                {
                    "case_id": case_id,
                    "scope": case.get("scope"),
                    "family": case.get("family"),
                    "category": case.get("category"),
                    "baseline_passed_run_count": 0,
                    "candidate_passed_run_count": 0,
                },
            )
            summary["baseline_passed_run_count"] += int(
                (case.get("baseline") or {}).get("passed") is True
            )
            summary["candidate_passed_run_count"] += int(
                (case.get("candidate") or {}).get("passed") is True
            )

    run_count = len(runs)
    per_case = []
    for summary in sorted(route_cases.values(), key=lambda item: item["case_id"]):
        summary["run_count"] = run_count
        summary["baseline_pass_rate"] = summary["baseline_passed_run_count"] / run_count
        summary["candidate_pass_rate"] = summary["candidate_passed_run_count"] / run_count
        per_case.append(summary)
    baseline_route_passes = sum(item["baseline_route_passed"] for item in run_summaries)
    candidate_route_passes = sum(item["candidate_route_passed"] for item in run_summaries)
    route_observations = sum(item["route_case_count"] for item in run_summaries)
    accuracy_delta = (candidate_route_passes - baseline_route_passes) / route_observations
    faster_candidate_runs = sum(delta < 0 for delta in latency_deltas)
    faster_baseline_runs = sum(delta > 0 for delta in latency_deltas)
    platform_gate_modes = sorted(
        {
            str(
                (run["baseline"].get("runtime_isolation") or {}).get(
                    "platform_schema_gate", "product_default_verified"
                )
            )
            for run in runs
        }
    )
    public = reference["baseline"].get("public_benchmark") or {}
    semantic = reference["baseline"].get("semantic_configuration") or {}
    return {
        "schema": STABILITY_SCHEMA,
        "status": "passed",
        "benchmark": {
            "benchmark_id": public.get("benchmark_id"),
            "version": public.get("version"),
            "sha256": public.get("sha256"),
        },
        "semantic_configuration": {
            source: {
                "semantic_version": value.get("semantic_version"),
                "metric_contract_version": value.get("metric_contract_version"),
                "sha256": value.get("sha256"),
            }
            for source, value in sorted(semantic.items())
        },
        "configuration_audit": {
            "run_count": run_count,
            "each_run_pair_controlled": True,
            "public_benchmark_consistent": True,
            "private_gold_consistent": True,
            "semantic_configuration_consistent": True,
            "runtime_isolation_invariants_consistent": True,
            "platform_schema_gate_modes": platform_gate_modes,
        },
        "metrics": {
            "route_observation_count": route_observations,
            "baseline_route_passed_count": baseline_route_passes,
            "candidate_route_passed_count": candidate_route_passes,
            "baseline_route_pass_rate": baseline_route_passes / route_observations,
            "candidate_route_pass_rate": candidate_route_passes / route_observations,
            "candidate_minus_baseline_pass_rate": accuracy_delta,
            "outcome_counts": dict(sorted(outcomes.items())),
            "latency": {
                "run_deltas_ms": latency_deltas,
                "mean_candidate_minus_baseline_ms": _mean(latency_deltas),
                "median_candidate_minus_baseline_ms": round(
                    statistics.median(latency_deltas), 3
                ),
                "candidate_faster_run_count": faster_candidate_runs,
                "baseline_faster_run_count": faster_baseline_runs,
            },
            "usage_candidate_minus_baseline_total": dict(sorted(token_deltas.items())),
        },
        "runs": run_summaries,
        "route_cases": per_case,
        "unstable_route_cases": [
            item
            for item in per_case
            if item["baseline_passed_run_count"] != run_count
            or item["candidate_passed_run_count"] != run_count
        ],
        "promotion_assessment": {
            "promotion_supported": False,
            "accuracy_conclusion": (
                "tied_across_repeated_runs"
                if accuracy_delta == 0
                else "accuracy_diff_detected_across_repeated_runs"
            ),
            "latency_conclusion": (
                "direction_inconsistent_across_runs"
                if faster_candidate_runs and faster_baseline_runs
                else "direction_consistent_across_runs"
            ),
            "reason": "candidate_does_not_demonstrate_repeated_accuracy_advantage",
        },
        "limitations": [
            "Only six cases per run exercise a different model planning route.",
            "The repeated sample is sufficient to expose instability, not to prove equivalence.",
            (
                "Latency includes remote model and network variance and is "
                "interpreted by direction across runs."
            ),
            (
                "No questions, SQL, source rows, private Gold identifiers, or "
                "result fingerprints are included."
            ),
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairwise-report", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = aggregate_stability_runs(
        [_run_input(path.resolve()) for path in args.pairwise_report]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": report["status"], "metrics": report["metrics"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
