#!/usr/bin/env python3
"""Apply the model compatibility gate across repeated controlled runs.

The single-run gate answers whether one report clears its profile thresholds.
This companion gate answers the product question that a model/profile remains
safe under repeated execution.  It never recomputes Gold, reads benchmark
questions, or changes route metrics; it only verifies that reports describe
the same model/profile/cohort and takes the lower bound across runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_abu_dhabi_model_compatibility_gate import evaluate  # noqa: E402


STABILITY_SCHEMA = "gda.nl2sql-model-compatibility-stability-gate.v1"


class CompatibilityStabilityConfigurationError(ValueError):
    """Repeated reports are not comparable for a release decision."""


def _ratio_summary(values: list[float | int | None]) -> dict[str, Any]:
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    if not numeric:
        return {"values": [], "minimum": None, "mean": None, "maximum": None}
    return {
        "values": numeric,
        "minimum": min(numeric),
        "mean": sum(numeric) / len(numeric),
        "maximum": max(numeric),
    }


def _model_identity(analysis: dict[str, Any]) -> dict[str, Any]:
    model = analysis.get("model") or {}
    compatibility = model.get("compatibility_profile") or {}
    installed = model.get("installed") or {}
    code = analysis.get("code_sha256") or {}
    runtime_code_fingerprint = None
    if isinstance(code, dict) and code and all(
        isinstance(path, str)
        and isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
        for path, digest in code.items()
    ):
        runtime_code_fingerprint = hashlib.sha256(
            json.dumps(code, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    return {
        "requested": model.get("id") or model.get("name") or model.get("model"),
        "effective_route": model.get("effective_route") or model.get("adk_route"),
        "profile_id": compatibility.get("profile_id"),
        "profile_version": compatibility.get("profile_version"),
        "profile_fingerprint": compatibility.get("fingerprint"),
        "model_digest": installed.get("digest"),
        "request_timeout_seconds": model.get("timeout_seconds"),
        "generation_budget_seconds": model.get("generation_budget_seconds"),
        "cohort_sha256": analysis.get("cohort_sha256"),
        "runtime_code_fingerprint": runtime_code_fingerprint,
    }


def _analysis_sha(analysis: dict[str, Any]) -> str:
    declared = str(analysis.get("report_sha256") or "").strip()
    if declared:
        return declared
    raw = json.dumps(analysis, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def evaluate_repeated(
    analyses: list[dict[str, Any]],
    model_name: str | None = None,
    *,
    minimum_runs: int = 3,
) -> dict[str, Any]:
    """Evaluate repeated reports using per-route lower-bound checks.

    All reports must share model identity, installed digest, profile
    fingerprint, and frozen cohort.  A route is stable only when every run's
    ordinary single-run gate passes; this makes promotion fail closed when a
    model succeeds only intermittently.
    """

    if minimum_runs < 2:
        raise CompatibilityStabilityConfigurationError("minimum_runs_must_be_at_least_two")
    if not analyses:
        raise CompatibilityStabilityConfigurationError("at_least_one_analysis_required")

    identities = [_model_identity(analysis) for analysis in analyses]
    reference_identity = identities[0]
    required_identity_fields = (
        "requested",
        "effective_route",
        "profile_id",
        "profile_version",
        "profile_fingerprint",
        "model_digest",
        "request_timeout_seconds",
        "generation_budget_seconds",
        "cohort_sha256",
        "runtime_code_fingerprint",
    )
    missing_identity = [
        key for key in required_identity_fields if not reference_identity.get(key)
    ]
    if missing_identity:
        raise CompatibilityStabilityConfigurationError(
            "configuration_identity_missing:" + ",".join(missing_identity)
        )
    for index, identity in enumerate(identities[1:], start=2):
        for key in (
            "requested",
            "effective_route",
            "profile_id",
            "profile_version",
            "profile_fingerprint",
            "model_digest",
            "request_timeout_seconds",
            "generation_budget_seconds",
            "cohort_sha256",
            "runtime_code_fingerprint",
        ):
            if reference_identity.get(key) != identity.get(key):
                raise CompatibilityStabilityConfigurationError(
                    f"configuration_mismatch:run_{index}:{key}"
                )

    report_shas = [_analysis_sha(analysis) for analysis in analyses]
    if len(set(report_shas)) != len(report_shas):
        raise CompatibilityStabilityConfigurationError("duplicate_analysis_reports")

    evaluated = [evaluate(analysis, model_name=model_name) for analysis in analyses]
    route_maps = [
        {str(route.get("run_key")): route for route in report.get("routes") or []}
        for report in evaluated
    ]
    route_keys = set(route_maps[0])
    if not route_keys:
        raise CompatibilityStabilityConfigurationError("no_model_routes_found")
    for index, route_map in enumerate(route_maps[1:], start=2):
        if set(route_map) != route_keys:
            raise CompatibilityStabilityConfigurationError(
                f"route_set_mismatch:run_{index}"
            )

    thresholds = evaluated[0]["model"]["profile"]["minimum_benchmark_thresholds"]
    routes: list[dict[str, Any]] = []
    for key in sorted(route_keys):
        observations = [route_map[key] for route_map in route_maps]
        first = observations[0]
        metric_fields = (
            "gold_rate",
            "refusal_precision",
            "refusal_recall",
            "query_execution_success_rate",
            "mean_generation_latency_ms",
            "p95_generation_latency_ms",
        )
        summaries = {
            field: _ratio_summary([item.get(field) for item in observations])
            for field in metric_fields
        }
        source = str(first.get("source") or "")
        gold_threshold = float(first.get("gold_threshold") or 0)
        lower_bound_checks = {
            "gold_equivalence": (
                summaries["gold_rate"]["minimum"] is not None
                and summaries["gold_rate"]["minimum"] >= gold_threshold
            ),
            # Reuse the single-run applicability decision. A route with no
            # expected or observed refusals is neutral; an unexpected or
            # missed refusal remains a failed per-run check.
            "refusal_precision": all(
                bool(item.get("checks", {}).get("refusal_precision"))
                for item in observations
            ),
            "refusal_recall": all(
                bool(item.get("checks", {}).get("refusal_recall"))
                for item in observations
            ),
            "query_execution_success": (
                summaries["query_execution_success_rate"]["minimum"] is not None
                and summaries["query_execution_success_rate"]["minimum"]
                >= float(thresholds["query_execution_success"])
            ),
        }
        routes.append(
            {
                "run_key": key,
                "source": source,
                "profile": first.get("profile"),
                "actual_route": first.get("actual_route"),
                "run_count": len(observations),
                "metrics": summaries,
                "thresholds": {
                    "gold_equivalence": gold_threshold,
                    "refusal_precision": thresholds["refusal_precision"],
                    "refusal_recall": thresholds["refusal_recall"],
                    "query_execution_success": thresholds["query_execution_success"],
                },
                "lower_bound_checks": lower_bound_checks,
                "stable_promotable": all(lower_bound_checks.values()),
                "single_run_decisions": [item.get("promotable") is True for item in observations],
            }
        )

    evidence_sufficient = len(analyses) >= minimum_runs
    all_routes_stable = bool(routes) and all(
        route["stable_promotable"] for route in routes
    )
    promote = evidence_sufficient and all_routes_stable
    return {
        "schema": STABILITY_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "complete",
        "model": {
            **reference_identity,
            "profile": evaluated[0]["model"].get("profile"),
        },
        "deterministic_contracts_excluded_from_model_gate": True,
        "configuration_audit": {
            "run_count": len(analyses),
            "minimum_runs": minimum_runs,
            "evidence_sufficient": evidence_sufficient,
            "same_model_profile_digest_cohort_and_runtime_code": True,
            "unique_reports": True,
            "route_set_consistent": True,
            "report_sha256": report_shas,
        },
        "runs": [
            {
                "report_sha256": report_sha,
                "decision": report.get("decision"),
                "promote": report.get("promote") is True,
            }
            for report_sha, report in zip(report_shas, evaluated)
        ],
        "routes": routes,
        "promote": promote,
        "decision": "promote" if promote else "canary_or_rollback",
        "reason": (
            "repeated_lower_bounds_clear_profile_thresholds"
            if promote
            else "repeated_lower_bound_or_evidence_threshold_failed"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis", type=Path, nargs="+")
    parser.add_argument("--model")
    parser.add_argument("--minimum-runs", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    analyses = [json.loads(path.read_text(encoding="utf-8")) for path in args.analysis]
    result = evaluate_repeated(
        analyses,
        model_name=args.model,
        minimum_runs=args.minimum_runs,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if result["promote"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
