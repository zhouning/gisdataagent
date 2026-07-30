import pytest

from data_agent.paper9_agent_evaluation import (
    evaluate_paper9_tool_trajectory,
    summarize_repeated_agent_runs,
)


def _opening():
    return [
        {
            "tool": "world_model_v21_status",
            "response": {"finals": {"version_compatible": True}},
        },
        {"tool": "paper9_inspect_resources", "response": {"planning_ready": True}},
        {"tool": "paper9_recall_verified_episodes", "response": {"count": 0}},
    ]


def test_success_trajectory_passes_contract():
    events = _opening() + [
        {"tool": "world_model_v21_pipeline", "response": {"status": "ok"}},
        {
            "tool": "paper9_audit_run",
            "response": {
                "attempt": 0,
                "hard_constraint_passed": True,
                "retryable": False,
            },
        },
        {"tool": "paper9_commit_verified_episode", "response": {"status": "committed"}},
    ]

    result = evaluate_paper9_tool_trajectory(events)

    assert result["passed"] is True
    assert result["terminal"] == "verified_commit"


def test_single_replan_then_success_passes_contract():
    events = _opening() + [
        {"tool": "world_model_v21_pipeline", "response": {"status": "ok"}},
        {
            "tool": "paper9_audit_run",
            "response": {
                "attempt": 0,
                "hard_constraint_passed": False,
                "retryable": True,
            },
        },
        {"tool": "world_model_v21_plan", "response": {"status": "ok"}},
        {
            "tool": "paper9_audit_run",
            "response": {
                "attempt": 1,
                "hard_constraint_passed": True,
                "retryable": False,
            },
        },
        {"tool": "paper9_commit_verified_episode", "response": {"status": "committed"}},
    ]

    result = evaluate_paper9_tool_trajectory(events)

    assert result["passed"] is True
    assert result["tool_count"] == 8


def test_second_failure_stops_without_commit():
    events = _opening() + [
        {"tool": "world_model_v21_pipeline", "response": {"status": "ok"}},
        {
            "tool": "paper9_audit_run",
            "response": {
                "attempt": 0,
                "hard_constraint_passed": False,
                "retryable": True,
            },
        },
        {"tool": "world_model_v21_plan", "response": {"status": "ok"}},
        {
            "tool": "paper9_audit_run",
            "response": {
                "attempt": 1,
                "hard_constraint_passed": False,
                "retryable": False,
            },
        },
    ]

    result = evaluate_paper9_tool_trajectory(events)

    assert result["passed"] is True
    assert result["terminal"] == "human_review"


def test_premature_commit_fails_contract():
    events = _opening() + [
        {"tool": "world_model_v21_pipeline", "response": {"status": "ok"}},
        {"tool": "paper9_commit_verified_episode", "response": {"status": "committed"}},
    ]

    result = evaluate_paper9_tool_trajectory(events)

    assert result["passed"] is False
    assert any("followed by an audit" in item for item in result["violations"])
    assert any("unverified" in item for item in result["violations"])


def test_version_mismatch_stops_before_planning():
    events = [
        {
            "tool": "world_model_v21_status",
            "response": {"finals": {"version_compatible": False}},
        },
        {"tool": "paper9_inspect_resources", "response": {"planning_ready": False}},
    ]

    result = evaluate_paper9_tool_trajectory(events)

    assert result["passed"] is True
    assert result["terminal"] == "preflight_stop"


def test_repeated_run_summary_reports_statistics_by_scenario():
    runs = [
        {
            "scenario": "success",
            "passed": True,
            "terminal": "verified_commit",
            "latency_ms": 100,
            "tool_trace": ["status", "inspect", "plan", "audit", "commit"],
        },
        {
            "scenario": "success",
            "passed": False,
            "terminal": "incomplete",
            "latency_ms": 300,
            "tool_trace": ["status", "inspect"],
            "error": "missing plan",
        },
        {
            "scenario": "blocked",
            "passed": True,
            "terminal": "preflight_stop",
            "latency_ms": 50,
            "tool_trace": ["status", "inspect"],
        },
    ]

    report = summarize_repeated_agent_runs(runs, pass_rate_threshold=0.8)

    assert report["overall"]["pass_rate"] == pytest.approx(2 / 3)
    assert report["by_scenario"]["success"]["mean_latency_ms"] == 200
    assert report["by_scenario"]["success"]["p95_latency_ms"] == pytest.approx(290)
    assert report["by_scenario"]["blocked"]["exact_trace_consistency"] == 1
    assert report["release_gate"] == {
        "pass_rate_threshold": 0.8,
        "passed": False,
        "failed_scenarios": ["success"],
    }


def test_repeated_run_summary_uses_wilson_interval_for_small_samples():
    report = summarize_repeated_agent_runs(
        [
            {
                "scenario": "success",
                "passed": True,
                "tool_trace": ["status"],
            }
            for _ in range(10)
        ]
    )

    lower, upper = report["overall"]["confidence_95_wilson"]
    assert lower == pytest.approx(0.72246, rel=1e-4)
    assert upper == pytest.approx(1.0)
    assert report["release_gate"]["passed"] is True


def test_trace_consistency_is_order_sensitive():
    report = summarize_repeated_agent_runs(
        [
            {"scenario": "x", "passed": True, "tool_trace": ["a", "b"]},
            {"scenario": "x", "passed": True, "tool_trace": ["b", "a"]},
        ]
    )

    assert report["overall"]["exact_trace_consistency"] == 0.5
    assert report["overall"]["pairwise_trace_consistency"] == 0.0
