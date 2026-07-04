from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_twm_runtime_benchmark_blocks_planner_and_negative_controls_after_simulator_passes(tmp_path):
    from data_agent.benchmarks.twm_runtime_v1.runner import run_twm_runtime_benchmark

    output = tmp_path / "twm_runtime_benchmark_v1.json"
    markdown_output = tmp_path / "twm_runtime_benchmark_v1.md"

    report = run_twm_runtime_benchmark(
        output_path=output,
        markdown_output_path=markdown_output,
        fail_on_failed=False,
    )

    assert report["schema"] == "territory_world_model.twm_runtime_benchmark.v1"
    assert report["suite_id"] == "twm_runtime_v1"
    assert report["status"] == "fail"
    assert "simulator_gate" not in report["failed_gates"]
    assert "planner_gate" in report["failed_gates"]
    assert "negative_control_gate" in report["failed_gates"]

    simulator_gate = report["gates"]["simulator_gate"]
    assert simulator_gate["status"] == "pass"
    assert "simulator_trace" not in simulator_gate["missing"]
    assert "runtime_metrics" not in simulator_gate["missing"]
    assert "action_mask_probability" not in simulator_gate["missing"]
    assert "holdout_metrics" not in simulator_gate["missing"]
    assert simulator_gate["checks"]["simulator_trace_present"]["status"] == "pass"
    assert simulator_gate["checks"]["facade_backend_forbidden"]["status"] == "pass"
    assert simulator_gate["checks"]["runtime_metrics"]["status"] == "pass"
    assert simulator_gate["checks"]["action_mask_probability"]["status"] == "pass"

    simulator_trace = report["simulator_trace"]
    assert simulator_trace["schema"] == "territory_world_model.simulator_trace.v1"
    assert simulator_trace["backend_type"] != "deterministic_planner_facade"
    assert simulator_trace["dataset_snapshot_hash"] == report["dataset_manifest_hash"]
    assert simulator_trace["model_family"] == "transparent_runtime_heads"
    assert simulator_trace["split"] == "test"
    assert simulator_trace["prediction_id"].startswith("twm-runtime-v1-")

    planner_gate = report["gates"]["planner_gate"]
    assert planner_gate["status"] == "fail"
    assert "planner_consumes_simulator_trace" in planner_gate["missing"]

    claim_boundary = report["claim_boundary"]
    assert claim_boundary["production_decision"] == "blocked_without_real_observed_history"
    assert claim_boundary["production_accuracy"] == "not_supported"
    assert claim_boundary["flus_superiority"] == "not_evaluated_by_this_benchmark"
    assert claim_boundary["not_for_production_boundary_preserved"] is True

    assert output.exists()
    assert markdown_output.exists()


def test_twm_runtime_benchmark_builds_canonical_observation_for_renderer_gate(tmp_path):
    from data_agent.benchmarks.twm_runtime_v1.runner import run_twm_runtime_benchmark

    report = run_twm_runtime_benchmark(
        output_path=tmp_path / "report.json",
        markdown_output_path=tmp_path / "report.md",
    )

    renderer_gate = report["gates"]["renderer_gate"]
    assert renderer_gate["status"] == "pass"
    assert "renderer_gate" not in report["failed_gates"]

    observation = report["canonical_observation"]
    assert observation["schema"] == "territory_world_model.runtime_observation.v1"
    assert observation["dataset_snapshot_hash"] == report["dataset_manifest_hash"]
    assert observation["boundary"]["not_for_production"] is True
    assert observation["object_summary"]["object_count"] >= 21000
    assert observation["relation_summary"]["relation_count"] >= 1700
    assert observation["rule_context"]["rule_evaluation_count"] >= 360
    assert observation["support_material_context"]["support_material_count"] >= 200
    assert observation["review_context"]["review_task_count"] >= 100
    assert observation["simulator_input"]["consumable"] is True
    assert set(observation["simulator_input"]["required_contexts"]) >= {
        "object_summary",
        "relation_summary",
        "rule_context",
        "support_material_context",
        "review_context",
        "trajectory_context",
    }


def test_twm_runtime_benchmark_cli_writes_outputs_and_exits_nonzero_on_failed(tmp_path):
    output = tmp_path / "cli_report.json"
    markdown_output = tmp_path / "cli_report.md"

    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/run_twm_runtime_benchmark.py"),
            "--suite",
            "twm_runtime_v1",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown_output),
            "--fail-on-failed",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert output.exists()
    assert markdown_output.exists()
    assert "status=fail" in completed.stdout


