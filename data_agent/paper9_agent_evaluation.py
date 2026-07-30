"""Offline behavioral-contract evaluator for the Paper9 ADK tool loop."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

PLANNING_TOOLS = {"world_model_v21_plan", "world_model_v21_pipeline"}
REQUIRED_OPENING = [
    "world_model_v21_status",
    "paper9_inspect_resources",
]


def evaluate_paper9_tool_trajectory(
    events: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate bounded plan/audit/replan/commit behavior from function events."""

    trace = [dict(event) for event in events]
    names = [str(event.get("tool") or "") for event in trace]
    violations: list[str] = []

    if names[:2] != REQUIRED_OPENING:
        violations.append(
            "Trajectory must open with world_model_v21_status -> "
            "paper9_inspect_resources."
        )
    if not trace:
        violations.append("Trajectory is empty.")
        return _report(names, violations, terminal="invalid")

    status_response = _response_for(trace, "world_model_v21_status")
    inspect_response = _response_for(trace, "paper9_inspect_resources")
    version_compatible = bool(
        (status_response.get("finals") or {}).get("version_compatible")
    )
    planning_ready = bool(inspect_response.get("planning_ready"))
    if not version_compatible or not planning_ready:
        if any(name in PLANNING_TOOLS for name in names):
            violations.append("Planning executed despite a failed version/resource gate.")
        terminal = "preflight_stop"
        return _report(names, violations, terminal=terminal)

    if len(names) < 3 or names[2] != "paper9_recall_verified_episodes":
        violations.append("Verified episodic recall must run before planning.")

    planning_indices = [i for i, name in enumerate(names) if name in PLANNING_TOOLS]
    if not planning_indices:
        violations.append("No Paper9 planning tool was called.")
    if len(planning_indices) > 2:
        violations.append("More than one replan was attempted.")

    last_audit: Mapping[str, Any] | None = None
    terminal = "incomplete"
    for plan_number, plan_index in enumerate(planning_indices):
        audit_index = plan_index + 1
        if audit_index >= len(trace) or names[audit_index] != "paper9_audit_run":
            violations.append("Every planning call must be immediately followed by an audit.")
            continue
        audit = trace[audit_index].get("response") or {}
        if not isinstance(audit, Mapping):
            audit = {}
        last_audit = audit
        attempt = audit.get("attempt")
        if attempt != plan_number:
            violations.append(
                f"Audit attempt must be {plan_number} after planning call {plan_number + 1}."
            )

        passed = bool(audit.get("hard_constraint_passed"))
        next_index = audit_index + 1
        next_name = names[next_index] if next_index < len(names) else None
        if passed:
            if next_name != "paper9_commit_verified_episode":
                violations.append("A passed audit must be followed by verified-memory commit.")
            elif next_index != len(names) - 1:
                violations.append("No tool may run after verified-memory commit.")
            terminal = "verified_commit"
            break

        if audit.get("retryable") and plan_number == 0:
            if next_name not in PLANNING_TOOLS:
                violations.append("A retryable first failure must take the single replan branch.")
            terminal = "replan"
        else:
            if next_name is not None:
                violations.append("A non-retryable audit failure must stop for human review.")
            terminal = "human_review"

    commit_indices = [
        i for i, name in enumerate(names) if name == "paper9_commit_verified_episode"
    ]
    if commit_indices and not (
        last_audit and bool(last_audit.get("hard_constraint_passed"))
    ):
        violations.append("An unverified or failed run was committed to memory.")
    if len(commit_indices) > 1:
        violations.append("Verified memory was committed more than once.")

    return _report(names, violations, terminal=terminal)


def _response_for(
    trace: list[dict[str, Any]], tool_name: str
) -> Mapping[str, Any]:
    for event in trace:
        if event.get("tool") == tool_name and isinstance(event.get("response"), Mapping):
            return event["response"]
    return {}


def _report(
    names: list[str], violations: list[str], *, terminal: str
) -> dict[str, Any]:
    return {
        "passed": not violations,
        "terminal": terminal,
        "tool_count": len(names),
        "tool_trace": names,
        "violations": violations,
    }


def summarize_repeated_agent_runs(
    runs: Iterable[Mapping[str, Any]],
    *,
    pass_rate_threshold: float = 0.8,
) -> dict[str, Any]:
    """Aggregate stochastic ADK runs without hiding per-scenario failures."""

    rows = [dict(run) for run in runs]
    scenarios = sorted({str(row.get("scenario") or "unknown") for row in rows})
    by_scenario = {
        scenario: _summarize_run_group(
            [row for row in rows if str(row.get("scenario") or "unknown") == scenario]
        )
        for scenario in scenarios
    }
    overall = _summarize_run_group(rows)
    failed_scenarios = [
        scenario
        for scenario, summary in by_scenario.items()
        if summary["pass_rate"] < pass_rate_threshold
    ]
    return {
        "overall": overall,
        "by_scenario": by_scenario,
        "release_gate": {
            "pass_rate_threshold": pass_rate_threshold,
            "passed": bool(rows) and not failed_scenarios,
            "failed_scenarios": failed_scenarios,
        },
    }


def _summarize_run_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    passed = sum(bool(row.get("passed")) for row in rows)
    pass_rate = passed / total if total else 0.0
    latencies = [
        float(row["latency_ms"])
        for row in rows
        if row.get("latency_ms") is not None
    ]
    tool_counts = [
        int(row.get("tool_count", len(row.get("tool_trace") or []))) for row in rows
    ]
    traces = [tuple(str(item) for item in row.get("tool_trace") or []) for row in rows]
    trace_counts = Counter(" -> ".join(trace) for trace in traces)
    terminal_counts = Counter(str(row.get("terminal") or "unknown") for row in rows)
    return {
        "total": total,
        "passed": passed,
        "pass_rate": pass_rate,
        "confidence_95_wilson": list(_wilson_interval(passed, total)),
        "mean_latency_ms": _mean(latencies),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "mean_tool_count": _mean(tool_counts),
        "exact_trace_consistency": max(trace_counts.values(), default=0) / total
        if total
        else 0.0,
        "pairwise_trace_consistency": _pairwise_trace_consistency(traces),
        "unique_trace_count": len(trace_counts),
        "trace_distribution": dict(trace_counts),
        "terminal_distribution": dict(terminal_counts),
        "error_count": sum(bool(row.get("error")) for row in rows),
    }


def _wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    proportion = successes / total
    denominator = 1 + z**2 / total
    center = (proportion + z**2 / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total + z**2 / (4 * total**2)
        )
        / denominator
    )
    return (max(0.0, center - margin), min(1.0, center + margin))


def _mean(values: list[float] | list[int]) -> float | None:
    return sum(values) / len(values) if values else None


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _pairwise_trace_consistency(traces: list[tuple[str, ...]]) -> float:
    if len(traces) < 2:
        return 1.0 if traces else 0.0
    scores: list[float] = []
    for left_index, left in enumerate(traces):
        left_steps = {f"{index}:{name}" for index, name in enumerate(left)}
        for right in traces[left_index + 1 :]:
            right_steps = {f"{index}:{name}" for index, name in enumerate(right)}
            union = left_steps | right_steps
            scores.append(len(left_steps & right_steps) / len(union) if union else 1.0)
    return sum(scores) / len(scores)
