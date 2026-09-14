#!/usr/bin/env python3
"""Verify complete matched populations and separately score actual runtime paths."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.analyze_abu_dhabi_local_smoke import failure_layer  # noqa: E402
from scripts.evaluate_abu_dhabi_local_full import (  # noqa: E402
    PROFILES,
    sha256,
    validate_population,
    write_json,
)


def route_of(row: dict) -> str:
    planner = row.get("observed", {}).get("planner") or {}
    if planner.get("llm_invoked") is True:
        return "llm"
    return planner.get("route") or "unobserved"


def summarize(rows: list[dict]) -> dict:
    gold = [r for r in rows if r["has_gold"]]
    current_gold = [r for r in gold if r.get("gold_source_status") == "current"]
    expected_refusals = [r for r in rows if r["expected_status"] == "rejected"]
    expected_queries = [r for r in rows if r["expected_status"] == "ok"]
    refusal_tp = sum(r["observed"]["status"] == "rejected" for r in expected_refusals)
    refusal_fp = sum(
        r["expected_status"] != "rejected" and r["observed"]["status"] == "rejected"
        for r in rows
    )
    refusal_fn = len(expected_refusals) - refusal_tp
    latency_values = [
        float(((r.get("observed") or {}).get("generation") or {}).get("latency_ms"))
        for r in rows
        if ((r.get("observed") or {}).get("generation") or {}).get("latency_ms") is not None
    ]

    def percentile(values: list[float], percentile_value: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        rank = (len(ordered) - 1) * percentile_value / 100
        lower = int(rank)
        upper = min(lower + 1, len(ordered) - 1)
        fraction = rank - lower
        return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 3)

    def rate_with_wilson_95(successes: int, total: int) -> dict | None:
        """Return a binomial rate and its Wilson 95% interval.

        Full local runs contain small, stochastic model cohorts. Reporting a
        point estimate alone makes a single run look more conclusive than it
        is, so every release-relevant rate carries its sample size and interval.
        """

        if total == 0:
            return None
        rate = successes / total
        z = 1.96
        denominator = 1 + z**2 / total
        center = (rate + z**2 / (2 * total)) / denominator
        margin = (
            z
            * math.sqrt((rate * (1 - rate) + z**2 / (4 * total)) / total)
            / denominator
        )
        return {
            "successes": successes,
            "total": total,
            "rate": round(rate, 6),
            "wilson_95": [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)],
        }

    contract_passed = sum(r["status"] == "passed" for r in rows)
    gold_equivalent = sum(
        r["checks"].get("gold_result_equivalence_match") is True for r in current_gold
    )
    query_execution_success = sum(r["observed"]["status"] == "ok" for r in expected_queries)

    return {
        "case_count": len(rows),
        "contract_passed": contract_passed,
        "gold_case_count": len(gold),
        "current_gold_case_count": len(current_gold),
        "gold_equivalent": gold_equivalent,
        "gold_contract_passed": sum(r["status"] == "passed" for r in current_gold),
        "expected_refusals": len(expected_refusals),
        "correct_refusals": refusal_tp,
        "observed_refusals": sum(r["observed"]["status"] == "rejected" for r in rows),
        "refusal": {
            "true_positive_count": refusal_tp,
            "false_positive_count": refusal_fp,
            "false_negative_count": refusal_fn,
            "precision": refusal_tp / (refusal_tp + refusal_fp)
            if refusal_tp + refusal_fp
            else None,
            "recall": refusal_tp / (refusal_tp + refusal_fn)
            if refusal_tp + refusal_fn
            else None,
        },
        "expected_query_case_count": len(expected_queries),
        "query_execution_success_count": query_execution_success,
        "query_execution_success_rate": query_execution_success / len(expected_queries)
        if expected_queries
        else None,
        "rates": {
            "contract_pass": rate_with_wilson_95(contract_passed, len(rows)),
            "current_gold_result_equivalence": rate_with_wilson_95(
                gold_equivalent, len(current_gold)
            ),
            "expected_query_execution_success": rate_with_wilson_95(
                query_execution_success, len(expected_queries)
            ),
            "expected_refusal_correct": rate_with_wilson_95(
                refusal_tp, len(expected_refusals)
            ),
        },
        "mean_generation_latency_ms": (
            round(sum(latency_values) / len(latency_values), 3)
            if latency_values
            else None
        ),
        "p95_generation_latency_ms": percentile(latency_values, 95),
        "actual_status_counts": dict(Counter(r["observed"]["status"] for r in rows)),
        "failure_layers": dict(Counter(r["failure_layer"] for r in rows if r["failure_layer"])),
    }


def summarize_model_generated_free_form(rows: list[dict]) -> dict:
    """Report only questions that actually invoked the model.

    This deliberately excludes reviewed metric contracts and deterministic
    answerability policies. A case can belong to more than one semantic
    capability, so capability rows are explicitly overlapping diagnostics,
    not a partition or a release-gate denominator.
    """

    model_rows = [row for row in rows if row.get("actual_route") == "llm"]

    def grouped_summary(
        group_key,
        *,
        include_group_value: bool = False,
    ) -> list[dict]:
        groups = defaultdict(list)
        for row in model_rows:
            groups[group_key(row)].append(row)
        result = []
        for key, grouped_rows in sorted(groups.items(), key=lambda item: item[0]):
            source, profile, value = key
            item = {
                "source": source,
                "profile": profile,
                **summarize(grouped_rows),
            }
            if include_group_value:
                item["capability"] = value
            else:
                item["split"] = value
            result.append(item)
        return result

    by_split = grouped_summary(
        lambda row: (
            str(row.get("source_key") or "unknown"),
            str(row.get("execution_profile") or "unknown"),
            str(row.get("split") or "unclassified"),
        )
    )
    profile_groups = defaultdict(list)
    for row in model_rows:
        profile_groups[
            (
                str(row.get("source_key") or "unknown"),
                str(row.get("execution_profile") or "unknown"),
            )
        ].append(row)
    by_profile = [
        {"source": source, "profile": profile, **summarize(grouped_rows)}
        for (source, profile), grouped_rows in sorted(profile_groups.items())
    ]
    capability_rows: list[dict] = []
    unclassified_rows = 0
    for row in model_rows:
        capabilities = [
            str(value).strip()
            for value in row.get("capabilities") or []
            if str(value).strip()
        ]
        if not capabilities:
            unclassified_rows += 1
            continue
        for capability in sorted(set(capabilities)):
            capability_rows.append({**row, "_capability": capability})
    by_capability = []
    capability_groups = defaultdict(list)
    for row in capability_rows:
        capability_groups[
            (
                str(row.get("source_key") or "unknown"),
                str(row.get("execution_profile") or "unknown"),
                row["_capability"],
            )
        ].append(row)
    for (source, profile, capability), grouped_rows in sorted(capability_groups.items()):
        by_capability.append(
            {
                "source": source,
                "profile": profile,
                "capability": capability,
                **summarize(grouped_rows),
            }
        )
    return {
        "definition": {
            "actual_llm_invocation_only": True,
            "deterministic_reviewed_contracts_excluded": True,
            "deterministic_answerability_policies_excluded": True,
            "capability_rows_overlap": True,
            "cross_profile_overall_is_diagnostic_only": True,
        },
        "overall": summarize(model_rows),
        "by_profile": by_profile,
        "by_split": by_split,
        "by_capability": by_capability,
        "unclassified_model_case_count": unclassified_rows,
    }


def analyze(directory: Path) -> dict:
    from data_agent.free_form_nl2sql_benchmark import (
        _load_gold_source_cohort,
        _validate_benchmark,
    )

    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest["status"] != "completed":
        raise ValueError("full run has not completed without infrastructure failures")
    expected_runs = {
        f"{source}_{profile}" for source in manifest["sources"] for profile in PROFILES
    }
    if set(manifest["runs"]) != expected_runs:
        raise ValueError("missing or extra source/profile run")
    stability_identity = {
        "model_digest": bool((manifest.get("model") or {}).get("digest")),
        "model_profile": bool(
            ((manifest.get("model") or {}).get("compatibility_profile") or {}).get("fingerprint")
        ),
        "cohort_sha256": bool(manifest.get("cohort_sha256")),
        "runtime_code_sha256": bool(manifest.get("code_sha256")),
    }
    all_rows = []
    populations = {}
    run_metrics = {}
    for source, descriptor in manifest["sources"].items():
        benchmark_path = ROOT / descriptor["benchmark_path"]
        semantic_path = ROOT / descriptor["semantic_path"]
        for role, path in (("benchmark", benchmark_path), ("semantic", semantic_path)):
            if sha256(path) != descriptor[role + "_sha256"]:
                raise ValueError(f"{source} {role} input has changed")
        benchmark = json.loads(benchmark_path.read_text())
        semantic = json.loads(semantic_path.read_text())
        source_id = descriptor["source"]["source_id"]
        cases = _validate_benchmark(
            benchmark, semantic, source_id=source_id, benchmark_path=benchmark_path
        )
        expectations = {case["case_id"]: case for case in cases}
        if set(expectations) != set(descriptor["case_ids"]):
            raise ValueError("manifest does not cover the full frozen definition")
        gold_path = directory / descriptor["gold_audit"]["path"]
        if sha256(gold_path) != descriptor["gold_audit"]["sha256"]:
            raise ValueError("independent Gold audit checksum changed")
        cohort = _load_gold_source_cohort(
            gold_path,
            benchmark=benchmark,
            semantic_layer=semantic,
            binding=semantic["source_binding"],
            source_id=source_id,
            cases=cases,
        )
        for profile in PROFILES:
            run_id = f"{source}_{profile}"
            run = manifest["runs"][run_id]
            report_path = directory / run["report_path"]
            if sha256(report_path) != run["sha256"]:
                raise ValueError("case report checksum changed")
            report = json.loads(report_path.read_text())
            if report["benchmark"]["execution_profile"] != profile:
                raise ValueError("report profile mismatch")
            if report["model"]["requested"] != manifest["model"]["name"]:
                raise ValueError("report requested model mismatch")
            population = validate_population(report, descriptor["case_ids"])
            if not population["all_cases_attempted"] or population["infrastructure_failures"]:
                raise ValueError("full report contains infrastructure failures")
            if report["benchmark"]["gold_source_cohort"]["cohort_id"] != cohort["cohort_id"]:
                raise ValueError("report uses a different Gold source audit")
            populations[run_id] = population
            run_metrics[run_id] = report["metrics"]
            for original in report["cases"]:
                observed = original.get("observed") or {}
                model = observed.get("model") or {}
                if (
                    model.get("adk_route")
                    and model["adk_route"] != manifest["model"]["effective_route"]
                ):
                    raise ValueError("actual model route differs from frozen local profile")
                versions = (observed.get("generation") or {}).get("observed_model_versions") or []
                if any(version != manifest["model"]["effective_route"] for version in versions):
                    raise ValueError("observed model version differs from frozen local profile")
                expected = expectations[original["case_id"]]["expected"]
                all_rows.append(
                    {
                        **original,
                        "source_key": source,
                        "execution_profile": profile,
                        "actual_route": route_of(original),
                        "expected_status": expected["status"],
                        "has_gold": bool(expected.get("gold_result_contract")),
                        "failure_layer": failure_layer(original, expected),
                    }
                )
    if len(all_rows) != manifest["expected_executions"]:
        raise ValueError("execution count differs from frozen full scope")
    groups = defaultdict(list)
    for row in all_rows:
        groups[(row["source_key"], row["execution_profile"], row["actual_route"])].append(row)
    by_route = [
        {"source": source, "profile": profile, "route": route, **summarize(rows)}
        for (source, profile, route), rows in sorted(groups.items())
    ]
    overall = [
        {
            "source": source,
            "profile": profile,
            **summarize(
                [
                    r
                    for r in all_rows
                    if r["source_key"] == source and r["execution_profile"] == profile
                ]
            ),
        }
        for source in manifest["sources"]
        for profile in PROFILES
    ]
    pairs = defaultdict(dict)
    for row in all_rows:
        pairs[(row["source_key"], row["case_id"])][row["execution_profile"]] = row
    comparison = Counter()
    for (source, _case_id), pair in pairs.items():
        sql, ir = (pair[profile] for profile in PROFILES)
        label = (
            "both_pass"
            if sql["status"] == ir["status"] == "passed"
            else "sql_only_pass"
            if sql["status"] == "passed"
            else "ir_only_pass"
            if ir["status"] == "passed"
            else "both_fail"
        )
        comparison[(source, label)] += 1
    return {
        "schema": "gda.abu-dhabi-local-full-analysis.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "manifest_sha256": sha256(manifest_path),
        "model": manifest["model"],
        "cohort_sha256": manifest.get("cohort_sha256"),
        "code_sha256": manifest.get("code_sha256"),
        "stability_identity": {
            **stability_identity,
            "complete": all(stability_identity.values()),
        },
        "claim_boundary": {**manifest["claim_boundary"], "presentation_scored": False},
        "population": populations,
        "execution_count": len(all_rows),
        "overall": overall,
        "by_actual_route": by_route,
        "model_generated_free_form": summarize_model_generated_free_form(all_rows),
        "paired_contract_comparison": {
            source: {label: count for (key, label), count in comparison.items() if key == source}
            for source in manifest["sources"]
        },
        "failure_layers": dict(Counter(r["failure_layer"] for r in all_rows if r["failure_layer"])),
        "duplicate_result_column_cases": [
            {
                "source": row["source_key"],
                "case_id": row["case_id"],
                "profile": row["execution_profile"],
                "duplicate_columns": sorted(
                    column
                    for column, count in Counter(
                        row["observed"].get("result_columns") or []
                    ).items()
                    if count > 1
                ),
            }
            for row in all_rows
            if len(row["observed"].get("result_columns") or [])
            != len(set(row["observed"].get("result_columns") or []))
        ],
        "failure_cases": [
            {
                key: row.get(key)
                for key in (
                    "source_key",
                    "case_id",
                    "language",
                    "execution_profile",
                    "actual_route",
                    "expected_status",
                    "status",
                    "failure_layer",
                    "failure_reasons",
                    "gold_source_status",
                    "checks",
                    "observed",
                )
            }
            for row in all_rows
            if row["status"] != "passed"
        ],
        "raw_run_metrics": run_metrics,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.directory)
    write_json(args.directory / "analysis.json", result)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "execution_count",
                    "overall",
                    "by_actual_route",
                    "paired_contract_comparison",
                    "failure_layers",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