def test_twm_runtime_benchmark_leakage_guard_passes_with_explicit_feature_contract(tmp_path):
    from data_agent.benchmarks.twm_runtime_v1.runner import run_twm_runtime_benchmark

    report = run_twm_runtime_benchmark(
        output_path=tmp_path / "report.json",
        markdown_output_path=tmp_path / "report.md",
    )

    feature_contract = report["canonical_observation"]["feature_vector_contract"]
    forbidden = {
        "action_mask_allowed",
        "action_mask_required_reviews",
        "action_mask_hard_blocks",
        "action_mask_policy",
        "next_state_score",
        "constraint_risk_delta",
        "planning_utility_delta",
        "outcome",
        "treatment_effect",
        "uncertainty",
    }
    assert forbidden.isdisjoint(set(feature_contract["input_feature_columns"]))
    assert forbidden.issubset(set(feature_contract["excluded_target_columns"]))

    leakage_gate = report["gates"]["leakage_guard_gate"]
    assert leakage_gate["status"] == "pass"
    assert leakage_gate["checks"]["feature_vector_contract"]["status"] == "pass"
    assert leakage_gate["checks"]["target_feature_columns_excluded"]["status"] == "pass"
    assert "leakage_guard_gate" not in report["failed_gates"]


def test_twm_runtime_benchmark_evaluates_action_mask_head_without_label_leakage(tmp_path):
    from data_agent.benchmarks.twm_runtime_v1.runner import run_twm_runtime_benchmark

    markdown_output = tmp_path / "report.md"
    report = run_twm_runtime_benchmark(
        output_path=tmp_path / "report.json",
        markdown_output_path=markdown_output,
    )

    feature_contract = report["canonical_observation"]["feature_vector_contract"]
    forbidden = {
        "action_mask_allowed",
        "action_mask_required_reviews",
        "action_mask_hard_blocks",
        "action_mask_policy",
        "next_state_score",
        "constraint_risk_delta",
        "planning_utility_delta",
        "outcome",
        "treatment_effect",
        "uncertainty",
    }
    assert forbidden.isdisjoint(set(feature_contract["input_feature_columns"]))
    assert forbidden.issubset(set(feature_contract["excluded_target_columns"]))

    action_mask_head = report["simulator_trace"]["predictive_heads"]["action_mask_probability"]
    assert action_mask_head["status"] == "evaluated"
    assert action_mask_head["train_rows"] == report["measurements"]["split_counts"]["train"]
    assert action_mask_head["test_rows"] == report["measurements"]["split_counts"]["test"]
    assert action_mask_head["input_feature_columns"] == feature_contract["input_feature_columns"]
    assert action_mask_head["test"]["action_mask_accuracy"] >= 0.85
    assert action_mask_head["test"]["blocked_action_recall"] >= 0.85

    simulator_gate = report["gates"]["simulator_gate"]
    assert simulator_gate["checks"]["action_mask_probability"]["status"] == "pass"
    assert "action_mask_probability" not in simulator_gate["missing"]

    markdown = markdown_output.read_text(encoding="utf-8")
    assert "## Action-Mask Head" in markdown
    assert "Test action-mask accuracy: `1.0`" in markdown
    assert "Synthetic not-for-production fixture" in markdown


def test_twm_runtime_benchmark_evaluates_dynamics_heads_without_target_leakage(tmp_path):
    from data_agent.benchmarks.twm_runtime_v1.runner import run_twm_runtime_benchmark

    markdown_output = tmp_path / "report.md"
    report = run_twm_runtime_benchmark(
        output_path=tmp_path / "report.json",
        markdown_output_path=markdown_output,
    )

    feature_contract = report["canonical_observation"]["feature_vector_contract"]
    forbidden = {
        "next_state_score",
        "constraint_risk_delta",
        "planning_utility_delta",
        "outcome",
        "treatment_effect",
        "uncertainty",
    }
    assert forbidden.isdisjoint(set(feature_contract["input_feature_columns"]))
    assert forbidden.issubset(set(feature_contract["excluded_target_columns"]))

    predictive_heads = report["simulator_trace"]["predictive_heads"]
    for name in [
        "future_state_delta",
        "constraint_violation_probability",
        "planning_utility_delta",
    ]:
        assert predictive_heads[name]["status"] == "evaluated"
        assert predictive_heads[name]["test"]["mae"] <= 0.05
        assert forbidden.isdisjoint(set(predictive_heads[name]["used_feature_columns"]))

    runtime_metrics = report["simulator_trace"]["runtime_metrics"]
    assert runtime_metrics["transition_mae"] <= 0.05
    assert runtime_metrics["constraint_risk_mae"] <= 0.05
    assert runtime_metrics["planning_utility_mae"] <= 0.05
    assert runtime_metrics["ranking_correlation_proxy"] >= 0.6

    simulator_gate = report["gates"]["simulator_gate"]
    assert simulator_gate["status"] == "pass"
    assert simulator_gate["checks"]["runtime_metrics"]["status"] == "pass"
    assert "simulator_gate" not in report["failed_gates"]

    markdown = markdown_output.read_text(encoding="utf-8")
    assert "## Dynamics Heads" in markdown
    assert "Test transition MAE:" in markdown
    assert "Planning utility ranking correlation proxy:" in markdown
